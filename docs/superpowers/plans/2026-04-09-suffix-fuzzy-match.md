# Suffix Fuzzy Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ES'te `variations_suffix` alanı üzerinden suffix token'larını fuzzy olarak eşleştiren yeni bir `SUFFIX_FUZZY` stage eklemek; firma ismi kısmı exact, suffix kısmı fuzzy (AUTO:4,7) eşleşmesini sağlamak.

**Architecture:** `es_ingest.py`'daki Painless script `variations_suffix` alanını (generic token'ları = suffix token'ları) index time'da hesaplar. `es_queries.py` bu alana fuzzy match + `variations_stripped`'a operator:or match gönderir. `main_processor.py`'daki `_post_verify()` SUFFIX_FUZZY branch'inde name token coverage >= 0.85 kontrolü yapar.

**Tech Stack:** Python 3.12, Elasticsearch 8.x (Painless scripts), pytest

**Spec:** `docs/superpowers/specs/2026-04-09-suffix-fuzzy-match-design.md`

---

## File Map

| Dosya | Değişiklik |
|---|---|
| `config.py` | `MatchType.SUFFIX_FUZZY` + `SUFFIX_FUZZY_MIN_SCORE` + `SUFFIX_FUZZY_SCORE` + STAGES entry |
| `es_manager.py` | `variations_suffix` field mapping (`type: text`, `analyzer: standard`) |
| `es_ingest.py` | `_build_suffix_script()` + yeni processor `build_pipeline_body()`'de |
| `es_queries.py` | `SUFFIX_FUZZY()` sorgu fonksiyonu |
| `main_processor.py` | `_post_verify()` içine SUFFIX_FUZZY branch |
| `tests/test_config.py` | SUFFIX_FUZZY stage varlık testi |
| `tests/test_es_queries.py` | SUFFIX_FUZZY query yapı testleri |
| `tests/test_main_processor.py` | `_post_verify()` SUFFIX_FUZZY testleri |

---

## Task 1: config.py — MatchType, sabitler ve STAGES

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_config.py — mevcut dosyaya EKLE (üstüne yazma)

def test_suffix_fuzzy_match_type_exists():
    assert hasattr(config.MatchType, "SUFFIX_FUZZY")
    assert config.MatchType.SUFFIX_FUZZY == "SUFFIX_FUZZY"


def test_suffix_fuzzy_constants_exist():
    assert hasattr(config, "SUFFIX_FUZZY_MIN_SCORE")
    assert hasattr(config, "SUFFIX_FUZZY_SCORE")
    assert config.SUFFIX_FUZZY_SCORE == 85


def test_suffix_fuzzy_stage_in_stages():
    names = [s["name"] for s in config.STAGES]
    assert "SUFFIX_FUZZY" in names


def test_suffix_fuzzy_stage_order_between_stripped_and_token_coverage():
    """SUFFIX_FUZZY, STRIPPED_EXACT'tan sonra TOKEN_COVERAGE'dan önce gelmeli."""
    stages_by_name = {s["name"]: s["order"] for s in config.STAGES}
    assert stages_by_name["SUFFIX_FUZZY"] > stages_by_name["STRIPPED_EXACT"]
    assert stages_by_name["SUFFIX_FUZZY"] < stages_by_name["TOKEN_COVERAGE"]
