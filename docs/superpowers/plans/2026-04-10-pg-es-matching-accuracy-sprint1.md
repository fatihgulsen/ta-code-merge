# PG ↔ ES Matching Accuracy — Sprint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Sprint 1 guardrails from `2026-04-10-pg-es-matching-accuracy-audit-design.md` — widen `BUSINESS_DESCRIPTORS`, apply the guard in the synonym loader, harden `_post_verify`, stop cascade by flipping three stages to `index_variation=False`, re-register ES pipelines, and add a regression test suite.

**Architecture:** Changes are purely additive on the Python side (no schema migration). The ES ingest pipeline is regenerated with updated tokens and existing docs are updated in-place via `update_by_query`. A new regression test fixture (tests/test_matching_regression.py) pins the behaviour of every known false positive from the spec §2.

**Tech Stack:** Python 3.11+, pytest, psycopg2, elasticsearch-py 8.x, Painless (via ingest pipeline).

**Spec reference:** `docs/superpowers/specs/2026-04-10-pg-es-matching-accuracy-audit-design.md`

---

## File Structure

### Files to create

| Path | Responsibility |
|------|----------------|
| `tests/test_matching_regression.py` | Regression fixture: FP pairs must return `False` from `_post_verify`, TP pairs must return `True`. Unit tests for new helpers (`_first_meaningful_token`). |
| `scripts/sprint1_baseline_snapshot.py` | Capture pre-change metrics (match_type counts, master count, variations per master percentile) to `baseline_<timestamp>.json`. |
| `scripts/sprint1_reindex.py` | Re-register ingest pipelines and run `update_by_query` on the `living_companies_v1` index to recompute `variations_stripped` and `variations_suffix`. Idempotent, logs progress. |

### Files to modify

| Path | Change |
|------|--------|
| `config.py` | Expand `BUSINESS_DESCRIPTORS` frozenset. Flip `index_variation` to `False` for `CANONICAL_EXACT`, `SUFFIX_FUZZY`, `TOKEN_COVERAGE`. |
| `synonym_loader.py` | Subtract `BUSINESS_DESCRIPTORS` at the end of `_parse_company_type_tokens`. |
| `main_processor.py` | Add `_first_meaningful_token` helper. Harden `_post_verify`: remove `min_tokens < 2` loophole, raise CANONICAL/STRIPPED `word_count_ratio` to 0.9, add brand-anchor check for TOKEN_COVERAGE/FUZZY_PHRASE/NGRAM_MATCH, require ≥2 meaningful tokens for SUFFIX_FUZZY. |

No file is expected to grow past the 800-line soft cap. `main_processor.py` is currently 1341 lines — the changes add ~30 lines and the file should be split in Sprint 2, not here.

---

## Task 0: Baseline metrics snapshot

**Files:**
- Create: `scripts/sprint1_baseline_snapshot.py`

- [ ] **Step 1: Create the baseline snapshot script**

Write `scripts/sprint1_baseline_snapshot.py`:

```python
"""Sprint 1 baseline metrics — captures pre-change state for before/after diff."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_CONFIG, RAW_TABLE_NAME  # noqa: E402


def snapshot() -> dict:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {RAW_TABLE_NAME}")
    total = cur.fetchone()[0]

    cur.execute(
        f"SELECT COUNT(*) FROM {RAW_TABLE_NAME} WHERE master_code IS NULL"
    )
    unmatched = cur.fetchone()[0]

    cur.execute(
        f"SELECT COUNT(DISTINCT master_code) FROM {RAW_TABLE_NAME} "
        f"WHERE master_code IS NOT NULL"
    )
    unique_masters = cur.fetchone()[0]

    cur.execute(
        f"SELECT match_type, COUNT(*) FROM {RAW_TABLE_NAME} "
        f"WHERE master_code IS NOT NULL GROUP BY match_type ORDER BY 2 DESC"
    )
    by_type = {row[0]: row[1] for row in cur.fetchall()}

    conn.close()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_rows": total,
        "unmatched": unmatched,
        "unique_masters": unique_masters,
        "matches_by_type": by_type,
    }


def main() -> None:
    data = snapshot()
    out_dir = Path(__file__).resolve().parent.parent / "baselines"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"baseline_{stamp}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Baseline written to {out_file}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the snapshot**

Run: `python scripts/sprint1_baseline_snapshot.py`
Expected: file `baselines/baseline_<timestamp>.json` is created. Stdout shows total_rows ≈ 18_452_901, matches_by_type includes `NEW_MASTER`, `CANONICAL_EXACT`, `STRIPPED_EXACT`, `SUFFIX_FUZZY`.

- [ ] **Step 3: Commit**

```bash
git add scripts/sprint1_baseline_snapshot.py baselines/baseline_*.json
git commit -m "chore: add Sprint 1 baseline metrics snapshot script"
```

---

## Task 1: Regression fixture file — FP and TP pairs

**Files:**
- Create: `tests/test_matching_regression.py`

This task lays down the regression test file with the known false positives from spec §2 and the positive controls from §2.5. All tests in this file are expected to FAIL initially on the FP side (because current code accepts these pairs) and PASS on the TP side. Later tasks drive the FP side to green.

- [ ] **Step 1: Write the regression fixture file with shared helpers and initial TP tests**

Create `tests/test_matching_regression.py`:

```python
"""Regression tests for matching accuracy.

Each false positive from docs/superpowers/specs/2026-04-10-pg-es-matching-accuracy-audit-design.md §2
is encoded as a test case that must return False from _post_verify after Sprint 1.

Each true positive from §2.5 must continue to return True — these guard against recall collapse.
"""
from __future__ import annotations

import pytest


def _master_source(variations: list[str], variations_stripped: list[str] | None = None) -> dict:
    """Build a minimal master doc as returned by Elasticsearch.

    For SUFFIX_FUZZY the _post_verify reads variations_stripped; caller must supply it.
    For the other stages the first element of variations is used as the canonical master name.
    """
    return {
        "variations": variations,
        "variations_stripped": variations_stripped if variations_stripped is not None else [],
    }


# ---- Positive controls (§2.5) -------------------------------------------------
# These are the benign variations the system already handles correctly. They must keep passing.

