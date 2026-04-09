# ES Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python firma ismine dokunmaz; tüm normalizasyon ES Ingest Pipeline'da yapılır. Eşleştirme 6 aşamalı waterfall modeliyle çalışır; her aşamanın sonucu `match_stages_log` tablosuna yazılır.

**Architecture:** Stage-by-stage batch waterfall (TAX_EXACT → NGRAM_MATCH). Her stage tüm kalan kayıtlara msearch ile uygulanır, eşleşenler durur. Stage config tek bir liste (`config.STAGES`) ile yönetilir. Yeni stage eklemek = listeye dict + `es_queries.py`'e fonksiyon.

**Tech Stack:** Python 3.11+, Elasticsearch 8.x (analysis-icu, analysis-phonetic opsiyonel), psycopg2, pytest

---

## Dosya Haritası

| Dosya | Durum | Sorumluluk |
|-------|-------|------------|
| `config.py` | Değişir | `STAGES` listesi eklenir |
| `es_queries.py` | **Yeni** | 6 stage sorgu fonksiyonu (fonksiyon adı = stage adı) |
| `es_ingest.py` | Değişir | Painless script'e fused suffix splitting + spaced letter normalization eklenir |
| `es_manager.py` | Değişir | `stripped_search_analyzer` eklenir (`variations_stripped` query-time için) |
| `main_processor.py` | **Tamamen yeniden yazılır** | Stage döngüsü orkestrasyonu |
| `schema.sql` | Değişir | `match_stages_log` tablosu eklenir |
| `matcher_logic.py` | **Silinir** | ES'e taşındı |
| `synonym_normalizer.py` | **Silinir** | ES analyzer'a taşındı |
| `es_batch_search.py` | **Silinir** | main_processor'a taşındı |
| `es_scripts.py` | **Silinir** | Rescore script artık kullanılmıyor |
| `tests/test_config.py` | **Yeni** | STAGES listesi validasyonu |
| `tests/test_es_queries.py` | **Yeni** | Her stage query yapısı |
| `tests/test_main_processor.py` | **Yeni** | Stage orchestration (mock ES) |

---

## Task 1: match_stages_log Tablosu

**Files:**
- Modify: `schema.sql`

Not: `ensure_stage_log_table()` Python fonksiyonu Task 6'daki main_processor.py tam yeniden yazımında yer alır.

- [ ] **Step 1: `schema.sql`'e tablo ekle**

```sql
-- schema.sql sonuna ekle
CREATE TABLE IF NOT EXISTS match_stages_log (
    id               SERIAL PRIMARY KEY,
    input_id         INTEGER,
    input_name       TEXT,
    country_code     VARCHAR(10),
    stage_name       VARCHAR(30),
    stage_order      INTEGER,
    matched          BOOLEAN,
    master_id        TEXT,
    es_score         FLOAT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_msl_input_id ON match_stages_log (input_id);
CREATE INDEX IF NOT EXISTS idx_msl_stage_name ON match_stages_log (stage_name);
CREATE INDEX IF NOT EXISTS idx_msl_matched ON match_stages_log (matched);
```

- [ ] **Step 2: `main_processor.py`'deki `ensure_audit_table`'ı `ensure_stage_log_table` olarak değiştir**

```python
def ensure_stage_log_table(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_stages_log (
            id               SERIAL PRIMARY KEY,
            input_id         INTEGER,
            input_name       TEXT,
            country_code     VARCHAR(10),
            stage_name       VARCHAR(30),
            stage_order      INTEGER,
            matched          BOOLEAN,
            master_id        TEXT,
            es_score         FLOAT,
            created_at       TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_msl_input_id ON match_stages_log (input_id);
        CREATE INDEX IF NOT EXISTS idx_msl_stage_name ON match_stages_log (stage_name);
        CREATE INDEX IF NOT EXISTS idx_msl_matched ON match_stages_log (matched);
    """)
    conn.commit()
    cursor.close()
    logger.info("match_stages_log tablosu hazır.")
```

- [ ] **Step 3: DB'de tabloyu oluştur ve doğrula**

```bash
psql -d market_calculus -c "\d match_stages_log"
```

Expected: `id, input_id, input_name, country_code, stage_name, stage_order, matched, master_id, es_score, created_at` sütunları listesi.

- [ ] **Step 4: Commit**

```bash
git add schema.sql main_processor.py
git commit -m "feat: add match_stages_log table"
```

---

## Task 2: config.py — STAGES Listesi

**Files:**
- Modify: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_config.py
import importlib
import config


def test_stages_has_required_keys():
    required = {"name", "order", "query_fn", "min_score", "enabled"}
    for stage in config.STAGES:
        missing = required - stage.keys()
        assert not missing, f"Stage '{stage.get('name')}' için eksik anahtarlar: {missing}"


def test_stages_ordered_correctly():
    enabled = [s for s in config.STAGES if s["enabled"]]
    orders = [s["order"] for s in enabled]
    assert orders == sorted(orders), "Aktif stage'ler 'order' değerine göre sıralı değil"


def test_stage_query_fns_exist_in_es_queries():
    import es_queries
    for stage in config.STAGES:
        assert hasattr(es_queries, stage["query_fn"]), (
            f"es_queries.py'de '{stage['query_fn']}' fonksiyonu bulunamadı "
            f"(stage: {stage['name']})"
        )


def test_stage_names_unique():
    names = [s["name"] for s in config.STAGES]
    assert len(names) == len(set(names)), "STAGES listesinde tekrarlı isim var"
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
cd c:\All-project\ta-code-merge
python -m pytest tests/test_config.py -v
```

Expected: FAIL — `config` modülünde `STAGES` yok.

- [ ] **Step 3: `config.py`'e `STAGES` listesi ekle**

```python
# config.py sonuna ekle