```

- [ ] **Step 2: Testi çalıştır — FAIL bekliyoruz**

```bash
cd /c/All-project/ta-code-merge
python -m pytest tests/test_config.py::test_suffix_fuzzy_match_type_exists tests/test_config.py::test_suffix_fuzzy_constants_exist tests/test_config.py::test_suffix_fuzzy_stage_in_stages tests/test_config.py::test_suffix_fuzzy_stage_order_between_stripped_and_token_coverage -v
```

Beklenen: 4 test FAIL — `AttributeError` veya `AssertionError`

- [ ] **Step 3: config.py'i güncelle**

`config.py`'de `MatchType` sınıfını bul, `STRIPPED_EXACT` satırının hemen altına ekle:

```python
SUFFIX_FUZZY = "SUFFIX_FUZZY"
# Suffix kısmı fuzzy eşleşme, name kısmı exact
```

`TOKEN_COVERAGE` tanımının hemen üstünde, dosyanın herhangi uygun yerine ekle:

```python
SUFFIX_FUZZY_MIN_SCORE = 1.5   # ES score eşiği — prod testleriyle kalibre edilmeli
SUFFIX_FUZZY_SCORE     = 85    # match sonucu skoru
```

`STAGES` listesinde `STRIPPED_EXACT` entry'sinin hemen altına yeni entry ekle ve TOKEN_COVERAGE / FUZZY_PHRASE / NGRAM_MATCH order'larını birer artır:

```python
    {
        "name": "STRIPPED_EXACT",
        "order": 3,
        "query_fn": "STRIPPED_EXACT",
        "min_score": 3.0,
        "enabled": True,
    },
    {
        "name": "SUFFIX_FUZZY",      # YENİ
        "order": 4,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": 1.5,
        "enabled": True,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 5,                  # 4 → 5
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 6,                  # 5 → 6
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
    },
    {
        "name": "NGRAM_MATCH",
        "order": 7,                  # 6 → 7
        "query_fn": "NGRAM_MATCH",
        "min_score": 3.0,
        "enabled": True,
    },
```

- [ ] **Step 4: Testi çalıştır — PASS bekliyoruz**

```bash
python -m pytest tests/test_config.py -v
```

Beklenen: Tüm testler PASS (mevcut + yeni 4 test)

**Not:** `test_stage_query_fns_exist_in_es_queries` testi şu an FAIL verebilir — `SUFFIX_FUZZY` fonksiyonu henüz `es_queries.py`'de yok. Bu normaldir, Task 4'te düzeltilecek.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add SUFFIX_FUZZY match type, constants and stage to config"
```

---

## Task 2: es_manager.py — `variations_suffix` field mapping

**Files:**
- Modify: `es_manager.py`

- [ ] **Step 1: `build_index_settings()` fonksiyonunda mapping'i bul**

`es_manager.py`'de `"variations_stripped"` mapping bloğunu bul (satır ~225). Hemen altına yeni alan ekle:

```python
                "variations_suffix": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                    },
                },
```

Tam yerleşimi için referans — `variations_stripped` bloğu şu şekilde görünür:

```python
                "variations_stripped": {
                    "type": "text",
                    "analyzer": "standard",
                    "search_analyzer": "stripped_search_analyzer",
                    "fields": { ... },
                },
                # YENİ alan buraya:
                "variations_suffix": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                    },
                },
```

- [ ] **Step 2: Mapping test — manuel doğrulama**

```bash
python -c "
from es_manager import build_index_settings
settings = build_index_settings()
props = settings['mappings']['properties']
assert 'variations_suffix' in props, 'variations_suffix yok!'
assert props['variations_suffix']['type'] == 'text'
assert props['variations_suffix']['analyzer'] == 'standard'
print('OK: variations_suffix mapping dogru')
"
```

Beklenen: `OK: variations_suffix mapping dogru`

- [ ] **Step 3: Commit**

```bash
git add es_manager.py
git commit -m "feat: add variations_suffix field mapping to ES index"
```

---

## Task 3: es_ingest.py — Suffix Painless script ve processor

**Files:**
- Modify: `es_ingest.py`

- [ ] **Step 1: `_build_suffix_script()` için failing test yaz**

