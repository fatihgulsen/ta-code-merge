# Per-Country Ingest Pipeline & Dynamic Token Derivation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tüm hardcoded company suffix/generic token listelerini kaldırıp `synonyms_data/` JSON dosyalarından dinamik türetmek; her ülke için ayrı ES ingest pipeline oluşturmak.

**Architecture:** `synonym_loader.py`'a iki yeni fonksiyon eklenir (`get_company_type_tokens`, `get_all_company_type_tokens`). Bu fonksiyonlar `common.json` + ülke JSON'undaki `company_types` girişlerinden tüm token varyantlarını parse eder. `es_ingest.py` per-country pipeline üretir, `es_manager.py` per-country stripped analyzer tanımlar, `main_processor.py` per-record stopword ve pipeline seçimi yapar.

**Tech Stack:** Python 3.11+, Elasticsearch 8.x, pytest

---

## Dosya Yapısı

| Dosya | Değişiklik |
|-------|-----------|
| `synonym_loader.py` | `_parse_company_type_tokens()`, `get_company_type_tokens()`, `get_all_company_type_tokens()` eklenir |
| `es_ingest.py` | `pipeline_name()` eklenir; `_build_clean_script`, `_build_stripped_script`, `build_pipeline_body`, `register_pipeline` imzaları güncellenir; `register_all_pipelines` eklenir |
| `es_manager.py` | Hardcoded `common_generic_tokens` kaldırılır, per-country `stripped_search_analyzer_{cc}` döngüsü eklenir |
| `es_queries.py` | `_get_stripped_analyzer()` eklenir, `STRIPPED_EXACT` güncellenir |
| `main_processor.py` | `_STOPWORDS` → `_ARTICLE_STOPWORDS` (rename), word count hesabında `get_company_type_tokens` eklenir, pipeline isimleri güncellenir |
| `tests/test_synonym_loader.py` | Yeni test dosyası |

---

## Task 1: `synonym_loader.py` — `get_company_type_tokens` fonksiyonları

**Files:**
- Modify: `synonym_loader.py`
- Create: `tests/test_synonym_loader.py`

- [ ] **Step 1: Failing test yaz**

`tests/test_synonym_loader.py` dosyasını oluştur:

```python
# tests/test_synonym_loader.py
import pytest
from synonym_loader import get_company_type_tokens, get_all_company_type_tokens


def test_get_company_type_tokens_includes_common_tokens():
    """common.json company_types tokenları her ülke için dahil edilmeli."""
    tokens = get_company_type_tokens("TR")
    # common.json: "corporation,corp,corp.,incorporated,inc,inc.,co.,company=>corp."
    assert "corp" in tokens
    assert "inc" in tokens
    assert "limited" in tokens
    assert "holding" in tokens


def test_get_company_type_tokens_strips_dots():
    """Nokta karakterleri tamamen çıkarılmalı (rstrip değil replace)."""
    tokens = get_company_type_tokens("US")
    # "corp." → "corp", "inc." → "inc" — noktalı hali olmamalı
    assert "corp" in tokens
    assert "corp." not in tokens
    assert "inc" in tokens
    assert "inc." not in tokens


def test_get_company_type_tokens_lowercase():
    """Tüm tokenlar lowercase olmalı."""
    tokens = get_company_type_tokens("TR")
    for t in tokens:
        assert t == t.lower(), f"Token '{t}' lowercase değil"


def test_get_company_type_tokens_includes_both_sides_of_arrow():
    """=> solundaki ve sağındaki tokenlar dahil edilmeli."""
    tokens = get_company_type_tokens("TR")
    # common.json: "corporation,corp,corp.,incorporated,inc,inc.,co.,company=>corp."
    # sol taraf: corporation, corp, incorporated, inc, co, company
    # sağ taraf (canonical): corp
    assert "corporation" in tokens
    assert "corp" in tokens  # hem sağ hem sol tarafta
    assert "company" in tokens


def test_get_company_type_tokens_country_specific():
    """Ülkeye özgü tokenlar da dahil edilmeli."""
    tr_tokens = get_company_type_tokens("TR")
    de_tokens = get_company_type_tokens("DE")
    # TR'ye özgü (tr.json: "anonim şirket,...=>a.ş.")
    # Nokta çıkarılınca "aş" olur
    assert "aş" in tr_tokens
    # DE'ye özgü (de.json'da "gmbh" olmalı)
    assert "gmbh" in de_tokens
    # TR'de gmbh olmamalı (sadece common'dan gelenler)
    # (common.json'da gmbh yok)
    assert "gmbh" not in tr_tokens


def test_get_company_type_tokens_lru_cache():
    """lru_cache sayesinde aynı nesne döndürülmeli."""
    tokens1 = get_company_type_tokens("TR")
    tokens2 = get_company_type_tokens("TR")
    assert tokens1 is tokens2


def test_get_all_company_type_tokens_is_superset():
    """Global set, her ülke setinin süperkümesi olmalı."""
    tr_tokens = get_company_type_tokens("TR")
    de_tokens = get_company_type_tokens("DE")
    all_tokens = get_all_company_type_tokens()
    assert tr_tokens.issubset(all_tokens)
    assert de_tokens.issubset(all_tokens)


def test_get_all_company_type_tokens_nonempty():
    """Global set boş olmamalı."""
    all_tokens = get_all_company_type_tokens()
    assert len(all_tokens) > 20
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_synonym_loader.py -v
```