# --- Stage Konfigürasyonu ---
# Stage eklemek:   Listeye yeni dict ekle + es_queries.py'e aynı isimde fonksiyon yaz
# Stage çıkarmak:  "enabled": False yap veya listeden sil
# Sıralamak:       "order" değerini veya listenin sırasını değiştir

STAGES = [
    {
        "name": "TAX_EXACT",
        "order": 1,
        "query_fn": "TAX_EXACT",
        "min_score": 1.0,
        "enabled": True,
    },
    {
        "name": "CANONICAL_EXACT",
        "order": 2,
        "query_fn": "CANONICAL_EXACT",
        "min_score": 50.0,
        "enabled": True,
    },
    {
        "name": "STRIPPED_EXACT",
        "order": 3,
        "query_fn": "STRIPPED_EXACT",
        "min_score": 30.0,
        "enabled": True,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 4,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 10.0,
        "enabled": True,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 5,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
    },
    {
        "name": "NGRAM_MATCH",
        "order": 6,
        "query_fn": "NGRAM_MATCH",
        "min_score": 3.0,
        "enabled": True,
    },
]
```

- [ ] **Step 4: Test çalıştır — `test_stage_query_fns_exist_in_es_queries` hariç hepsi geçmeli**

```bash
python -m pytest tests/test_config.py::test_stages_has_required_keys tests/test_config.py::test_stages_ordered_correctly tests/test_config.py::test_stage_names_unique -v
```

Expected: 3 PASS, `test_stage_query_fns_exist_in_es_queries` FAIL (es_queries.py henüz yok).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add STAGES config list with stage definitions"
```

---

## Task 3: es_queries.py — Stage Sorgu Fonksiyonları

**Files:**
- Create: `es_queries.py`
- Create: `tests/test_es_queries.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_es_queries.py
import pytest
import es_queries


def _get_country_filter(query_dict: dict) -> str | None:
    """Query içindeki country_code filter değerini döner."""
    bool_q = query_dict.get("query", {}).get("bool", {})
    for f in bool_q.get("filter", []):
        if "term" in f and "country_code" in f["term"]:
            return f["term"]["country_code"]
    return None


def test_tax_exact_structure():
    q = es_queries.TAX_EXACT("acme inc", "TR", tax_number="1234567890")
    filters = q["query"]["bool"]["filter"]
    tax_filter = next(f["term"]["tax_number"] for f in filters if "term" in f and "tax_number" in f["term"])
    assert tax_filter == "1234567890"
    assert _get_country_filter(q) == "TR"
    assert q.get("size") == 1


def test_tax_exact_normalizes_tax():
    q = es_queries.TAX_EXACT("acme inc", "TR", tax_number="123-456.789/0")
    filters = q["query"]["bool"]["filter"]
    tax_val = next(f["term"]["tax_number"] for f in filters if "term" in f and "tax_number" in f["term"])
    assert tax_val == "1234567890"


def test_canonical_exact_structure():
    q = es_queries.CANONICAL_EXACT("apple trading", "TR")
    assert _get_country_filter(q) == "TR"
    bool_q = q["query"]["bool"]
    must_phrases = [
        c["match_phrase"]["variations"]["query"]
        for c in bool_q.get("must", [])
        if "match_phrase" in c and "variations" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases


def test_canonical_exact_uses_country_analyzer():
    q = es_queries.CANONICAL_EXACT("apple trading", "DE")
    must = q["query"]["bool"]["must"]
    analyzer = must[0]["match_phrase"]["variations"]["analyzer"]
    assert analyzer == "clean_analyzer_DE"


def test_canonical_exact_fallback_analyzer_for_unknown_country():
    q = es_queries.CANONICAL_EXACT("apple trading", "XX")
    must = q["query"]["bool"]["must"]
    analyzer = must[0]["match_phrase"]["variations"]["analyzer"]
    assert analyzer == "clean_analyzer_common"


def test_stripped_exact_structure():
    q = es_queries.STRIPPED_EXACT("apple trading", "US")
    assert _get_country_filter(q) == "US"
    bool_q = q["query"]["bool"]
    must_phrases = [
        c["match_phrase"]["variations_stripped"]["query"]
        for c in bool_q.get("must", [])
        if "match_phrase" in c and "variations_stripped" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases


def test_token_coverage_uses_and_operator():
    q = es_queries.TOKEN_COVERAGE("apple trading limited", "US")
    must = q["query"]["bool"]["must"]
    match_clause = next(
        c["match"]["variations"]
        for c in must
        if "match" in c and "variations" in c["match"]
    )
    assert match_clause["operator"] == "and"


def test_fuzzy_phrase_has_slop():
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    must = q["query"]["bool"]["must"]
    phrase = next(
        c["match_phrase"]["variations"]
        for c in must
        if "match_phrase" in c and "variations" in c["match_phrase"]
    )
    assert phrase.get("slop", 0) >= 1


def test_ngram_match_queries_ngram_field():
    q = es_queries.NGRAM_MATCH("apple", "US")
    must = q["query"]["bool"]["must"]
    assert any(
        "match" in c and "variations.ngram" in c["match"]
        for c in must
    )


def test_all_queries_include_country_filter():
    name = "test company"
    country = "FR"
    fns = [
        lambda: es_queries.CANONICAL_EXACT(name, country),
        lambda: es_queries.STRIPPED_EXACT(name, country),
        lambda: es_queries.TOKEN_COVERAGE(name, country),
        lambda: es_queries.FUZZY_PHRASE(name, country),
        lambda: es_queries.NGRAM_MATCH(name, country),
    ]
    for fn in fns:
        assert _get_country_filter(fn()) == country, f"{fn} country filter eksik"
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```bash
python -m pytest tests/test_es_queries.py -v
```

Expected: FAIL — `es_queries` modülü bulunamadı.

- [ ] **Step 3: `es_queries.py` oluştur**

```python
# ============================================================================
# es_queries.py - Stage Sorgu Fonksiyonları
# ============================================================================
# Her fonksiyon bir ES query body döner.
# Fonksiyon adı config.STAGES[*]["query_fn"] ile birebir eşleşmeli.
#
# Stage eklemek için:
#   1. Bu dosyaya yeni fonksiyon ekle (aynı imza: name, country, **kwargs)
#   2. config.STAGES listesine yeni dict ekle (query_fn = fonksiyon adı)
# ============================================================================