```python
# tests/test_es_ingest.py — yoksa yeni dosya oluştur, varsa EKLE

import es_ingest


def test_build_suffix_script_returns_string():
    """_build_suffix_script bir string (Painless kodu) döner."""
    result = es_ingest._build_suffix_script(["ltd", "limited", "inc"])
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_suffix_script_contains_generic_tokens():
    """Script içinde generic token listesi bulunmalı."""
    result = es_ingest._build_suffix_script(["ltd", "limited"])
    assert "'ltd'" in result
    assert "'limited'" in result


def test_build_suffix_script_sets_variations_suffix():
    """Script ctx.variations_suffix'i set etmeli."""
    result = es_ingest._build_suffix_script(["ltd"])
    assert "ctx.variations_suffix" in result


def test_build_suffix_script_uses_generic_set_contains():
    """Script generic token'ları IÇEREN token'ları toplamalı (excluded değil)."""
    result = es_ingest._build_suffix_script(["ltd"])
    # Stripped script'in tersine: contains yerine NOT contains yok
    # "genericSet.contains(token)" olmalı
    assert "genericSet.contains(token)" in result


def test_build_pipeline_body_has_three_processors():
    """Pipeline body 3 processor içermeli: clean, stripped, suffix."""
    body = es_ingest.build_pipeline_body()
    assert len(body["processors"]) == 3


def test_build_pipeline_body_suffix_processor_last():
    """Suffix processor en son gelmeli."""
    body = es_ingest.build_pipeline_body()
    last_proc = body["processors"][-1]
    assert "script" in last_proc
    assert "variations_suffix" in last_proc["script"]["source"]
```

- [ ] **Step 2: Test çalıştır — FAIL bekliyoruz**

```bash
python -m pytest tests/test_es_ingest.py -v
```

Beklenen: `AttributeError: module 'es_ingest' has no attribute '_build_suffix_script'`

- [ ] **Step 3: `_build_suffix_script()` fonksiyonunu ekle**

`es_ingest.py`'de `_build_stripped_script()` fonksiyonunun hemen altına yeni fonksiyon ekle:

```python
def _build_suffix_script(generic_tokens: list[str]) -> str:
    """
    Painless script: variations'tan sadece generic (suffix) token'ları toplayarak
    variations_suffix array'ini oluşturur. _build_stripped_script() tersine —
    generic SET'te OLAN token'ları tutar, position-independent (sorted).
    """
    tokens_literal = ", ".join(f"'{t}'" for t in generic_tokens)

    script_parts = [
        "List genericTokens = [" + tokens_literal + "];",
        "Set genericSet = new HashSet(genericTokens);",
        "if (ctx.variations == null) { return; }",
        "List suffixes = new ArrayList();",
        "for (int i = 0; i < ctx.variations.size(); i++) {",
        "  String text = ctx.variations[i];",
        r"  def tokens = / /.split(text);",
        "  List suffixTokens = new ArrayList();",
        "  for (int t = 0; t < tokens.length; t++) {",
        "    String token = /[.]/.matcher(tokens[t]).replaceAll('').trim();",
        "    if (token.length() > 0 && genericSet.contains(token)) {",
        "      suffixTokens.add(token);",
        "    }",
        "  }",
        "  Collections.sort(suffixTokens);",
        "  StringBuilder sb = new StringBuilder();",
        "  for (int s = 0; s < suffixTokens.size(); s++) {",
        "    if (s > 0) { sb.append(' '); }",
        "    sb.append(suffixTokens[s]);",
        "  }",
        "  String result = sb.toString().trim();",
        "  if (!suffixes.contains(result)) {",
        "    suffixes.add(result);",
        "  }",
        "}",
        "ctx.variations_suffix = suffixes;",
    ]

    return "\n".join(script_parts)
```

- [ ] **Step 4: `build_pipeline_body()` içine yeni processor ekle**

`build_pipeline_body()` fonksiyonunda `common_generic` listesini bul (zaten var). `processors` listesine üçüncü eleman olarak suffix processor ekle:

```python
    return {
        "description": "Firma ismi temizleme ve normalizasyon pipeline'i",
        "processors": [
            {
                "script": {
                    "description": "light_clean: ...",
                    "source": _build_clean_script(),
                }
            },
            {
                "script": {
                    "description": "stripped_form: generic token'lari kaldir",
                    "source": _build_stripped_script(common_generic),
                }
            },
            {
                "script": {                                          # YENİ
                    "description": "suffix_form: sadece generic token'lari tut",
                    "source": _build_suffix_script(common_generic),
                }
            },
        ],
    }
```

- [ ] **Step 5: Test çalıştır — PASS bekliyoruz**

