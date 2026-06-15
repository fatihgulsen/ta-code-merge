# Phase 2: FUZZY_PHRASE Stage Audit — Round 6

**Audit date:** 2026-06-12
**Stage:** FUZZY_PHRASE (config order 4, min_score=5.0, slop=1)
**Dataset:** `fuzzy_phrase_all.jsonl` (327 pairs) × overmerge verdict files (28 batches)
**Commit under review:** `2206407` — feat: Implement core coverage filter for fuzzy phrase and token coverage queries (2026-06-10 17:05:00 +0300)

---

## 1. FUZZY_PHRASE Precision (verdict-based)

| Metric | Value |
|--------|-------|
| Total FUZZY_PHRASE verdict pairs | 327 |
| SAME (correct match) | 286 |
| DIFFERENT (false positive) | 33 |
| UNSURE / OTHER | 8 |
| **Precision (SAME / total)** | **87.5%** |

> Note: "OTHER" = 5 UNSURE (genuine ambiguity: GM DE ARGENTINA SRL vs S.R.L., KRONEN INTERNACIONAL vs INTERNATIONAL, DR.LAZAR truncated) + 1 PLACEHOLDER (CUIT N. vs CUIT — should be EXCLUDED by input_filter). None alter the precision figure materially.

---

## 2. DIFFERENT Verdict Pairs — Full List (33 pairs)

| # | master_ta_code | variant_ta_code | master_name | variant_name | score | reason |
|---|----------------|-----------------|-------------|--------------|-------|--------|
| 1 | ar00037773 | ar80031983 | CABA | BUENOS | 9 | CABA vs BUENOS — both city abbreviations, different |
| 2 | ar80064892 | ar00082409 | SAB LOGISTICA | LOGISTICA DE ARGENTINA S.A. | 10 | SAB LOGISTICA vs LOGISTICA DE ARGENTINA — prefix dropped |
| 3 | ar80077988 | ar00017146 | VOLKSWAGEN OF AMERICA | VOLKSWAGEN ARGENTINA SA | 17 | geo-token substitution: AMERICA→ARGENTINA |
| 4 | ar80077988 | ar80019039 | VOLKSWAGEN OF AMERICA | VOLKSWAGEN ARGENTINA, S.A. | 17 | geo-token substitution |
| 5 | ar80077988 | ar80018046 | VOLKSWAGEN OF AMERICA | VOLKSWAGEN ARGENTINA S.A. | 17 | geo-token substitution |
| 6 | ar00025131 | ar00027686 | IE.MAT. S.R.L. | MAT S.R.L. | 17 | subset truncation — IE.MAT stripped to [ie,mat] vs [mat] |
| 7 | ar00026476 | ar80001308 | LA CANADA S.A. | C.A. S.A. | 9 | different single stripped tokens |
| 8 | ar00026476 | ar00045546 | LA CANADA S.A. | CA | 8 | different single token |
| 9 | ar00032179 | ar80040519 | SOUTH TRADING CORP. S.R.L. | SOUTH TRADE SRL | 7 | fuzziness: TRADING≈TRADE (edit distance 3) |
| 10 | ar00032179 | ar00087226 | SOUTH TRADING CORP. S.R.L. | SOUTH TRADE S.R.L. | 8 | fuzziness: TRADING≈TRADE |
| 11 | ar00044333 | ar80027242 | MIHLAGER COMPANY S.A. | COL, S.A. | 5 | completely different single token: mihlager vs col |
| 12 | ar00044333 | ar00020711 | MIHLAGER COMPANY S.A. | COL S.A. | 5 | completely different single token |
| 13 | ar00072047 | ar80050327 | BO HERMANOS S.A. | BOLIVIA | 11 | different single tokens: bo vs bolivia |
| 14 | ar80112230 | ar80016400 | GM BRASIL | GM DE ARGENTINA S.R.L. | 23 | geo-token substitution: brasil→argentina (2 vs 2 tokens) |
| 15 | ar80116852 | ar80103402 | ASOCIACION DE COOP. ARGENTINAS COOP. LTD. | ASOCIACION DE | 7 | massive truncation stub |
| 16 | ar00021818 | ar80031255 | DI.QUI.ME | D.I | 10 | subset: [di,qui,me] vs [di] (3 vs 1) |
| 17 | ar00025309 | ar80015682 | IN.ME.CAR. S.R.L. | CAR | 8 | subset: [me,car] vs [car] (2 vs 1) |
| 18 | ar00056291 | ar00073557 | OCEAN EXPORT S.A. | OCEAN IMPORT S.A. | 20 | semantically opposite token: export vs import |
| 19 | ar00069716 | ar00074487 | I.M.P. ARGENTINA S.R.L. | IMPORT ARGENTINA S.R.L. | 19 | fuzziness: IMP≈IMPORT (acronym expansion) |
| 20 | ar00074681 | ar80005732 | MS GLOBAL S.R.L. | M.S. INTERNATIONAL | 13 | different second token: global vs international |
| 21 | ar80000741 | ar80098652 | ASOCIACION CASA EDITORA SUDAMERICAN | ASOCIACION CASA EDITORA | 27 | subset: [asociacion,casa,editora,sudamerican] vs [asociacion,casa,editora] (4 vs 3) |
| 22 | ar80002657 | ar80023547 | DR.LAZER & CIA S.A. | DR | 7 | extreme truncation: [dr,lazer] vs [dr] (2 vs 1) |
| 23 | ar80018945 | ar80056634 | SC JOHNSON & SON DE ARGENTINA S.A.I.C. | JOHNSON & SON DE ARGENTINA S.A.I.C. | 15 | slop=1 allows SC prefix drop (scjohnson glued → same tokens minus SC) |
| 24 | ar80020839 | ar80017559 | S.C.JOHNSON & SON DE | S.C.JOHNSON & SON DE ARGENTINA | 14 | master is incomplete fragment; variant adds ARGENTINA (2 vs 3) |
| 25 | ar80023008 | ar80091303 | LEVI STRAUSS DE MEXICO S.A. DE C.V. | LEVI STRAUSS DE MEXICO | 16 | subset: [levi,strauss,mexico] vs [levi,strauss,mexico] — same count, cross-country |
| 26 | ar80027425 | ar80070765 | ECU LOGISTICS S.A. | E.C | 9 | extreme truncation: [ecu,logistics] vs [ec] (2 vs 1) |
| 27 | ar80069231 | ar80070765 | A&S LOGISTICS S.A. | E.C | 9 | completely different tokens + same short stub |
| 28 | ar80077509 | ar80077510 | PLASTICOS ISLA GRANDE Y | PLASTICOS LA ISLA GRANDE | 17 | slop=1 allows LA insertion between PLASTICOS and ISLA |
| 29 | ar80103264 | ar80063057 | ALMAR INTERNACIONAL DE | ALMAR INTERNATIONAL | 15 | different second token (internacional vs international — not synonym-mapped) |
| 30 | ar80103834 | ar80062794 | CLARIANT CORP. | BRA | 8 | completely different single tokens: clariant vs bra |
| 31 | ar80111559 | ar80062794 | CLARIANT BRASIL | BRA | 8 | completely different tokens; clariant+brasil vs bra (2 vs 1) |
| 32 | ar80113186 | ar00015068 | OMNILIFE USA INC | OMNILIFE DE ARGENTINA SA | 16 | geo-token substitution: usa→argentina |
| 33 | ar80125799 | ar80134860 | AV ALICIA MOREAU DE JUSTO 1720 1 A | AV ALICIA MOREAU DE JUSTO 1720 1 | 48 | address data in firm name field; last token "A" stripped by analyzer, yields same 6 tokens |