import re
from synonym_loader import get_all_country_codes

_KNOWN_COUNTRY_CODES = None


def _get_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"clean_analyzer_{cc}"
    return "clean_analyzer_common"


def _normalize_tax(tax: str) -> str:
    return re.sub(r"[^\w]", "", tax).upper()


def TAX_EXACT(name: str, country: str, tax_number: str = "", **kwargs) -> dict:
    """
    Vergi no birebir eşleşme — deterministik.
    tax_number boşsa bu stage atlanır (main_processor tarafından skip edilir).
    """
    return {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"tax_number": _normalize_tax(tax_number)}},
                    {"term": {"country_code": country.upper()}},
                ]
            }
        },
        "size": 1,
    }


def CANONICAL_EXACT(name: str, country: str, **kwargs) -> dict:
    """
    Synonym-aware canonical form tam phrase eşleşmesi.
    Ülkeye özel analyzer arama zamanında canonical form üretir.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def STRIPPED_EXACT(name: str, country: str, **kwargs) -> dict:
    """
    Suffix temizlenmiş tam phrase eşleşmesi.
    variations_stripped alanı ingest pipeline tarafından doldurulur.
    Sorgu search_analyzer ile query-time'da da stripped forma dönüştürülür.
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations_stripped": {
                                "query": name,
                                "analyzer": "stripped_search_analyzer",
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def TOKEN_COVERAGE(name: str, country: str, **kwargs) -> dict:
    """
    Tüm anlamlı token'ların presence kontrolü (operator:and).
    Kelime sırası önemsiz, tüm token'lar bulunmalı.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                                "operator": "and",
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def FUZZY_PHRASE(name: str, country: str, **kwargs) -> dict:
    """
    Kelime sırası toleranslı phrase eşleşmesi (slop=3).
    Aynı kelimeler ama farklı sırada veya araya kelime girmiş durumları yakalar.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                                "slop": 3,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def NGRAM_MATCH(name: str, country: str, **kwargs) -> dict:
    """
    Trigram index-time fuzzy eşleşmesi — en geniş ağ.
    Yazım hatalarını ve kısmi eşleşmeleri yakalar.
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "variations.ngram": {
                                "query": name,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }
```

- [ ] **Step 4: Testleri çalıştır — hepsi geçmeli**

```bash
python -m pytest tests/test_es_queries.py -v
```

Expected: 10 PASS

- [ ] **Step 5: config testini de çalıştır — hepsi geçmeli**

```bash
python -m pytest tests/test_config.py -v
```

Expected: 4 PASS (artık es_queries.py mevcut)

- [ ] **Step 6: Commit**

```bash
git add es_queries.py tests/test_es_queries.py
git commit -m "feat: add es_queries.py with 6 stage query functions"
```

---

## Task 4: es_manager.py — stripped_search_analyzer Ekle

**Files:**
- Modify: `es_manager.py`

STRIPPED_EXACT stage'inde sorgu tarafında generic token'ları kaldırmak için `stripped_search_analyzer` gereklidir. Bu analyzer `variations_stripped` alanının `search_analyzer`'ı olarak kullanılır.

- [ ] **Step 1: `build_index_settings()`'e `stripped_search_analyzer` ekle**

`es_manager.py` içindeki `build_index_settings()` fonksiyonunda, `analyzers` dict'ine şu bloğu ekle (mevcut `analyzers["clean_analyzer_common"] = ...` tanımının altına):

```python
# ── Stripped Search Analyzer (variations_stripped sorgu zamanı için) ──
# Generic company suffix'lerini stopword olarak kaldırır.
# variations_stripped alanının search_analyzer'ı olarak kullanılır.
common_generic_tokens = [
    "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "llc", "gmbh", "ag", "sa", "srl", "bv", "nv", "plc", "co",
    "company", "pty", "pvt", "private", "public", "holding",
    "holdings", "group", "international", "intl", "and",
    "the", "of", "a", "an",
]
filters["generic_stopwords"] = {
    "type": "stop",
    "stopwords": common_generic_tokens,
}
analyzers["stripped_search_analyzer"] = {
    "tokenizer": "standard",
    "filter": ["lowercase", "generic_stopwords"],
}
```

- [ ] **Step 2: `variations_stripped` mapping'ine `search_analyzer` ekle**

`build_index_settings()` içinde `"variations_stripped"` mapping bloğunu bul ve `search_analyzer` ekle:

```python
# Eski:
"variations_stripped": {
    "type": "text",
    "analyzer": "standard",
    "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
},

# Yeni:
"variations_stripped": {
    "type": "text",
    "analyzer": "standard",
    "search_analyzer": "stripped_search_analyzer",
    "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
},
```

- [ ] **Step 3: Index'i zorla yeniden oluştur**

```bash
cd c:\All-project\ta-code-merge
python es_manager.py --force
```

Expected: `Index 'living_companies_v1' silindi.` ardından `Index 'living_companies_v1' olusturuldu: ...`

- [ ] **Step 4: Analyzer'ın varlığını doğrula**

```bash
python -c "
from es_manager import get_es_client, build_index_settings
es = get_es_client()
settings = es.indices.get_settings(index='living_companies_v1')
analyzers = settings['living_companies_v1']['settings']['index']['analysis']['analyzer']
assert 'stripped_search_analyzer' in analyzers, 'stripped_search_analyzer eksik!'
print('OK: stripped_search_analyzer mevcut')
"
```

- [ ] **Step 5: Commit**

```bash
git add es_manager.py
git commit -m "feat: add stripped_search_analyzer for STRIPPED_EXACT stage"
```

---

## Task 5: es_ingest.py — Fused Suffix Splitting Ekle

**Files:**
- Modify: `es_ingest.py`

Mevcut ingest pipeline'da `PVTLTD → PVT LTD` (birleşik suffix ayırma) ve `L T D → LTD` (boşluklu harf birleştirme) yoktur. Bu adımları Painless script'e ekle.

- [ ] **Step 1: `_build_clean_script()` fonksiyonuna fused suffix ve spaced letter adımları ekle**

`es_ingest.py` içinde `_build_clean_script()` içindeki `script_parts` listesinde `# Sonuca ekle` satırından hemen önce şu blokları ekle:

```python
# --- Bu satırları "# Sonuca ekle" bloğundan ÖNCE ekle ---

# 9b. Boşluklu tek harf birleştirme: "l t d" -> "ltd"
# Ard arda gelen tek-harf token'ları birleştir (bilinen suffix oluşturuyorsa)
"  def knownSuffixes = ['ltd', 'inc', 'llc', 'bv', 'nv', 'ag', 'sa', 'plc', 'co', 'pvt'];",
r"  def spTokens = / /.split(text);",
"  List spResult = new ArrayList();",
"  int si = 0;",
"  while (si < spTokens.length) {",
"    if (spTokens[si].length() == 1 && spTokens[si].matches('[a-z]')) {",
"      StringBuilder run = new StringBuilder(spTokens[si]);",
"      int sj = si + 1;",
"      while (sj < spTokens.length && spTokens[sj].length() == 1 && spTokens[sj].matches('[a-z]')) {",
"        run.append(spTokens[sj]); sj++;",
"      }",
"      String joined = run.toString();",
"      if (sj > si + 1 && knownSuffixes.contains(joined)) {",
"        spResult.add(joined); si = sj;",
"      } else {",
"        spResult.add(spTokens[si]); si++;",
"      }",
"    } else {",
"      spResult.add(spTokens[si]); si++;",
"    }",
"  }",
"  StringBuilder spJoined = new StringBuilder();",
"  for (int spi = 0; spi < spResult.size(); spi++) {",
"    if (spi > 0) spJoined.append(' ');",
"    spJoined.append(spResult[spi]);",
"  }",
"  text = spJoined.toString().trim();",

# 9c. Birleşik suffix ayırma: "pvtltd" -> "pvt ltd"
"  def fusedMap = ['pvtltd': 'pvt ltd', 'ltdco': 'ltd co', 'corpltd': 'corp ltd',",
"    'incltd': 'inc ltd', 'gmbhco': 'gmbh co', 'sarl': 'sarl'];",
r"  def fTokens = / /.split(text);",
"  List fResult = new ArrayList();",
"  for (int ft = 0; ft < fTokens.length; ft++) {",
"    String ftok = fTokens[ft];",
"    if (fusedMap.containsKey(ftok)) {",
"      fResult.add((String)fusedMap.get(ftok));",
"    } else {",
"      fResult.add(ftok);",
"    }",
"  }",
"  StringBuilder fJoined = new StringBuilder();",
"  for (int fi = 0; fi < fResult.size(); fi++) {",
"    if (fi > 0) fJoined.append(' ');",
"    fJoined.append(fResult[fi]);",
"  }",
"  text = fJoined.toString().trim();",
```

- [ ] **Step 2: Pipeline'ı ES'e yeniden kaydet**

```bash
python es_ingest.py
```

Expected: `Pipeline 'company_name_clean' basariyla kaydedildi.`

- [ ] **Step 3: Pipeline'ı manuel test et**

```bash
python -c "
from es_manager import get_es_client
from es_ingest import PIPELINE_NAME

es = get_es_client()
result = es.ingest.simulate(
    id=PIPELINE_NAME,
    body={
        'docs': [
            {'_source': {'variations': ['PVTLTD ACME'], 'variations_stripped': [], 'country_code': 'TR'}},
            {'_source': {'variations': ['L T D APPLE'], 'variations_stripped': [], 'country_code': 'US'}},
        ]
    }
)
for doc in result['docs']:
    print(doc['doc']['_source']['variations'])
"
```

Expected:
```
['pvtltd acme']   # 'pvtltd' -> 'pvt ltd' dönüşümü (fused suffix ayrıldı)
['ltd apple']     # 'l t d' -> 'ltd' birleşti
```

- [ ] **Step 4: Commit**

```bash
git add es_ingest.py
git commit -m "feat: add fused suffix splitting and spaced letter normalization to ingest pipeline"
```

---

## Task 6: main_processor.py — Stage-by-Stage Batch Orchestrator (Tam Yeniden Yazım)

**Files:**
- Modify: `main_processor.py` (tam yeniden yazılır)
- Create: `tests/test_main_processor.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_main_processor.py
from unittest.mock import MagicMock, patch, call
import pytest
import importlib


def _make_es_hit(master_id: str, score: float = 80.0) -> dict:
    return {"_source": {"master_id": master_id}, "_score": score}


def _make_msearch_response(hits_per_query: list[list[dict]]) -> dict:
    """Her sorgu için hit listesi içeren msearch yanıtı üretir."""
    return {
        "responses": [
            {"hits": {"hits": hits, "total": {"value": len(hits)}}}
            for hits in hits_per_query
        ]
    }


def test_run_stage_returns_matched_and_unmatched():
    """Eşleşen kayıtlar matched, eşleşmeyenler unmatched listesine girer."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Ltd", "country": "TR", "tax": "", "phone": ""},
        {"row_id": 2, "raw_name": "Beta Corp", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "CANONICAL_EXACT", "order": 2, "query_fn": "CANONICAL_EXACT",
             "min_score": 50.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=80.0)],  # record 1 eşleşti
        [],                                          # record 2 eşleşmedi
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 1
    assert matched[0]["row_id"] == 1
    assert matched[0]["master_id"] == "master-001"
    assert matched[0]["stage_name"] == "CANONICAL_EXACT"

    assert len(unmatched) == 1
    assert unmatched[0]["row_id"] == 2