```bash
python -m pytest tests/test_es_ingest.py -v
```

Beklenen: 6 test PASS

- [ ] **Step 6: Commit**

```bash
git add es_ingest.py tests/test_es_ingest.py
git commit -m "feat: add variations_suffix Painless script to ingest pipeline"
```

---

## Task 4: es_queries.py — SUFFIX_FUZZY sorgu fonksiyonu

**Files:**
- Modify: `es_queries.py`
- Test: `tests/test_es_queries.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_es_queries.py — mevcut dosyaya EKLE

def test_suffix_fuzzy_structure():
    """SUFFIX_FUZZY query'si must + should içermeli."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    bool_q = q["query"]["bool"]
    assert "must" in bool_q, "must clause eksik"
    assert "should" in bool_q, "should clause eksik"
    assert _get_country_filter(q) == "TR"
    assert q.get("size") == 1


def test_suffix_fuzzy_must_queries_variations_stripped():
    """must clause variations_stripped alanını sorgulamalı."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    must = q["query"]["bool"]["must"]
    stripped_clauses = [
        c["match"]["variations_stripped"]
        for c in must
        if "match" in c and "variations_stripped" in c["match"]
    ]
    assert stripped_clauses, "variations_stripped match clause yok"
    clause = stripped_clauses[0]
    assert clause["query"] == "komerci limted"
    assert clause["analyzer"] == "stripped_search_analyzer"
    assert clause["operator"] == "or"
    assert clause["minimum_should_match"] == 1


def test_suffix_fuzzy_should_queries_variations_suffix_with_fuzziness():
    """should clause variations_suffix alanını fuzzy sorgulamalı."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    should = q["query"]["bool"]["should"]
    suffix_clauses = [
        c["match"]["variations_suffix"]
        for c in should
        if "match" in c and "variations_suffix" in c["match"]
    ]
    assert suffix_clauses, "variations_suffix fuzzy clause yok"
    clause = suffix_clauses[0]
    assert clause["fuzziness"] == "AUTO:4,7"
    assert clause["operator"] == "or"


def test_suffix_fuzzy_includes_country_filter():
    """SUFFIX_FUZZY country filter içermeli."""
    q = es_queries.SUFFIX_FUZZY("acme limted", "DE")
    assert _get_country_filter(q) == "DE"


```

**Not:** `test_all_queries_include_country_filter` zaten `test_es_queries.py`'de mevcut. Yeni fonksiyon EKLEME — sadece `fns` listesine şu satırı ekle:

```python
        lambda: es_queries.SUFFIX_FUZZY(name, country),   # YENİ
```

- [ ] **Step 2: Test çalıştır — FAIL bekliyoruz**

```bash
python -m pytest tests/test_es_queries.py::test_suffix_fuzzy_structure tests/test_es_queries.py::test_suffix_fuzzy_must_queries_variations_stripped tests/test_es_queries.py::test_suffix_fuzzy_should_queries_variations_suffix_with_fuzziness tests/test_es_queries.py::test_suffix_fuzzy_includes_country_filter -v
```

Beklenen: `AttributeError: module 'es_queries' has no attribute 'SUFFIX_FUZZY'`

- [ ] **Step 3: SUFFIX_FUZZY fonksiyonunu ekle**

`es_queries.py`'de `STRIPPED_EXACT()` fonksiyonunun hemen altına ekle:

