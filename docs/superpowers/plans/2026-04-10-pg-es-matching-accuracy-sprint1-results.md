# Sprint 1 Results — 2026-04-10

## Baseline (before Sprint 1)

From `baselines/baseline_20260410T114018Z.json`:
- Total rows: 18,452,901
- Unmatched: 18,430,850
- Unique masters: 17,066
- By type: NEW_MASTER=18,879 · CANONICAL_EXACT=2,012 · STRIPPED_EXACT=913 · SUFFIX_FUZZY=243 · FUZZY_PHRASE=2 · NGRAM_MATCH=2

## After Sprint 1 (code only, no full reprocessing)

From `baselines/baseline_20260410T124414Z.json`:
- Total rows: 18,452,901
- Unmatched: 18,430,850
- Unique masters: 17,066
- By type: NEW_MASTER=18,879 · CANONICAL_EXACT=2,012 · STRIPPED_EXACT=913 · SUFFIX_FUZZY=243 · FUZZY_PHRASE=2 · NGRAM_MATCH=2
- Expected: counts are unchanged because Sprint 1 does not retroactively reclassify existing rows. Confirmed — every count is identical to the pre-Sprint 1 baseline.

## Regression fixture status

- `tests/test_matching_regression.py`: 41 passed (all 29 false positives rejected + 7 positive controls + 5 helper tests)
- `tests/` full suite: 142 passed

## Spot-check of a known contaminated cluster

Pulled from `p7_raw_firms_data` on 2026-04-10 via the `JAY & CO.` master cluster
(spec §4 reference cluster). The corrupt matches are still present, as expected
under Sprint 1's no-backfill policy:

```
in00024939  JAY CHEMICAL INDUSTRIES LTD                CANONICAL_EXACT
in00024939  JAY CHEMICAL INDUSTRIES LIMITED            CANONICAL_EXACT
in00024939  JAY CHEMICAL INDUSTRIES PRIVATE LIMITED    CANONICAL_EXACT
in00024939  JAY CHEMICAL INDUSTRIES LTD.               CANONICAL_EXACT
in00024923  JAY & CO.                                  NEW_MASTER
in00024949  JAY INTERNATIONAL.,                        STRIPPED_EXACT
in00024950  JAY INTERNATIONAL                          STRIPPED_EXACT
in00024948  JAY INTERNATIONAL..                        STRIPPED_EXACT
```

Observation: CANONICAL_EXACT is matching `JAY CHEMICAL INDUSTRIES *` against the
`JAY & CO.` master, and STRIPPED_EXACT is matching `JAY INTERNATIONAL` into the
same cluster. These are exactly the class of false positives Sprint 1's
`_post_verify` brand-anchor + min_tokens guard now rejects on the write path.
Existing rows are untouched until spec §7 cleanup runs.

## Sprint 1 implementation summary

| Task | Change | Commit |
|------|--------|--------|
| 0    | Baseline snapshot script | 2d5c462 |
| 1    | Regression fixtures      | cecb951 |
| 2    | BUSINESS_DESCRIPTORS widen | 032cf8b |
| 3    | Guard in synonym_loader  | 0d4fcba |
| 4    | Plural canonicalization + _first_meaningful_token | eae5356 |
| 5    | _post_verify min_tokens + CANONICAL/STRIPPED thresholds | 5b7f787 |
| 6    | TOKEN_COVERAGE brand-anchor | 78185e4 |
| 7    | SUFFIX_FUZZY min 2 tokens | 2c254be |
| 8    | Cascade freeze (index_variation=False for 3 stages) | 76b1f24 |
| 9    | ES reindex helper (dry-run tested) | f5e38e2 |

## Follow-ups (required before full production reindex)

### Blocker: Pre-existing corrupt doc

Doc `da203c97-7e9e-4f43-bce2-74d387d34f8f` has the variation
`"DECCAN NUTRACEUTICALS              PRIVATE LIMITED"` (14 consecutive spaces).
Painless regex engine hits a `circuit_breaking_exception` during the
`\s*&\s*` pattern match. The doc was never successfully processed by any
pipeline — `variations_stripped: []`, `variations_suffix: None`. Task 9
dry-run aborted at 8,999/19,726 IN docs because of this.

**Required action before running full `python scripts/sprint1_reindex.py`:**

Option A — repair the doc:
```sql
UPDATE p7_firms_v2
SET company_name = regexp_replace(company_name, '\s+', ' ', 'g')
WHERE ta_code IN (
  SELECT ta_code FROM p7_firms_v2
  WHERE company_name ~ '\s{3,}'
);
```
And/or delete the ES doc and re-ingest after fix.

Option B — harden `es_ingest._build_clean_script`:
Add a pre-regex whitespace collapse at the start of the clean processor:
`text = /\s+/.matcher(text).replaceAll(' ').trim();` BEFORE any other regex
operations.

### Verified Sprint 1 pipeline behaviour (via `ingest.simulate`)

For input `"ketan pharma"`:
- `variations_stripped: ['ketan pharma']` (pharma preserved as meaningful)
- `variations_suffix: []` (pharma correctly excluded from suffix list)

For input `"aurobindo pharma limited"` (actual reprocessed IN doc):
- `variations_stripped: ['aurobindo pharma']`
- `variations_suffix: ['limited']`

Sprint 1 Task 3 guard is flowing through the ES pipeline correctly.

### Dataset observation

The `living_companies_v1` ES index currently contains only IN (India)
masters — 19,726 docs. Other country codes exist in `synonyms_data/` but
have no master docs yet. Sprint 1 therefore effectively optimises for
the India-only workload.

### Spec §7 cleanup — not addressed

The existing 3,172 contaminated matches in PG (CANONICAL_EXACT 2,012 +
STRIPPED_EXACT 913 + SUFFIX_FUZZY 243 + FUZZY_PHRASE 2 + NGRAM_MATCH 2)
are NOT cleaned by Sprint 1. Cleanup strategy is documented in spec §7
(three options: full reset, selective rollback, or leave as-is). Decision
deferred to user per the design discussion.

## Recommended next steps

1. User reviews this results document
2. User decides spec §7 cleanup strategy
3. Fix the corrupt doc (Option A or B above) OR decide to skip the full
   reindex and live with partial Sprint 1 benefits on new writes only
4. If fixing the doc: run `python scripts/sprint1_reindex.py` (full mode)
5. Monitor `match_stages_log` for 7 days per spec §6.3
6. Start Sprint 2 planning (synonym schema refactor) only after Sprint 1
   stabilises in production