def test_run_stage_respects_min_score():
    """min_score altındaki hit'ler eşleşme sayılmaz."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Ltd", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "NGRAM_MATCH", "order": 6, "query_fn": "NGRAM_MATCH",
             "min_score": 3.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=1.5)],  # min_score altında
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 0
    assert len(unmatched) == 1


def test_tax_exact_skips_records_without_tax():
    """TAX_EXACT stage, tax numarası olmayan kayıtları atlamalı (unmatched'a eklemeli)."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme", "country": "TR", "tax": "", "phone": ""},
        {"row_id": 2, "raw_name": "Beta", "country": "TR", "tax": "123", "phone": ""},
    ]
    stage = {"name": "TAX_EXACT", "order": 1, "query_fn": "TAX_EXACT",
             "min_score": 1.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-002", score=1.0)],  # sadece record 2 için query gönderildi
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 1
    assert matched[0]["row_id"] == 2

    assert len(unmatched) == 1
    assert unmatched[0]["row_id"] == 1
```

- [ ] **Step 2: Testleri çalıştır, başarısız olduğunu doğrula**

```bash
python -m pytest tests/test_main_processor.py -v
```

Expected: FAIL — `run_stage` fonksiyonu mevcut `main_processor.py`'de yok.

- [ ] **Step 3: `main_processor.py`'i tamamen yeniden yaz**

```python
# ============================================================================
# main_processor.py - Stage-by-Stage Batch Eşleştirme Orkestrasyonu
# ============================================================================
# Mimari:
#   1. PostgreSQL'den master_code IS NULL kayıtları batch olarak oku
#   2. config.STAGES listesindeki her aktif stage için:
#      a. Tüm unmatched kayıtlara msearch ile stage sorgusu gönder
#      b. Eşleşenleri PG'ye yaz, match_stages_log'a kaydet, unmatched'dan çıkar
#      c. Eşleşmeyenleri match_stages_log'a kaydet (matched=False)
#      d. ES refresh (yeni master'lar için)
#   3. Tüm stage'lerden sonra hala unmatched → NEW_MASTER
#      Sub-batch'ler halinde index'le + refresh (within-batch duplike minimizasyonu)
# ============================================================================

import logging
import sys
import uuid
from typing import Any

import psycopg2
from psycopg2.extras import DictCursor, execute_values
from elasticsearch import helpers

from config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    DB_CONFIG,
    ES_INDEX,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    AUTO_CREATE_UPDATE_COLUMNS,
    RAW_TABLE_NAME,
    STAGES,
    MSEARCH_CHUNK_SIZE,
)
from es_manager import create_index, get_es_client
from es_ingest import PIPELINE_NAME, register_pipeline
import es_queries as _es_queries
from synonym_loader import get_all_country_codes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("elasticsearch").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# NEW_MASTER oluştururken sub-batch boyutu (within-batch duplicate minimizasyonu)
NEW_MASTER_SUBBATCH_SIZE = 200


