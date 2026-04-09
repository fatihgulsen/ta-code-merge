# Suffix Fuzzy Match — Design Spec
**Date:** 2026-04-09  
**Project:** ta-code-merge (Firma Eşleştirme Sistemi)

---

## Amaç

Firma isimlerindeki suffix/company type token'larında yazım hataları olabilir (`Limited` → `Limted`, `Company` → `Compny`). Bu hataları tüm varyantları synonym dosyalarına eklemeden ES'in built-in fuzzy mekanizması ile yakalamak.

**Temel kural:**
- Suffix'te harf hatası → aynı firma (`Komerci Limited` = `Komerci Limted`) ✓
- Firma isminde harf hatası → farklı firma (`Komerci Limited` ≠ `Kommerci Limted`) ✗

**Suffix sırası önemli değildir:**
- `Komerci Limited Company` = `Komerci Company Limited` = `Komerci Compny Limted` (suffix typo ile)

---

## Yeni Match Type: `SUFFIX_FUZZY`

| Tip | Skor | Açıklama |
|-----|------|----------|
| TAX_MATCH | 100 | Vergi numarası kesin eşleşmesi |
| CANONICAL_EXACT | 100 | Synonym-aware canonical tam eşleşme |
| STRIPPED_EXACT | 100 | Suffix temizlendikten sonra tam eşleşme |
| **SUFFIX_FUZZY** | **85** | **Name kısmı tam, suffix fuzzy eşleşme** |
| TOKEN_COVERAGE | 90 | Anlamlı token örtüşme eşiği |
| NEW_MASTER | 100 | Eşleşmedi — yeni kayıt |

---

## Mimari

```
Input
  │
  ├── canonical_form() + stripped_form()
  │        │
  │        └── variations_stripped  (mevcut — name kısmı)
  │
  ├── suffix extraction (YENİ)
  │        │
  │        └── variations_suffix    (YENİ — sadece suffix token'ları)
  │
  └── ES Query
           ├── must:   variations_stripped  (operator:or, min_should_match:1)
           └── should: variations_suffix    (fuzziness: AUTO:4,7)
                                │
                           Post-ES Python verification
                                │
                           SUFFIX_FUZZY MatchType
```

---

## Bölüm 1: Yeni ES Alanı — `variations_suffix`

### Field Mapping (`es_manager.py`)

```json
"variations_suffix": {
  "type": "text",
  "analyzer": "standard_lowercase",
  "fields": {
    "keyword": { "type": "keyword" }
  }
}
```

`standard_lowercase`: sadece lowercase + tokenize. Synonym expansion yok, stopword yok. Fuzzy matching ham token'lara karşı çalışsın diye kasıtlı sade tutuldu.

**Not:** Bu analyzer `es_manager.py`'daki analyzer tanımlarına eklenmeli — mevcut `standard` analyzer yeterli olabilir, implementation'da kontrol edilmeli.

### Örnekler

| Input | `variations_stripped` | `variations_suffix` |
|---|---|---|
| `"Komerci Limited"` | `"komerci"` | `"limited"` |
| `"Komerci Limited Company"` | `"komerci"` | `"company limited"` |
| `"Komerci Company Limited"` | `"komerci"` | `"company limited"` |
| `"ABC Pvt. Ltd."` | `"abc"` | `"ltd. pvt."` |
| `"Solo Firma"` (suffix yok) | `"solo firma"` | `""` |

**Not:** `variations_suffix` token'ları sorted olarak saklanır — sıra bağımsız eşleşme için.

### Index Rebuild

Alan değişikliği sonrası: `python es_manager.py --force`

---

## Bölüm 2: Ingest Pipeline — `variations_suffix` Hesaplama (`es_ingest.py`)

Mevcut `canonical_form()` ve `stripped_form()` fonksiyonlarının set farkından türetilir:

```python
canonical = canonical_form(name, country_code)
stripped  = stripped_form(canonical, country_code)

# Set farkı — pozisyon bağımsız
canonical_tokens = set(canonical.split())
stripped_tokens  = set(stripped.split())
suffix_tokens    = canonical_tokens - stripped_tokens

variations_suffix = " ".join(sorted(suffix_tokens))
```

### Edge Case'ler

| Durum | Davranış |
|---|---|
| Suffix yok | `variations_suffix: ""` — fuzzy match tetiklenmez |
| Canonical değilse | `canonical_form()` zaten normalize eder |
| Çoklu suffix | Tüm suffix token'ları space-separated olarak saklanır |
| `stripped_form()` suffix typo'yu tanımıyorsa | Index'te `""` — query tarafında ES fuzzy yakalar |

---

## Bölüm 3: Query Yapısı (`matcher_logic.py`)

Python tam query metnini her iki field'a gönderir, ES halleder.

```json
{
  "bool": {
    "must": [
      {
        "match": {
          "variations_stripped": {
            "query": "<full_input>",
            "analyzer": "stripped_search_analyzer",
            "operator": "or",
            "minimum_should_match": 1
          }
        }
      }
    ],
    "should": [
      {
        "match": {
          "variations_suffix": {
            "query": "<full_input>",
            "fuzziness": "AUTO:4,7",
            "operator": "or"
          }
        }
      }
    ]
  }
}
```

### Fuzziness Parametresi