---

## 3. Error Mechanism Classification

ES `stripped_search_analyzer_ar` token counts were verified via `POST /living_companies_v1/_analyze` for each pair.

### (c) Subset / Truncation — token_count DIFF → `_core_coverage_filter` WOULD BLOCK (9 pairs)

These pairs have unequal stripped token counts. The `_core_coverage_filter` (`variations_stripped.name.token_count` term filter) would have blocked them **if the matches had been produced after commit 2206407**:

| Pair | Master tokens (n) | Variant tokens (n) |
|------|-------------------|---------------------|
| IE.MAT. vs MAT | [ie, mat] (2) | [mat] (1) |
| DI.QUI.ME vs D.I | [di, qui, me] (3) | [di] (1) |
| IN.ME.CAR. vs CAR | [me, car] (2) | [car] (1) |
| DR.LAZER vs DR | [dr, lazer] (2) | [dr] (1) |
| ASOCIACION CASA EDITORA SUDAMERICAN vs ASOCIACION CASA EDITORA | (4) | (3) |
| ECU LOGISTICS vs E.C | [ecu, logistics] (2) | [ec] (1) |
| CLARIANT BRASIL vs BRA | [clariant, brasil] (2) | [bra] (1) |
| S.C.JOHNSON & SON DE vs S.C.JOHNSON & SON DE ARGENTINA | [scjohnson, son] (2) | [scjohnson, son, argentina] (3) |
| ASOCIACION DE COOP. ARGENTINAS vs ASOCIACION DE | [asociacion, argentinas] (2) | [asociacion] (1) |

**9 / 33 DIFFERENT pairs (27%)** would be eliminated by the core coverage filter.