# ─────────────────────────────────────────────────────────────────────
# DB YARDIMCILARI
# ─────────────────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def ensure_stage_log_table(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_stages_log (
            id               SERIAL PRIMARY KEY,
            input_id         INTEGER,
            input_name       TEXT,
            country_code     VARCHAR(10),
            stage_name       VARCHAR(30),
            stage_order      INTEGER,
            matched          BOOLEAN,
            master_id        TEXT,
            es_score         FLOAT,
            created_at       TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_msl_input_id ON match_stages_log (input_id);
        CREATE INDEX IF NOT EXISTS idx_msl_stage_name ON match_stages_log (stage_name);
        CREATE INDEX IF NOT EXISTS idx_msl_matched ON match_stages_log (matched);
    """)
    conn.commit()
    cursor.close()
    logger.info("match_stages_log tablosu hazır.")


def validate_db_schema(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);",
        (RAW_TABLE_NAME,),
    )
    if not cursor.fetchone()[0]:
        raise RuntimeError(f"HATA: '{RAW_TABLE_NAME}' tablosu bulunamadı!")

    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s;",
        (RAW_TABLE_NAME,),
    )
    existing_columns = {row[0] for row in cursor.fetchall()}

    for internal_name in MANDATORY_READ_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col or db_col not in existing_columns:
            raise RuntimeError(f"Zorunlu okuma sütunu eksik: {internal_name} → {db_col}")

    missing_update = []
    for internal_name in MANDATORY_UPDATE_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col or db_col not in existing_columns:
            missing_update.append((internal_name, db_col))

    if missing_update and AUTO_CREATE_UPDATE_COLUMNS:
        for internal_name, db_col in missing_update:
            col_type = {"master_code": "VARCHAR(50)", "match_score": "INTEGER"}.get(internal_name, "TEXT")
            cursor.execute(f"ALTER TABLE {RAW_TABLE_NAME} ADD COLUMN {db_col} {col_type};")
            conn.commit()
            logger.info(f"Sütun oluşturuldu: {db_col} ({col_type})")
    elif missing_update:
        raise RuntimeError(f"Eksik güncelleme sütunları: {[x[1] for x in missing_update]}")

    cursor.close()
    logger.info(f"Schema doğrulama başarılı: '{RAW_TABLE_NAME}'")


# ─────────────────────────────────────────────────────────────────────
# STAGE ORKESTRASYONU
# ─────────────────────────────────────────────────────────────────────

def run_stage(
    es,
    records: list[dict],
    stage: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Bir stage'i tüm unmatched kayıtlara uygular.

    Args:
        es:      Elasticsearch client
        records: [{"row_id", "raw_name", "country", "tax", "phone"}, ...]
        stage:   config.STAGES'den bir stage dict'i

    Returns:
        (matched, unmatched)
        matched:   [{"row_id", "raw_name", "country", "master_id", "es_score", "stage_name", "stage_order"}, ...]
        unmatched: records ile aynı format, eşleşmeyenler
    """
    stage_name = stage["name"]
    stage_order = stage["order"]
    min_score = stage["min_score"]
    query_fn = getattr(_es_queries, stage["query_fn"])

    # TAX_EXACT için tax numarası olmayanları direkt unmatched'a al
    if stage_name == "TAX_EXACT":
        tax_records = [r for r in records if r.get("tax")]
        no_tax_records = [r for r in records if not r.get("tax")]
    else:
        tax_records = records
        no_tax_records = []

    if not tax_records:
        return [], records

    # msearch için (query, routing, record) üçlüleri oluştur
    queries = []
    for rec in tax_records:
        q = query_fn(
            name=rec["raw_name"],
            country=rec["country"],
            tax_number=rec.get("tax", ""),
        )
        queries.append((q, rec["country"], rec))

    # msearch çalıştır
    hits_map = _execute_msearch(es, queries)

    matched = []
    unmatched = list(no_tax_records)

    for i, (_, _, rec) in enumerate(queries):
        hits = hits_map.get(i, [])
        top_hit = hits[0] if hits else None
        top_score = top_hit["_score"] if top_hit else 0.0

        if top_hit and top_score >= min_score:
            matched.append({
                **rec,
                "master_id": top_hit["_source"]["master_id"],
                "es_score": top_score,
                "stage_name": stage_name,
                "stage_order": stage_order,
            })
        else:
            unmatched.append(rec)

    return matched, unmatched