`AUTO:4,7` — kelime uzunluğuna göre otomatik edit distance:
- 1–3 karakter: 0 edit (exact)
- 4–6 karakter: 1 edit (`Ltd` → `Ldt`)
- 7+ karakter: 2 edit (`Limited` → `Limted`, `Limitted`)

### Neden Çalışır

| Senaryo | `variations_stripped` must | `variations_suffix` should | Sonuç |
|---|---|---|---|
| `"Komerci Limted"` → doc `"Komerci Limited"` | "komerci" ✓ (min 1 karşılandı) | "limted" ≈ "limited" ✓ | **SUFFIX_FUZZY** |
| `"Kommerci Limted"` → doc `"Komerci Limited"` | "kommerci" ✗, "limted" ✗ → min 1 karşılanamadı | — | **NO MATCH** |
| `"Komerci Compny Limted"` → doc `"Komerci Limited Company"` | "komerci" ✓ | "compny"≈"company" ✓, "limted"≈"limited" ✓ | **SUFFIX_FUZZY** |
| `"Komerci Limited"` → doc `"Komerci Limited"` | STRIPPED_EXACT zaten yakalar — bu sorgu çalışmaz | — | **STRIPPED_EXACT** |

### `minimum_should_match: 1` Güvenceleri

Gevşek görünen bu eşik iki mekanizma ile korunur:
1. `variations_suffix` fuzzy `should` clause — suffix kısmı ES'te doğrulanır
2. Post-ES Python verification — SUFFIX_FUZZY kesinleştirilir

---

## Bölüm 4: Post-ES Verification & Detection (`matcher_logic.py`)

### Match Type Sırası

```
CANONICAL_EXACT kontrolü → başarısız
STRIPPED_EXACT kontrolü  → başarısız
SUFFIX_FUZZY kontrolü    → ?
  ├─ name token coverage ≥ 85% ?
  ├─ ES score ≥ SUFFIX_FUZZY_MIN_SCORE ?
  └─ ✓ → SUFFIX_FUZZY
TOKEN_COVERAGE kontrolü  → fallback
```

### Verification Mantığı

```python
def check_suffix_fuzzy(query_name: str, doc: dict, es_score: float, country_code: str) -> bool:
    query_stripped = stripped_form(canonical_form(query_name, country_code), country_code)
    doc_stripped   = doc["variations_stripped"]

    query_tokens = set(query_stripped.split())
    doc_tokens   = set(doc_stripped.split())

    if not doc_tokens:
        return False

    # Name token coverage: query'nin name token'ları doc'ta var mı?
    coverage = len(query_tokens & doc_tokens) / len(doc_tokens)
    if coverage < 0.85:
        return False

    # ES yeterli fuzzy score vermiş olmalı
    if es_score < SUFFIX_FUZZY_MIN_SCORE:
        return False

    return True
```

### Coverage Örnekleri

| Query stripped | Doc stripped | Coverage | Sonuç |
|---|---|---|---|
| `"komerci limted"` | `"komerci"` | `{"komerci"}/{"komerci"}` = 1.0 | ✓ |
| `"kommerci"` | `"komerci"` | `{}/{"komerci"}` = 0.0 | ✗ |
| `"komerci trading limted"` | `"komerci trading"` | `{"komerci","trading"}/{"komerci","trading"}` = 1.0 | ✓ |

---

## Bölüm 5: Config Değişiklikleri (`config.py`)

```python
class MatchType:
    TAX_MATCH       = "TAX_MATCH"
    CANONICAL_EXACT = "CANONICAL_EXACT"
    STRIPPED_EXACT  = "STRIPPED_EXACT"
    SUFFIX_FUZZY    = "SUFFIX_FUZZY"    # YENİ
    TOKEN_COVERAGE  = "TOKEN_COVERAGE"
    NEW_MASTER      = "NEW_MASTER"

SUFFIX_FUZZY_MIN_SCORE = 1.5   # ES score eşiği — başlangıç değeri, prod testleriyle kalibre edilmeli
SUFFIX_FUZZY_SCORE     = 85    # match sonucu skoru
```

---

## Etkilenen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `es_manager.py` | `variations_suffix` field mapping + `standard_lowercase` analyzer |
| `es_ingest.py` | Index time'da `variations_suffix` hesaplama (set farkı) |
| `matcher_logic.py` | Yeni SUFFIX_FUZZY sub-query + `check_suffix_fuzzy()` verification |
| `config.py` | `MatchType.SUFFIX_FUZZY`, `SUFFIX_FUZZY_MIN_SCORE`, `SUFFIX_FUZZY_SCORE` |

## Değişmeyen Dosyalar

| Dosya | Neden |
|---|---|
| `synonyms_data/*.json` | SABIT — dokunulmaz |
| `synonym_loader.py` | Değişiklik gerekmez |
| `synonym_normalizer.py` | `canonical_form()` / `stripped_form()` olduğu gibi kullanılır |

---

## Calistirma Sırası (Implementation Sonrası)

```bash
# 1. Index yeniden oluştur (variations_suffix field için)
python es_manager.py --force

# 2. Tüm kayıtları yeniden index'le
python es_ingest.py

# 3. Eşleştirme çalıştır
python main_processor.py

# 4. Güvenlik testleri
python test_safety.py
```
