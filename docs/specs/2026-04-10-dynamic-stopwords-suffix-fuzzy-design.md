# Design: Dynamic Stopwords + Suffix Fuzzy Detection

**Tarih:** 2026-04-10  
**Kapsam:** A-2 (hardcode temizliği) + B-3 (unknown suffix typo detection)

---

## Motivasyon

### A — Hardcoded Python yapılarını kaldır

`main_processor.py`'da iki hardcoded dict/frozenset mevcut:

- `_SUFFIX_NORMALIZE` — "limited → ltd" gibi normalizasyon map'i. `get_company_type_tokens()` ile zaten JSON'dan yönetilen verinin Python kopyası.
- `_ARTICLE_STOPWORDS` — "and, of, the, de, del, …" gibi artikeller. Ülke bazında yönetilemiyor, senkronizasyon riski var.

Hedef: tek kaynak of truth = `synonyms_data/*.json`. Her şey buradan okunur; Python ve ES tutarlı kalır.

### B — Bilinmeyen suffix typo'larını yakala

Mevcut `SUFFIX_TYPO_MAP` sadece elle tanımlanmış typo'ları düzeltir. "limted" gibi bilinen bir örnek SUFFIX_TYPO_MAP'te varsa ingest-time düzeltilir, ama bilinmeyen bir typo varsa:

- İngest pipeline onu suffix olarak tanımaz → `variations_stripped`'a girer
- `_post_verify` phrase check'te `["komerci", "limtdd"] ≠ ["komerci"]` → False döner

Bu durum aynı zamanda **mevcut SUFFIX_FUZZY'yi "Komerci Limted" için de kırıyor** — `"limted"` SUFFIX_NORMALIZE'da olmadığı için `suffix_tokens`'ta yer almıyor ve phrase check'i geçemiyor.

---

## Mimari Değişiklikler

### 1. JSON Format — `"articles"` key

`synonyms_data/common.json`'a yeni key eklenir (synonym formatında değil, düz liste):

```json
{
  "company_types": [ ... ],
  "address_abbreviations": [ ... ],
  "articles": [
    "and", "of", "the", "for", "in", "on", "at", "to", "by",
    "de", "del", "la", "le", "les", "des", "du", "et",
    "und", "der", "die", "das", "von"
  ]
}
```

Ülke dosyaları (örn. `tr.json`, `de.json`) kendi dillerine özgü makaleleri ayrıca tanımlayabilir:

```json
{ "articles": ["ve", "ile", "için", "da", "de", "bir"] }
```

`_extract_rules_from_file()` dokunulmaz — `"articles"` key'ini synonym format beklemediği için zaten skip eder.

### 2. `synonym_loader.py` — `get_article_stopwords()`

```python
@lru_cache(maxsize=None)
def get_article_stopwords(country_code: str) -> frozenset:
    """
    Ülkeye özgü article/stopword listesi döner.
    common.json articles + ülke dosyası articles birleştirilerek hesaplanır.
    """
    stopwords: set[str] = set()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for token in data.get("articles", []):
            t = token.strip().lower()
            if t:
                stopwords.add(t)

    return frozenset(stopwords)
```

### 3. `es_manager.py` — Article'ları stop filter'a ekle

`stripped_search_analyzer_{cc}` (per-country) ve global `stripped_search_analyzer`'ın stop filter'larına article token'ları eklenir:

```python
for cc in get_all_country_codes():
    cc_tokens = list(get_company_type_tokens(cc))
    article_tokens = list(get_article_stopwords(cc))      # YENİ
    filter_name = f"generic_stopwords_{cc.lower()}"
    filters[filter_name] = {
        "type": "stop",
        "stopwords": cc_tokens + article_tokens,          # BİRLEŞİK
    }
    # analyzer tanımı değişmez
```

Global fallback için (`"common"` kodu COMMON_FILES'taki `common.json`'ı okur):
```python
global_tokens = list(get_all_company_type_tokens())
global_articles = list(get_article_stopwords("common"))       # YENİ
filters["generic_stopwords_global"] = {
    "type": "stop",
    "stopwords": global_tokens + global_articles,
}
```

**Not:** Bu değişiklik index rebuild gerektirir (`python es_manager.py --force`).

### 4. `main_processor.py` — `_SUFFIX_NORMALIZE` + `_ARTICLE_STOPWORDS` kaldırma

#### 4a. `_tokenize()` refactor

`_SUFFIX_NORMALIZE` lookup'ı kaldırılır; normalizasyon yerine doğrudan exclusion yapılır:

```python
def _tokenize(name: str, country: str = "") -> set[str]:
    """Firma ismini anlamlı tokenlara ayırır.
    - Küçük harf, suffix ve article token'ları dışlanır
    - Tek char: alfanumerik ise korunur (inisyal/rakam), değilse atlanır
    - country verilirse, ülke adı token'ları çıkarılır
    """
    cleaned = _clean_labels(name)
    tokens = cleaned.lower().split()
    country_tokens = _COUNTRY_NAME_TOKENS.get(country.upper(), frozenset())
    suffix_tokens = get_company_type_tokens(country)
    article_tokens = get_article_stopwords(country)
    result = set()
    for t in tokens:
        t_clean = t.rstrip('.,')
        if not t_clean:
            continue
        if len(t_clean) <= 1 and not t_clean.isalnum():
            continue
        if t_clean in country_tokens:
            continue
        if t_clean in suffix_tokens or t_clean in article_tokens:
            continue
        result.add(t_clean)
    return result
```

**Etki:** `_tokenize()` artık direkt "meaningful" token'ları döner. `_post_verify`'da gereksiz kalan satırlar:
```python
# SİLİNECEK:
suffix_tokens = set(_SUFFIX_NORMALIZE.values())
input_meaningful = input_tokens - suffix_tokens
master_meaningful = master_tokens - suffix_tokens
min_meaningful = min(len(input_meaningful), len(master_meaningful))
```
Yerine direkt `input_tokens` ve `master_tokens` kullanılır.

#### 4b. `_post_verify()` sadeleştirmesi

`_word_count` hesabında da `_ARTICLE_STOPWORDS` → `get_article_stopwords(country)`:

```python
_wc_stopwords = get_article_stopwords(country) | get_company_type_tokens(country)
```

`coverage` / `meaningful_coverage` ikisi artık eşdeğer — `coverage` tek başına yeterli.

### 5. B-3 — Fuzzy suffix detection

#### 5a. `_edit_distance()` yardımcısı

Standart Levenshtein, dış bağımlılık yok:

```python
def _edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]
```

#### 5b. `_is_fuzzy_suffix()` — ES AUTO:4,7 ile tutarlı eşik

```python
def _is_fuzzy_suffix(token: str, suffix_tokens: frozenset) -> bool:
    """Token, bilinen bir suffix'e ES AUTO:4,7 ile eşleşiyor mu?
    - len < 4 : 0 edit (exact)
    - len 4-6 : 1 edit
    - len 7+  : 2 edit
    """
    if token in suffix_tokens:
        return True
    n = len(token)
    max_edits = 0 if n < 4 else (1 if n < 7 else 2)
    if max_edits == 0:
        return False
    for known in suffix_tokens:
        if abs(len(known) - n) > max_edits:
            continue
        if _edit_distance(token, known) <= max_edits:
            return True
    return False
```

#### 5c. `_post_verify()` SUFFIX_FUZZY branch güncelleme

`input_stripped_ordered` inşasında değişen tek satır:

```python
# ESKİ:
# _tn = _SUFFIX_NORMALIZE.get(_tc, _tc)
# if _tn not in suffix_tokens:
#     input_stripped_ordered.append(_tn)

# YENİ:
if not _is_fuzzy_suffix(_tc, suffix_tokens):
    input_stripped_ordered.append(_tc)
```

`suffix_tokens` = `get_company_type_tokens(country)` (artık JSON'dan).

---

## Değişen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `synonyms_data/common.json` | `"articles"` key eklenir |
| `synonyms_data/*.json` (opsiyonel) | Ülkeye özgü `"articles"` key |
| `synonym_loader.py` | `get_article_stopwords()` eklenir |
| `es_manager.py` | Stop filter'lara article ekle |
| `main_processor.py` | `_SUFFIX_NORMALIZE`, `_ARTICLE_STOPWORDS` kaldırılır; `_tokenize()`, `_post_verify()`, `_edit_distance()`, `_is_fuzzy_suffix()` güncellenir |

## Değişmeyen Dosyalar

| Dosya | Neden |
|-------|-------|
| `es_queries.py` | ES sorgu yapısı değişmez |
| `es_ingest.py` | Ingest pipeline değişmez |
| `config.py` | Konfigürasyon değişmez |
| `synonyms_data/*.json` company_types | İçerik değişmez |

---

## Test Senaryoları

| Input | Master | Mevcut | Yeni |
|-------|--------|--------|------|
| "Komerci Limted" | "Komerci Limited" | ❌ False (phrase check) | ✅ True (fuzzy suffix) |
| "Komerci Limtdd" | "Komerci Limited" | ❌ False | ❌ False (distance=3, doğru) |
| "d b corp" | "b d industries" | ❌ False (phrase order) | ❌ False (korunur) |
| "Komerci Ltd" | "Komerci Limited" | ✅ True | ✅ True |
| "Industries of India Ltd" | "Industries India Ltd" | belirsiz (of kalırdı) | ✅ (of artık dışlanır) |

---

## Uygulama Sonrası

```bash
# ES index yeniden oluştur (stop filter değişti)
python es_manager.py --force

# Testler
python test_safety.py
python test_stripped_exact.py
python debug_match.py
```