def _execute_msearch(
    es,
    queries: list[tuple[dict, str, dict]],
) -> dict[int, list[dict]]:
    """
    msearch API ile toplu sorgu çalıştırır.

    Args:
        queries: [(query_body, routing_country, record), ...]

    Returns:
        {index: hits_list} mapping
    """
    results: dict[int, list[dict]] = {}
    indices = list(range(len(queries)))

    for chunk_start in range(0, len(indices), MSEARCH_CHUNK_SIZE):
        chunk = indices[chunk_start:chunk_start + MSEARCH_CHUNK_SIZE]
        body: list[dict[str, Any]] = []

        for idx in chunk:
            query, country, _ = queries[idx]
            body.append({"index": ES_INDEX, "routing": country.upper()})
            body.append(query)

        try:
            response = es.msearch(body=body)
        except Exception:
            logger.exception("msearch başarısız")
            for idx in chunk:
                results[idx] = []
            continue

        for i, idx in enumerate(chunk):
            resp = response["responses"][i]
            if "error" in resp:
                logger.error(f"msearch item #{idx} hata: {resp['error']}")
                results[idx] = []
            else:
                results[idx] = resp["hits"].get("hits", [])

    return results


# ─────────────────────────────────────────────────────────────────────
# YAZMA İŞLEMLERİ
# ─────────────────────────────────────────────────────────────────────

def write_matched_to_pg(write_cursor, write_conn, matched: list[dict]) -> None:
    if not matched:
        return
    col_id = COLUMN_MAPPING["id"]
    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]

    execute_values(
        write_cursor,
        f"""
        UPDATE {RAW_TABLE_NAME} AS t
        SET {col_master} = d.master_code,
            {col_score}  = d.match_score,
            {col_type}   = d.match_type
        FROM (VALUES %s) AS d(master_code, match_score, match_type, id)
        WHERE t.{col_id} = d.id
        """,
        [(r["master_id"], int(r["es_score"]), r["stage_name"], r["row_id"]) for r in matched],
    )
    write_conn.commit()


def write_stage_log(write_cursor, write_conn, matched: list[dict], unmatched: list[dict], stage: dict) -> None:
    """matched ve unmatched kayıtları match_stages_log'a yazar."""
    rows = []
    for r in matched:
        rows.append((
            r["row_id"], r["raw_name"], r["country"],
            stage["name"], stage["order"],
            True, r["master_id"], r["es_score"],
        ))
    for r in unmatched:
        rows.append((
            r["row_id"], r["raw_name"], r["country"],
            stage["name"], stage["order"],
            False, None, None,
        ))

    if not rows:
        return

    execute_values(
        write_cursor,
        """
        INSERT INTO match_stages_log
            (input_id, input_name, country_code, stage_name, stage_order,
             matched, master_id, es_score)
        VALUES %s
        """,
        rows,
    )
    write_conn.commit()


