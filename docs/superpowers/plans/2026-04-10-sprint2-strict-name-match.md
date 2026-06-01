# Sprint 2 — Strict Name Match + Synonym Schema Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current fuzzy-suffix-based matching with a strict name-match algorithm backed by a per-country-isolated synonym schema; eliminate cross-country legal-suffix contamination (`other.json`) and the `_is_fuzzy_suffix` edit-distance loophole that merges unrelated companies like `ATLAS CHEMICALS ↔ ATLAS FINE CHEMICALS PVT LTD`.

**Architecture:**
The synonym JSON schema is split into `legal_suffixes` (stripped during normalization) and `business_sectors` (preserved as meaningful brand differentiators). `synonyms_data/other.json` is archived because its 425 rules pooled legal suffixes from all countries into a single dump that polluted every per-country pipeline. `main_processor._post_verify` gets a new `strict_name_match(input, master, country)` helper that:

1. Extracts meaningful tokens by stripping *only* per-country `legal_suffixes` and `articles`
2. Canonicalises business-sector tokens through the rule targets (synonym `=>` right-hand side), giving principled plural/abbreviation handling including irregular forms
3. Requires the resulting name-token list to be **order-sensitive equal** between input and master

The `_is_fuzzy_suffix` + `_edit_distance` machinery is deleted — it caused "fine" to be identified as a fuzzy suffix (edit distance 1 from some foreign `fie` entry) and silently stripped from brand names. Fuzzy suffix support now comes exclusively from the deterministic `config.SUFFIX_TYPO_MAP` dict.

**Tech Stack:** Python 3.14+, pytest, psycopg2, elasticsearch-py 8.x, Painless (ES ingest).

**Spec reference:** `docs/superpowers/specs/2026-04-10-pg-es-matching-accuracy-audit-design.md` §5 (Sprint 2 schema refactor) + real-world FPs from session 2026-04-10 (`ATLAS FINE CHEMICALS`, `BABA WOOD PRODUCTS`, `BABA ENGINEERING WORKS`).

**Decisions locked in by user:**
1. Schema refactor scope: **Plan B** — full schema migration + new algorithm
2. `other.json`: **delete** (verified unnecessary — all its useful legal suffixes either duplicate `common.json` entries or belong in per-country files that we are not actively populating for IN)
3. `common.json`: **migrate** to new schema
4. TOKEN_COVERAGE / FUZZY_PHRASE / NGRAM_MATCH stages: **keep** (but their `_post_verify` branches now benefit from correct stripping and rule-based canonicalisation)

---

## File Structure

### Files to create

| Path | Responsibility |
|------|----------------|
| `synonyms_data/_archive/other.json.bak` | Preserved copy of the deleted `other.json` so its content is retrievable if any country migration needs it in Sprint 2+. |
| `tests/test_strict_name_match.py` | Unit tests + regression fixtures for the new strict-name-match algorithm. Contains the three new FPs from session 2026-04-10 plus positive controls. |
| `scripts/sprint2_baseline_snapshot.py` | Capture pre-Sprint-2 metrics (rows, masters, match-type counts) for before/after comparison. Mirrors Sprint 1's baseline script but writes to `baselines/sprint2_*.json`. |
| `scripts/sprint2_reindex.py` | Re-registers per-country ingest pipelines under the new token set, then runs `update_by_query --only CC` for dry-run targets. |
| `docs/superpowers/plans/2026-04-10-sprint2-strict-name-match-results.md` | Post-implementation results: before/after metrics, regression counts, known follow-ups. |

### Files to modify

| Path | Change |
|------|--------|
| `synonyms_data/common.json` | Migrate `company_types` → `legal_suffixes` + `business_sectors`. `articles` stays. `address_abbreviations` stays. |
| `synonyms_data/other.json` | **DELETE** (archived in Task 3). |
| `synonym_loader.py` | Add `get_legal_suffix_tokens`, `get_business_sector_tokens`, `get_business_sector_canonical_map`. Deprecate `get_company_type_tokens` as a thin shim returning `legal ∪ sectors` for backward compatibility. Exclude filenames starting with `_` from `get_all_country_codes()`. Remove `get_generic_tokens_for_country` (dead code from before Sprint 1). |
| `main_processor.py` | Delete `_is_fuzzy_suffix`, `_edit_distance`, `_build_business_descriptor_canonical_map`, `_BUSINESS_DESCRIPTOR_CANONICAL`. Add `_rule_based_canonical_map` helper that reads `business_sector` rule targets from synonym data. Update `_tokenize` + `_first_meaningful_token` to use per-country canonical map from rules. Add `strict_name_match(input_name, master_name, country)` function. Refactor `_post_verify` SUFFIX_FUZZY branch to use `strict_name_match`. |
| `config.py` | Remove `BUSINESS_DESCRIPTORS` frozenset (now derived from JSON). Keep `SUFFIX_TYPO_MAP` (this is the ONLY place deterministic fuzzy suffix handling lives). |
| `es_ingest.py` | `_build_stripped_script` and `_build_suffix_script` use `get_legal_suffix_tokens` instead of `get_company_type_tokens`. `_build_clean_script` spaced-suffix rejoining uses legal suffixes only. |
| `es_manager.py` | Stripped search analyzer stop filter uses `get_legal_suffix_tokens` instead of `get_company_type_tokens`. |
| `tests/test_config.py` | Remove the Sprint 1 `test_business_descriptors_includes_sector_words` test (constant no longer exists). |
| `tests/test_synonym_loader.py` | Add tests for the three new loader APIs. Remove tests that asserted `BUSINESS_DESCRIPTORS` guard behaviour. |
| `tests/test_matching_regression.py` | Add the three Sprint 2 FPs as parametrized rejection tests. Keep all Sprint 1 tests green. |

### Files explicitly NOT touched in Sprint 2

- Per-country JSON files other than `in.json` (already migrated manually in the previous session) and `common.json` — rest of the 50+ country files stay in their legacy `company_types` shape. `synonym_loader` falls back gracefully: if a country file lacks `legal_suffixes`/`business_sectors`, the shim returns empty frozensets for that country and the downstream stripping degenerates to a no-op (safe). Full country migration is a Sprint 3 concern.
- `es_queries.py` — query bodies unchanged. The post-verification layer is where the fix lives.
- Baseline Python 3.14 interpreter, psycopg2 install, ES 8.x client.

---

## Task 0: Sprint 2 baseline snapshot

**Files:**
- Create: `scripts/sprint2_baseline_snapshot.py`

- [ ] **Step 1: Create the baseline script**

Write `scripts/sprint2_baseline_snapshot.py`:

```python
"""Sprint 2 baseline — captures pre-change state for before/after diff."""
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
        "sprint": 2,
        "phase": "pre",
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
    out_file = out_dir / f"sprint2_pre_{stamp}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Sprint 2 baseline written to {out_file}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the baseline**

Run: `python scripts/sprint2_baseline_snapshot.py`
Expected: file `baselines/sprint2_pre_<timestamp>.json` is created with non-zero `matches_by_type`.

- [ ] **Step 3: Commit**

```bash
git add scripts/sprint2_baseline_snapshot.py baselines/sprint2_pre_*.json
git commit -m "chore: add Sprint 2 baseline snapshot (pre-refactor state)"
```

---

## Task 1: Sprint 2 regression fixtures — new FPs + positive controls

**Files:**
- Create: `tests/test_strict_name_match.py`

This fixture file is DIFFERENT from `tests/test_matching_regression.py`. It targets the new `strict_name_match` helper (added in Task 11). Until Task 11 lands, these tests fail with `AttributeError`. That is the intended red state.

- [ ] **Step 1: Write the Sprint 2 regression fixtures**

Create `tests/test_strict_name_match.py`:

```python
"""Sprint 2 — regression tests for strict_name_match.

Each false positive from session 2026-04-10 is encoded as a test case that
must return False from main_processor.strict_name_match after Sprint 2.

Positive controls guard against recall collapse: same-brand name variations
that differ only in legal suffix or typo must still return True.
"""
from __future__ import annotations

import pytest


# ---- False positives from session 2026-04-10 ---------------------------------
# These are real records from p7_firms_v2 that matched via SUFFIX_FUZZY pre-Sprint-2.

FP_PAIRS: list[tuple[str, str, str]] = [
    # (country, name_a, name_b) — must NOT match
    ("IN", "ATLAS CHEMICALS(PROP. KIRTI GOVERDHANDAS THAKKAR)", "ATLAS FINE CHEMICALS PVT LTD"),
    ("IN", "AB WOOD PRODUCTS PVT.LTD.", "BABA WOOD PRODUCTS PVT LTD"),
    ("IN", "A.S. ENGINEERING WORKS", "BABA ENGINEERING WORKS"),
]


@pytest.mark.parametrize("country,name_a,name_b", FP_PAIRS)
def test_sprint2_fp_rejected_forward(country, name_a, name_b):
    """strict_name_match must return False in the A→B direction."""
    import main_processor as mp
    assert mp.strict_name_match(name_a, name_b, country) is False