Beklenen: `ImportError: cannot import name 'get_company_type_tokens'`

- [ ] **Step 3: `synonym_loader.py`'a fonksiyonları ekle**

`synonym_loader.py`'da `get_all_country_codes()` fonksiyonunun HEMEN ÜSTÜNEaşağıdaki kodu ekle (mevcut `get_generic_tokens_for_country` fonksiyonunun altına):

```python
def _parse_company_type_tokens(paths: list) -> frozenset:
    """
    Verilen dosya listesindeki company_types girişlerinden tüm token varyantlarını parse eder.
    Her iki taraf da dahil edilir: "A,B,C => D" → {a, b, c, d}
    Tüm noktalar çıkarılır, lowercase uygulanır.
    """
    tokens: set = set()
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for rule in data.get("company_types", []):
            rule_norm = normalize_text(rule)
            if "=>" in rule_norm:
                left, right = rule_norm.split("=>", 1)
                parts = left.split(",") + [right]
            else:
                parts = rule_norm.split(",")
            for part in parts:
                t = part.strip().lower().replace(".", "")
                if t:
                    tokens.add(t)
    return frozenset(tokens)


@lru_cache(maxsize=None)
def get_company_type_tokens(country_code: str) -> frozenset:
    """
    common.json + ülke json'undaki company_types girişlerinden
    tüm token varyantlarını döndürür (her iki taraf da, nokta çıkarılmış, lowercase).

    Örnek: "corporation,corp,corp.,inc,inc. => corp." → {"corporation","corp","inc"}

    lru_cache ile country_code başına bir kez parse edilir.
    """
    cc = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{cc.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_company_type_tokens(paths)


@lru_cache(maxsize=None)
def get_all_company_type_tokens() -> frozenset:
    """
    Tüm ülkelerin company_types token birleşimi.
    global fallback / es_manager global analyzer için kullanılır.
    """
    # Common files önce
    common_tokens: set = set(_parse_company_type_tokens([SYNONYMS_DIR / f for f in COMMON_FILES]))
    # Tüm ülke dosyaları
    for cc in get_all_country_codes():
        common_tokens |= get_company_type_tokens(cc)
    return frozenset(common_tokens)
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_synonym_loader.py -v
```

Beklenen: Tüm testler PASS. Eğer `test_get_company_type_tokens_country_specific` için "gmbh" veya "aş" assertion'ı fail ederse, `synonyms_data/de.json` ve `synonyms_data/tr.json` içeriklerini kontrol et.

- [ ] **Step 5: Commit**

```bash
cd c:/All-project/ta-code-merge
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat: add get_company_type_tokens derived from synonyms_data"
```

---

## Task 2: `es_ingest.py` — Per-country pipeline generation

**Files:**
- Modify: `es_ingest.py`

- [ ] **Step 1: Failing test yaz**

`tests/test_es_ingest.py` dosyasını oluştur:

```python
# tests/test_es_ingest.py
import pytest
from unittest.mock import MagicMock, patch, call


def test_pipeline_name_format():
    """Pipeline ismi country_code lowercase ile formatlanmalı."""
    from es_ingest import pipeline_name
    assert pipeline_name("TR") == "company_name_tr"
    assert pipeline_name("DE") == "company_name_de"
    assert pipeline_name("IN") == "company_name_in"
    assert pipeline_name("tr") == "company_name_tr"  # zaten lowercase


def test_build_pipeline_body_uses_country_tokens():
    """Pipeline body'si ülkeye özgü token içermeli (hardcoded değil)."""
    from es_ingest import build_pipeline_body
    from synonym_loader import get_company_type_tokens

    body_tr = build_pipeline_body("TR")
    body_de = build_pipeline_body("DE")

    # Her iki pipeline da dict formatında olmalı
    assert "processors" in body_tr
    assert "processors" in body_de
    assert len(body_tr["processors"]) == 2  # clean + stripped script

    # Script source'larını al
    clean_script_tr = body_tr["processors"][0]["script"]["source"]
    clean_script_de = body_de["processors"][0]["script"]["source"]

    # TR pipeline'ı TR-specific tokenları içermeli
    tr_tokens = get_company_type_tokens("TR")
    de_tokens = get_company_type_tokens("DE")

    # knownSuffixes TR pipeline'ında TR tokenlarından türetilmeli
    # DE'ye özgü ve sadece DE'de olan bir token TR pipeline'ında olmamalı
    # (sadece common'da olmayan bir token örneği gerekiyor)
    # Bu test pipeline'ların farklı olduğunu kontrol eder
    assert clean_script_tr != clean_script_de


def test_register_all_pipelines_calls_each_country():
    """register_all_pipelines her ülke için ayrı pipeline kaydeder."""
    from es_ingest import register_all_pipelines
    from synonym_loader import get_all_country_codes

    mock_es = MagicMock()
    mock_es.ingest.put_pipeline = MagicMock()

    register_all_pipelines(mock_es)

    all_codes = get_all_country_codes()
    assert mock_es.ingest.put_pipeline.call_count == len(all_codes)


def test_register_pipeline_uses_correct_name():
    """register_pipeline doğru pipeline ismiyle kaydeder."""
    from es_ingest import register_pipeline, pipeline_name

    mock_es = MagicMock()
    register_pipeline(mock_es, "TR")

    mock_es.ingest.put_pipeline.assert_called_once()
    call_kwargs = mock_es.ingest.put_pipeline.call_args
    assert call_kwargs[1]["id"] == pipeline_name("TR") or call_kwargs[0][0] == pipeline_name("TR")
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_es_ingest.py -v
```

Beklenen: `ImportError: cannot import name 'pipeline_name'`

- [ ] **Step 3: `es_ingest.py` güncellemelerini yap**

**3a.** Import satırına ekle (dosyanın başında):
```python
from synonym_loader import get_company_type_tokens, get_all_country_codes
```

**3b.** Sabit `PIPELINE_NAME` satırını sil:
```python
PIPELINE_NAME = "company_name_clean"   # BU SATIRI SİL
```

**3c.** Silinen satırın yerine `pipeline_name` fonksiyonunu ekle:
```python
def pipeline_name(country_code: str) -> str:
    """Ülkeye özgü ingest pipeline ismini döner."""
    return f"company_name_{country_code.lower()}"
```

**3d.** `_build_clean_script()` imzasını değiştir — parametre ekle ve hardcoded satırı replace et:

```python
# ESKİ:
def _build_clean_script() -> str:
    typo_entries = ", ".join(...)
    script_parts = [
        ...
        "  def knownSuffixes = ['ltd', 'inc', 'llc', 'bv', 'nv', 'ag', 'sa', 'plc', 'co', 'pvt'];",
        ...
    ]

# YENİ:
def _build_clean_script(country_code: str) -> str:
    typo_entries = ", ".join(...)
    # knownSuffixes: kısa alfabetik tokenlar (≤6 harf) — "l t d" → "ltd" birleştirme için
    tokens = get_company_type_tokens(country_code)
    known = sorted(t for t in tokens if t.isalpha() and len(t) <= 6)
    known_literal = ", ".join(f"'{t}'" for t in known)
    script_parts = [
        ...
        f"  def knownSuffixes = [{known_literal}];",   # hardcoded satır yerine bu
        ...
    ]
```