```python
def SUFFIX_FUZZY(name: str, country: str, **kwargs) -> dict:
    """
    Suffix fuzzy eşleştirme:
      - must: variations_stripped'a operator:or match (name kısmının doğru olduğunu garanti eder)
      - should: variations_suffix'e fuzziness AUTO:4,7 (suffix typo'larını yakalar)

    Örnek: "Komerci Limted" → "Komerci Limited" eşleşir (suffix typo)
           "Kommerci Limted" → "Komerci Limited" eşleşmez (name typo)
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "variations_stripped": {
                                "query": name,
                                "analyzer": "stripped_search_analyzer",
                                "operator": "or",
                                "minimum_should_match": 1,
                            }
                        }
                    }
                ],
                "should": [
                    {
                        "match": {
                            "variations_suffix": {
                                "query": name,
                                "fuzziness": "AUTO:4,7",
                                "operator": "or",
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

- [ ] **Step 4: Test çalıştır — PASS bekliyoruz**

```bash
python -m pytest tests/test_es_queries.py -v
```

Beklenen: Tüm testler PASS (eskiler + yeni 4)

- [ ] **Step 5: config.py test çalıştır — PASS bekliyoruz**

```bash
python -m pytest tests/test_config.py::test_stage_query_fns_exist_in_es_queries -v
```

Beklenen: PASS — artık `SUFFIX_FUZZY` fonksiyonu `es_queries.py`'de var

- [ ] **Step 6: Commit**

```bash
git add es_queries.py tests/test_es_queries.py
git commit -m "feat: add SUFFIX_FUZZY query function to es_queries"
```

---

## Task 5: main_processor.py — `_post_verify()` SUFFIX_FUZZY branch

**Files:**
- Modify: `main_processor.py`
- Test: `tests/test_main_processor.py`

- [ ] **Step 1: Failing test yaz**

```python
# tests/test_main_processor.py — mevcut dosyaya EKLE