@pytest.mark.parametrize("country,name_a,name_b", FP_PAIRS)
def test_sprint2_fp_rejected_reverse(country, name_a, name_b):
    """strict_name_match must return False in the B→A direction (symmetry)."""
    import main_processor as mp
    assert mp.strict_name_match(name_b, name_a, country) is False


# ---- Positive controls — same-brand variations that MUST match ----------------

TP_PAIRS: list[tuple[str, str, str]] = [
    # (country, name_a, name_b) — must match (after legal suffix strip + canonicalisation)
    ("IN", "ATLAS FINE CHEMICALS PVT LTD", "ATLAS FINE CHEMICALS PRIVATE LIMITED"),
    ("IN", "ATLAS FINE CHEMICALS PVT LTD", "atlas fine chemicals pvt. ltd."),
    ("IN", "BABA WOOD PRODUCTS PVT LTD", "BABA WOOD PRODUCTS PRIVATE LIMITED"),
    ("IN", "AB WOOD PRODUCTS PVT.LTD.", "AB WOOD PRODUCTS LIMITED"),
    ("IN", "ISHA ENTERPRISES", "ISHA ENTERPRISE"),   # plural normalisation
    ("IN", "JAY CHEMICAL INDUSTRIES PVT LTD", "JAY CHEMICAL INDUSTRIES LIMITED"),
    ("IN", "KT INTERNATIONAL", "K T INTERNATIONAL"),  # single-char split OK
]


@pytest.mark.parametrize("country,name_a,name_b", TP_PAIRS)
def test_sprint2_tp_match_forward(country, name_a, name_b):
    """strict_name_match must return True in the A→B direction."""
    import main_processor as mp
    assert mp.strict_name_match(name_a, name_b, country) is True


@pytest.mark.parametrize("country,name_a,name_b", TP_PAIRS)
def test_sprint2_tp_match_reverse(country, name_a, name_b):
    """strict_name_match must return True in the B→A direction (symmetry)."""
    import main_processor as mp
    assert mp.strict_name_match(name_b, name_a, country) is True


# ---- Single-token-brand rejection ---------------------------------------------

def test_sprint2_rejects_single_token_brand():
    """When stripping reduces either side to <2 meaningful tokens, reject."""
    import main_processor as mp
    # "Apex Ltd" → [apex], too short to trust
    assert mp.strict_name_match("Apex Ltd", "Apex Inc", "IN") is False


def test_sprint2_rejects_empty_after_strip():
    """All-stopword input rejected."""
    import main_processor as mp
    assert mp.strict_name_match("Ltd Pvt", "Inc Corp", "IN") is False
```

- [ ] **Step 2: Run the new fixtures — they must FAIL with AttributeError**

Run: `python -m pytest tests/test_strict_name_match.py -v --tb=line -q`
Expected: Every test FAILS with `AttributeError: module 'main_processor' has no attribute 'strict_name_match'`. This red state is intentional.

- [ ] **Step 3: Commit**

```bash
git add tests/test_strict_name_match.py
git commit -m "test: add Sprint 2 strict_name_match regression fixtures

Encodes three real false positives from session 2026-04-10 plus positive
controls. Currently red because strict_name_match doesn't exist yet —
Task 11 makes them green."
```

---

## Task 2: Migrate `synonyms_data/common.json` to new schema

**Files:**
- Modify: `synonyms_data/common.json` (replace `company_types` with `legal_suffixes` + `business_sectors`)

- [ ] **Step 1: Rewrite common.json**

Replace the entire contents of `synonyms_data/common.json` with:

```json
{
  "_schema_version": "2.0",
  "_description": "Tum ulkelere yuklenen ortak synonym kurallari. Yalnizca evrensel Ingilizce hukuki formlar (Ltd, Inc, Corp, LLC, LLP) ve evrensel sektor kelimeleri burada yer alir. Ulkeye ozgu hukuki formlar (AB, AS, SA, GmbH, vb.) ilgili ulke dosyasinda tanimlanmalidir.",

  "legal_suffixes": [
    "corporation,corp,corp.,incorporated,inc,inc.=>corp.",
    "company,co,co.,comp=>co.",
    "limited liability company,llc,l.l.c,l.l.c.,limited liability=>llc",
    "limited partnership,lp,l.p,l.p.,ltd partnership=>lp",
    "limited liability partnership,llp,l.l.p,l.l.p.=>llp",
    "public limited company,plc,p.l.c,p.l.c.,public ltd=>plc",
    "unlimited company,unlimited,ultd=>unlimited",
    "private limited company,pvt ltd,pvt. ltd.,private ltd,lim,ltd,limited,ltd.,ltda,limitada=>ltd.",
    "limited,ltd,ltd.,limited.=>ltd.",
    "pvt,private,priv,prvt=>pvt",
    "sole proprietorship,sole prop,individual,sole trader,sole proprietor,proprietor=>sole proprietor",
    "cooperative,coop,co-op,co op=>cooperative",
    "partnership,partners,p.ship,ptnrs=>partnership",
    "brothers,bros,bros.,bro,hnos,hermanos=>bros."
  ],

  "business_sectors": [
    "holding,holdings,hold.,hldg,hldgs=>holdings",
    "group,grp,grp.,groupe,grupo=>group",
    "international,intl,int.,int,inter=>international",
    "industries,industry,industrial,ind,ind.=>industries",
    "services,service,svc,svcs,serv.=>services",
    "solutions,solution,sol.,soln=>solutions",
    "technologies,technology,tech,tech.,technol.=>technologies",
    "enterprises,enterprise,ent,ent.,entrp=>enterprises",
    "trading,traders,trade,trdg,trd=>trading",
    "manufacturing,mfg,mfg.,manuf.,manufact.=>manufacturing",
    "import export,import,export,imp,exp,imp exp=>import export"
  ],

  "address_abbreviations": [
    "street,st,st.,str,str.=>st.",
    "road,rd,rd.=>rd.",
    "avenue,ave,ave.,av,av.=>ave.",
    "boulevard,blvd,blvd.,bd,bd.=>blvd.",
    "drive,dr,dr.=>dr.",
    "lane,ln,ln.=>ln.",
    "place,pl,pl.=>pl.",
    "court,ct,ct.=>ct.",
    "circle,cir,cir.=>cir.",
    "highway,hwy,hwy.=>hwy.",
    "square,sq,sq.=>sq.",
    "crescent,cres,cres.=>cres.",
    "way,wy,wy.=>way",
    "terrace,ter,ter.,terr,terr.=>ter.",
    "parkway,pkwy,pkwy.=>pkwy.",
    "alley,aly,aly.,a.=>aly.",
    "building,bldg,bldg.,bld,bld.=>bldg.",
    "floor,fl,fl.,flr,flr.=>fl.",
    "room,rm,rm.=>rm.",
    "apartment,apt,apt.,appt,appt.=>apt.",
    "suite,ste,ste.=>ste.",
    "unit,u.=>unit",
    "number,no,no.,num,num.=>number",
    "north,n,n.=>n.",
    "south,s,s.=>s.",
    "east,e,e.=>e.",
    "west,w,w.=>w.",
    "northwest,nw,n.w.=>nw",
    "northeast,ne,n.e.=>ne",
    "southwest,sw,s.w.=>sw",
    "southeast,se,s.e.=>se",
    "post office box,po box,p.o. box,pob,p.o.b.=>p.o. box"
  ],

  "articles": [
    "and", "of", "the", "for", "in", "on", "at", "to", "by",
    "de", "del", "la", "le", "les", "des", "du", "et",
    "und", "der", "die", "das", "von"
  ]
}
```

**Key removals from old common.json (why each moved):**
- `"and,amp,y,et,und,e=>amp"` — was in `company_types` but represents ampersand-like conjunctions; dropped because `articles` already covers `"and"` / `"et"` / `"und"` and `"amp"` is an HTML-entity artifact we do not want in the active rule set.
- `"limited, ltd, ltd., ltd, ltd.,ltd,ltd.,ltda,limitada=>ltd."` — duplicate of the earlier `"private limited company..."` rule with a leading whitespace bug; consolidated into the canonical `limited,ltd,...=>ltd.` entry.

**Key classification decisions:**
- `brothers` / `bros` → `legal_suffixes` (traditional family-business designator like `"Warner Bros"` where the suffix is NOT a brand differentiator in the Sprint 2 sense).
- `holding` / `holdings` → `business_sectors` (keep Sprint 1 decision: `"Apex Holdings"` ≠ `"Apex Group"`).
- `industries`, `services`, `solutions`, `technologies`, `enterprises`, `trading`, `manufacturing`, `import export` → `business_sectors`.

- [ ] **Step 2: Validate the JSON parses**

Run: `python -c "import json; json.load(open('synonyms_data/common.json', encoding='utf-8'))"`
Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add synonyms_data/common.json
git commit -m "refactor: migrate common.json to Sprint 2 schema (legal_suffixes + business_sectors)"
```