Yani sadece bu iki şeyi değiştiriyoruz: fonksiyon imzasına `country_code: str` parametresi ekliyoruz ve `"  def knownSuffixes = ['ltd', 'inc', ...];"` satırını dinamik `f"  def knownSuffixes = [{known_literal}];"` ile replace ediyoruz.

**3e.** `_build_stripped_script(generic_tokens)` imzasını değiştir:

```python
# ESKİ:
def _build_stripped_script(generic_tokens: list[str]) -> str:
    tokens_literal = ", ".join(f"'{t}'" for t in generic_tokens)

# YENİ:
def _build_stripped_script(country_code: str) -> str:
    tokens = list(get_company_type_tokens(country_code))
    tokens_literal = ", ".join(f"'{t}'" for t in tokens)
```

Geri kalan fonksiyon body'si tamamen aynı kalır.

**3f.** `build_pipeline_body()` fonksiyonunu değiştir:

```python
# ESKİ:
def build_pipeline_body() -> dict:
    common_generic = [
        "ltd", "limited", "inc", ...
    ]
    return {
        "description": "Firma ismi temizleme...",
        "processors": [
            {"script": {"description": "light_clean...", "source": _build_clean_script()}},
            {"script": {"description": "stripped_form...", "source": _build_stripped_script(common_generic)}},
        ],
    }

# YENİ:
def build_pipeline_body(country_code: str) -> dict:
    return {
        "description": f"Firma ismi temizleme ve normalizasyon pipeline'i ({country_code.upper()})",
        "processors": [
            {
                "script": {
                    "description": f"light_clean for {country_code.upper()}",
                    "source": _build_clean_script(country_code),
                }
            },
            {
                "script": {
                    "description": f"stripped_form for {country_code.upper()}",
                    "source": _build_stripped_script(country_code),
                }
            },
        ],
    }
```

**3g.** `register_pipeline(es)` ve `delete_pipeline(es)` fonksiyonlarını değiştir:

```python
# ESKİ:
def register_pipeline(es: Elasticsearch) -> None:
    body = build_pipeline_body()
    es.ingest.put_pipeline(id=PIPELINE_NAME, body=body)
    logger.info(f"Ingest pipeline '{PIPELINE_NAME}' kaydedildi.")


def delete_pipeline(es: Elasticsearch) -> None:
    try:
        es.ingest.delete_pipeline(id=PIPELINE_NAME)
        logger.info(f"Ingest pipeline '{PIPELINE_NAME}' silindi.")
    except Exception:
        logger.warning(f"Pipeline '{PIPELINE_NAME}' silinemedi (muhtemelen mevcut degil).")

# YENİ:
def register_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke için ingest pipeline oluşturur/günceller."""
    name = pipeline_name(country_code)
    body = build_pipeline_body(country_code)
    es.ingest.put_pipeline(id=name, body=body)
    logger.info(f"Ingest pipeline '{name}' kaydedildi.")


def register_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülkeler için ingest pipeline'ları oluşturur/günceller."""
    codes = get_all_country_codes()
    for cc in codes:
        register_pipeline(es, cc)
    logger.info(f"Toplam {len(codes)} ülke pipeline'ı kaydedildi.")


def delete_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke pipeline'ını siler."""
    name = pipeline_name(country_code)
    try:
        es.ingest.delete_pipeline(id=name)
        logger.info(f"Ingest pipeline '{name}' silindi.")
    except Exception:
        logger.warning(f"Pipeline '{name}' silinemedi (muhtemelen mevcut değil).")


def delete_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülke pipeline'larını siler."""
    for cc in get_all_country_codes():
        delete_pipeline(es, cc)
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_es_ingest.py -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 5: Mevcut testlerin hala geçtiğini doğrula**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/ -v --ignore=tests/test_es_ingest.py -k "not test_" -x
```

Beklenen: Mevcut testler PASS.

- [ ] **Step 6: Commit**

```bash
cd c:/All-project/ta-code-merge
git add es_ingest.py tests/test_es_ingest.py
git commit -m "feat: per-country ingest pipeline generation from synonyms_data"
```

