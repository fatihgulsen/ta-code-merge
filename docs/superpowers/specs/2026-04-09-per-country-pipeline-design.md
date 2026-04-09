# Per-Country Ingest Pipeline & Dynamic Token Derivation — Design Spec
**Date:** 2026-04-09  
**Project:** ta-code-merge (Firma Eşleştirme Sistemi)

---

## Amaç

Sistemdeki tüm hardcoded company suffix/generic token listelerini kaldırıp `synonyms_data/` JSON dosyalarından otomatik türetmek. Her ülke için ayrı ES ingest pipeline oluşturarak `variations_stripped` alanını ülkeye özgü token setiyle hesaplamak.

**Kaldırılan sabit listeler:**

| Dosya | Sabit | Kullanım |
|-------|-------|----------|
| `es_ingest.py:90` | `knownSuffixes` (Painless) | "l t d" → "ltd" birleştirme |
| `es_ingest.py:188` | `common_generic` | `variations_stripped` oluşturma |
| `es_manager.py:104` | `common_generic_tokens` | ES stopword filter |
| `main_processor.py:285` | `_STOPWORDS` frozenset | TOKEN_COVERAGE hesaplama |

**Yeni tek kaynak:** `synonym_loader.get_company_type_tokens(country_code)` — `common.json` + ülke JSON'u birleştirerek döndürür.

---

## Mimari Özet

```
synonyms_data/
  common.json  ──────────────────────────────────────────────┐
  tr.json  ──┐                                               │
  de.json  ──┤  synonym_loader.get_company_type_tokens(cc)  │
  in.json  ──┘  → common tokens ∪ ülke tokens               │
                      │                                      │
                      ├──→ es_ingest.py                      │
                      │    pipeline_company_tr               │
                      │    pipeline_company_de               │
                      │    pipeline_company_in  ...          │
                      │                                      │
                      ├──→ es_manager.py                     │
                      │    stripped_search_analyzer_tr       │
                      │    stripped_search_analyzer_de ...   │
                      │                                      │
                      └──→ main_processor.py                 │
                           per-record country-aware lookup   │
```

---

## Bölüm 1: `synonym_loader.py` Değişiklikleri

### Yeni fonksiyonlar

```python
from functools import lru_cache

@lru_cache(maxsize=None)
def get_company_type_tokens(country_code: str) -> frozenset[str]:
    """
    common.json + ülke json'undaki company_types girişlerinden
    tüm token varyantlarını döndürür.

    "corporation,corp,corp.,incorporated,inc,inc. => corp."
    → {"corporation", "corp", "incorporated", "inc"}
    => solundaki her token alınır, nokta strip edilir, lowercase.
    Sağ taraf (canonical form) da eklenir.

    lru_cache ile country_code başına bir kez parse edilir.
    """

@lru_cache(maxsize=None)
def get_all_company_type_tokens() -> frozenset[str]:
    """Tüm ülkelerin birleşimi — global fallback için."""
```

### Parse mantığı

`company_types` satırı: `"corporation,corp,corp.,inc => corp."`
- `=>` ile split edilir
- Sol taraftaki her virgülle ayrılmış token alınır
- Nokta strip edilir, lowercase uygulanır
- Sağ taraftaki canonical form da token setine eklenir

---

## Bölüm 2: `es_ingest.py` Değişiklikleri

### Pipeline isimlendirme

```python
def pipeline_name(country_code: str) -> str:
    return f"company_name_{country_code.lower()}"
```

### Script fonksiyonlarına country_code parametresi

```python
def _build_clean_script(country_code: str) -> str:
    tokens = get_company_type_tokens(country_code)
    # Sadece kısa alfabetik tokenlar knownSuffixes için (≤6 harf, nokta yok)
    known = sorted(t for t in tokens if t.isalpha() and len(t) <= 6)
    known_literal = "'" + "','".join(known) + "'"
    # Painless: def knownSuffixes = ['ltd','inc','llc',...];
    ...

def _build_stripped_script(country_code: str) -> str:
    tokens = list(get_company_type_tokens(country_code))
    # Mevcut _build_stripped_script(generic_tokens) imzasıyla aynı mantık
    ...
```