POSITIVE_CONTROLS_CANONICAL: list[tuple[str, str, str]] = [
    # (country, input_name, master_variation_as_stored_in_ES)
    # NOTE: master_variation must be the POST-ingest-cleaned form, because
    # _post_verify reads master_source["variations"][0] which ES stores after
    # running the clean_script pipeline (lowercase, dot-between-letters removed,
    # punctuation normalised).
    ("IN", "ISHA ENTERPRISES", "isha enterprise."),
    ("IN", "J. J. OVERSEAS", "j j overseas"),
    ("IN", "BALAJI IMPEX ,,", "balaji impex."),
    ("IN", "KRISHNA OVERSEAS .", "krishna overseas,."),
    ("IN", "KT INTERNATIONAL", "kt international"),  # k.t. → kt via ingest
    ("IN", "ARIHANT ENTERPRISES ,,", "arihant enterprise.."),
    ("IN", "J. M. CORPORATION", "j m corporation."),
]


@pytest.mark.parametrize("country,input_name,master_variation", POSITIVE_CONTROLS_CANONICAL)
def test_canonical_exact_positive_controls_still_match(country, input_name, master_variation):
    """True positives from spec §2.5 must continue to return True."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "CANONICAL_EXACT", country) is True


# ---- False positives — CANONICAL_EXACT (§2.1) --------------------------------

FP_CANONICAL: list[tuple[str, str, str]] = [
    ("IN", "JAY CHEMICAL INDUSTRIES PRIVATE LIMITED", "jay & co."),
    ("IN", "IMPERIAL AUTO INDUSTRIES LIMITED", "hotel imperial"),
    ("IN", "AJANTA PHARMA LIMITED", "ajanta industries,"),
    ("IN", "ATUL LIMITED", "atul commodities pvt. ltd."),
    ("IN", "LIFE.", "agri life"),
    ("IN", "ELECTRO", "ag electro services"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_CANONICAL)
def test_canonical_exact_false_positives_rejected(country, input_name, master_variation):
    """False positives from spec §2.1 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "CANONICAL_EXACT", country) is False


# ---- False positives — STRIPPED_EXACT (§2.2) ---------------------------------

FP_STRIPPED: list[tuple[str, str, str]] = [
    ("IN", "GOEL STEEL COMPANY", "goel enterprises.."),
    ("IN", "ANAND TECHNOLOGIES,", "anand enterprises,,_"),
    ("IN", "GLOBAL CARE", "care enterprises"),
    ("IN", "DYNAMIC TRADERS.", "auto dynamic corporation"),
    ("IN", "APEX INDUSTRIES,.", "apex auto limited,"),
    ("IN", "AH CHEMICALS PVT. LTD.", "a.h. international"),
    ("IN", "ARIHANT TRADERS..", "arihant enterprise.."),
    ("IN", "AKSHAYA TEXTILE,", "akshaya corp,"),
    ("IN", "KAMAL INDUSTRIES,", "kamal international."),
    ("IN", "HARSH INTERNATIONAL..", "harsh agencies."),
    ("IN", "AMAN INTERNATIONAL,,", "aman trading co."),
    ("IN", "LAKSHMI METALS", "lakshmi agencies."),
    ("IN", "LAXMI ELECTRONICS.", "laxmi agro industrial consultants and"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_STRIPPED)
def test_stripped_exact_false_positives_rejected(country, input_name, master_variation):
    """False positives from spec §2.2 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "STRIPPED_EXACT", country) is False


# ---- False positives — SUFFIX_FUZZY (§2.3) -----------------------------------
# SUFFIX_FUZZY reads variations_stripped; supply a realistic stripped form.

FP_SUFFIX_FUZZY: list[tuple[str, str, str, list[str]]] = [
    # (country, input_name, master_variation, master_variations_stripped)
    ("IN", "ACE INDUSTRIES-", "ace aviation (prop: john penry evans)", ["ace aviation"]),
    ("IN", "DELTA TEXTTILES", "delta electronics", ["delta electronics"]),
    ("IN", "EXCEL METAL ENGINEERING PVT.LTD,", "excel communications", ["excel communications"]),
    ("IN", "GALAXY INDUSTRIES_", "galaxy.", ["galaxy"]),
    ("IN", "INDIAN CHEMICAL CORPORATION", "indian trading corporation.", ["indian trading"]),
    ("IN", "AGGARWAL ELECTRIC CO.", "aggarwal & co.", ["aggarwal and"]),
    ("IN", "APEX TRADERS,;", "apex auto limited,", ["apex auto"]),
    ("IN", "ANIL ENTERPRISES-", "anil agencies pvt.ltd", ["anil agencies"]),
]


@pytest.mark.parametrize("country,input_name,master_variation,master_stripped", FP_SUFFIX_FUZZY)
def test_suffix_fuzzy_false_positives_rejected(country, input_name, master_variation, master_stripped):
    """False positives from spec §2.3 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation], master_stripped)
    assert mp._post_verify(input_name, master, "SUFFIX_FUZZY", country) is False


# ---- False positives — TOKEN_COVERAGE (§2.4) ---------------------------------

