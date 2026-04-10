# Dynamic Stopwords + Suffix Fuzzy Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove hardcoded `_SUFFIX_NORMALIZE` / `_ARTICLE_STOPWORDS` from Python by moving article stopwords into JSON synonym files and ES stop filters; add fuzzy suffix typo detection to `_post_verify` so that unknown suffix typos (e.g. "Limted") are correctly excluded from name comparison.

**Architecture:** Articles are added to `common.json` (and optionally per-country JSONs) under a new `"articles"` key. `synonym_loader.get_article_stopwords()` reads them. `es_manager` feeds them into per-country stop filters. `main_processor._tokenize()` replaces `_SUFFIX_NORMALIZE` + `_ARTICLE_STOPWORDS` with calls to `get_company_type_tokens()` + `get_article_stopwords()`. `_post_verify` SUFFIX_FUZZY branch gains a Levenshtein-based fuzzy suffix detector consistent with ES `AUTO:4,7` fuzziness.

**Tech Stack:** Python 3.11, Elasticsearch 8.x, pytest. No new dependencies.

**Design spec:** `docs/specs/2026-04-10-dynamic-stopwords-suffix-fuzzy-design.md`

---

## File Map

| File | Action | Change |
|------|--------|--------|
| `synonyms_data/common.json` | Modify | Add `"articles"` key with global article list |
| `synonym_loader.py` | Modify | Add `get_article_stopwords(country_code)` |
| `tests/test_synonym_loader.py` | Modify | Add tests for `get_article_stopwords` |
| `es_manager.py` | Modify | Merge articles into per-country + global stop filters |
| `tests/test_es_manager.py` | Modify | Add test verifying articles in stop filter |
| `main_processor.py` | Modify | Remove `_SUFFIX_NORMALIZE`, `_ARTICLE_STOPWORDS`; refactor `_tokenize`, `_post_verify`; add `_edit_distance`, `_is_fuzzy_suffix` |
| `tests/test_main_processor.py` | Modify | Add tests for `_edit_distance`, `_is_fuzzy_suffix`, `_tokenize`, `_post_verify` SUFFIX_FUZZY |

---

## Task 1: Add `"articles"` key to `common.json`

**Files:**
- Modify: `synonyms_data/common.json`

- [ ] **Step 1: Add articles key to common.json**

Open `synonyms_data/common.json` and add the `"articles"` key after `"address_abbreviations"`. The full file becomes:

```json
{
  "company_types": [ ... existing content unchanged ... ],
  "address_abbreviations": [ ... existing content unchanged ... ],
  "articles": [
    "and", "of", "the", "for", "in", "on", "at", "to", "by",
    "de", "del", "la", "le", "les", "des", "du", "et",
    "und", "der", "die", "das", "von"
  ]
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python -c "import json; json.load(open('synonyms_data/common.json'))"
```

Expected: no output (no error).

- [ ] **Step 3: Commit**

```bash
git add synonyms_data/common.json
git commit -m "feat: add articles stopword list to common.json"
```

---

## Task 2: Add `get_article_stopwords()` to `synonym_loader.py`

**Files:**
- Modify: `synonym_loader.py`
- Modify: `tests/test_synonym_loader.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_synonym_loader.py`:

```python
from synonym_loader import get_article_stopwords


def test_get_article_stopwords_returns_frozenset():
    result = get_article_stopwords("TR")
    assert isinstance(result, frozenset)


def test_get_article_stopwords_contains_common_articles():
    """common.json articles her ülke için yüklenmeli."""
    result = get_article_stopwords("TR")
    assert "and" in result
    assert "of" in result
    assert "the" in result
    assert "de" in result
    assert "von" in result


def test_get_article_stopwords_unknown_country_returns_common():
    """Ülke dosyası olmayan ülke için sadece common articles döner."""
    result = get_article_stopwords("XX")
    assert "and" in result
    assert isinstance(result, frozenset)


def test_get_article_stopwords_empty_if_no_articles_key():
    """articles key'i olmayan dosya için boş ek döner (ortak yeterli)."""
    # Herhangi bir ülke için common articles mutlaka gelir
    result = get_article_stopwords("US")
    assert len(result) >= 13  # common.json'daki minimum article sayısı


def test_get_article_stopwords_lru_cache():
    """lru_cache sayesinde aynı nesne döndürülmeli."""
    r1 = get_article_stopwords("TR")
    r2 = get_article_stopwords("TR")
    assert r1 is r2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_synonym_loader.py::test_get_article_stopwords_returns_frozenset -v
```