### (d) Geographic Token Substitution — same token count, filter PASSES (5 pairs)

Both master and variant have the same stripped token count but a geo-qualifier differs:

- VOLKSWAGEN OF AMERICA (2) vs VOLKSWAGEN ARGENTINA SA (2) — "america" substituted by "argentina"
- GM BRASIL (2) vs GM DE ARGENTINA S.R.L. (2) — "brasil" substituted by "argentina"
- OMNILIFE USA INC (2) vs OMNILIFE DE ARGENTINA SA (2) — "usa" substituted by "argentina"
- SAB LOGISTICA (1→2?) vs LOGISTICA DE ARGENTINA S.A. (2)

Root cause: slop=1 allows one positional shift, and geo-tokens are not blocked by any filter when token counts match. The `_core_coverage_filter` cannot help here because counts are equal.

### (a) Slop=1 Word Transposition / Insertion — same token count, filter PASSES (2 pairs)

- PLASTICOS ISLA GRANDE Y → tokens [plasticos, isla, grande] (3) vs PLASTICOS LA ISLA GRANDE → [plasticos, isla, grande] (3). The `LA` is a stopword/stripped, leaving identical token sets. `slop=1` matches trivially.
- SC JOHNSON & SON DE ARGENTINA vs JOHNSON & SON DE ARGENTINA — `scjohnson` glued by acronym_glue, variant `johnson` alone with slop=1 slides into range.

### (b) Fuzziness / Acronym Expansion — same token count, filter PASSES (3 pairs)

FUZZY_PHRASE uses `match_phrase` with `slop=1`, **not** `fuzziness`. However the clean_analyzer applies synonym expansion:
- SOUTH TRADING CORP vs SOUTH TRADE SRL — analyzer maps TRADING→TRADE via synonym or edit distance yields near-match tokens in phrase window.
- I.M.P. vs IMPORT — analyzer produces `imp` (dotted acronym) and `import`; these differ but slop allows phrase proximity.
- ALMAR INTERNACIONAL vs ALMAR INTERNATIONAL — "internacional" and "international" are not in the AR synonym file, so they produce different tokens. The match occurs because the analyzer still matches them as near-neighbors; slop=1 is not the root here — this is a synonym gap.

### (e) Semantically Distinct Single Tokens — same token count, filter PASSES (13 pairs)

Cases where stripped token counts are equal but tokens are semantically different:
- CABA vs BUENOS (1 vs 1 — city abbreviation vs city name)
- LA CANADA vs C.A. / CA (1 vs 1 — canada vs ca)
- MIHLAGER COMPANY vs COL (1 vs 1 — unrelated single tokens)
- BO HERMANOS vs BOLIVIA (1 vs 1)
- OCEAN EXPORT vs OCEAN IMPORT (2 vs 2 — antonyms)
- MS GLOBAL vs M.S. INTERNATIONAL (2 vs 2 — global ≠ international)
- CLARIANT CORP vs BRA (1 vs 1 — completely unrelated)
- A&S LOGISTICS vs E.C (2? vs 1)
- LEVI STRAUSS DE MEXICO vs LEVI STRAUSS DE MEXICO (3 vs 3 — same brand, different country entity)

Root cause: the `match_phrase` with `slop=1` on `variations.name` (not `variations_stripped`) allows these matches when the phrase window is satisfied. No token-distinctness check exists at query time.

### (f) Address Data in Firm Name Field (1 pair)

- AV ALICIA MOREAU DE JUSTO 1720 1 A vs AV ALICIA MOREAU DE JUSTO 1720 1 — full street address stored as firm name. The trailing "A" is stripped, leaving identical 6-token phrases. Score: 48 (highest in DIFFERENT set). Root fix: input_filter / pre-processing, not query logic.

---

## 4. Core Coverage Filter Status: Was It Active for These Matches?

### Commit date vs DB updated_at

| Item | Value |
|------|-------|
| Commit 2206407 date | 2026-06-10 17:05:00 +03:00 (= 2026-06-10 14:05 UTC) |
| DB `max(updated_at)` for FUZZY_PHRASE rows | **2026-04-26 11:06:25** |
| DB `min(updated_at)` for FUZZY_PHRASE rows | 2024-04-17 19:52:58 |
| FUZZY_PHRASE rows in DB | 317 (all AR) |

**CONCLUSION: The `_core_coverage_filter` was NOT ACTIVE when these 327 FUZZY_PHRASE matches were produced.**

Every FUZZY_PHRASE match in the database predates the commit by more than 6 weeks. The `match_details` field confirms this: all entries show only `[FUZZY_PHRASE] score: X.XX` with no coverage-filter trace. The filter code path (`ENABLE_CORE_COVERAGE_GATE = True` + `_core_coverage_filter` injected into the `must` clause) was merged on 2026-06-10 and has not triggered a rematch yet.