### Pipeline registration

```python
def register_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke için pipeline oluşturur/günceller."""
    pipeline_def = {
        "description": f"Company name normalization for {country_code}",
        "processors": [
            {"lowercase": {"field": "variations", "ignore_missing": True}},
            {"script": {"source": _build_clean_script(country_code)}},
            {"script": {"source": _build_stripped_script(country_code)}},
        ]
    }
    es.ingest.put_pipeline(id=pipeline_name(country_code), body=pipeline_def)

def register_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülkeler için pipeline'ları oluşturur."""
    for cc in get_all_country_codes():
        register_pipeline(es, cc)
```

### `main_processor.py`'da pipeline seçimi

```python
# Index ederken ülkeye göre doğru pipeline
es.index(..., pipeline=pipeline_name(row["country_code"]))
```

---

## Bölüm 3: `es_manager.py` Değişiklikleri

### Per-country stripped analyzer

```python
# Her ülke için ayrı stopword filter + stripped_search_analyzer
for cc in get_all_country_codes():
    tokens = list(get_company_type_tokens(cc))
    filter_name = f"generic_stopwords_{cc}"
    analyzer_name = f"stripped_search_analyzer_{cc}"

    filters[filter_name] = {"type": "stop", "stopwords": tokens}
    analyzers[analyzer_name] = {
        "tokenizer": "standard",
        "filter": ["lowercase", filter_name],
    }

# Global fallback (geriye dönük uyumluluk)
filters["generic_stopwords_global"] = {
    "type": "stop",
    "stopwords": list(get_all_company_type_tokens()),
}
analyzers["stripped_search_analyzer"] = {
    "tokenizer": "standard",
    "filter": ["lowercase", "generic_stopwords_global"],
}
```

### `es_queries.py`'da search_analyzer

`variations_stripped` alanı için sorgu zaman analyzer `stripped_search_analyzer_{cc}` olarak belirtilir. `country_code` zaten routing üzerinden query'e geliyor.

---

## Bölüm 4: `main_processor.py` Değişiklikleri

### `_STOPWORDS` kaldırılır

```python
# Kaldırılır:
_STOPWORDS = frozenset({"ltd", "limited", "inc", ...})

# Yerine import:
from synonym_loader import get_company_type_tokens
```

### Kullanım noktaları

**Token coverage hesaplama:**
```python
stopwords = get_company_type_tokens(country_code)
word_count = len([
    t for t in tokens
    if t.rstrip(".,") not in stopwords
    and t.rstrip(".,")
    and t.rstrip(".,").isalnum()
])
```

**Eşleşme doğrulaması:**
```python
stopwords = get_company_type_tokens(row["country_code"])
if t_clean in stopwords:
    continue
```

`lru_cache` sayesinde aynı ülke için parse işlemi yalnızca bir kez yapılır.

---

## Değişmeyen Kurallar

- `synonyms_data/*.json` dosyaları **SABIT** — içeriklerine dokunulmaz, sadece okunur
- Country hard filter korunur — farklı ülke eşleşmesi yapılmaz
- `MatchType` isimleri değişmez
- ES index mapping yapısı değişmez (`variations`, `variations_stripped` alanları aynı kalır)

---

## Etkilenen Dosyalar

| Dosya | Değişiklik Tipi |
|-------|----------------|
| `synonym_loader.py` | Yeni fonksiyonlar eklenir |
| `es_ingest.py` | Per-country pipeline generation |
| `es_manager.py` | Per-country stripped analyzer |
| `main_processor.py` | `_STOPWORDS` → per-record lookup |
| `es_queries.py` | search_analyzer per-country |

## Etkilenmeyen Dosyalar

`config.py`, `matcher_logic.py`, `synonym_normalizer.py`, `debug_match.py`, `synonyms_data/`