def build_new_master_doc(row_id: int, name: str, country: str, tax: str, phone: str) -> dict:
    master_id = str(uuid.uuid4())
    doc = {
        "_index": ES_INDEX,
        "_id": master_id,
        "_routing": country.upper(),
        "_source": {
            "master_id": master_id,
            "variations": [name],
            "variations_stripped": [],
            "country_code": country.upper(),
        },
    }
    if tax:
        doc["_source"]["tax_number"] = tax
    if phone:
        doc["_source"]["phone_number"] = phone
    return doc, master_id


def create_new_masters(es, write_cursor, write_conn, records: list[dict]) -> None:
    """
    Unmatched kayıtları NEW_MASTER olarak ES'e index'ler.

    Sub-batch'ler halinde işler: her sub-batch sonrası ES refresh yapılır.
    Bu sayede aynı batch içindeki duplicate firmalar birbirini bulabilir.
    """
    for chunk_start in range(0, len(records), NEW_MASTER_SUBBATCH_SIZE):
        chunk = records[chunk_start:chunk_start + NEW_MASTER_SUBBATCH_SIZE]
        es_docs = []
        pg_updates = []
        log_rows = []

        for rec in chunk:
            doc, master_id = build_new_master_doc(
                rec["row_id"], rec["raw_name"], rec["country"],
                rec.get("tax", ""), rec.get("phone", ""),
            )
            es_docs.append(doc)

            col_master = COLUMN_MAPPING["master_code"]
            col_score = COLUMN_MAPPING["match_score"]
            col_type = COLUMN_MAPPING["match_type"]
            pg_updates.append((master_id, 100, "NEW_MASTER", rec["row_id"]))
            log_rows.append((
                rec["row_id"], rec["raw_name"], rec["country"],
                "NEW_MASTER", 7, True, master_id, 100.0,
            ))

        if es_docs:
            helpers.bulk(es, es_docs, raise_on_error=True)
            es.indices.refresh(index=ES_INDEX)

        col_id = COLUMN_MAPPING["id"]
        col_master = COLUMN_MAPPING["master_code"]
        col_score = COLUMN_MAPPING["match_score"]
        col_type = COLUMN_MAPPING["match_type"]
        execute_values(
            write_cursor,
            f"""
            UPDATE {RAW_TABLE_NAME} AS t
            SET {col_master} = d.master_code,
                {col_score}  = d.match_score,
                {col_type}   = d.match_type
            FROM (VALUES %s) AS d(master_code, match_score, match_type, id)
            WHERE t.{col_id} = d.id
            """,
            pg_updates,
        )
        execute_values(
            write_cursor,
            """
            INSERT INTO match_stages_log
                (input_id, input_name, country_code, stage_name, stage_order,
                 matched, master_id, es_score)
            VALUES %s
            """,
            log_rows,
        )
        write_conn.commit()
        logger.info(f"  NEW_MASTER sub-batch: {len(chunk)} yeni firma oluşturuldu.")


# ─────────────────────────────────────────────────────────────────────
# ANA İŞLEM DÖNGÜSÜ
# ─────────────────────────────────────────────────────────────────────

def process_all_data() -> None:
    es = get_es_client()
    logger.info("Elasticsearch index kontrol ediliyor...")
    create_index(es)

    logger.info("Ingest pipeline kontrol ediliyor...")
    register_pipeline(es)

    logger.info("Veritabanına bağlanılıyor...")
    read_conn = get_db_connection()
    write_conn = get_db_connection()

    active_stages = sorted(
        [s for s in STAGES if s["enabled"]],
        key=lambda s: s["order"],
    )
    logger.info(f"Aktif stage'ler: {[s['name'] for s in active_stages]}")

    try:
        validate_db_schema(read_conn)
        ensure_stage_log_table(write_conn)

        read_cursor = read_conn.cursor(name="matching_cursor", cursor_factory=DictCursor)
        write_cursor = write_conn.cursor()

        col_id = COLUMN_MAPPING["id"]
        col_name = COLUMN_MAPPING["company_name"]
        col_country = COLUMN_MAPPING["country_code"]
        col_tax = COLUMN_MAPPING.get("tax_number")
        col_phone = COLUMN_MAPPING.get("phone_number")
        col_master = COLUMN_MAPPING["master_code"]

        select_cols = [col_id, col_name, col_country]
        if col_tax:
            select_cols.append(col_tax)
        if col_phone:
            select_cols.append(col_phone)

        read_cursor.execute(
            f"""
            SELECT {', '.join(select_cols)}
            FROM {RAW_TABLE_NAME}
            WHERE {col_master} IS NULL
            ORDER BY {col_id}
            """
        )

        batch_num = 0
        while True:
            rows = read_cursor.fetchmany(BATCH_SIZE)
            if not rows:
                logger.info("İşlenecek veri kalmadı.")
                break

            batch_num += 1
            logger.info(f"Batch #{batch_num}: {len(rows)} kayıt okundu.")

            # Kayıtları standart formata dönüştür
            records = []
            for row in rows:
                records.append({
                    "row_id": row[col_id],
                    "raw_name": row[col_name],
                    "country": (row[col_country] or "DEFAULT").upper(),
                    "tax": row.get(col_tax) or "" if col_tax else "",
                    "phone": row.get(col_phone) or "" if col_phone else "",
                })

            unmatched = records
            total_matched = 0

            # Stage döngüsü
            for stage in active_stages:
                if not unmatched:
                    break

                logger.info(f"  Stage {stage['order']}: {stage['name']} — {len(unmatched)} kayıt deneniyor...")
                matched, unmatched = run_stage(es, unmatched, stage)

                # PG güncelle
                write_matched_to_pg(write_cursor, write_conn, matched)

                # Log tüm kayıtları (matched + unmatched for this stage)
                write_stage_log(write_cursor, write_conn, matched, unmatched, stage)

                # ES refresh (eşleşenler arasında yeni masterlar olabilir)
                if matched:
                    es.indices.refresh(index=ES_INDEX)

                total_matched += len(matched)
                logger.info(f"    → {len(matched)} eşleşti, {len(unmatched)} kaldı.")

            # Hiçbir stage'de eşleşmeyen → NEW_MASTER
            if unmatched:
                logger.info(f"  NEW_MASTER: {len(unmatched)} kayıt yeni firma olarak oluşturuluyor...")
                create_new_masters(es, write_cursor, write_conn, unmatched)
                total_matched += len(unmatched)

            logger.info(
                f"Batch #{batch_num} Tamamlandı: {len(records)} kayıt işlendi, "
                f"{total_matched} sonuçlandı."
            )

        read_cursor.close()
        write_cursor.close()
        logger.info("Tüm veriler başarıyla işlendi.")

    except Exception as e:
        if "read_conn" in locals():
            read_conn.rollback()
        if "write_conn" in locals():
            write_conn.rollback()
        logger.error(f"HATA: {e}", exc_info=True)
        raise
    finally:
        if "read_conn" in locals():
            read_conn.close()
        if "write_conn" in locals():
            write_conn.close()
        logger.info("Veritabanı bağlantıları kapatıldı.")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Firma Eşleştirme Sistemi başlatılıyor...")
    logger.info("=" * 60)
    process_all_data()