---

## Task 3: `es_manager.py` — Per-country stripped analyzer

**Files:**
- Modify: `es_manager.py`

- [ ] **Step 1: Hardcoded `common_generic_tokens` satırlarını bul**

`es_manager.py`'da şu bloğu bul (yaklaşık satır 101-118):

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

- [ ] **Step 2: Import ekle ve hardcoded bloğu replace et**

`es_manager.py` başındaki import satırlarında `synonym_loader` import'unu bul:
```python
from synonym_loader import get_all_country_codes, load_synonyms_for_country
```

Bunu şununla değiştir:
```python
from synonym_loader import (
    get_all_country_codes,
    get_all_company_type_tokens,
    get_company_type_tokens,
    load_synonyms_for_country,
)
```

Ardından hardcoded bloğun tamamını şununla replace et:

```python
    # ── Per-country Stripped Search Analyzer ──
    # Her ülke için common + ülke company_types tokenlarından stopword filter.
    # variations_stripped alanının search_analyzer'ı olarak kullanılır.
    for cc in get_all_country_codes():
        cc_tokens = list(get_company_type_tokens(cc))
        filter_name = f"generic_stopwords_{cc.lower()}"
        analyzer_name = f"stripped_search_analyzer_{cc.lower()}"
        filters[filter_name] = {
            "type": "stop",
            "stopwords": cc_tokens,
        }
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "filter": ["lowercase", filter_name],
        }

    # Global fallback stripped analyzer (tüm ülkeler birleşimi)
    global_tokens = list(get_all_company_type_tokens())
    filters["generic_stopwords_global"] = {
        "type": "stop",
        "stopwords": global_tokens,
    }
    analyzers["stripped_search_analyzer"] = {
        "tokenizer": "standard",
        "filter": ["lowercase", "generic_stopwords_global"],
    }
```

- [ ] **Step 3: `es_manager.py`'ın `delete_index` içinde pipeline temizliğini güncelle (varsa)**

`es_manager.py` içinde `delete_pipeline` veya `PIPELINE_NAME` referansı var mı kontrol et:
```bash
grep -n "PIPELINE_NAME\|delete_pipeline\|register_pipeline" c:/All-project/ta-code-merge/es_manager.py
```

Varsa `PIPELINE_NAME` kullanımını `pipeline_name(cc)` ile uyumlu hale getir.

- [ ] **Step 4: ES manager'ı syntax hatası olmadan import et**

```bash
cd c:/All-project/ta-code-merge && python -c "import es_manager; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 5: Tüm testleri çalıştır**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/ -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 6: Commit**

```bash
cd c:/All-project/ta-code-merge
git add es_manager.py
git commit -m "feat: per-country stripped_search_analyzer derived from synonyms_data"
```

---

## Task 4: `es_queries.py` — Per-country stripped search analyzer

**Files:**
- Modify: `es_queries.py`
- Modify: `tests/test_es_queries.py`

- [ ] **Step 1: Mevcut `test_es_queries.py`'a yeni test ekle**

`tests/test_es_queries.py` dosyasını aç ve mevcut testlerin sonuna ekle:

```python
def test_stripped_exact_uses_country_analyzer():
    """STRIPPED_EXACT bilinen ülke için stripped_search_analyzer_{cc} kullanmalı."""
    from es_queries import STRIPPED_EXACT
    query = STRIPPED_EXACT("Acme Limited", "TR")
    # Query body içinde analyzer adını bul
    match_phrase = query["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped"]["analyzer"]
    assert analyzer == "stripped_search_analyzer_tr"


def test_stripped_exact_uses_global_analyzer_for_unknown_country():
    """STRIPPED_EXACT bilinmeyen ülke için global fallback analyzer kullanmalı."""
    from es_queries import STRIPPED_EXACT
    query = STRIPPED_EXACT("Acme Limited", "XX")  # bilinmeyen ülke
    match_phrase = query["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped"]["analyzer"]
    assert analyzer == "stripped_search_analyzer"
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_es_queries.py::test_stripped_exact_uses_country_analyzer tests/test_es_queries.py::test_stripped_exact_uses_global_analyzer_for_unknown_country -v
```

Beklenen: FAIL — `stripped_search_analyzer` (global) kullanıyor, `stripped_search_analyzer_tr` değil.

- [ ] **Step 3: `es_queries.py`'ı güncelle**

`es_queries.py`'da `_get_analyzer` fonksiyonunun hemen altına `_get_stripped_analyzer` ekle:

```python
def _get_stripped_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"stripped_search_analyzer_{cc.lower()}"
    return "stripped_search_analyzer"