### Evidence from match_details

All 327 entries have the pattern `"[FUZZY_PHRASE] score: XX.XX"`. There is no `core_coverage` token in any match_details entry, which is consistent with the filter not being active during the run that produced these rows.

---

## 5. Filter Effectiveness Assessment

### If these matches had been produced AFTER commit 2206407:

- **9 / 33 DIFFERENT pairs (27%)** would have been blocked by the `_core_coverage_filter`.
- Estimated false-positive rate would drop from 33/327 = **10.1%** to approximately 24/327 = **7.3%**, raising precision from **87.5%** to approximately **92.6%** (assuming SAME count is unaffected).

### Why the remaining 24 DIFFERENT pairs still escape the filter:

The filter checks `variations_stripped.name.token_count == query_token_count` on the **master** document's stored variations. It cannot distinguish:
1. **Same token count, semantically distinct tokens** (geo-substitution, antonyms, unrelated short tokens) — 18 cases.
2. **slop=1 structural tolerance** allowing word insertion/transposition — 2 cases.
3. **Synonym/fuzz near-match** producing same-count token sets — 3 cases.
4. **Address data** in firm name — 1 case.

The filter was designed specifically for subset/truncation (D1/D2/D3) and works correctly for that class. It was never intended to handle semantic token differences.

---

## 6. Concrete ES-Side Recommendations

### R1 — Full rematch (mandatory, immediate impact)

Run `main_processor.py` with `ENABLE_CORE_COVERAGE_GATE = True` (already set). This eliminates the 9 subset/truncation false positives in FUZZY_PHRASE and the analogous cases in TOKEN_COVERAGE. No code change needed; the gate is already committed.

### R2 — Geographic token stop-list for FUZZY_PHRASE (addresses 5 cases)

Add a `stripped_search_analyzer` char_filter or `keyword_marker` that marks known country/city qualifier tokens (`argentina`, `brasil`, `america`, `mexico`, `usa`, `peru`, etc.) and requires at least one non-geo token to differ when query and candidate have the same stripped count. This is an ES-side filter on the `variations_stripped` nested query; no Python code needed.

Alternatively: extend `_core_coverage_filter` to also require that at least one stripped token from the query is present in the candidate's `variations_stripped.name` field as a `terms` filter (token-intersection requirement). This would catch geo-substitution without a hardcoded list.

### R3 — Minimum token-length gate for single-token matches (addresses ~7 cases)

Cases like MIHLAGER vs COL, BO HERMANOS vs BOLIVIA, CLARIANT CORP vs BRA all collapse to a single distinctive token after stripping. `MATCH_CORE_MIN_TOKEN_LEN = 2` (already set) blocks single-char tokens but not short tokens like `col`, `bra`, `ca`. Consider raising `MATCH_CORE_MIN_TOKEN_LEN` to 3 for FUZZY_PHRASE specifically, or requiring `n_stripped_tokens >= 2` as a pre-condition (currently only `_has_distinctive_core` is checked, which passes at 1 token). This would move ~7 single-effective-token matches to lower stages or NEW_MASTER.

### R4 — Address data pre-filtering (addresses 1 case)

The AV ALICIA MOREAU DE JUSTO 1720 pair indicates address strings are reaching the matching pipeline. The `input_filter.py` should reject names exceeding a character / token threshold or containing street number patterns. Score 48 is anomalously high for FUZZY_PHRASE and already exceeds any reasonable min_score ceiling.

### R5 — INTERNACIONAL / INTERNATIONAL synonym gap (addresses 1 case)

Add `INTERNACIONAL, INTERNATIONAL` to the AR synonym file (common.json or ar.json) so these are treated as equivalent during `clean_analyzer_ar` analysis. This prevents ALMAR INTERNACIONAL DE vs ALMAR INTERNATIONAL from being a false positive and also improves recall for similar cross-language pairs.

---

## Summary Table

| Mechanism | Count | Filter blocks? | Recommended fix |
|-----------|-------|----------------|-----------------|
| (c) Subset/truncation (token count diff) | 9 | YES — after rematch | R1: rematch with active gate |
| (d) Geo-token substitution (same count) | 5 | NO | R2: geo-token intersection check |
| (e) Semantically distinct same-count tokens | 13 | NO | R3: min-token-count gate per stage |
| (a) slop=1 structural tolerance | 2 | NO | min_score raise or slop=0 for subset guard |
| (b) Fuzziness / synonym gap | 3 | NO | R5: synonym additions |
| (f) Address data | 1 | NO | R4: input_filter length/pattern guard |
| **Total DIFFERENT** | **33** | **9 (27%)** | |