Expected: `ImportError: cannot import name 'get_article_stopwords'`

- [ ] **Step 3: Implement `get_article_stopwords` in `synonym_loader.py`**

Add after the `get_all_company_type_tokens` function (after line ~206):

```python
@lru_cache(maxsize=None)
def get_article_stopwords(country_code: str) -> frozenset:
    """
    Ülkeye özgü article/stopword listesi döner.
    common.json articles + ülke dosyası articles birleştirilerek hesaplanır.

    Dönüş: frozenset (lru_cache için hashable, immutable)
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

- [ ] **Step 4: Run all synonym_loader tests**

```bash
python -m pytest tests/test_synonym_loader.py -v
```

Expected: all tests PASS including the new 5 tests.

- [ ] **Step 5: Commit**

```bash
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat: add get_article_stopwords() to synonym_loader"
```

---

## Task 3: Update `es_manager.py` — add articles to stop filters

**Files:**
- Modify: `es_manager.py`
- Modify: `tests/test_es_manager.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_es_manager.py`:

```python
def test_build_index_settings_includes_articles_in_stop_filter():
    """Per-country stop filter article token'larını içermeli."""
    from synonym_loader import get_article_stopwords
    settings = build_index_settings(es=None)
    filters = settings["settings"]["analysis"]["filter"]

    # TR için stop filter kontrol et
    tr_filter = filters.get("generic_stopwords_tr")
    assert tr_filter is not None
    stopwords = tr_filter["stopwords"]
    assert "and" in stopwords
    assert "of" in stopwords
    assert "the" in stopwords