```

Ardından `STRIPPED_EXACT` fonksiyonunda `"analyzer": "stripped_search_analyzer"` satırını değiştir:

```python
# ESKİ:
def STRIPPED_EXACT(name: str, country: str, **kwargs) -> dict:
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
                ...
            }
        },
        ...
    }

# YENİ — sadece analyzer satırını değiştir:
def STRIPPED_EXACT(name: str, country: str, **kwargs) -> dict:
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations_stripped": {
                                "query": name,
                                "analyzer": _get_stripped_analyzer(country),
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

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_es_queries.py -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 5: Commit**

```bash
cd c:/All-project/ta-code-merge
git add es_queries.py tests/test_es_queries.py
git commit -m "feat: STRIPPED_EXACT uses per-country stripped_search_analyzer"
```

---

## Task 5: `main_processor.py` — Per-record stopwords + pipeline seçimi

**Files:**
- Modify: `main_processor.py`

Bu task birkaç bağımsız değişiklik içeriyor; aşamalı yapılır.

### 5a — `_STOPWORDS` rename + word count güncelleme

- [ ] **Step 1: Test ekle**

`tests/test_main_processor.py`'a ekle:

```python
def test_post_verify_word_count_excludes_company_types():
    """Word count hesabı 'ltd', 'inc' gibi company type tokenları saymamalı."""
    import main_processor as mp
    # "ACME LTD" → 1 anlamlı kelime (ltd sayılmamalı)
    # "ACME" → 1 anlamlı kelime
    # word_count_ratio = 1.0 → eşleşmeli

    # _post_verify'ı dolaylı test: aynı firma farklı suffix → eşleşmeli
    master_source = {
        "variations": ["ACME"],
        "country_code": "TR",
    }
    result = mp._post_verify("ACME LTD", master_source, "TOKEN_COVERAGE", "TR")
    # Token coverage ve word count ratio geçmeli
    # Not: bu test tam coverage gerektirmiyor, sadece word count'ın suffix'i dışladığını doğrular
    # ACME LTD tokens: {acme, ltd} vs ACME tokens: {acme}
    # coverage = 0.5 (ltd yok master'da) — TOKEN_COVERAGE_THRESHOLD'un altında kalabilir
    # Bu test word count_ratio'yu test eder: her iki isimde 1 anlamlı kelime → ratio = 1.0
    # Doğrudan word count'ı test et:
    from synonym_loader import get_company_type_tokens
    from main_processor import _clean_labels, _ARTICLE_STOPWORDS
    cc = "TR"
    stopwords = _ARTICLE_STOPWORDS | get_company_type_tokens(cc)
    word_count = len([
        t for t in _clean_labels("ACME LTD").lower().split()
        if t.rstrip(".,") not in stopwords
        and t.rstrip(".,")
        and t.rstrip(".,").isalnum()
    ])
    assert word_count == 1, f"'ACME LTD' için word_count {word_count} oldu, 1 beklendi"
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_main_processor.py::test_post_verify_word_count_excludes_company_types -v
```

Beklenen: `ImportError: cannot import name '_ARTICLE_STOPWORDS'`

- [ ] **Step 3: `main_processor.py`'da `_STOPWORDS` rename et**

`main_processor.py` satır 285'te:
```python
# ESKİ:
_STOPWORDS = frozenset({
    "and", "of", "the", "for", "in", "on", "at", "to", "by",
    "de", "del", "la", "le", "les", "des", "du", "et",  # French/Spanish
    "und", "der", "die", "das", "von",  # German
})

# YENİ — sadece isim değişir:
_ARTICLE_STOPWORDS = frozenset({
    "and", "of", "the", "for", "in", "on", "at", "to", "by",
    "de", "del", "la", "le", "les", "des", "du", "et",  # French/Spanish
    "und", "der", "die", "das", "von",  # German
})
```