---

## Task 3: Archive and delete `other.json` + filename underscore filter

**Files:**
- Create: `synonyms_data/_archive/other.json.bak`
- Delete: `synonyms_data/other.json`
- Modify: `synonym_loader.py:237-248` (`get_all_country_codes` — exclude files starting with `_`)

- [ ] **Step 1: Archive other.json**

```bash
mkdir -p synonyms_data/_archive
cp synonyms_data/other.json synonyms_data/_archive/other.json.bak
```

- [ ] **Step 2: Delete the active copy**

```bash
rm synonyms_data/other.json
```

- [ ] **Step 3: Update `synonym_loader.COMMON_FILES`**

In `synonym_loader.py`, find the line:

```python
COMMON_FILES = ["common.json", "countries.json", "other.json"]
```

Replace with:

```python
COMMON_FILES = ["common.json", "countries.json"]
```

- [ ] **Step 4: Update `get_all_country_codes` to exclude underscore-prefixed files**

In `synonym_loader.py`, find `get_all_country_codes`:

```python
def get_all_country_codes() -> list[str]:
    """
    synonyms_data/ klasöründeki tüm ülke dosyalarının kodlarını döner.
    Ortak dosyalar (common, countries, other) hariç tutulur.
    """
    excluded = {"common", "countries", "other"}
    codes = []
    for f in SYNONYMS_DIR.glob("*.json"):
        stem = f.stem.upper()
        if f.stem.lower() not in excluded:
            codes.append(stem)
    return sorted(codes)
```

Replace with:

```python
def get_all_country_codes() -> list[str]:
    """
    synonyms_data/ klasöründeki tüm ülke dosyalarının kodlarını döner.
    Ortak dosyalar (common, countries) hariç tutulur.
    Underscore ile baslayan dosyalar (_template.json, _archive/) de hariç.
    """
    excluded = {"common", "countries"}
    codes = []
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.startswith("_"):
            continue  # _template.json, _internal, etc.
        if f.stem.lower() in excluded:
            continue
        codes.append(f.stem.upper())
    return sorted(codes)
```

- [ ] **Step 5: Clear all lru_caches by restarting Python and verifying get_all_country_codes**

Run:

```bash
python -c "from synonym_loader import get_all_country_codes; codes = get_all_country_codes(); print(len(codes), 'countries'); assert '_TEMPLATE' not in codes; assert 'OTHER' not in codes; print('OK')"
```

Expected: `<N> countries` followed by `OK`. `_TEMPLATE` and `OTHER` must not appear in the list.

- [ ] **Step 6: Commit**

```bash
git add synonyms_data/_archive/ synonym_loader.py
git rm synonyms_data/other.json
git commit -m "refactor: archive other.json and exclude underscore-prefixed files from country codes

other.json pooled legal suffixes from all countries into a single global dump,
polluting every per-country pipeline. Example: 'ab' (Swedish Aktiebolag) made
Indian 'AB WOOD PRODUCTS' strip to 'wood products' and match 'BABA WOOD PRODUCTS'.
Archived under _archive/ for retrievability; loader no longer reads it.

Also: synonym_loader now ignores files starting with '_' so _template.json
can live in the synonyms_data directory without being loaded as a country."
```

---

## Task 4: Add `get_legal_suffix_tokens` to synonym_loader

**Files:**
- Modify: `synonym_loader.py` (add function near `get_company_type_tokens`)
- Modify: `tests/test_synonym_loader.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synonym_loader.py`:

```python
def test_get_legal_suffix_tokens_returns_frozenset():
    """Sprint 2: get_legal_suffix_tokens reads the 'legal_suffixes' category
    from common.json plus the per-country file."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    assert isinstance(tokens, frozenset)
    # Universal English legal forms from common.json
    for expected in ("ltd", "inc", "corp", "llc", "llp", "pvt"):
        assert expected in tokens, f"{expected!r} missing from IN legal suffixes"
    # IN-specific legal forms from in.json
    for expected in ("opc", "huf", "nidhi"):
        assert expected in tokens, f"{expected!r} (IN-specific) missing"


def test_get_legal_suffix_tokens_excludes_sectors():
    """Legal suffixes must NOT contain business sector words."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    for sector in ("pharma", "chemicals", "industries", "enterprises",
                   "trading", "international", "technologies"):
        assert sector not in tokens, f"{sector!r} leaked into legal_suffixes"


def test_get_legal_suffix_tokens_excludes_foreign_suffixes():
    """Sprint 2 fix: 'ab' (Swedish) and 'as' (Norwegian/Latvian) must NOT
    appear in IN legal suffixes. other.json is archived."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    # These caused the BABA WOOD PRODUCTS false positive before Sprint 2.
    assert "ab" not in tokens, "Swedish 'ab' leaking into IN suffixes"
    assert "as" not in tokens, "Norwegian 'as' leaking into IN suffixes"
```

Note: the `import pytest` and `import frozenset` are not needed; `frozenset` is a builtin.

- [ ] **Step 2: Run the test — it must FAIL**

Run: `python -m pytest tests/test_synonym_loader.py::test_get_legal_suffix_tokens_returns_frozenset -v`
Expected: FAIL with `ImportError: cannot import name 'get_legal_suffix_tokens' from 'synonym_loader'`.

- [ ] **Step 3: Add the new function to synonym_loader**

In `synonym_loader.py`, add this function immediately after `_parse_company_type_tokens` (before `get_company_type_tokens`):

```python
def _parse_category_tokens(paths: list, category: str) -> frozenset:
    """Verilen JSON dosyalarindan belirli bir kategoriden tum token'lari cikarir.

    Solr synonym format: 'src1,src2,src3=>target'
    Her iki taraftaki (sol ve sag) her token ayri ayri donulur.
    Noktalar silinir, kucuk harfe cevrilir.
    """
    tokens: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get(category, [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            rule_norm = normalize_text(rule)
            if "=>" in rule_norm:
                left, right = rule_norm.split("=>", 1)
                all_parts = left.split(",") + [right]
            else:
                all_parts = rule_norm.split(",")
            for part in all_parts:
                t = part.strip().lower().replace(".", "")
                if t:
                    tokens.add(t)
    return frozenset(tokens)


@lru_cache(maxsize=None)
def get_legal_suffix_tokens(country_code: str) -> frozenset:
    """Ulkeye ozgu legal_suffixes token'larini doner.

    Hem common.json hem de ulke dosyasindan 'legal_suffixes' kategorisini okur.
    Bunlar stripping pipeline'inda silinir (tuzel kisi ekleri).
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "legal_suffixes")
```

- [ ] **Step 4: Run the tests — they must PASS**

Run: `python -m pytest tests/test_synonym_loader.py -k legal_suffix -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat: add get_legal_suffix_tokens and _parse_category_tokens helpers

Sprint 2 — new per-category reader replaces the old company_types-only path.
get_legal_suffix_tokens reads the new legal_suffixes category from common.json
plus the per-country file. Tested on IN: includes ltd/inc/opc/huf, excludes
pharma/industries/ab/as."
```

---

## Task 5: Add `get_business_sector_tokens` + `get_business_sector_canonical_map`

**Files:**
- Modify: `synonym_loader.py` (add two more functions)
- Modify: `tests/test_synonym_loader.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_synonym_loader.py`:

```python
def test_get_business_sector_tokens_returns_frozenset():
    """Sprint 2: business sector tokens are preserved, not stripped."""
    from synonym_loader import get_business_sector_tokens

    tokens = get_business_sector_tokens("IN")
    assert isinstance(tokens, frozenset)
    # Universal sectors from common.json
    for expected in ("industries", "enterprises", "trading", "international",
                     "technologies", "services", "solutions"):
        assert expected in tokens
    # IN-specific sectors
    for expected in ("pharma", "chemicals", "auto", "electronics", "steel"):
        assert expected in tokens


def test_get_business_sector_tokens_excludes_legal_suffixes():
    """Business sectors and legal suffixes are disjoint."""
    from synonym_loader import (
        get_business_sector_tokens,
        get_legal_suffix_tokens,
    )

    sectors = get_business_sector_tokens("IN")
    legal = get_legal_suffix_tokens("IN")
    overlap = sectors & legal
    assert not overlap, f"Categories must be disjoint, overlap={sorted(overlap)}"


def test_get_business_sector_canonical_map_maps_to_rule_target():
    """Each source token on the left of => maps to the rule's canonical target."""
    from synonym_loader import get_business_sector_canonical_map

    mapping = get_business_sector_canonical_map("IN")
    # Regular plurals
    assert mapping.get("enterprise") == "enterprises"
    assert mapping.get("enterprises") == "enterprises"
    # Irregular plurals handled via explicit rule target
    assert mapping.get("industry") == "industries"
    assert mapping.get("industries") == "industries"
    assert mapping.get("technology") == "technologies"
    assert mapping.get("technologies") == "technologies"
    # Abbreviations canonicalise to full form
    assert mapping.get("tech") == "technologies"
    assert mapping.get("intl") == "international"
    # Sector words from IN-specific file
    assert mapping.get("pharmaceutical") == "pharma"
    assert mapping.get("pharmaceuticals") == "pharma"
```