def test_build_index_settings_global_filter_includes_articles():
    """Global fallback stop filter da article token'larını içermeli."""
    settings = build_index_settings(es=None)
    filters = settings["settings"]["analysis"]["filter"]
    global_filter = filters.get("generic_stopwords_global")
    assert global_filter is not None
    assert "and" in global_filter["stopwords"]
    assert "von" in global_filter["stopwords"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_es_manager.py::test_build_index_settings_includes_articles_in_stop_filter -v
```

Expected: FAIL — "and" not in stopwords.

- [ ] **Step 3: Update `es_manager.py` — add import and per-country filter**

Add `get_article_stopwords` to the import from `synonym_loader` at the top of `es_manager.py`:

```python
from synonym_loader import (
    get_all_country_codes,
    get_all_company_type_tokens,
    get_article_stopwords,          # YENİ
    get_company_type_tokens,
    get_company_type_tokens,
    load_synonyms_for_country,
)
```

In `build_index_settings()`, find the per-country stripped analyzer block (around line 109) and update:

```python
# ── Per-country Stripped Search Analyzer ──
for cc in get_all_country_codes():
    cc_tokens = list(get_company_type_tokens(cc))
    article_tokens = list(get_article_stopwords(cc))          # YENİ
    filter_name = f"generic_stopwords_{cc.lower()}"
    analyzer_name = f"stripped_search_analyzer_{cc.lower()}"
    filters[filter_name] = {
        "type": "stop",
        "stopwords": cc_tokens + article_tokens,              # GÜNCELLENDİ
    }
    analyzers[analyzer_name] = {
        "tokenizer": "standard",
        "filter": ["lowercase", filter_name],
    }
```

Then find the global fallback block (around line 123) and update:

```python
# Global fallback stripped analyzer (tüm ülkeler birleşimi)
global_tokens = list(get_all_company_type_tokens())
global_articles = list(get_article_stopwords("common"))       # YENİ
filters["generic_stopwords_global"] = {
    "type": "stop",
    "stopwords": global_tokens + global_articles,             # GÜNCELLENDİ
}
```

- [ ] **Step 4: Run all es_manager tests**

```bash
python -m pytest tests/test_es_manager.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add es_manager.py tests/test_es_manager.py
git commit -m "feat: add article stopwords to ES per-country and global stop filters"
```

---

## Task 4: Refactor `_tokenize()` — remove `_SUFFIX_NORMALIZE` + `_ARTICLE_STOPWORDS`

**Files:**
- Modify: `main_processor.py` (lines 285–341 bölgesi)
- Modify: `tests/test_main_processor.py`

- [ ] **Step 1: Write failing tests for new `_tokenize` behavior**

Add to `tests/test_main_processor.py`:

```python
from main_processor import _tokenize


def test_tokenize_excludes_suffix_tokens():
    """Suffix token'ları (ltd, corp, inc) sonuç setine girmemeli."""
    result = _tokenize("Komerci Limited", "TR")
    assert "komerci" in result
    assert "limited" not in result
    assert "ltd" not in result


def test_tokenize_excludes_article_tokens():
    """Article token'ları (of, the, and) sonuç setine girmemeli."""
    result = _tokenize("Industries of India Ltd", "IN")
    assert "industries" in result
    assert "india" in result
    assert "of" not in result
    assert "ltd" not in result


def test_tokenize_keeps_initials():
    """Tek harfli alfanumerik token'lar (inisyal/rakam) korunmalı."""
    result = _tokenize("A B Impex Ltd", "IN")
    assert "a" in result
    assert "b" in result
    assert "impex" in result


def test_tokenize_drops_single_non_alnum():
    """Tek harfli non-alnum token'lar (& - .) atlanmalı."""
    result = _tokenize("A & B Corp", "US")
    assert "&" not in result
    assert "a" in result
    assert "b" in result


def test_tokenize_returns_set():
    result = _tokenize("Komerci Ltd", "TR")
    assert isinstance(result, set)
```

- [ ] **Step 2: Run tests to verify they fail (or partially fail)**

```bash
python -m pytest tests/test_main_processor.py::test_tokenize_excludes_article_tokens -v
```

Expected: FAIL — "of" currently stays in set (old `_tokenize` doesn't use `get_article_stopwords`).

- [ ] **Step 3: Update imports in `main_processor.py`**

Find the import block from `synonym_loader` and add `get_article_stopwords`:

```python
from synonym_loader import get_company_type_tokens, get_article_stopwords
```

- [ ] **Step 4: Delete `_SUFFIX_NORMALIZE` and `_ARTICLE_STOPWORDS` constants**

Remove lines 292–311 entirely (the `_SUFFIX_NORMALIZE` dict and `_ARTICLE_STOPWORDS` frozenset).

- [ ] **Step 5: Replace `_tokenize()` body**

Replace the entire `_tokenize` function (lines 314–341) with:

```python
def _tokenize(name: str, country: str = "") -> set[str]:
    """Firma ismini anlamlı tokenlara ayırır.

    - Küçük harf
    - Suffix token'ları dışlanır (get_company_type_tokens)
    - Article token'ları dışlanır (get_article_stopwords)
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

- [ ] **Step 6: Run the new tokenize tests**

```bash
python -m pytest tests/test_main_processor.py -k "tokenize" -v
```

Expected: all 5 tokenize tests PASS.

- [ ] **Step 7: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "refactor: replace _SUFFIX_NORMALIZE/_ARTICLE_STOPWORDS with dynamic get_company_type_tokens/get_article_stopwords in _tokenize"
```

---

## Task 5: Add `_edit_distance()` + `_is_fuzzy_suffix()` helpers

**Files:**
- Modify: `main_processor.py` (insert after `_symmetric_token_coverage`)
- Modify: `tests/test_main_processor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_main_processor.py`:

```python
from main_processor import _edit_distance, _is_fuzzy_suffix


def test_edit_distance_identical():
    assert _edit_distance("limited", "limited") == 0


def test_edit_distance_one_edit():
    assert _edit_distance("limted", "limited") == 1


def test_edit_distance_two_edits():
    assert _edit_distance("limtedd", "limited") == 2


def test_edit_distance_three_edits():
    assert _edit_distance("limtddd", "limited") == 3


def test_edit_distance_empty():
    assert _edit_distance("", "ltd") == 3
    assert _edit_distance("ltd", "") == 3


def test_is_fuzzy_suffix_exact_match():
    suffix_tokens = frozenset(["ltd", "limited", "inc", "corp"])
    assert _is_fuzzy_suffix("ltd", suffix_tokens) is True


def test_is_fuzzy_suffix_one_edit_len6():
    """'limted' (6 chars) → max 1 edit → 'limited' (distance=1) → True."""
    suffix_tokens = frozenset(["limited", "ltd", "corp"])
    assert _is_fuzzy_suffix("limted", suffix_tokens) is True


def test_is_fuzzy_suffix_two_edit_len7():
    """'limtedd' (7 chars) → max 2 edits → 'limited' (distance=2) → True."""
    suffix_tokens = frozenset(["limited", "ltd"])
    assert _is_fuzzy_suffix("limtedd", suffix_tokens) is True


def test_is_fuzzy_suffix_too_many_edits():
    """'limtddd' (7 chars) → max 2 edits → 'limited' (distance=3) → False."""
    suffix_tokens = frozenset(["limited", "ltd"])
    assert _is_fuzzy_suffix("limtddd", suffix_tokens) is False


def test_is_fuzzy_suffix_name_token_not_matched():
    """'komerci' hiçbir suffix'e benzemez → False."""
    suffix_tokens = frozenset(["limited", "ltd", "corp", "inc"])
    assert _is_fuzzy_suffix("komerci", suffix_tokens) is False


def test_is_fuzzy_suffix_short_token_exact_only():
    """3 char → max 0 edit → exact only."""
    suffix_tokens = frozenset(["ltd", "inc"])
    assert _is_fuzzy_suffix("ltd", suffix_tokens) is True
    assert _is_fuzzy_suffix("lte", suffix_tokens) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_main_processor.py -k "edit_distance or fuzzy_suffix" -v
```

Expected: `ImportError: cannot import name '_edit_distance'`

- [ ] **Step 3: Implement `_edit_distance()` and `_is_fuzzy_suffix()`**

Insert after `_symmetric_token_coverage` (after line ~355) in `main_processor.py`:

```python
def _edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance. Dış bağımlılık yok."""
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


def _is_fuzzy_suffix(token: str, suffix_tokens: frozenset) -> bool:
    """Token, bilinen bir suffix'e ES AUTO:4,7 eşiğiyle eşleşiyor mu?

    ES fuzziness AUTO:4,7 ile tutarlı eşik:
      - len < 4  → 0 edit (exact)
      - len 4-6  → max 1 edit
      - len 7+   → max 2 edit
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

- [ ] **Step 4: Run the new helper tests**

```bash
python -m pytest tests/test_main_processor.py -k "edit_distance or fuzzy_suffix" -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "feat: add _edit_distance and _is_fuzzy_suffix helpers for AUTO:4,7 fuzzy suffix detection"
```

---

## Task 6: Refactor `_post_verify()` — simplify + fix SUFFIX_FUZZY branch

**Files:**
- Modify: `main_processor.py` (lines 358–467)
- Modify: `tests/test_main_processor.py`

- [ ] **Step 1: Write failing tests for updated `_post_verify`**

Add to `tests/test_main_processor.py`:

```python
from main_processor import _post_verify


def _make_master(variations, stripped=None, suffix=None):
    src = {"variations": variations}
    if stripped is not None:
        src["variations_stripped"] = stripped
    if suffix is not None:
        src["variations_suffix"] = suffix
    return src


def test_post_verify_suffix_fuzzy_known_typo_passes():
    """'Komerci Limted' → 'limted' fuzzy-matches 'limited' → stripped match → True."""
    master = _make_master(
        variations=["komerci limited"],
        stripped=["komerci"],
        suffix=["limited"],
    )
    assert _post_verify("Komerci Limted", master, "SUFFIX_FUZZY", "IN") is True


def test_post_verify_suffix_fuzzy_exact_suffix_passes():
    """'Komerci Ltd' → exact suffix match → True."""
    master = _make_master(
        variations=["komerci limited"],
        stripped=["komerci"],
        suffix=["limited"],
    )
    assert _post_verify("Komerci Ltd", master, "SUFFIX_FUZZY", "IN") is True


def test_post_verify_suffix_fuzzy_bad_typo_fails():
    """'Komerci Limtddd' → edit distance 3 > threshold → False."""
    master = _make_master(
        variations=["komerci limited"],
        stripped=["komerci"],
        suffix=["limited"],
    )
    assert _post_verify("Komerci Limtddd", master, "SUFFIX_FUZZY", "IN") is False


def test_post_verify_suffix_fuzzy_order_mismatch_fails():
    """'D B Corp' vs master stripped=['b','d'] → phrase sırası farklı → False."""
    master = _make_master(
        variations=["b d industries pvt ltd"],
        stripped=["b", "d"],
        suffix=["pvt", "ltd"],
    )
    assert _post_verify("D B Corp", master, "SUFFIX_FUZZY", "IN") is False


def test_post_verify_suffix_fuzzy_single_token_fails():
    """Tek meaningful token varsa min 2 şartı sağlanmaz → False."""
    master = _make_master(
        variations=["komerci limited"],
        stripped=["komerci"],
        suffix=["limited"],
    )
    assert _post_verify("Komerci Ltd", master, "SUFFIX_FUZZY", "IN") is True
    # Sadece 1 token — False olmalı
    master2 = _make_master(
        variations=["a limited"],
        stripped=["a"],
        suffix=["limited"],
    )
    assert _post_verify("A Ltd", master2, "SUFFIX_FUZZY", "IN") is False


def test_post_verify_articles_excluded_in_suffix_fuzzy():
    """'Industries of India Ltd' stripped ordered → ['industries','india'] == doc."""
    master = _make_master(
        variations=["industries india limited"],
        stripped=["industries", "india"],
        suffix=["limited"],
    )
    assert _post_verify("Industries of India Ltd", master, "SUFFIX_FUZZY", "IN") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_main_processor.py -k "post_verify_suffix_fuzzy" -v
```

Expected: `test_post_verify_suffix_fuzzy_known_typo_passes` FAILs — current code rejects "Limted".

- [ ] **Step 3: Rewrite `_post_verify()`**

Replace the entire `_post_verify` function (lines 358–467) with:

```python
def _post_verify(input_name: str, master_source: dict, stage_name: str, country: str = "") -> bool:
    """Post-ES verification: ES sonucunu Python tarafinda dogrular.

    TAX_EXACT icin dogrulama yapilmaz (deterministic).
    CANONICAL_EXACT/STRIPPED_EXACT icin yuksek simetrik token coverage (>= 0.9).
    TOKEN_COVERAGE/FUZZY_PHRASE/NGRAM_MATCH icin TOKEN_COVERAGE_THRESHOLD.
    SUFFIX_FUZZY icin fuzzy suffix detection + phrase order check.
    country verilirse, ayni ulke adi token'lardan cikarilir.
    """
    if stage_name == "TAX_EXACT":
        return True

    master_variations = master_source.get("variations", [])
    if not master_variations:
        return False
    master_name = master_variations[0]

    # _tokenize artık suffix + article token'larını dışlar → direkt meaningful token'lar
    input_tokens = _tokenize(input_name, country)
    master_tokens = _tokenize(master_name, country)

    if not input_tokens or not master_tokens:
        return False

    min_tokens = min(len(input_tokens), len(master_tokens))

    # ── SUFFIX_FUZZY ──────────────────────────────────────────────────────────
    if stage_name == "SUFFIX_FUZZY":
        doc_stripped_raw = master_source.get("variations_stripped", [])
        if isinstance(doc_stripped_raw, list) and doc_stripped_raw:
            doc_stripped = doc_stripped_raw[0]
        elif isinstance(doc_stripped_raw, str):
            doc_stripped = doc_stripped_raw
        else:
            doc_stripped = ""
        doc_name_tokens_list = doc_stripped.split() if doc_stripped else []
        doc_name_tokens = set(doc_name_tokens_list)
        if not doc_name_tokens or not input_tokens:
            return False
        # Min 2 anlamli token olmali (tek token esleme cok riskli)
        if min(len(input_tokens), len(doc_name_tokens)) < 2:
            return False
        # Simetrik coverage
        coverage = _symmetric_token_coverage(input_tokens, doc_name_tokens)

        # PHRASE + FUZZY-SUFFIX CHECK:
        # input token'larını sırayla tara; suffix token'ı veya suffix'e fuzzy-match
        # edenler dışarıda bırakılır. Geri kalanların sırası doc ile eşleşmeli.
        suffix_tokens = get_company_type_tokens(country)
        article_tokens = get_article_stopwords(country)
        _cleaned = _clean_labels(input_name).lower()
        input_stripped_ordered = []
        for _t in _cleaned.split():
            _tc = _t.rstrip('.,')
            if not _tc or (len(_tc) <= 1 and not _tc.isalnum()):
                continue
            if _tc in article_tokens:
                continue
            if _is_fuzzy_suffix(_tc, suffix_tokens):   # exact OR fuzzy match
                continue
            input_stripped_ordered.append(_tc)
        if input_stripped_ordered != doc_name_tokens_list:
            return False
        return coverage >= SUFFIX_FUZZY_COVERAGE_THRESHOLD

    # ── Diğer stage'ler ───────────────────────────────────────────────────────
    if min_tokens < 2:
        if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
            if input_tokens == master_tokens:
                return True
        return False

    coverage = _symmetric_token_coverage(input_tokens, master_tokens)

    # Token tekrar farkı: "RADHE RADHE CREATION" (3 token) vs "RADHE CREATION" (2 token)
    _wc_stopwords = get_article_stopwords(country) | get_company_type_tokens(country)
    input_word_count = len([
        t for t in _clean_labels(input_name).lower().split()
        if t.rstrip('.,') not in _wc_stopwords and t.rstrip('.,') and t.rstrip('.,').isalnum()
    ])
    master_word_count = len([
        t for t in _clean_labels(master_name).lower().split()
        if t.rstrip('.,') not in _wc_stopwords and t.rstrip('.,') and t.rstrip('.,').isalnum()
    ])
    word_count_ratio = (
        min(input_word_count, master_word_count) / max(input_word_count, master_word_count)
        if max(input_word_count, master_word_count) > 0 else 0.0
    )

    # Uzunluk oranı kontrolu
    len_input = len(_clean_labels(input_name).strip())
    len_master = len(_clean_labels(master_name).strip())
    max_len = max(len_input, len_master)
    len_ratio = min(len_input, len_master) / max_len if max_len > 0 else 0
    if len_ratio < LENGTH_RATIO_THRESHOLD:
        return False

    if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
        if coverage < 0.9:
            return False
        if word_count_ratio < 0.8:
            return False

    if stage_name in ("TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"):
        if coverage < TOKEN_COVERAGE_THRESHOLD:
            return False
        if word_count_ratio < 0.7:
            return False

    return True
```

- [ ] **Step 4: Run all `_post_verify` tests**

```bash
python -m pytest tests/test_main_processor.py -k "post_verify" -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "refactor: simplify _post_verify, fix SUFFIX_FUZZY fuzzy suffix detection"
```

---

## Task 7: ES index rebuild + smoke test

**Files:** None (runtime verification)

- [ ] **Step 1: Rebuild ES index**

```bash
python es_manager.py --force
```

Expected output (no error):
```
XX ulke icin per-country analyzer olusturuluyor...
Index 'companies' olusturuldu: XX ulke analyzer, routing=country_code, ozellikler: synonym, fingerprint, ngram
```

- [ ] **Step 2: Re-register ingest pipelines**

```bash
python es_ingest.py
```

Expected: `Tüm ülke pipeline'ları başarıyla kaydedildi.`

- [ ] **Step 3: Run existing safety and stripped exact tests**

```bash
python test_safety.py && python test_stripped_exact.py
```

Expected: all pass with no failures.

- [ ] **Step 4: Smoke test with debug_match**

Run at minimum two pairs:

```bash
python debug_match.py
```

Verify:
- "Komerci Limted" vs "Komerci Limited" → SUFFIX_FUZZY eşleşmeli
- "D B Corp Ltd" vs "B D Industries Pvt Ltd" → eşleşmemeli (farklı isim)

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "chore: rebuild ES index with article stop filters, verify SUFFIX_FUZZY smoke test"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** JSON articles ✓ | `get_article_stopwords` ✓ | ES stop filter ✓ | `_tokenize` refactor ✓ | `_edit_distance` + `_is_fuzzy_suffix` ✓ | `_post_verify` SUFFIX_FUZZY fix ✓ | index rebuild ✓
- [x] **Placeholder scan:** Tüm test ve kod örnekleri somut, "TBD" yok
- [x] **Type consistency:** `get_article_stopwords` → `frozenset`, `get_company_type_tokens` → `frozenset`, `_is_fuzzy_suffix` → `bool`, `_edit_distance` → `int` — hepsi tutarlı
- [x] **`_post_verify` `meaningful_coverage`:** Kaldırıldı — `_tokenize` zaten meaningful token'lar döndürüyor, `coverage` tek başına yeterli
- [x] **`get_article_stopwords("common")`:** `"common"` kodu `COMMON_FILES` içindeki `common.json`'ı okur → `get_article_stopwords` `country_code.lower()` ile `common.json`'ı zaten `COMMON_FILES` üzerinden yükler, ek ülke dosyası aranmaz → güvenli