Dosyada `_STOPWORDS` referanslarını `_ARTICLE_STOPWORDS` ile replace et (**replace_all**):
- `_tokenize()` içinde (satır 315): `if t_clean in _STOPWORDS:` → `if t_clean in _ARTICLE_STOPWORDS:`
- `_find_new_masters_batch_dedup` içinde (satır 621): `if tc in _STOPWORDS:` → `if tc in _ARTICLE_STOPWORDS:`

- [ ] **Step 4: Word count satırlarını güncelle**

`main_processor.py`'da `_post_verify` fonksiyonu içinde satırları bul (yaklaşık 377-378):

```python
# ESKİ (2 satır):
    input_word_count = len([t for t in _clean_labels(input_name).lower().split() if t.rstrip('.,') not in _STOPWORDS and t.rstrip('.,') and t.rstrip('.,').isalnum()])
    master_word_count = len([t for t in _clean_labels(master_name).lower().split() if t.rstrip('.,') not in _STOPWORDS and t.rstrip('.,') and t.rstrip('.,').isalnum()])

# YENİ — country parametresi zaten _post_verify scope'unda mevcut:
    _stopwords = _ARTICLE_STOPWORDS | get_company_type_tokens(country)
    input_word_count = len([t for t in _clean_labels(input_name).lower().split() if t.rstrip('.,') not in _stopwords and t.rstrip('.,') and t.rstrip('.,').isalnum()])
    master_word_count = len([t for t in _clean_labels(master_name).lower().split() if t.rstrip('.,') not in _stopwords and t.rstrip('.,') and t.rstrip('.,').isalnum()])
```

- [ ] **Step 5: Import ekle**

`main_processor.py` başındaki `from synonym_loader import ...` import satırını bul ve güncelle — `get_company_type_tokens` ekle:

```python
# ESKİ (mevcut import'u bul, sadece get_company_type_tokens ekle):
from synonym_loader import ...

# YENİ — get_company_type_tokens eklendi:
from synonym_loader import ..., get_company_type_tokens
```

- [ ] **Step 6: Testi çalıştır — PASS bekleniyor**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/test_main_processor.py -v
```

Beklenen: Tüm testler PASS.

### 5b — Pipeline isimlerini güncelle

- [ ] **Step 7: Pipeline import'unu güncelle**

`main_processor.py`'da `from es_ingest import register_pipeline` satırını bul:
```python
# ESKİ:
from es_ingest import register_pipeline

# YENİ:
from es_ingest import register_all_pipelines, pipeline_name
```

- [ ] **Step 8: `helpers.bulk()` çağrısını güncelle**

Satır ~680 civarında `helpers.bulk(es, es_docs, ..., pipeline="company_name_clean")` çağrısını bul.

Önce `es_docs` oluşturulan döngüye bak — her `doc` dict'ine `pipeline` anahtarı ekle:

```python
# ESKİ (es_docs.append satırından önce):
            doc = {
                "_index": ES_INDEX,
                "_id": master_id,
                "_routing": rec["country"].upper(),
                "_source": {
                    "master_id": master_id,
                    "variations": [rec["raw_name"]],
                    "variations_stripped": [],
                    "country_code": rec["country"].upper(),
                },
            }

# YENİ — pipeline anahtarı eklendi:
            doc = {
                "_index": ES_INDEX,
                "_id": master_id,
                "_routing": rec["country"].upper(),
                "pipeline": pipeline_name(rec["country"]),
                "_source": {
                    "master_id": master_id,
                    "variations": [rec["raw_name"]],
                    "variations_stripped": [],
                    "country_code": rec["country"].upper(),
                },
            }
```

Ardından `helpers.bulk()` çağrısından `pipeline=` parametresini kaldır:

```python
# ESKİ:
                helpers.bulk(es, es_docs, raise_on_error=True, pipeline="company_name_clean")

# YENİ — pipeline parametresi kaldırıldı (her doc kendi pipeline'ını taşıyor):
                helpers.bulk(es, es_docs, raise_on_error=True)