```

- [ ] **Step 4: Testleri çalıştır — hepsi geçmeli**

```bash
python -m pytest tests/test_main_processor.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Tüm testleri çalıştır**

```bash
python -m pytest tests/ -v
```

Expected: Tüm testler PASS

- [ ] **Step 6: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "feat: rewrite main_processor.py with stage-by-stage batch orchestration"
```

---

## Task 7: Eski Dosyaları Sil

**Files:**
- Delete: `matcher_logic.py`
- Delete: `synonym_normalizer.py`
- Delete: `es_batch_search.py`
- Delete: `es_scripts.py`

- [ ] **Step 1: Dosyaların başka yerde import edilip edilmediğini kontrol et**

```bash
python -c "
import subprocess
files = ['matcher_logic', 'synonym_normalizer', 'es_batch_search', 'es_scripts']
for f in files:
    result = subprocess.run(['grep', '-r', f'from {f}', '--include=*.py', '.'], capture_output=True, text=True)
    if result.stdout.strip():
        print(f'UYARI: {f} hala import ediliyor:')
        print(result.stdout)
    else:
        print(f'OK: {f} import edilmiyor')
"
```

Expected: 4 satır `OK: ... import edilmiyor`

Eğer bir dosya hala import ediliyorsa, o import'ı kaldır veya yeni dosyaya taşı, sonra sil.

- [ ] **Step 2: Dosyaları sil**

```bash
cd c:\All-project\ta-code-merge
rm matcher_logic.py synonym_normalizer.py es_batch_search.py es_scripts.py
```

- [ ] **Step 3: Import'ların temiz olduğunu doğrula**

```bash
python -c "import main_processor; print('main_processor import OK')"
python -c "import es_queries; print('es_queries import OK')"
python -c "import es_ingest; print('es_ingest import OK')"
python -c "import es_manager; print('es_manager import OK')"
```

Expected: 4 satır `... import OK`

- [ ] **Step 4: Tüm testler hala geçiyor mu kontrol et**

```bash
python -m pytest tests/ -v
```

Expected: Tüm testler PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove matcher_logic, synonym_normalizer, es_batch_search, es_scripts (moved to ES)"
```

---

## Task 8: End-to-End Doğrulama

- [ ] **Step 1: Index'i sıfırdan oluştur, pipeline kaydet**

```bash
python es_manager.py --force
python es_ingest.py
```

Expected: Her ikisi de hata vermeden tamamlanır.

- [ ] **Step 2: Küçük test batch'i ile çalıştır (5 kayıt)**

PostgreSQL'de 5 kayıt için `master_code = NULL` olduğundan emin ol, sonra:

```bash
python main_processor.py
```

Expected: Log çıktısında stage'lerin çalıştığı görülür:
```
Stage 1: TAX_EXACT — 5 kayıt deneniyor...
  → X eşleşti, Y kaldı.
Stage 2: CANONICAL_EXACT — Y kayıt deneniyor...
...
Batch #1 Tamamlandı: 5 kayıt işlendi.
```

- [ ] **Step 3: match_stages_log'u sorgula, stage'lerin yazıldığını doğrula**

```bash
psql -d market_calculus -c "
SELECT stage_name, stage_order, matched, COUNT(*) 
FROM match_stages_log 
GROUP BY stage_name, stage_order, matched 
ORDER BY stage_order;
"
```

Expected: Her kayıt için denenen stage'ler, eşleşme sonuçları görünür.

- [ ] **Step 4: Eşleşen bir kaydın tüm stage geçmişini sorgula**

```bash
psql -d market_calculus -c "
SELECT stage_name, stage_order, matched, es_score
FROM match_stages_log
WHERE input_id = (SELECT input_id FROM match_stages_log WHERE matched = TRUE LIMIT 1)
ORDER BY stage_order;
"
```

Expected: Eşleşen stage'e kadar `matched=FALSE`, eşleşen stage'de `matched=TRUE`, sonrasında satır yok.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: ES pipeline redesign complete — stage-by-stage waterfall matching"
```