- [ ] **Step 2: Run the tests — they must FAIL**

Run: `python -m pytest tests/test_synonym_loader.py -k "business_sector" -v`
Expected: 3 tests FAIL with `ImportError`.

- [ ] **Step 3: Add the two functions to synonym_loader**

In `synonym_loader.py`, add immediately after `get_legal_suffix_tokens`:

```python
@lru_cache(maxsize=None)
def get_business_sector_tokens(country_code: str) -> frozenset:
    """Ulkeye ozgu business_sector token'larini doner.

    Bunlar stripping'e GIRMEZ — firma ismini AYIRT eden sektor/is kolu kelimeleridir.
    "Apex Pharma" ve "Apex Steel" farkli firmalardir.
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "business_sectors")


@lru_cache(maxsize=None)
def get_business_sector_canonical_map(country_code: str) -> dict:
    """Ulkeye ozgu business_sectors kurallarindan {source: target} map'i doner.

    Her kural 'src1,src2,src3=>target' formatinda. Soldaki her token ve
    target'in kendisi target'a map edilir. Hem cogul normalizasyonu
    (industry -> industries) hem de kisaltma normalizasyonu (intl ->
    international) tek bir yerden yonetilir.

    Donus: dict (NOT frozenset — bu bir map)
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    mapping: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("business_sectors", [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            rule_norm = normalize_text(rule)
            if "=>" not in rule_norm:
                continue
            left, right = rule_norm.split("=>", 1)
            target = right.strip().lower().replace(".", "")
            if not target:
                continue
            for src in left.split(","):
                src_token = src.strip().lower().replace(".", "")
                if src_token:
                    mapping[src_token] = target
            # Target also maps to itself (idempotent canonicalisation)
            mapping[target] = target
    return mapping
```

- [ ] **Step 4: Run the tests — they must PASS**

Run: `python -m pytest tests/test_synonym_loader.py -k "business_sector" -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat: add get_business_sector_tokens and canonical_map

Sprint 2 — business_sectors category is preserved during stripping.
The canonical map derives plural/abbreviation normalisation from rule
targets (e.g. industry -> industries, intl -> international) including
irregular plurals, replacing Sprint 1's brittle +s heuristic."
```

---

## Task 6: Update `synonym_loader.get_company_type_tokens` as a shim

**Files:**
- Modify: `synonym_loader.py` (reroute `get_company_type_tokens` through new APIs)
- Modify: `tests/test_synonym_loader.py` (update expectations)

This step keeps existing callers working without a big bang. `get_company_type_tokens(country)` now returns just `get_legal_suffix_tokens(country)` — the sector-word preservation guarantee moves inside the loader. The old `_parse_company_type_tokens` function is kept for one more release so callers that still expect the union can migrate gradually, but nothing in Sprint 2 uses it.

- [ ] **Step 1: Update `get_company_type_tokens` to shim over `get_legal_suffix_tokens`**

In `synonym_loader.py`, replace the body of `get_company_type_tokens` (keep signature + decorator):

```python
@lru_cache(maxsize=None)
def get_company_type_tokens(country_code: str) -> frozenset:
    """DEPRECATED shim — use get_legal_suffix_tokens directly.

    Sprint 2: Bu fonksiyon artik yalnizca legal_suffixes kategorisini doner.
    business_sectors ayri bir kategori haline geldi ve stripping'e girmez.
    Eski cagrilar icin backward-compat saglamak uzere korunuyor.
    """
    return get_legal_suffix_tokens(country_code)
```

Also delete the now-unused old helper `_parse_company_type_tokens` (lines 145-172). Nothing references it any more after the shim.

- [ ] **Step 2: Delete the Sprint 1 subtraction test that no longer applies**

In `tests/test_synonym_loader.py`, find `test_get_company_type_tokens_excludes_business_descriptors`. This test asserted the Sprint 1 BUSINESS_DESCRIPTORS subtraction. Under Sprint 2 the guarantee comes from JSON category separation, not from a Python frozenset. Replace the test body with:

```python
def test_get_company_type_tokens_equals_legal_suffixes():
    """Sprint 2: get_company_type_tokens is a shim over get_legal_suffix_tokens."""
    from synonym_loader import get_company_type_tokens, get_legal_suffix_tokens
    assert get_company_type_tokens("IN") == get_legal_suffix_tokens("IN")
```

- [ ] **Step 3: Delete `get_generic_tokens_for_country` (dead code)**

In `synonym_loader.py`, delete the entire `get_generic_tokens_for_country` function (lines ~99-142). Nothing in Sprint 1 or Sprint 2 uses it — it is pre-Sprint-1 dead code. Also remove the matching `from config import BUSINESS_DESCRIPTORS` import at the top of `synonym_loader.py` because `BUSINESS_DESCRIPTORS` is about to be deleted from config entirely in Task 14.

- [ ] **Step 4: Run the tests — they must PASS**

Run: `python -m pytest tests/test_synonym_loader.py -v`
Expected: all tests pass. If the old `test_get_company_type_tokens_includes_common_tokens` test now fails because it asserted `"corp"` is in the tokens but the common.json migration renamed the rule, update that test's expected set to match the new legal_suffixes content (`ltd`, `inc`, `corp`, `co`, `llc`, `llp`, `pvt`).

- [ ] **Step 5: Commit**

```bash
git add synonym_loader.py tests/test_synonym_loader.py
git commit -m "refactor: reroute get_company_type_tokens through get_legal_suffix_tokens

Sprint 2 — the shim keeps existing callers working while the canonical
source of truth moves to get_legal_suffix_tokens. Dead code removed:
get_generic_tokens_for_country and _parse_company_type_tokens.
BUSINESS_DESCRIPTORS import removed (config constant deleted in Task 14)."
```

---

## Task 7: Remove `_is_fuzzy_suffix` and `_edit_distance` from main_processor

**Files:**
- Modify: `main_processor.py` (delete two helpers + their callers)

This is the core bug kill. `_is_fuzzy_suffix` was the source of "fine" → "fie" edit-distance-1 match that silently removed brand tokens from input. It must die entirely.

- [ ] **Step 1: Delete the two helpers**

In `main_processor.py`, locate:

```python
def _edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance. Dış bağımlılık yok."""
    ...


def _is_fuzzy_suffix(token: str, suffix_tokens: frozenset) -> bool:
    """Token, bilinen bir suffix'e ES AUTO:4,7 eşiğiyle eşleşiyor mu?
    ...
    """
    ...
```

Delete both functions and their docstrings. They are approximately 40 lines together.

- [ ] **Step 2: Remove the SUFFIX_FUZZY branch's use of `_is_fuzzy_suffix`**

In `main_processor.py`, inside `_post_verify`'s SUFFIX_FUZZY branch, find:

```python
        for _t in _cleaned.split():
            _tc = _t.rstrip('.,')
            if not _tc or (len(_tc) <= 1 and not _tc.isalnum()):
                continue
            if _tc in article_tokens:
                continue
            # Fuzzy suffix ise ve doc'ta geçmiyorsa atla; doc'ta geçiyorsa koru
            if _is_fuzzy_suffix(_tc, suffix_tokens) and _tc not in doc_name_tokens:
                continue
            input_stripped_ordered.append(_tc)
```

Replace the `_is_fuzzy_suffix` line block with a deterministic exact-match plus typo-map check:

```python
        for _t in _cleaned.split():
            _tc = _t.rstrip('.,')
            if not _tc or (len(_tc) <= 1 and not _tc.isalnum()):
                continue
            if _tc in article_tokens:
                continue
            # Sprint 2: yalnizca exact suffix match + deterministic typo map.
            # _is_fuzzy_suffix deleted — caused "fine" ↔ "fie" ghost matches.
            typo_canonical = SUFFIX_TYPO_MAP.get(_tc, _tc)
            if typo_canonical in suffix_tokens and typo_canonical not in doc_name_tokens:
                continue
            input_stripped_ordered.append(_tc)
```

Add the `SUFFIX_TYPO_MAP` import to the existing `from config import (...)` block in `main_processor.py` (alphabetically after `STAGES`):

```python
from config import (
    ...
    STAGES,
    SUFFIX_FUZZY_SCORE,
    SUFFIX_TYPO_MAP,
    TOKEN_COVERAGE_THRESHOLD,
)
```

- [ ] **Step 3: Run the full test suite to check for collateral damage**