FP_TOKEN_COVERAGE: list[tuple[str, str, str]] = [
    ("IN", "KAY BEE TRADING CO.,", "bee kay enterprises"),
    ("IN", "KAY DEE ENTERPRISES", "dee kay exports"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_TOKEN_COVERAGE)
def test_token_coverage_false_positives_rejected(country, input_name, master_variation):
    """Order-swap false positives from spec §2.4 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "TOKEN_COVERAGE", country) is False
```

- [ ] **Step 2: Run the positive controls — they must pass**

Run: `pytest tests/test_matching_regression.py::test_canonical_exact_positive_controls_still_match -v`
Expected: 7 passed.

- [ ] **Step 3: Run the false-positive tests — they must currently FAIL**

Run: `pytest tests/test_matching_regression.py -k "false_positives_rejected" -v`
Expected: The majority FAIL (current code accepts these). Record the exact pass/fail count in the commit message for later delta tracking. This red state is intentional — Tasks 2-8 drive it to green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_matching_regression.py
git commit -m "test: add Sprint 1 regression fixtures for known matching false positives

Adds parametrized tests for every false positive listed in the audit
design doc §2 plus positive controls from §2.5. False-positive tests
currently FAIL (red state) — Tasks 2-8 drive them to green."
```

---

## Task 2: Widen BUSINESS_DESCRIPTORS

**Files:**
- Modify: `config.py:108-126`
- Modify: `tests/test_config.py` (add new test)

- [ ] **Step 1: Add a failing test for expected descriptor tokens**

Append to `tests/test_config.py` (read the existing file first to keep imports consistent):

```python
def test_business_descriptors_includes_sector_words():
    """Sprint 1: BUSINESS_DESCRIPTORS must include sector differentiators
    so that synonym_loader does not strip them from canonical/stripped forms."""
    from config import BUSINESS_DESCRIPTORS

    required = {
        # tekil/çoğul
        "enterprise", "enterprises", "industry", "industries",
        "holding", "holdings",
        "service", "services", "solution", "solutions",
        "technology", "technologies",
        # ticari roller
        "trader", "traders", "exports", "imports", "export", "import",
        "dealers", "distributors", "suppliers", "agency", "agencies",
        "consultants", "consulting", "associates", "ventures", "systems",
        "overseas",
        # sektör
        "pharma", "pharmaceuticals", "chemicals", "chemical",
        "textiles", "textile", "steel", "metals", "metal",
        "plastics", "packaging", "foods", "food", "agro",
        "auto", "automobile", "automotive",
        "electronics", "electric", "electrical",
        "software", "hardware", "media", "communications",
        "healthcare", "education", "finance", "capital",
        "investments", "securities", "insurance", "commodities",
        "power", "energy", "petroleum",
        "hotel", "hospitality", "resort",
        "aviation", "shipping", "marine",
        "logistics", "transport", "engineering", "construction",
        "infra", "realty", "developers", "retail", "global",
    }
    missing = required - BUSINESS_DESCRIPTORS
    assert not missing, f"Missing descriptor tokens: {sorted(missing)}"
```

- [ ] **Step 2: Run the test — it must FAIL**

Run: `pytest tests/test_config.py::test_business_descriptors_includes_sector_words -v`
Expected: FAIL with `Missing descriptor tokens: [...]`.

- [ ] **Step 3: Replace BUSINESS_DESCRIPTORS in config.py**

In `config.py`, replace the block at lines 108-126 (`BUSINESS_DESCRIPTORS = frozenset({ ... })`) with:

```python
# --- Business Descriptors (Generic Token'dan Hariç Tutulacaklar) ---
# Bu kelimeler company_types hedeflerinde yer alsa da firma isminin
# ANLAMLI parçalarıdır. stripped_form'da kaldırılmamalı.
# Örnek: "Apple Trading" vs "Apple Manufacturing" = farklı firmalar
#
# Sprint 1 (2026-04-10): liste sektör/rol kelimeleriyle genişletildi.
# Bakınız docs/superpowers/specs/2026-04-10-pg-es-matching-accuracy-audit-design.md §4.1
BUSINESS_DESCRIPTORS = frozenset({
    # mevcut (eski liste)
    "comercial", "enterprises", "group", "holding", "industrial", "industries",
    "internacional", "international", "koncern", "manufacturing", "prod",
    "sanayi", "services", "solutions", "technologies", "ticaret", "trading",
    # tekil/çoğul çeşitleri
    "enterprise", "holdings", "service", "solution", "technology",
    # tekil/çoğul (ek — industry eksikti)
    "industry",
    # ticari rol kelimeleri
    "trader", "traders", "exports", "imports", "export", "import",
    "dealers", "dealer", "distributors", "distributor",
    "suppliers", "supplier", "agency", "agencies",
    "consultants", "consultant", "consulting",
    "associates", "associate", "ventures", "venture",
    "systems", "system", "overseas",
    # sektör kelimeleri
    "pharma", "pharmaceuticals", "pharmaceutical",
    "chemicals", "chemical", "textiles", "textile",
    "steel", "steels", "metals", "metal",
    "plastics", "plastic", "packaging",
    "foods", "food", "agro", "agriculture",
    "auto", "automobile", "automobiles", "automotive",
    "electronics", "electronic", "electric", "electrical",
    "software", "hardware", "media", "communications",
    "healthcare", "health", "education", "educational",
    "finance", "financial", "capital", "investments", "investment",
    "securities", "insurance", "leasing", "commodities", "commodity",
    "power", "energy", "petroleum", "petro",
    "hotel", "hotels", "hospitality", "resort", "resorts",
    "aviation", "shipping", "marine", "maritime",
    "logistics", "transport", "transportation",
    "engineering", "engineers", "construction", "constructions",
    "infra", "infrastructure", "realty", "developers", "developer",
    "retail", "retails", "global",
})
```

- [ ] **Step 4: Run the test — it must PASS**

Run: `pytest tests/test_config.py::test_business_descriptors_includes_sector_words -v`
Expected: 1 passed.

- [ ] **Step 5: Run the full existing config tests to catch regressions**

Run: `pytest tests/test_config.py -v`
Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: expand BUSINESS_DESCRIPTORS with sector and role words

Sprint 1 Task 2 — add 60+ sector/role tokens (pharma, chemicals, auto,
electronics, traders, agencies, etc.) to the list that is protected
from stripping. Ref: audit design §4.1."
```

---

## Task 3: Apply BUSINESS_DESCRIPTORS guard in synonym_loader

**Files:**
- Modify: `synonym_loader.py:145-172`
- Modify: `tests/test_synonym_loader.py` (add new test)

- [ ] **Step 1: Add a failing test for the guard**

Append to `tests/test_synonym_loader.py`:

```python
def test_get_company_type_tokens_excludes_business_descriptors():
    """Sprint 1: get_company_type_tokens must subtract BUSINESS_DESCRIPTORS so
    that stripping pipelines do not remove sector/role words."""
    from synonym_loader import get_company_type_tokens
    from config import BUSINESS_DESCRIPTORS

    tokens = get_company_type_tokens("IN")

    # Legal suffixes must still be present
    for legal in ("ltd", "pvt", "inc", "llp", "opc", "huf"):
        assert legal in tokens, f"Expected legal suffix {legal!r} in IN tokens"

    # Sector/role words must NOT be present
    for sector in ("pharma", "chemicals", "auto", "electronics", "steel",
                   "industries", "traders", "enterprises", "international",
                   "agencies", "overseas", "global"):
        assert sector not in tokens, (
            f"Sector token {sector!r} leaked into company_type tokens for IN"
        )

    # Guard must not produce intersection with BUSINESS_DESCRIPTORS
    assert tokens.isdisjoint(BUSINESS_DESCRIPTORS)
```

- [ ] **Step 2: Run the test — it must FAIL**

Run: `pytest tests/test_synonym_loader.py::test_get_company_type_tokens_excludes_business_descriptors -v`
Expected: FAIL (current code lets sector tokens leak through).

- [ ] **Step 3: Apply the guard in `_parse_company_type_tokens`**

In `synonym_loader.py`, modify `_parse_company_type_tokens` (lines 145-172). The function currently ends with `return frozenset(tokens)`. Replace the last line so the function subtracts `BUSINESS_DESCRIPTORS`:

```python
    return frozenset(tokens) - BUSINESS_DESCRIPTORS
```

The file already imports `BUSINESS_DESCRIPTORS` from `config` at line 19; no new import is needed.

- [ ] **Step 4: Clear the lru_cache so the test picks up the change**

Both `get_company_type_tokens` and `get_all_company_type_tokens` are decorated with `@lru_cache(maxsize=None)`. Because this is a fresh test run, the cache will be empty, so no explicit `cache_clear()` is needed — but verify by running the test in isolation.

- [ ] **Step 5: Run the guard test — it must PASS**

Run: `pytest tests/test_synonym_loader.py::test_get_company_type_tokens_excludes_business_descriptors -v`
Expected: 1 passed.

- [ ] **Step 6: Run the full synonym_loader tests to catch regressions**

Run: `pytest tests/test_synonym_loader.py -v`
Expected: all previously passing tests still pass. If any existing test asserts that, for example, `"industries"` is in the returned tokens, update it to reflect the new contract and note the change in the commit message.

- [ ] **Step 7: Commit**

```bash
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat: subtract BUSINESS_DESCRIPTORS from company_type tokens

Sprint 1 Task 3 — _parse_company_type_tokens now removes protected
sector/role words before returning the frozenset. This is the single
place where the guard takes effect for the ingest pipeline, the
stripped search analyzer, and _post_verify._tokenize. Ref: §4.2."
```

---

## Task 4: Add brand-anchor helper and plural-canonicalisation for business descriptors

**Files:**
- Modify: `main_processor.py` (add helpers near `_tokenize`, around lines 291-318)
- Modify: `tests/test_matching_regression.py` (add helper unit tests)

**Why plural normalisation is needed:** After Task 3, sector words like `enterprise`/`enterprises`, `holding`/`holdings`, `service`/`services` are preserved as meaningful tokens. But `_tokenize` does exact string comparison, so `{isha, enterprise}` ≠ `{isha, enterprises}` even though the synonym layer at ES search time treats them as equivalent. We need a Python-side canonical map so both forms collapse to the same token. Without this, the positive controls `ISHA ENTERPRISE ↔ ISHA ENTERPRISES` and `ARIHANT ENTERPRISE ↔ ARIHANT ENTERPRISES` break after Task 5.

**Design:** A module-level dict derived once from `BUSINESS_DESCRIPTORS`. For every word `X` in the set where `X+'s'` is also in the set, map `X` → `Xs` (canonical = plural). Applied inside `_tokenize` after the existing cleaning, and inside `_first_meaningful_token` before returning.

- [ ] **Step 1: Add unit tests for both helpers and plural canonicalisation**

Append to `tests/test_matching_regression.py`:

```python
# ---- Helper unit tests -------------------------------------------------------

def test_first_meaningful_token_strips_leading_articles_and_suffixes():
    import main_processor as mp

    # "the apex trading co" → "apex" (the = article, trading/co filtered)
    # Note: trading is in BUSINESS_DESCRIPTORS so it's meaningful, but apex comes first.
    assert mp._first_meaningful_token("the apex trading co", "IN") == "apex"


def test_first_meaningful_token_returns_none_for_empty_or_only_stopwords():
    import main_processor as mp

    assert mp._first_meaningful_token("", "IN") is None
    assert mp._first_meaningful_token("and of the", "IN") is None
    assert mp._first_meaningful_token("ltd pvt", "IN") is None


def test_first_meaningful_token_canonicalises_plural_descriptors():
    """Plural canonicalisation: 'enterprise' and 'enterprises' both return 'enterprises'."""
    import main_processor as mp

    # Both strings share the same canonical brand token
    a = mp._first_meaningful_token("acme enterprise", "IN")
    b = mp._first_meaningful_token("acme enterprises", "IN")
    assert a == "acme"
    assert b == "acme"


def test_tokenize_canonicalises_plural_descriptors():
    """_tokenize produces identical token sets for singular/plural descriptor pairs."""
    import main_processor as mp

    t1 = mp._tokenize("isha enterprise", "IN")
    t2 = mp._tokenize("isha enterprises", "IN")
    assert t1 == t2
    # Canonical form is the plural
    assert "enterprises" in t1
    assert "enterprise" not in t1


def test_business_descriptor_canonical_map_covers_regular_plurals():
    """Sanity check: the auto-derived plural map contains every regular +s pair.
    Irregular plurals (industry/industries, agency/agencies, technology/technologies)
    are intentionally NOT handled in Sprint 1 — Sprint 2 will add an explicit table."""
    import main_processor as mp

    m = mp._BUSINESS_DESCRIPTOR_CANONICAL
    for singular, plural in [
        ("enterprise", "enterprises"),
        ("holding", "holdings"),
        ("service", "services"),
        ("solution", "solutions"),
        ("trader", "traders"),
        ("venture", "ventures"),
        ("dealer", "dealers"),
        ("supplier", "suppliers"),
        ("consultant", "consultants"),
    ]:
        assert m.get(singular) == plural, f"{singular} should map to {plural}"

    # Irregular plurals must NOT appear in the map (documented limitation)
    for irregular in ("industry", "agency", "technology", "commodity", "security"):
        assert m.get(irregular) is None, (
            f"{irregular} is irregular and should not auto-map in Sprint 1"
        )
```

Note: `agency`/`agencies`, `industry`/`industries`, `technology`/`technologies` are irregular plurals. Because Sprint 1 uses the auto-derived +s heuristic, these pairs will NOT be canonicalised and token-set comparisons across their singular/plural forms will fail. This is an accepted recall limitation, aligned with the temkinli mode preference — Sprint 2 will add an explicit irregular-plural table if production data shows it matters.

- [ ] **Step 2: Run the tests — they must FAIL**

Run: `pytest tests/test_matching_regression.py -k "first_meaningful_token or canonicalises_plural or canonical_map" -v`
Expected: FAIL with `AttributeError: module 'main_processor' has no attribute '_first_meaningful_token'` (and similar for `_BUSINESS_DESCRIPTOR_CANONICAL`).

- [ ] **Step 3: Add BUSINESS_DESCRIPTORS to the existing config import block**

`BUSINESS_DESCRIPTORS` is not currently imported in `main_processor.py`. Add it to the existing multi-line `from config import (...)` block at lines 44-58 in alphabetical order:

```python
from config import (
    BATCH_SIZE,
    BUSINESS_DESCRIPTORS,   # added Sprint 1 Task 4
    COLUMN_MAPPING,
    DB_CONFIG,
    ES_INDEX,
    LENGTH_RATIO_THRESHOLD,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    AUTO_CREATE_UPDATE_COLUMNS,
    RAW_TABLE_NAME,
    STAGES,
    MSEARCH_CHUNK_SIZE,
    SUFFIX_FUZZY_SCORE,
    TOKEN_COVERAGE_THRESHOLD,
)
```

- [ ] **Step 3b: Add the canonical map helper at module level**

In `main_processor.py`, find the `_COUNTRY_NAME_TOKENS` dict (lines 245-282). Immediately after its closing `}`, add the canonical map helper and the module-level constant:

```python
# Plural canonicalisation for BUSINESS_DESCRIPTORS: map singular → plural so
# token-set comparisons treat 'enterprise' and 'enterprises' as equal.
# Derived once from BUSINESS_DESCRIPTORS. Only regular +s plurals are handled;
# irregular forms (agency/agencies, industry/industries) are not collapsed in
# Sprint 1 — temkinli mode accepts these as potential recall losses.
def _build_business_descriptor_canonical_map(descriptors: frozenset) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for word in descriptors:
        plural = word + "s"
        if plural in descriptors:
            mapping[word] = plural
    return mapping


_BUSINESS_DESCRIPTOR_CANONICAL = _build_business_descriptor_canonical_map(BUSINESS_DESCRIPTORS)
```

- [ ] **Step 4: Update `_tokenize` to canonicalise tokens**

In `main_processor.py`, modify `_tokenize` (lines 291-317). The existing loop builds a `result` set. Change the final `result.add(t_clean)` to canonicalise first:

```python
def _tokenize(name: str, country: str = "") -> set[str]:
    """Firma ismini anlamlı tokenlara ayırır.

    - Küçük harf
    - Suffix token'ları dışlanır (get_company_type_tokens)
    - Article token'ları dışlanır (get_article_stopwords)
    - Tek char: alfanumerik ise korunur (inisyal/rakam), değilse atlanır
    - country verilirse, ülke adı token'ları çıkarılır
    - BUSINESS_DESCRIPTORS içindeki tekil/çoğul çiftleri canonicalise edilir
      (enterprise → enterprises) — Sprint 1 Task 4
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
        # Sprint 1 Task 4: canonicalise plural business descriptors
        t_canonical = _BUSINESS_DESCRIPTOR_CANONICAL.get(t_clean, t_clean)
        result.add(t_canonical)
    return result
```

- [ ] **Step 5: Implement `_first_meaningful_token` using the same canonical map**

In `main_processor.py`, add the helper immediately after `_tokenize` (before `_symmetric_token_coverage`):

```python
def _first_meaningful_token(name: str, country: str = "") -> str | None:
    """İsmin ilk anlamlı token'ını döner (brand anchor).

    Label temizliği + article/suffix/ülke-adı çıkarması sonrası kalan
    ilk alfanumerik token'ı döner. Hiçbir token kalmazsa None döner.
    BUSINESS_DESCRIPTORS içindeki tekil/çoğul çiftleri canonicalise edilir.

    _post_verify içindeki TOKEN_COVERAGE brand-anchor kontrolü için kullanılır —
    "BEE KAY" vs "KAY BEE" gibi sıra farklarını yakalar.
    """
    cleaned = _clean_labels(name).lower()
    country_tokens = _COUNTRY_NAME_TOKENS.get(country.upper(), frozenset())
    suffix_tokens = get_company_type_tokens(country)
    article_tokens = get_article_stopwords(country)
    for raw in cleaned.split():
        t = raw.rstrip('.,')
        if not t:
            continue
        if len(t) <= 1 and not t.isalnum():
            continue
        if t in country_tokens:
            continue
        if t in suffix_tokens or t in article_tokens:
            continue
        return _BUSINESS_DESCRIPTOR_CANONICAL.get(t, t)
    return None
```

- [ ] **Step 6: Run the helper tests — they must PASS**

Run: `pytest tests/test_matching_regression.py -k "first_meaningful_token or canonicalises_plural or canonical_map" -v`
Expected: 5 passed.

- [ ] **Step 7: Run the positive control tests — they must still pass**

Run: `pytest tests/test_matching_regression.py::test_canonical_exact_positive_controls_still_match -v`
Expected: 7 passed. This confirms plural canonicalisation keeps ISHA ENTERPRISE ↔ ENTERPRISES and ARIHANT ENTERPRISE ↔ ENTERPRISES green.

- [ ] **Step 8: Commit**

```bash
git add main_processor.py tests/test_matching_regression.py
git commit -m "feat: add plural canonicalisation + brand-anchor helper

Sprint 1 Task 4 — introduces _BUSINESS_DESCRIPTOR_CANONICAL map
(singular → plural for every regular pair in BUSINESS_DESCRIPTORS),
applies it inside _tokenize and the new _first_meaningful_token helper.
This keeps ISHA ENTERPRISE ↔ ISHA ENTERPRISES positive controls green
after Task 5's threshold hardening, and unblocks the TOKEN_COVERAGE
brand-anchor check in Task 6. Ref: audit design §4.4(c)."
```

---

## Task 5: Harden `_post_verify` — min_tokens floor + CANONICAL/STRIPPED thresholds

**Files:**
- Modify: `main_processor.py:448-491` (inside `_post_verify`)

- [ ] **Step 1: Verify the current state of regression tests**

Run: `pytest tests/test_matching_regression.py -k "stripped_exact_false_positives_rejected or canonical_exact_false_positives_rejected" -v`
Expected: some still FAIL. This is the baseline this task drives to green for these cases that hinge on the min_tokens/word_count thresholds.

- [ ] **Step 2: Apply (a) — kill the `min_tokens < 2` loophole**

In `main_processor.py`, find the block starting at line 448:

```python
    # ── Diğer stage'ler ───────────────────────────────────────────────────────
    if min_tokens < 2:
        if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
            if input_tokens == master_tokens:
                return True
        return False
```

Replace with:

```python
    # ── Diğer stage'ler ───────────────────────────────────────────────────────
    # Sprint 1 temkinli mod: stripping sonrası tek anlamlı token'a inen
    # eşleşmeler ret. Brand-only çakışmalar riskli (§4.4a).
    if min_tokens < 2:
        return False
```

- [ ] **Step 3: Apply (b) — raise CANONICAL/STRIPPED word_count_ratio**

A few lines below, find:

```python
    if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
        if coverage < 0.9:
            return False
        if word_count_ratio < 0.8:
            return False
```

Change the ratio from `0.8` to `0.9`:

```python
    if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
        if coverage < 0.9:
            return False
        if word_count_ratio < 0.9:  # Sprint 1: 0.8 → 0.9 (§4.4b)
            return False
```

- [ ] **Step 4: Run the regression tests**

Run: `pytest tests/test_matching_regression.py -k "stripped_exact_false_positives_rejected or canonical_exact_false_positives_rejected" -v`
Expected: **all 19 tests** (6 canonical + 13 stripped) pass. The `JAY & CO ↔ JAY CHEMICAL INDUSTRIES PRIVATE LIMITED` case passes because after Task 3, sector words like `chemical`, `industries` are meaningful tokens → input has 3 tokens {jay, chemical, industries}, master has 1 {jay}, word_count_ratio = 1/3 < 0.9 → rejected.

If any case still fails, STOP and diagnose before moving on. Do not proceed to Task 6.

- [ ] **Step 5: Run the positive controls**

Run: `pytest tests/test_matching_regression.py::test_canonical_exact_positive_controls_still_match -v`
Expected: **7 passed**. If any positive control fails, recall has collapsed — STOP, diagnose, and relax the threshold incrementally (ex: 0.85) or fix _tokenize edge cases rather than proceed.

- [ ] **Step 6: Run the full existing test suite**

Run: `pytest tests/ -v`
Expected: all previously green tests still green.

- [ ] **Step 7: Commit**

```bash
git add main_processor.py
git commit -m "feat: harden _post_verify — kill min_tokens loophole, raise word_count_ratio

Sprint 1 Task 5 — _post_verify now rejects any match whose stripping
reduces both sides to <2 meaningful tokens, and raises the CANONICAL/
STRIPPED word_count_ratio floor from 0.8 to 0.9. These two changes
kill the JAY & CO ↔ JAY CHEMICAL INDUSTRIES family of cascade false
positives. Ref: audit design §4.4(a)(b)."
```

---

## Task 6: Harden `_post_verify` — TOKEN_COVERAGE brand anchor

**Files:**
- Modify: `main_processor.py` (inside `_post_verify`, TOKEN_COVERAGE branch)

- [ ] **Step 1: Verify the target regression state**

Run: `pytest tests/test_matching_regression.py::test_token_coverage_false_positives_rejected -v`
Expected: FAILS (`BEE KAY ENTERPRISES ↔ KAY BEE TRADING CO` still passes the symmetric-token-coverage check).

- [ ] **Step 2: Add brand-anchor check**

In `main_processor.py`, find the TOKEN_COVERAGE branch inside `_post_verify` (around line 486):

```python
    if stage_name in ("TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"):
        if coverage < TOKEN_COVERAGE_THRESHOLD:
            return False
        if word_count_ratio < 0.7:
            return False

    return True
```

Replace with:

```python
    if stage_name in ("TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"):
        if coverage < TOKEN_COVERAGE_THRESHOLD:
            return False
        if word_count_ratio < 0.7:
            return False
        # Sprint 1 brand-anchor: ilk anlamlı token'lar her iki tarafta da aynı
        # olmalı. "BEE KAY" vs "KAY BEE" gibi sıra farklarını yakalar. (§4.4c)
        input_first = _first_meaningful_token(input_name, country)
        master_first = _first_meaningful_token(master_name, country)
        if input_first is None or master_first is None:
            return False
        if input_first != master_first:
            return False

    return True
```

- [ ] **Step 3: Run the regression test**

Run: `pytest tests/test_matching_regression.py::test_token_coverage_false_positives_rejected -v`
Expected: **2 passed**.

- [ ] **Step 4: Run the full regression file**

Run: `pytest tests/test_matching_regression.py -v`
Expected: every false-positive test green; positive controls still green.

- [ ] **Step 5: Commit**

```bash
git add main_processor.py
git commit -m "feat: add TOKEN_COVERAGE brand-anchor check in _post_verify

Sprint 1 Task 6 — TOKEN_COVERAGE/FUZZY_PHRASE/NGRAM_MATCH now require
the first meaningful token of both input and master to match. This
kills the 'BEE KAY ↔ KAY BEE' order-swap family. Ref: §4.4(c)."
```

---

## Task 7: Harden `_post_verify` — SUFFIX_FUZZY minimum meaningful tokens

**Files:**
- Modify: `main_processor.py:390-437` (SUFFIX_FUZZY branch)

- [ ] **Step 1: Verify SUFFIX_FUZZY regression state**

Run: `pytest tests/test_matching_regression.py::test_suffix_fuzzy_false_positives_rejected -v`
Expected: some still FAIL. Each failing case is a brand-only match like `ACE AVIATION ↔ ACE INDUSTRIES` where both stripped names collapse to a single brand token.

- [ ] **Step 2: Add the minimum meaningful-token check**

In `main_processor.py`, find the SUFFIX_FUZZY branch starting around line 391. The branch currently computes `doc_multi_char` and `input_stripped_ordered`. After the `input_stripped_ordered` list is built but **before** the `input_stripped_ordered != doc_name_tokens_list` check, add:

```python
        # Sprint 1 temkinli mod: her iki tarafta da ≥2 anlamlı token olmalı.
        # Tek-brand eşleşmesi ("ACE AVIATION" vs "ACE INDUSTRIES") yasak. (§4.4d)
        if len(doc_multi_char) < 2:
            return False
        if len(input_stripped_ordered) < 2:
            return False
```

The resulting block should look like:

```python
        if not input_stripped_ordered:
            return False
        # Sprint 1 temkinli mod: her iki tarafta da ≥2 anlamlı token olmalı.
        # Tek-brand eşleşmesi ("ACE AVIATION" vs "ACE INDUSTRIES") yasak. (§4.4d)
        if len(doc_multi_char) < 2:
            return False
        if len(input_stripped_ordered) < 2:
            return False
        if input_stripped_ordered != doc_name_tokens_list:
            return False

        return True
```

- [ ] **Step 3: Run the regression test**

Run: `pytest tests/test_matching_regression.py::test_suffix_fuzzy_false_positives_rejected -v`
Expected: **8 passed**.

- [ ] **Step 4: Run every regression test + existing smoke tests**

Run: `pytest tests/test_matching_regression.py tests/test_main_processor.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add main_processor.py
git commit -m "feat: require ≥2 meaningful tokens for SUFFIX_FUZZY match

Sprint 1 Task 7 — SUFFIX_FUZZY now rejects any match where either the
input or doc stripped form reduces to a single meaningful token. Kills
the 'ACE AVIATION ↔ ACE INDUSTRIES' brand-only family. Ref: §4.4(d)."
```

---

## Task 8: Flip `index_variation` for CANONICAL / SUFFIX_FUZZY / TOKEN_COVERAGE

**Files:**
- Modify: `config.py:144-201`
- Modify: `tests/test_config.py` (new assertion)

- [ ] **Step 1: Write a failing config assertion**

Append to `tests/test_config.py`:

```python
def test_stage_index_variation_sprint1_cascade_freeze():
    """Sprint 1 temkinli mod: yalnızca TAX_EXACT variations listesini besler."""
    from config import STAGES

    by_name = {s["name"]: s for s in STAGES}
    # TAX_EXACT alone keeps indexing variations (deterministic, safe)
    assert by_name["TAX_EXACT"]["index_variation"] is True

    # These three are flipped off as part of Sprint 1 cascade freeze
    for frozen in ("CANONICAL_EXACT", "SUFFIX_FUZZY", "TOKEN_COVERAGE"):
        assert by_name[frozen]["index_variation"] is False, (
            f"{frozen} must be PG-only during Sprint 1 to stop cascade "
            f"contamination — see audit design §4.5"
        )

    # Already-frozen stages remain False
    for always_pg in ("FUZZY_PHRASE", "NGRAM_MATCH", "STRIPPED_EXACT"):
        assert by_name[always_pg]["index_variation"] is False
```

- [ ] **Step 2: Run the test — it must FAIL**

Run: `pytest tests/test_config.py::test_stage_index_variation_sprint1_cascade_freeze -v`
Expected: FAIL because CANONICAL_EXACT / SUFFIX_FUZZY / TOKEN_COVERAGE still have `index_variation: True`.

- [ ] **Step 3: Flip the flags in `config.py`**

In `config.py`, update the three entries inside `STAGES` (lines 154, 162, 170). Find and change each `"index_variation": True` to `"index_variation": False` with a Sprint 1 comment:

`CANONICAL_EXACT` entry:

```python
    {
        "name": "CANONICAL_EXACT",
        "order": 2,
        "query_fn": "CANONICAL_EXACT",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,  # Sprint 1 (§4.5): cascade freeze
    },
```

`SUFFIX_FUZZY` entry:

```python
    {
        "name": "SUFFIX_FUZZY",
        "order": 3,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": SUFFIX_FUZZY_MIN_SCORE,
        "enabled": True,
        "index_variation": False,  # Sprint 1 (§4.5): cascade freeze
    },
```

`TOKEN_COVERAGE` entry:

```python
    {
        "name": "TOKEN_COVERAGE",
        "order": 4,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,  # Sprint 1 (§4.5): cascade freeze
    },
```

`TAX_EXACT`, `FUZZY_PHRASE`, `NGRAM_MATCH`, `STRIPPED_EXACT` entries stay as they are.

- [ ] **Step 4: Run the config test — it must PASS**

Run: `pytest tests/test_config.py::test_stage_index_variation_sprint1_cascade_freeze -v`
Expected: 1 passed.

- [ ] **Step 5: Run the entire existing test suite**

Run: `pytest tests/ -v`
Expected: all previously green tests still green. Any existing test that hard-codes `index_variation=True` for these three stages needs updating with the same Sprint 1 comment.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: freeze cascade — flip CANONICAL/SUFFIX_FUZZY/TOKEN_COVERAGE to PG-only

Sprint 1 Task 8 — during Sprint 1 only TAX_EXACT keeps indexing matched
variations back into the master ES doc. This stops cascade contamination
while the stripping guard (Tasks 2-3) and _post_verify hardening
(Tasks 5-7) stabilise. Sprint 2 will re-enable indexing for verified
stages. Ref: audit design §4.5."
```

---

## Task 9: Re-register ingest pipelines and recompute variations_stripped

**Files:**
- Create: `scripts/sprint1_reindex.py`

- [ ] **Step 1: Create the reindex helper script**

Write `scripts/sprint1_reindex.py`:

```python
"""Sprint 1 — re-register ingest pipelines and recompute variations_stripped.

After Tasks 2-3 widen BUSINESS_DESCRIPTORS and apply the guard, the Painless
scripts embedded in each per-country ingest pipeline need to be re-generated,
and every existing document in living_companies_v1 must run through the
updated pipeline so that `variations_stripped` and `variations_suffix` reflect
the new token set.

Strategy: update_by_query with explicit pipeline routing per country shard.
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ES_INDEX  # noqa: E402
from es_ingest import register_all_pipelines, pipeline_name  # noqa: E402
from es_manager import get_es_client  # noqa: E402
from synonym_loader import get_all_country_codes  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def reindex_country(es, country_code: str) -> dict:
    """Run update_by_query for a single country's shard, forcing the new pipeline."""
    cc = country_code.upper()
    pipe = pipeline_name(cc)
    body = {
        "query": {"term": {"country_code": cc}},
    }
    logger.info("Reindexing %s via pipeline %s ...", cc, pipe)
    start = time.time()
    result = es.update_by_query(
        index=ES_INDEX,
        body=body,
        pipeline=pipe,
        routing=cc,
        wait_for_completion=True,
        conflicts="proceed",
        refresh=True,
        request_timeout=3600,
    )
    elapsed = time.time() - start
    logger.info(
        "  %s: updated=%s, version_conflicts=%s, elapsed=%.1fs",
        cc,
        result.get("updated", 0),
        result.get("version_conflicts", 0),
        elapsed,
    )
    return result


def main() -> None:
    es = get_es_client()

    logger.info("Step 1/2 — re-registering all ingest pipelines")
    register_all_pipelines(es)

    codes = get_all_country_codes()
    logger.info("Step 2/2 — update_by_query for %d countries", len(codes))

    total_updated = 0
    failures: list[str] = []
    for cc in codes:
        try:
            res = reindex_country(es, cc)
            total_updated += res.get("updated", 0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Reindex failed for %s", cc)
            failures.append(f"{cc}: {exc}")

    logger.info("Total docs updated: %d", total_updated)
    if failures:
        logger.error("Failures (%d):", len(failures))
        for f in failures:
            logger.error("  %s", f)
        sys.exit(1)
    logger.info("Sprint 1 reindex complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run the pipeline registration only**

Before touching data, verify the pipeline registration step alone works. Run:

```bash
python -c "from es_manager import get_es_client; from es_ingest import register_all_pipelines; register_all_pipelines(get_es_client())"
```

Expected: stdout shows `Ingest pipeline 'company_name_XX' kaydedildi.` for each country, ending with `Toplam N ülke pipeline'ı kaydedildi.`. No exceptions.

- [ ] **Step 3: Verify a pipeline contains the new token set**

Run (replace `in` with a country you can inspect in Kibana or via curl):

```bash
python -c "
from es_manager import get_es_client
es = get_es_client()
pipe = es.ingest.get_pipeline(id='company_name_in')
src = pipe['company_name_in']['processors'][1]['script']['source']
assert 'pharma' not in src.lower(), 'pharma still leaking into stripped list'
print('OK — pharma not in stripped pipeline script')
"
```

Expected: `OK — pharma not in stripped pipeline script`. If assertion fails, something in Task 2/3 is not wired correctly — STOP and diagnose.

- [ ] **Step 4: Run the full reindex**

```bash
python scripts/sprint1_reindex.py
```

Expected: per-country update_by_query runs to completion; the summary line shows the total updated count (for 17k masters this should complete in minutes, not hours, because only NEW_MASTER docs live in ES). No failures.

If a country hits version conflicts, the script is configured with `conflicts="proceed"` — it continues and logs the count. That is acceptable.

- [ ] **Step 5: Spot-check a known bad master in ES**

Run:

```bash
python -c "
from es_manager import get_es_client
es = get_es_client()
res = es.search(index='living_companies_v1', routing='IN', body={
    'query': {'match_phrase': {'variations': 'goel enterprises'}},
    'size': 1,
})
hit = res['hits']['hits'][0]['_source']
print('variations_stripped:', hit.get('variations_stripped'))
"
```

Expected: `variations_stripped` now contains `goel enterprises` (or similar with `enterprises` preserved) rather than just `goel`. If it still shows only `goel`, Task 3 or the reindex did not take effect for that doc.

- [ ] **Step 6: Commit the script**

```bash
git add scripts/sprint1_reindex.py
git commit -m "chore: add Sprint 1 reindex helper

Sprint 1 Task 9 — re-registers per-country ingest pipelines and runs
update_by_query to recompute variations_stripped / variations_suffix
for every existing master doc. Idempotent. Ref: audit design §4.3."
```

---

## Task 10: Post-change smoke test and final regression run

**Files:**
- (no new files)

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: every test green — regression, config, synonym_loader, main_processor, and any existing suite. If any test is red, STOP and fix before proceeding.

- [ ] **Step 2: Capture a post-change baseline snapshot**

```bash
python scripts/sprint1_baseline_snapshot.py
```

This writes a new JSON under `baselines/`. The file from Task 0 is the "before"; this one is the "after (code-only, before any reprocessing)". They should be nearly identical because the code changes do not retroactively clean existing matches.

- [ ] **Step 3: Manual spot-check — compare a few FP clusters in PG**

Pick three of the master_codes associated with §2 false positives (Task 0 baseline contains these). Run for each:

```bash
python -c "
import psycopg2
from config import DB_CONFIG, RAW_TABLE_NAME
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute(
    f\"SELECT ta_code, company_name, match_type FROM {RAW_TABLE_NAME} \"
    f\"WHERE master_code = %s ORDER BY match_type\", ('<paste-master-code>',)
)
for row in cur.fetchall():
    print(row)
conn.close()
"
```

Observe: existing contaminated clusters still exist in PG (§7 defers cleanup to a user decision). Purpose of this step is to confirm the contamination is visible and documented, not to fix it.

- [ ] **Step 4: Summarise Sprint 1 results**

Create `docs/superpowers/plans/2026-04-10-pg-es-matching-accuracy-sprint1-results.md` with the following template (fill in real numbers):

```markdown
# Sprint 1 Results — 2026-04-10

## Baseline (before)
- Total rows: ...
- Matched: ...
- By type: ...

## After (code + reindex)
- Total rows: ... (unchanged)
- Matched: ... (unchanged — no reprocessing)
- Regression fixture: N FP tests green, M TP tests green

## Follow-ups
- Decision pending: §7 cleanup strategy (A / B / C)
- Sprint 2 schema refactor: on schedule / delayed
```

- [ ] **Step 5: Commit results document and close Sprint 1**

```bash
git add docs/superpowers/plans/2026-04-10-pg-es-matching-accuracy-sprint1-results.md baselines/
git commit -m "docs: Sprint 1 matching accuracy results and post-change baseline"
```

---

## Sprint 1 Exit Criteria

Sprint 1 is done when **every item** below is checked:

- [ ] All tests in `tests/test_matching_regression.py` green (false positives rejected, positive controls preserved)
- [ ] `tests/test_config.py` green including the new BUSINESS_DESCRIPTORS and stage-freeze assertions
- [ ] `tests/test_synonym_loader.py` green including the guard assertion
- [ ] `python scripts/sprint1_reindex.py` completed without failures
- [ ] Spot-check in ES confirms sector words (e.g. `pharma`, `enterprises`) are now preserved in `variations_stripped` for at least 3 sample masters from different countries
- [ ] Post-change baseline JSON written to `baselines/`
- [ ] Results summary committed
- [ ] Spec §7 cleanup decision raised with the user (no action taken yet)

Sprint 2 (schema refactor) does NOT start until the user reviews Sprint 1 production behaviour over at least 7 days and confirms no recall collapse.

---

## Self-Review Notes

Spec coverage pass:

| Spec § | Task |
|--------|------|
| §4.1 BUSINESS_DESCRIPTORS widen | Task 2 |
| §4.2 guard in synonym_loader | Task 3 |
| §4.3 ES pipeline re-register + reindex | Task 9 |
| §4.4(a) min_tokens loophole | Task 5 |
| §4.4(b) CANONICAL/STRIPPED ratios | Task 5 |
| §4.4(c) TOKEN_COVERAGE brand anchor | Tasks 4 + 6 |
| §4.4(d) SUFFIX_FUZZY min tokens | Task 7 |
| §4.5 cascade freeze | Task 8 |
| §4.6 smoke test script | Tasks 1 + 10 |
| §4.7 acceptance criteria | Sprint 1 Exit Criteria |
| §6 measurement & validation | Tasks 0 + 10 (baseline diff) |
| §7 cleanup (reporting only) | Task 10 Step 3 (spot check, no action) |

Spec §5 (Sprint 2 schema refactor) is intentionally NOT in this plan — it will get its own plan document once Sprint 1 is stable in production.