def test_post_verify_suffix_fuzzy_passes_when_name_matches():
    """SUFFIX_FUZZY: name token'ları doc stripped'da >= 85% örtüşünce True döner."""
    import main_processor as mp

    # "Komerci Limted" → doc variations_stripped = ["komerci"]
    # input_meaningful = {"komerci"} (suffix "limited/ltd" çıkarıldı)
    # doc_name_tokens = {"komerci"}
    # coverage = 1.0 >= 0.85 → True
    doc_source = {
        "variations": ["komerci limited"],
        "variations_stripped": ["komerci"],
    }
    result = mp._post_verify("Komerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is True


def test_post_verify_suffix_fuzzy_fails_when_name_differs():
    """SUFFIX_FUZZY: name token'ları < 85% örtüşünce False döner."""
    import main_processor as mp

    # "Kommerci Limted" → input_meaningful = {"kommerci"}
    # doc_name_tokens = {"komerci"}
    # coverage = 0.0 < 0.85 → False
    doc_source = {
        "variations": ["komerci limited"],
        "variations_stripped": ["komerci"],
    }
    result = mp._post_verify("Kommerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is False


def test_post_verify_suffix_fuzzy_passes_with_multiple_name_tokens():
    """SUFFIX_FUZZY: çok tokenlı isimde yüksek coverage True döner."""
    import main_processor as mp

    # "Komerci Trading Limted" → input_meaningful = {"komerci", "trading"}
    # doc stripped = "komerci trading"
    # coverage = 2/2 = 1.0 → True
    doc_source = {
        "variations": ["komerci trading limited"],
        "variations_stripped": ["komerci trading"],
    }
    result = mp._post_verify("Komerci Trading Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is True


def test_post_verify_suffix_fuzzy_fails_when_doc_stripped_empty():
    """SUFFIX_FUZZY: doc variations_stripped boşsa False döner."""
    import main_processor as mp

    doc_source = {
        "variations": ["limited"],
        "variations_stripped": [],
    }
    result = mp._post_verify("Komerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is False
```

- [ ] **Step 2: Test çalıştır — FAIL bekliyoruz**

```bash
python -m pytest tests/test_main_processor.py::test_post_verify_suffix_fuzzy_passes_when_name_matches tests/test_main_processor.py::test_post_verify_suffix_fuzzy_fails_when_name_differs tests/test_main_processor.py::test_post_verify_suffix_fuzzy_passes_with_multiple_name_tokens tests/test_main_processor.py::test_post_verify_suffix_fuzzy_fails_when_doc_stripped_empty -v
```

Beklenen: FAIL — `_post_verify()` henüz SUFFIX_FUZZY bilmiyor (stage tanımsız olduğunda `return True` mu `return False` mu döner test gösterir)

- [ ] **Step 3: `_post_verify()` içine SUFFIX_FUZZY branch ekle**

`main_processor.py`'de `_post_verify()` fonksiyonunu bul (satır ~336). Mevcut branch'ler:

```python
    # CANONICAL_EXACT / STRIPPED_EXACT: siki kontrol
    if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
        ...

    # TOKEN_COVERAGE, FUZZY_PHRASE, NGRAM_MATCH: standart esik
    if stage_name in ("TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"):
        ...

    return True
```

`CANONICAL_EXACT / STRIPPED_EXACT` bloğunun hemen altına, `TOKEN_COVERAGE` bloğundan önce ekle:

```python
    # SUFFIX_FUZZY: name kısmı (suffix çıkarılmış) doc stripped ile örtüşmeli
    if stage_name == "SUFFIX_FUZZY":
        doc_stripped_raw = master_source.get("variations_stripped", [])
        doc_stripped = doc_stripped_raw[0] if isinstance(doc_stripped_raw, list) and doc_stripped_raw else (doc_stripped_raw if isinstance(doc_stripped_raw, str) else "")
        doc_name_tokens = set(doc_stripped.split()) if doc_stripped else set()
        if not doc_name_tokens:
            return False
        coverage = len(input_meaningful & doc_name_tokens) / len(doc_name_tokens)
        return coverage >= 0.85
```

**Dikkat:** Bu kod `input_meaningful` değişkenini kullanır. `input_meaningful` şu an `_post_verify()` içinde `suffix_tokens = set(_SUFFIX_NORMALIZE.values())` ile hesaplanıyor. SUFFIX_FUZZY branch'ini bu hesaplamadan SONRA, diğer branch'lerle aynı bölgeye ekle.

- [ ] **Step 4: Test çalıştır — PASS bekliyoruz**

```bash
python -m pytest tests/test_main_processor.py -v
```

Beklenen: Tüm testler PASS

- [ ] **Step 5: Tüm testleri çalıştır**

```bash
python -m pytest tests/ -v
```

Beklenen: Tüm testler PASS

- [ ] **Step 6: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "feat: add SUFFIX_FUZZY verification branch to _post_verify"
```

---

## Task 6: Index Rebuild ve Smoke Test

**Files:** Değişiklik yok — sadece ES operasyonları

**Not:** Bu task için ES ve PostgreSQL çalışıyor olmalı.

- [ ] **Step 1: Index yeniden oluştur**

```bash
python es_manager.py --force
```

Beklenen çıktı:
```
Index 'living_companies_v1' silindi.
X ulke icin per-country analyzer olusturuluyor...
Index 'living_companies_v1' olusturuldu: ...
```

- [ ] **Step 2: Mapping'de variations_suffix alanını doğrula**

```bash
python -c "
from es_manager import get_es_client
from config import ES_INDEX
es = get_es_client()
mapping = es.indices.get_mapping(index=ES_INDEX)
props = mapping[ES_INDEX]['mappings']['properties']
assert 'variations_suffix' in props, 'HATA: variations_suffix yok!'
print('OK: variations_suffix mapping ES index icinde mevcut')
print('  type:', props['variations_suffix']['type'])
print('  analyzer:', props['variations_suffix']['analyzer'])
"
```

Beklenen:
```
OK: variations_suffix mapping ES index icinde mevcut
  type: text
  analyzer: standard
```

- [ ] **Step 3: Ingest pipeline'ı kaydet**

```bash
python es_ingest.py
```

Beklenen: `Pipeline 'company_name_clean' basariyla kaydedildi.`

- [ ] **Step 4: Pipeline'ın üç processor içerdiğini doğrula**

```bash
python -c "
from es_manager import get_es_client
es = get_es_client()
pipeline = es.ingest.get_pipeline(id='company_name_clean')
procs = pipeline['company_name_clean']['processors']
print(f'Processor sayisi: {len(procs)}')
assert len(procs) == 3, f'HATA: 3 beklendi, {len(procs)} bulundu'
last_desc = procs[-1]['script']['description']
print(f'Son processor: {last_desc}')
assert 'suffix' in last_desc.lower(), 'HATA: Son processor suffix degil'
print('OK: Pipeline 3 processor iceriyor, son processor suffix')
"
```

Beklenen:
```
Processor sayisi: 3
Son processor: suffix_form: sadece generic token'lari tut
OK: Pipeline 3 processor iceriyor, son processor suffix
```

- [ ] **Step 5: Smoke test — tek kayıt manuel index**

```bash
python -c "
from es_manager import get_es_client
from config import ES_INDEX

es = get_es_client()

doc = {
    'master_id': 'test-suffix-001',
    'country_code': 'TR',
    'tax_number': '',
    'phone_number': '',
    'variations': ['Komerci Limited'],
}

es.index(
    index=ES_INDEX,
    id='test-suffix-001',
    routing='TR',
    pipeline='company_name_clean',
    body=doc,
)
es.indices.refresh(index=ES_INDEX)

result = es.get(index=ES_INDEX, id='test-suffix-001', routing='TR')
src = result['_source']
print('variations_suffix:', src.get('variations_suffix'))
print('variations_stripped:', src.get('variations_stripped'))
assert src.get('variations_suffix'), 'HATA: variations_suffix bos'
assert 'limited' in str(src['variations_suffix']), 'HATA: limited suffix yok'
print('OK: Smoke test gecti')

# Temizle
es.delete(index=ES_INDEX, id='test-suffix-001', routing='TR')
"
```

Beklenen:
```
variations_suffix: ['limited']
variations_stripped: ['komerci']
OK: Smoke test gecti
```

- [ ] **Step 6: SUFFIX_FUZZY sorgusu smoke test**

```bash
python -c "
from es_manager import get_es_client
from config import ES_INDEX
import es_queries

es = get_es_client()

# Test dokümanı index'le
doc = {
    'master_id': 'test-suffix-002',
    'country_code': 'TR',
    'tax_number': '',
    'phone_number': '',
    'variations': ['Komerci Limited'],
}
es.index(index=ES_INDEX, id='test-suffix-002', routing='TR',
         pipeline='company_name_clean', body=doc)
es.indices.refresh(index=ES_INDEX)

# SUFFIX_FUZZY sorgusu — typo'lu suffix ile ara
query = es_queries.SUFFIX_FUZZY('Komerci Limted', 'TR')
result = es.search(index=ES_INDEX, routing='TR', body=query)
hits = result['hits']['hits']

print(f'Hit sayisi: {len(hits)}')
if hits:
    print(f'Top hit: {hits[0][\"_source\"][\"master_id\"]} score={hits[0][\"_score\"]:.2f}')
    assert hits[0]['_source']['master_id'] == 'test-suffix-002'
    print('OK: SUFFIX_FUZZY dogru kaydi buldu')
else:
    print('WARN: Hit bulunamadi — min_score veya suffix token sorunu olabilir')

# Temizle
es.delete(index=ES_INDEX, id='test-suffix-002', routing='TR')
"
```

Beklenen:
```
Hit sayisi: 1
Top hit: test-suffix-002 score=X.XX
OK: SUFFIX_FUZZY dogru kaydi buldu
```

Eğer hit bulunamazsa: `SUFFIX_FUZZY_MIN_SCORE` değerini `config.py`'de düşür (1.5 → 0.5) ve Stage min_score'u da düşür (1.5 → 0.5), sonra tekrar dene.

- [ ] **Step 7: Final commit**

```bash
git add .
git commit -m "chore: verify SUFFIX_FUZZY integration with ES smoke test"
```

---

## Özet Akış

```
Task 1: config.py → MatchType + sabitler + STAGES (order güncelleme)
Task 2: es_manager.py → variations_suffix field mapping
Task 3: es_ingest.py → _build_suffix_script() + 3. processor
Task 4: es_queries.py → SUFFIX_FUZZY() fonksiyonu
Task 5: main_processor.py → _post_verify() SUFFIX_FUZZY branch
Task 6: ES rebuild + smoke test
```

Tüm testler geçtikten sonra `python main_processor.py` ile normal batch işlemi çalıştırılabilir.