Run: `python -m pytest tests/ -v --tb=short`
Expected: most tests pass. Any test that asserted `_is_fuzzy_suffix` behaviour (e.g., Sprint 1's `test_post_verify_suffix_fuzzy_known_typo_passes`) will break. Update those tests by replacing any direct `_is_fuzzy_suffix` import with `SUFFIX_TYPO_MAP`-based assertions, or delete the tests if they were purely testing the deleted mechanism.

Concretely, in `tests/test_main_processor.py`, any test body that reads `mp._is_fuzzy_suffix(...)` must be removed or rewritten. A test that used `_edit_distance` directly gets the same treatment. Keep tests that exercise `_post_verify` at its public interface — those should continue to pass as long as their fixture data does not rely on the old ghost-match behaviour.

- [ ] **Step 4: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "fix: remove _is_fuzzy_suffix and _edit_distance (root cause of FPs)

Sprint 2 — _is_fuzzy_suffix identified 'fine' as a fuzzy match for a foreign
'fie' legal form at edit distance 1 and silently stripped it from input
tokens, collapsing ATLAS FINE CHEMICALS into ATLAS CHEMICALS.

Replacement: exact-suffix check + deterministic SUFFIX_TYPO_MAP. All
fuzzy tolerance is now hand-curated, no edit-distance free-for-all."
```

---

## Task 8: Replace `_BUSINESS_DESCRIPTOR_CANONICAL` with rule-based map

**Files:**
- Modify: `main_processor.py` (delete Sprint 1 +s heuristic, add per-country rule-based helper)
- Modify: `tests/test_matching_regression.py` (update helper unit tests)

- [ ] **Step 1: Delete Sprint 1 canonical map infrastructure**

In `main_processor.py`, delete these definitions (approximately lines 280-305):

```python
def _build_business_descriptor_canonical_map(descriptors: frozenset) -> dict[str, str]:
    ...


_BUSINESS_DESCRIPTOR_CANONICAL = _build_business_descriptor_canonical_map(BUSINESS_DESCRIPTORS)
```

Also delete `BUSINESS_DESCRIPTORS` from the `from config import (...)` block in the same file. `BUSINESS_DESCRIPTORS` is about to vanish from config entirely in Task 14.

- [ ] **Step 2: Update `_tokenize` to use per-country canonical map**

In `main_processor.py`, find the existing `_tokenize` function:

```python
def _tokenize(name: str, country: str = "") -> set[str]:
    ...
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

Replace with:

```python
def _tokenize(name: str, country: str = "") -> set[str]:
    """Firma ismini anlamli tokenlara ayirir.

    Sprint 2 algoritmasi:
      - lower + strip labels + split
      - Tek-char (alfanumerik disinda) tokenlari at
      - Ulke-adi tokenlarini at
      - Legal suffix'leri at (typo map sonrasi)
      - Article'lari at
      - Business sector tokenlari canonical map uzerinden normalize et
    """
    cleaned = _clean_labels(name)
    tokens = cleaned.lower().split()
    country_tokens = _COUNTRY_NAME_TOKENS.get(country.upper(), frozenset())
    legal_suffixes = get_legal_suffix_tokens(country)
    article_tokens = get_article_stopwords(country)
    sector_canonical = get_business_sector_canonical_map(country)
    result = set()
    for t in tokens:
        t_clean = t.rstrip('.,')
        if not t_clean:
            continue
        if len(t_clean) <= 1 and not t_clean.isalnum():
            continue
        if t_clean in country_tokens:
            continue
        # Deterministik typo canonicalisation (limted -> limited)
        t_clean = SUFFIX_TYPO_MAP.get(t_clean, t_clean)
        if t_clean in legal_suffixes or t_clean in article_tokens:
            continue
        # Business sector canonicalisation (industry -> industries, intl -> international)
        t_clean = sector_canonical.get(t_clean, t_clean)
        result.add(t_clean)
    return result
```

Add `get_legal_suffix_tokens` and `get_business_sector_canonical_map` to the existing `from synonym_loader import ...` line in `main_processor.py`:

```python
from synonym_loader import (
    get_article_stopwords,
    get_business_sector_canonical_map,
    get_legal_suffix_tokens,
    get_company_type_tokens,  # kept for backward compat callers
)
```

- [ ] **Step 3: Update `_first_meaningful_token` to use the same canonical map**

In `main_processor.py`, find the existing `_first_meaningful_token`:

```python
def _first_meaningful_token(name: str, country: str = "") -> str | None:
    ...
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

Replace with:

```python
def _first_meaningful_token(name: str, country: str = "") -> str | None:
    """Ismin ilk anlamli token'ini doner (brand anchor).

    Sprint 2 — per-country canonical map ile tekil/cogul ve kisaltma
    normalizasyonu (industry/industries, intl/international, vb.).
    """
    cleaned = _clean_labels(name).lower()
    country_tokens = _COUNTRY_NAME_TOKENS.get(country.upper(), frozenset())
    legal_suffixes = get_legal_suffix_tokens(country)
    article_tokens = get_article_stopwords(country)
    sector_canonical = get_business_sector_canonical_map(country)
    for raw in cleaned.split():
        t = raw.rstrip('.,')
        if not t:
            continue
        if len(t) <= 1 and not t.isalnum():
            continue
        if t in country_tokens:
            continue
        t = SUFFIX_TYPO_MAP.get(t, t)
        if t in legal_suffixes or t in article_tokens:
            continue
        return sector_canonical.get(t, t)
    return None
```

- [ ] **Step 4: Update the canonical-map unit tests**

In `tests/test_matching_regression.py`, find `test_business_descriptor_canonical_map_covers_regular_plurals`. Replace the test body with:

```python
def test_business_sector_canonical_map_handles_regular_and_irregular():
    """Sprint 2: canonical map comes from rule targets, handles both regular
    and irregular plurals via the synonym JSON."""
    from synonym_loader import get_business_sector_canonical_map

    m = get_business_sector_canonical_map("IN")
    # Regular and irregular plurals — both handled because rule targets drive it
    expected_pairs = [
        ("enterprise", "enterprises"),
        ("enterprises", "enterprises"),
        ("industry", "industries"),
        ("industries", "industries"),
        ("technology", "technologies"),
        ("technologies", "technologies"),
        ("service", "services"),
        ("services", "services"),
    ]
    for src, tgt in expected_pairs:
        assert m.get(src) == tgt, f"{src!r} should map to {tgt!r}"

    # Abbreviations canonicalise too
    assert m.get("intl") == "international"
    assert m.get("tech") == "technologies"
```

The old test referenced `mp._BUSINESS_DESCRIPTOR_CANONICAL` which no longer exists — rename the test and import from the loader instead.

Also delete the Sprint 1 `test_tokenize_canonicalises_plural_descriptors` if it still uses the old attribute, or update it to reference the new behaviour by calling `_tokenize` directly (the external contract is unchanged: two singular/plural variants produce identical token sets).

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_matching_regression.py -v --tb=short`
Expected: regression tests pass. If any fail, they are likely asserting the old `_BUSINESS_DESCRIPTOR_CANONICAL` attribute — update them to call `get_business_sector_canonical_map("IN")` directly.

- [ ] **Step 6: Commit**

```bash
git add main_processor.py tests/test_matching_regression.py
git commit -m "refactor: drive plural canonicalisation from synonym rule targets

Sprint 2 — replaces Sprint 1's +s heuristic (which couldn't handle
irregular plurals like industry/industries) with a per-country canonical
map sourced from business_sectors rule targets. _tokenize and
_first_meaningful_token now apply SUFFIX_TYPO_MAP before legal-suffix
filtering and sector_canonical after."
```

---

## Task 9: Add `strict_name_match` helper

**Files:**
- Modify: `main_processor.py` (add new function)
- Uses tests already landed in Task 1 (`tests/test_strict_name_match.py`)

- [ ] **Step 1: Confirm the Task 1 fixtures are still red**

Run: `python -m pytest tests/test_strict_name_match.py -v --tb=line -q`
Expected: all tests FAIL with `AttributeError: module 'main_processor' has no attribute 'strict_name_match'`.

- [ ] **Step 2: Add the `strict_name_match` function**

In `main_processor.py`, add this function immediately after `_first_meaningful_token` (before `_symmetric_token_coverage`):

```python
def strict_name_match(input_name: str, master_name: str, country: str = "") -> bool:
    """Sprint 2 strict matching.

    Extract ordered name tokens from both names by:
      1. Cleaning labels + lowercasing
      2. Normalising every token through SUFFIX_TYPO_MAP
      3. Dropping tokens in legal_suffixes, articles, or country-name set
      4. Canonicalising business-sector tokens via rule-based map
      5. Dropping tokens that are single non-alphanumeric chars

    Returns True iff both sides produce at least 2 meaningful tokens AND
    the resulting ordered lists are strictly equal.

    This is the canonical "same company" check for Sprint 2. TOKEN_COVERAGE
    and fuzzy stages keep their own looser post-verify logic.
    """
    country_tokens = _COUNTRY_NAME_TOKENS.get(country.upper(), frozenset())
    legal_suffixes = get_legal_suffix_tokens(country)
    article_tokens = get_article_stopwords(country)
    sector_canonical = get_business_sector_canonical_map(country)

    def extract(name: str) -> list[str]:
        cleaned = _clean_labels(name).lower()
        out: list[str] = []
        for raw in cleaned.split():
            t = raw.rstrip('.,;:!?')
            if not t:
                continue
            if len(t) <= 1 and not t.isalnum():
                continue
            if t in country_tokens:
                continue
            t = SUFFIX_TYPO_MAP.get(t, t)
            if t in legal_suffixes or t in article_tokens:
                continue
            t = sector_canonical.get(t, t)
            out.append(t)
        return out

    in_name = extract(input_name)
    ma_name = extract(master_name)

    if len(in_name) < 2 or len(ma_name) < 2:
        return False
    return in_name == ma_name
```

- [ ] **Step 3: Run the Sprint 2 fixtures — they must PASS**

Run: `python -m pytest tests/test_strict_name_match.py -v --tb=short`
Expected: all tests in the file pass. Specifically:

- 3 FP forward + 3 FP reverse = 6 tests reject the ATLAS/BABA pairs
- 7 TP forward + 7 TP reverse = 14 tests accept the same-brand variants (including `ATLAS FINE CHEMICALS PVT LTD` ↔ `ATLAS FINE CHEMICALS PRIVATE LIMITED` and `ISHA ENTERPRISES` ↔ `ISHA ENTERPRISE`)
- 2 edge tests (single-token brand + empty after strip)

Total: 22 new tests green.

If any test fails, STOP and diagnose. The common failure modes:
- TP fails because `ATLAS FINE CHEMICALS PVT LTD` and `ATLAS FINE CHEMICALS PRIVATE LIMITED` produce different extract results — usually because `private` or `limited` is missing from `legal_suffixes`. Check that the common.json rule `"private limited company,...,limited,ltd.,limitada=>ltd."` is present.
- FP fails because stripping collapses a differing brand token into nothing — check the typo map and that `baba` / `atlas` / `fine` are NOT in any legal suffix list.

- [ ] **Step 4: Commit**

```bash
git add main_processor.py
git commit -m "feat: add strict_name_match with per-country isolation

Sprint 2 — the core new helper. Extracts ordered name tokens by stripping
only per-country legal_suffixes + articles, canonicalising business
sectors via rule targets, and comparing the resulting lists as strict
order-sensitive equality.

Passes all 22 Sprint 2 regression tests including the three real FPs
from session 2026-04-10: ATLAS CHEMICALS vs ATLAS FINE CHEMICALS,
AB WOOD PRODUCTS vs BABA WOOD PRODUCTS, A.S. ENGINEERING vs BABA
ENGINEERING."
```

---

## Task 10: Refactor `_post_verify` SUFFIX_FUZZY branch to use `strict_name_match`

**Files:**
- Modify: `main_processor.py` (`_post_verify` SUFFIX_FUZZY branch)

- [ ] **Step 1: Locate the current SUFFIX_FUZZY branch**

In `main_processor.py`, find `_post_verify`'s SUFFIX_FUZZY branch. It starts roughly:

```python
    # ── SUFFIX_FUZZY ──────────────────────────────────────────────────────────
    if stage_name == "SUFFIX_FUZZY":
        doc_stripped_raw = master_source.get("variations_stripped", [])
        ...
```

and ends with either `return True` or `return False`. It is approximately 60 lines long.

- [ ] **Step 2: Replace the entire SUFFIX_FUZZY branch with a thin call to `strict_name_match`**

Replace the whole branch with:

```python
    # ── SUFFIX_FUZZY ──────────────────────────────────────────────────────────
    # Sprint 2: delegates to strict_name_match. The ES query still uses the
    # variations_stripped + variations_suffix fields (see es_queries.SUFFIX_FUZZY)
    # to surface candidates, but post-verification requires exact name equality.
    if stage_name == "SUFFIX_FUZZY":
        return strict_name_match(input_name, master_name, country)
```

Note: `master_name` is already computed earlier in `_post_verify` as `master_variations[0]`. The strict_name_match function handles its own normalisation, so passing the raw first variation is correct.

- [ ] **Step 3: Run the regression suite**

```bash
python -m pytest tests/test_matching_regression.py tests/test_strict_name_match.py tests/test_main_processor.py -v --tb=short
```

Expected: all green. Specifically:

- Sprint 1 regression: 41/41 pass
- Sprint 2 regression: 22/22 pass
- test_main_processor: all pass (any remaining tests that poked SUFFIX_FUZZY's internal structure — `doc_multi_char`, `input_stripped_ordered`, etc. — must either be updated to assert the new `strict_name_match`-based behaviour or deleted)

If a Sprint 1 SUFFIX_FUZZY test fails because it asserted something like `doc_multi_char < 2 → False`, update that test to call `strict_name_match` directly, or convert it to an integration test that feeds a known fixture through `_post_verify` and expects the stricter behaviour.

- [ ] **Step 4: Commit**

```bash
git add main_processor.py tests/test_main_processor.py
git commit -m "refactor: _post_verify SUFFIX_FUZZY branch now calls strict_name_match

Sprint 2 — the 60-line branch with doc_multi_char, input_stripped_ordered,
fuzzy-suffix detection, and ordered comparison is replaced with a single
call. All Sprint 1 guarantees plus the three new FPs are covered.

The ES query layer (es_queries.SUFFIX_FUZZY) is unchanged — it still
surfaces candidates via variations_stripped + variations_suffix and
the post-verify layer makes the final decision."
```

---

## Task 11: Update `es_ingest` to use `get_legal_suffix_tokens` only

**Files:**
- Modify: `es_ingest.py` (four places reference `get_company_type_tokens`)

- [ ] **Step 1: Update the import**

In `es_ingest.py`, find:

```python
from synonym_loader import get_company_type_tokens, get_all_country_codes, get_article_stopwords
```

Replace with:

```python
from synonym_loader import (
    get_all_country_codes,
    get_article_stopwords,
    get_legal_suffix_tokens,
)
```

- [ ] **Step 2: Update `_build_clean_script` spaced-suffix rejoining**

In `es_ingest.py`, find in `_build_clean_script`:

```python
    tokens = get_company_type_tokens(country_code)
    known = sorted(t for t in tokens if t.isalpha() and " " not in t and len(t) <= 6)
```

Replace with:

```python
    tokens = get_legal_suffix_tokens(country_code)
    known = sorted(t for t in tokens if t.isalpha() and " " not in t and len(t) <= 6)
```

Rationale: the spaced-suffix rejoining ("l t d" → "ltd") should only happen for LEGAL suffixes. Business sector words like "p h a r m a" should not be rejoined because the brand would never naturally be space-separated.

- [ ] **Step 3: Update `_build_stripped_script`**

In `es_ingest.py`, find in `_build_stripped_script`:

```python
    # Company type + article token'larını birleştir; çok-kelimeli token'lar filtrele
    suffix_tokens = [t for t in get_company_type_tokens(country_code) if " " not in t]
    article_tokens = [t for t in get_article_stopwords(country_code) if " " not in t]
    all_tokens = list(dict.fromkeys(suffix_tokens + article_tokens))  # dedup, order preserved
```

Replace with:

```python
    # Sprint 2: yalnizca legal_suffixes + articles stripping'e girer.
    # business_sectors kategorisi PRESERVED — firma ismini ayirt eden kelimeler.
    suffix_tokens = [t for t in get_legal_suffix_tokens(country_code) if " " not in t]
    article_tokens = [t for t in get_article_stopwords(country_code) if " " not in t]
    all_tokens = list(dict.fromkeys(suffix_tokens + article_tokens))  # dedup, order preserved
```

- [ ] **Step 4: Update `build_pipeline_body` suffix-list source**

In `es_ingest.py`, find `build_pipeline_body`:

```python
def build_pipeline_body(country_code: str) -> dict:
    """Ingest pipeline tanımını oluşturur."""
    company_type_tokens = list(get_company_type_tokens(country_code))
    return {
        ...
    }
```

Replace with:

```python
def build_pipeline_body(country_code: str) -> dict:
    """Ingest pipeline tanımını oluşturur.

    Sprint 2: variations_suffix artik yalnizca legal_suffixes iceriyor.
    business_sectors variations_stripped'da KORUNUR.
    """
    legal_suffix_tokens = list(get_legal_suffix_tokens(country_code))
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
            {
                "script": {
                    "description": f"suffix_form for {country_code.upper()}",
                    "source": _build_suffix_script(legal_suffix_tokens),
                }
            },
        ],
    }
```

- [ ] **Step 5: Sanity check — simulate the pipeline on one problem input**

Run:

```bash
python -c "
from es_manager import get_es_client
from es_ingest import register_all_pipelines
es = get_es_client()
register_all_pipelines(es)
# Simulate
result = es.ingest.simulate(id='company_name_in', body={
    'docs': [{'_source': {'country_code': 'IN', 'variations': ['AB WOOD PRODUCTS PVT LTD']}}]
})
src = result['docs'][0]['doc']['_source']
print('variations         :', src.get('variations'))
print('variations_stripped:', src.get('variations_stripped'))
print('variations_suffix  :', src.get('variations_suffix'))
"
```

Expected output:

```
variations         : ['ab wood products pvt ltd']
variations_stripped: ['ab wood products']
variations_suffix  : ['ltd pvt']
```

Critical: `variations_stripped` must CONTAIN `ab` (because "ab" is no longer in `get_legal_suffix_tokens("IN")` after Sprint 2). This is the exact bug Sprint 2 fixes.

If `ab` is still missing, check that `other.json` is actually deleted (Task 3) and that `synonym_loader.COMMON_FILES` no longer references it.

- [ ] **Step 6: Commit**

```bash
git add es_ingest.py
git commit -m "refactor: es_ingest uses get_legal_suffix_tokens only

Sprint 2 — the ingest pipeline's clean + stripped + suffix scripts now
source from legal_suffixes only. Business sectors are preserved in
variations_stripped.

Verified via ingest.simulate: 'ab wood products pvt ltd' now strips to
'ab wood products' (ab preserved), previously stripped to 'wood products'."
```

---

## Task 12: Update `es_manager` analyzer stop filter

**Files:**
- Modify: `es_manager.py` (search for `get_company_type_tokens` references)

- [ ] **Step 1: Locate the call sites**

Run:

```bash
grep -n "get_company_type_tokens" es_manager.py
```

Expected: one or two lines, likely inside `create_index` where the stripped search analyzer is defined.

- [ ] **Step 2: Update the import**

In `es_manager.py`, find:

```python
from synonym_loader import (
    ...
    get_company_type_tokens,
    ...
)
```

Add `get_legal_suffix_tokens`:

```python
from synonym_loader import (
    ...
    get_company_type_tokens,
    get_legal_suffix_tokens,
    ...
)
```

(Keep `get_company_type_tokens` too for any other references — it is now a thin shim and still works, but we want all new code to use the explicit name.)

- [ ] **Step 3: Replace the stop filter source**

Wherever `es_manager.py` uses `get_company_type_tokens(cc)` to build a stop filter for the stripped search analyzer, replace with `get_legal_suffix_tokens(cc)`. The filter semantics are identical in Sprint 2 terms: only legal suffixes should be stopped at search time.

If the file builds a global fallback filter via `get_all_company_type_tokens()`, that function is also now a shim over a sector-free list in Sprint 2, so it stays. No change needed there.

- [ ] **Step 4: Rebuild the ES index to pick up analyzer changes**

Run:

```bash
python es_manager.py --force
```

Expected: index deleted and recreated with the new analyzer definitions. The stripped search analyzer stop filter for IN should no longer contain `ab`, `as`, `pharma`, `industries`, etc.

- [ ] **Step 5: Verify via _analyze API**

Run:

```bash
python -c "
from es_manager import get_es_client
es = get_es_client()
res = es.indices.analyze(index='living_companies_v1', body={
    'analyzer': 'stripped_search_analyzer_in',
    'text': 'ab wood products pvt ltd'
})
print([t['token'] for t in res['tokens']])
"
```

Expected: `['ab', 'wood', 'products']` — `ab` present (not stripped), `pvt`/`ltd` dropped.

- [ ] **Step 6: Commit**

```bash
git add es_manager.py
git commit -m "refactor: es_manager stripped analyzer uses get_legal_suffix_tokens

Sprint 2 — the stop filter for stripped_search_analyzer now sources from
legal_suffixes only, matching the ingest pipeline's stripping decisions.
Verified via _analyze: 'ab wood products pvt ltd' tokenises to
['ab', 'wood', 'products']."
```

---

## Task 13: Remove `config.BUSINESS_DESCRIPTORS`

**Files:**
- Modify: `config.py` (delete the frozenset)
- Modify: `tests/test_config.py` (delete the Sprint 1 test)

- [ ] **Step 1: Delete the frozenset**

In `config.py`, delete the entire `BUSINESS_DESCRIPTORS = frozenset({...})` definition plus the comment block above it (approximately lines 104-147 after Sprint 1's Task 2 widening).

- [ ] **Step 2: Delete the Sprint 1 test**

In `tests/test_config.py`, delete `test_business_descriptors_includes_sector_words` entirely. The constant no longer exists, and the guarantee it used to provide is now enforced by JSON schema separation at the loader level (tested in `test_synonym_loader.py::test_get_legal_suffix_tokens_excludes_sectors`).

- [ ] **Step 3: Verify no stragglers reference the constant**

Run:

```bash
grep -rn "BUSINESS_DESCRIPTORS" --include="*.py" .
```

Expected: zero matches. If any remain, delete them (typically in `synonym_loader.py` if Task 6 missed an import, or a leftover test).

- [ ] **Step 4: Run the full suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "chore: remove config.BUSINESS_DESCRIPTORS (replaced by JSON schema)

Sprint 2 — the sector-preservation guarantee now lives in the
synonyms_data JSON schema as the 'business_sectors' category. No Python
constant is needed."
```

---

## Task 14: Reindex helper + IN dry-run

**Files:**
- Create: `scripts/sprint2_reindex.py`

- [ ] **Step 1: Create the reindex script**

Write `scripts/sprint2_reindex.py`:

```python
"""Sprint 2 reindex — re-register per-country pipelines under the new
legal_suffixes-only token set, then run update_by_query on selected
country shards.

Usage:
    python scripts/sprint2_reindex.py                # full reindex (all countries)
    python scripts/sprint2_reindex.py --only IN      # dry-run: only IN shard
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ES_INDEX  # noqa: E402
from es_ingest import pipeline_name, register_all_pipelines  # noqa: E402
from es_manager import get_es_client  # noqa: E402
from synonym_loader import get_all_country_codes  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def reindex_country(es, country_code: str) -> dict:
    cc = country_code.upper()
    pipe = pipeline_name(cc)
    body = {"query": {"term": {"country_code": cc}}}
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
    parser = argparse.ArgumentParser(description="Sprint 2 reindex helper")
    parser.add_argument("--only", metavar="CC", help="Reindex only this country code")
    args = parser.parse_args()

    es = get_es_client()

    logger.info("Step 1/2 — re-registering all ingest pipelines (Sprint 2 tokens)")
    register_all_pipelines(es)

    if args.only:
        codes = [args.only.upper()]
    else:
        codes = get_all_country_codes()
        logger.info("Full reindex across %d countries", len(codes))

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
    logger.info("Sprint 2 reindex complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run IN**

Run: `python scripts/sprint2_reindex.py --only IN`

Expected: all 43 (or whatever the current count is) pipelines re-register, then IN shard is updated. Logs show `updated=<N>, version_conflicts=0`. Known pre-Sprint-1 blocker: doc `da203c97-...` with 14 consecutive spaces may still cause `circuit_breaking_exception` — if so, the script will log the failure but exit 1 after processing the rest.

If that pre-existing bad doc blocks the run, either repair it in PG or delete it from ES before retrying. This is a pre-existing data issue, documented in the Sprint 1 results doc as a known follow-up.

- [ ] **Step 3: Spot-check the three Sprint 2 FPs after reindex**

Run:

```bash
python -c "
from es_manager import get_es_client
es = get_es_client()
queries = [
    ('IN', 'ab wood products'),
    ('IN', 'as engineering works'),
    ('IN', 'atlas chemicals'),
]
for cc, q in queries:
    res = es.search(index='living_companies_v1', routing=cc, body={
        'query': {'match_phrase': {'variations': q}},
        'size': 2
    })
    print(f'=== {q} ===')
    for hit in res['hits']['hits']:
        src = hit['_source']
        print(f'  variations         : {src.get(\"variations\")}')
        print(f'  variations_stripped: {src.get(\"variations_stripped\")}')
        print()
"
```

Expected:
- `ab wood products` → stripped contains `ab wood products` (ab preserved)
- `as engineering works` → stripped contains `as engineering works` (as preserved)
- `atlas chemicals` → stripped contains `atlas chemicals` (unchanged)

- [ ] **Step 4: Commit**

```bash
git add scripts/sprint2_reindex.py
git commit -m "chore: add Sprint 2 reindex helper + IN dry-run

Re-registers pipelines under the legal_suffixes-only token set and runs
update_by_query. Verified via spot-check that 'ab wood products' and
'as engineering works' now preserve the brand tokens in stripped form."
```

---

## Task 15: Full regression + results summary

**Files:**
- Create: `docs/superpowers/plans/2026-04-10-sprint2-strict-name-match-results.md`

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest tests/ -v --tb=no -q
```

Expected: everything green. Record the total pass count.

- [ ] **Step 2: Capture post-Sprint-2 baseline**

```bash
python scripts/sprint2_baseline_snapshot.py
```

This writes `baselines/sprint2_pre_<new-timestamp>.json`. Rename it to `sprint2_post_<new-timestamp>.json` (or add a `--phase post` flag to the script if you prefer):

```bash
mv baselines/sprint2_pre_*T$(date -u +%H)*.json baselines/sprint2_post_$(date -u +%Y%m%dT%H%M%SZ).json
```

Note: counts may be identical to the pre snapshot if the matcher has not been re-run against the full PG dataset yet. That is expected.

- [ ] **Step 3: Manual spot-check the three problem cluster**

Run:

```bash
python -c "
import psycopg2
from config import DB_CONFIG, RAW_TABLE_NAME
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
for master_code in [
    '19c2ff10-b84b-4b19-9c83-2de027a355c0',   # ATLAS CHEMICALS cluster
    '1e013c0c-de4f-4514-b593-0627dc120a21',   # AB WOOD PRODUCTS cluster
    'd984e32d-7ab4-451f-a0d0-6c452673a140',   # A.S. ENGINEERING cluster
]:
    cur.execute(f'SELECT ta_code, company_name, match_type FROM {RAW_TABLE_NAME} WHERE master_code = %s', (master_code,))
    rows = cur.fetchall()
    print(f'--- {master_code} ({len(rows)} rows)')
    for r in rows:
        print(f'  {r[0]} {r[2]:15} {r[1]!r}')
    print()
conn.close()
"
```

Record what you see. These clusters already contain the bad matches from before the reset (the user reset the matcher then re-ran it pre-Sprint-2, which produced the FPs). Sprint 2's code changes do not retroactively clean existing rows. To observe Sprint 2 behaviour on fresh data, the user must re-run the matcher after Sprint 2 is deployed — that is documented as a follow-up step.

- [ ] **Step 4: Write the results document**

Create `docs/superpowers/plans/2026-04-10-sprint2-strict-name-match-results.md`:

```markdown
# Sprint 2 Results — 2026-04-10 (strict_name_match)

## Baseline (pre-Sprint-2)

From `baselines/sprint2_pre_<timestamp>.json`:
- Total rows: <fill in>
- Unmatched: <fill in>
- Unique masters: <fill in>
- By type: <fill in>

## After Sprint 2 (code + analyzer rebuild + dry-run reindex on IN)

From `baselines/sprint2_post_<timestamp>.json`:
- <fill in actual numbers>
- Expected: counts unchanged because Sprint 2 does not retroactively
  reclassify existing matches. New writes go through the Sprint 2
  strict_name_match path.

## Regression fixture status

- `tests/test_matching_regression.py` (Sprint 1 fixtures): <N> passed
- `tests/test_strict_name_match.py` (Sprint 2 fixtures): 22 passed (6 FP
  + 14 TP + 2 edge)
- `tests/` full suite: <N> passed

## Sprint 2 implementation summary

| Task | Change | Commit |
|------|--------|--------|
| 0    | Baseline snapshot       | <sha> |
| 1    | Sprint 2 FP fixtures    | <sha> |
| 2    | common.json schema      | <sha> |
| 3    | other.json archived     | <sha> |
| 4    | get_legal_suffix_tokens | <sha> |
| 5    | business_sector APIs    | <sha> |
| 6    | get_company_type_tokens shim | <sha> |
| 7    | Delete _is_fuzzy_suffix | <sha> |
| 8    | Rule-based canonical map| <sha> |
| 9    | strict_name_match       | <sha> |
| 10   | _post_verify refactor   | <sha> |
| 11   | es_ingest refactor      | <sha> |
| 12   | es_manager refactor     | <sha> |
| 13   | Remove BUSINESS_DESCRIPTORS | <sha> |
| 14   | Reindex helper + dry-run| <sha> |

## Follow-ups

### Already-known blocker (carried over from Sprint 1)

Doc `da203c97-7e9e-4f43-bce2-74d387d34f8f`:
`"DECCAN NUTRACEUTICALS              PRIVATE LIMITED"` has 14 consecutive
spaces that trip the Painless regex circuit breaker during `update_by_query`.
Still unresolved. Two fixes available:
- SQL repair: collapse whitespace in the source row
- Pipeline harden: prepend `\s+ -> ' '` to the clean script

### Per-country migration (Sprint 3)

Currently only `synonyms_data/common.json` and `synonyms_data/in.json`
have been migrated to the new `legal_suffixes` + `business_sectors`
schema. The other ~50 country files still use the legacy
`company_types` key, which `_parse_category_tokens` will silently
ignore. For those countries, `get_legal_suffix_tokens()` returns just
the common.json content.

This is safe (degrades to "strip nothing country-specific") but reduces
recall for company names in those countries. Sprint 3 should migrate
the remaining country files following the same pattern as `in.json`.

### Pending data cleanup

The 3 FP clusters in PG (ATLAS CHEMICALS, AB WOOD PRODUCTS, A.S.
ENGINEERING) remain contaminated until the matcher is re-run against
the affected PG rows. Options:
1. Full matcher re-run (slow, clean)
2. Selective re-run: rollback rows where `match_type = 'SUFFIX_FUZZY'`
   to `NULL` and re-run only those
3. Leave as-is (least effort, dirty data persists)

Decision deferred to user.

## Recommended next steps

1. User reviews this document
2. Repair or hard-delete `da203c97-...`
3. Run full `python scripts/sprint2_reindex.py`
4. Decide re-run strategy for the 3 known contaminated clusters
5. Start Sprint 3 per-country JSON migration
```

- [ ] **Step 5: Commit the results document**

```bash
git add docs/superpowers/plans/2026-04-10-sprint2-strict-name-match-results.md baselines/sprint2_*.json
git commit -m "docs: Sprint 2 strict_name_match implementation results"
```

---

## Sprint 2 Exit Criteria

Sprint 2 is done when every item below is checked:

- [ ] All tests in `tests/test_strict_name_match.py` green (22/22)
- [ ] All Sprint 1 regression tests in `tests/test_matching_regression.py` remain green
- [ ] All tests in `tests/test_synonym_loader.py` green including new APIs
- [ ] `BUSINESS_DESCRIPTORS` reference is gone from the codebase (verified via grep)
- [ ] `other.json` is in `_archive/`, not in the active synonyms_data directory
- [ ] `common.json` has `legal_suffixes` + `business_sectors` + `articles` + `address_abbreviations` (no more `company_types`)
- [ ] ES pipeline for IN re-registered under new token set (verified via `ingest.simulate`: `ab wood products pvt ltd` → `variations_stripped: ['ab wood products']`)
- [ ] ES index rebuilt with new analyzer definitions (verified via `_analyze`: `stripped_search_analyzer_in` tokenises `ab wood products pvt ltd` to `[ab, wood, products]`)
- [ ] `_is_fuzzy_suffix` and `_edit_distance` deleted from `main_processor.py`
- [ ] Results document committed
- [ ] Known follow-ups escalated in the results document

---

## Self-Review Notes

**Spec coverage map (Sprint 2 requirements → tasks):**

| Requirement | Task |
|-------------|------|
| Delete `other.json` (verified unnecessary) | Task 3 |
| Migrate `common.json` to new schema | Task 2 |
| Keep TOKEN_COVERAGE / FUZZY_PHRASE / NGRAM_MATCH stages | Implicit — Task 10 only touches SUFFIX_FUZZY branch |
| Strict name match (name part identical) | Task 9 + Task 10 |
| Per-country isolation (no cross-country legal suffix bleed) | Task 3 (other.json archived) + Task 4 (get_legal_suffix_tokens reads common + country only) |
| Fuzzy suffix support only via `SUFFIX_TYPO_MAP` | Task 7 (delete `_is_fuzzy_suffix`) + Task 9 (strict_name_match uses typo map) |
| Rule-based canonical map (handles irregular plurals) | Task 5 + Task 8 |
| Update synonym_loader API | Tasks 4, 5, 6 |
| Update ES ingest pipeline | Task 11 |
| Update ES analyzer | Task 12 |
| Remove `BUSINESS_DESCRIPTORS` constant | Task 13 |
| Reindex helper + dry-run IN | Task 14 |
| Results document | Task 15 |

**No placeholders scan:** searched the plan for `TBD`, `TODO`, `fill in details`, `similar to Task`, `appropriate error handling`, `handle edge cases`, `write tests for`. The results summary template in Task 15 intentionally contains `<fill in>` and `<sha>` markers because those are values the executing engineer produces at runtime.

**Type consistency:** signatures used across tasks:
- `get_legal_suffix_tokens(country_code: str) -> frozenset` — defined Task 4, used Tasks 11, 12
- `get_business_sector_tokens(country_code: str) -> frozenset` — defined Task 5, used in disjointness test
- `get_business_sector_canonical_map(country_code: str) -> dict` — defined Task 5, used Tasks 8, 9
- `strict_name_match(input_name: str, master_name: str, country: str = "") -> bool` — defined Task 9, used Task 10
- `_parse_category_tokens(paths: list, category: str) -> frozenset` — defined Task 4, reused by Task 5 internally

All consistent. Plan ready for execution.