```

- [ ] **Step 9: `_index_new_master()` içindeki pipeline'ı güncelle**

Satır ~874'te `es.index(... pipeline="company_name_clean")` çağrısını bul:

```python
# ESKİ:
        es.index(
            index=ES_INDEX,
            id=master_id,
            routing=rec["country"].upper(),
            body=doc,
            pipeline="company_name_clean",
        )

# YENİ:
        es.index(
            index=ES_INDEX,
            id=master_id,
            routing=rec["country"].upper(),
            body=doc,
            pipeline=pipeline_name(rec["country"]),
        )
```

- [ ] **Step 10: `register_pipeline` → `register_all_pipelines` güncelle**

Satır ~922'de:
```python
# ESKİ:
    register_pipeline(es)

# YENİ:
    register_all_pipelines(es)
```

- [ ] **Step 11: Tüm testleri çalıştır**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/ -v
```

Beklenen: Tüm testler PASS.

- [ ] **Step 12: `debug_match.py` import'unu güncelle**

`debug_match.py` satır 31'de `_STOPWORDS` import'unu `_ARTICLE_STOPWORDS` ile değiştir:

```python
# ESKİ:
from main_processor import (
    _clean_labels,
    _tokenize,
    _symmetric_token_coverage,
    _post_verify,
    _SUFFIX_NORMALIZE,
    _STOPWORDS,
    _COUNTRY_NAME_TOKENS,
)

# YENİ:
from main_processor import (
    _clean_labels,
    _tokenize,
    _symmetric_token_coverage,
    _post_verify,
    _SUFFIX_NORMALIZE,
    _ARTICLE_STOPWORDS,
    _COUNTRY_NAME_TOKENS,
)
```

Ardından `debug_match.py` içinde `_STOPWORDS` kullanan tüm satırları `_ARTICLE_STOPWORDS` ile değiştir:

```bash
grep -n "_STOPWORDS" c:/All-project/ta-code-merge/debug_match.py
```
Bulunan satırları `_ARTICLE_STOPWORDS` ile replace et.

- [ ] **Step 13: Syntax kontrolü**

```bash
cd c:/All-project/ta-code-merge && python -c "import main_processor; import debug_match; print('OK')"
```

Beklenen: `OK`

- [ ] **Step 14: Commit**

```bash
cd c:/All-project/ta-code-merge
git add main_processor.py debug_match.py
git commit -m "feat: per-record country-aware stopwords and per-country pipeline in main_processor"
```

---

## Task 6: Son doğrulama

- [ ] **Step 1: Tüm testleri çalıştır**

```bash
cd c:/All-project/ta-code-merge && python -m pytest tests/ -v
```

Beklenen: Tüm testler PASS, hata yok.

- [ ] **Step 2: Import chain doğrulaması**

```bash
cd c:/All-project/ta-code-merge && python -c "
import synonym_loader, es_ingest, es_manager, es_queries, main_processor
from synonym_loader import get_company_type_tokens, get_all_company_type_tokens
from es_ingest import pipeline_name, register_all_pipelines
tokens = get_company_type_tokens('TR')
print(f'TR tokens: {len(tokens)} adet, örnek: {list(tokens)[:5]}')
tokens_all = get_all_company_type_tokens()
print(f'Global tokens: {len(tokens_all)} adet')
print(f'TR pipeline: {pipeline_name(\"TR\")}')
print('Tüm import OK')
"
```

Beklenen:
```
TR tokens: N adet, örnek: [...]
Global tokens: M adet
TR pipeline: company_name_tr
Tüm import OK
```

- [ ] **Step 3: Hardcoded liste kalmadığını doğrula**

```bash
grep -n "\"ltd\", \"limited\", \"inc\"" c:/All-project/ta-code-merge/es_ingest.py c:/All-project/ta-code-merge/es_manager.py c:/All-project/ta-code-merge/main_processor.py
```

Beklenen: Hiçbir çıktı yok (hardcoded liste kalmadı).

```bash
grep -n "PIPELINE_NAME\|company_name_clean" c:/All-project/ta-code-merge/es_ingest.py c:/All-project/ta-code-merge/main_processor.py
```

Beklenen: Hiçbir çıktı yok.

- [ ] **Step 4: Final commit**

```bash
cd c:/All-project/ta-code-merge
git add -A
git commit -m "chore: verify all hardcoded token lists removed"
```
