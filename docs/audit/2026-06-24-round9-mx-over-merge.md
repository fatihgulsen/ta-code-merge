# Round 9 — MX Over-Merge Audit (`p7_firms_v2_mx`)

**Date:** 2026-06-24
**Table:** `p7_firms_v2_mx` (the user-named `p7_firms_v87_mx` does not exist; this is the only
fully-populated MX results table — 530,876 rows, all `master_code` filled, current-architecture
match types. The `_yedek` table is the old legacy run.)
**Scope (per user):** PHRASE_SLOP + CANONICAL (SQL-discriminated) over-merge; EXCLUDED/DIRTY_DATA
review; under-merge pass. This document = over-merge results.

---

## Headline

- **530,876 rows, MX-only, ZERO country leaks** (physical per-country isolation holds). ✅
- **No runaway magnet:** biggest group = 25 members (Halliburton MX); top magnets are all real large
  filers (Kimberly Clark, VW, Ford, Mondelez). ✅
- **Stage distribution:** NEW_MASTER 447,931 · CANONICAL_EXACT 72,868 · PHRASE_SLOP 6,304 ·
  DIRTY_DATA 2,394 · EXCLUDED 1,379. **TOKEN_COVERAGE produced 0 matches** this run.
- **Matched variant pairs = 79,109** (CANONICAL 72,806 + PHRASE_SLOP 6,303 attached to anchors).
- **Confirmed over-merges (reliable judging): ~184 PHRASE_SLOP** + a small real subset of CANONICAL.
  System precision is **≥ 99.4%**; the value is in the defect *clusters* below.

---

## Methodology (and a process finding)

1. **Deterministic discriminator first (not LLM).** For every matched pair, strip generic tokens
   (`get_generic_tokens(MX)` = legal∪article∪geo∪sector, 475 tokens) + de-accent + handle exact
   abbrev map (INTL→INTERNACIONAL, CIA→COMPANIA), then compare the distinctive-core multiset.
   - **PHRASE_SLOP:** 6,303 → 5,566 core-identical (correct by construction) + **737 suspects**
     (417 subset / 303 partial / 17 disjoint).
   - **CANONICAL_EXACT:** 72,806 → 45,085 raw-identical + 24,252 core-same + 569 abbrev-same +
     **2,900 suspects** (2,313 subset / 575 partial / 12 disjoint).
   - This isolates the real surface (3,637) from ~75,472 deterministically-correct pairs — defensible
     coverage, not sampling.

2. **⚠️ Haiku judges were UNRELIABLE — discarded.** The first pass dispatched Haiku to judge raw
   pairs. Results were incoherent: WRONG-rate ranged **0% to 56%** across statistically-identical
   batches; one agent **fabricated** verdicts (om_15/16 never written); 0%-batches blanket-stamped
   CORRECT. Inspection proved the high-WRONG agents **massively over-flagged** — labeling
   `KONTES MEXICO`↔`KONTES DE MEXICO`, `RRA&BE`↔`RRA & BE`, `SHARP ELECTRONCA`↔`ELECTRONICA`,
   `SAINT GOBAIN`↔`SAINT-GOBAIN` as `different_core`. **All of those are correct** (exactly what
   PHRASE_SLOP exists to catch). Haiku cannot reliably apply the MX rubric (DE-connector, &-vs-space,
   accents, INTL-abbrev, typos). **Re-judged the suspect residue with Sonnet → consistent, correct.**

3. **Sonnet judged the 3,637 suspect surface** (2,337 completed before a session limit; ~1,300 subset
   pending). Verdicts in `qa-artifacts/round9/verdicts/`.

---

## Over-merge findings

### CONFIRMED — PHRASE_SLOP fuzzy-collision magnet (real bug, ~12 pairs)
Short distinctive names merged by ES `fuzziness:AUTO`:
- `INNOVAIR` ↔ `INOVAR` ↔ `INFIERA` ↔ `ANVER` ↔ `INNOVARIA` ↔ `INNOVARR` ↔ `UNIFRIO`
- `UNIVAR` ↔ `UNIVER` (Univar Solutions vs Univer — distinct firms)
- `INFRAESTRUCTURA` ↔ `ANFORA` / `INNOVAIR` / `INOVAR` / `INFOR`
- `SIT INC` ↔ `S.I.T. INDEVA` (distinctive INDEVA dropped)

**Root cause:** `fuzziness:AUTO` allows ≤2 edits on ≤5-char-ish tokens; combined with PHRASE_SLOP
word-order tolerance, short brand tokens collide. **Fix direction (ES-side):** lower fuzziness for
short core tokens (`fuzziness:"AUTO:7,10"` or `0` under ~6 chars) and/or require the distinctive
first-token to match exactly in PHRASE_SLOP.

### CONFIRMED — PHRASE_SLOP subset-phrase leak (dominant error, `extra_brand_dropped`)
A shorter name (missing a distinctive brand token) phrase-matches *within* a longer master:
- `DHL GLOBAL FORWARDING` ↔ `GLOBAL FORWARDING` (DHL dropped; shorter is generic-only)
- `AMERICAN EAGLE AIRLINES` ↔ `AMERICAN AIRLINES` (EAGLE — separate carrier)
- `APOTEX PHARMACHEM` ↔ `APOTEX` · `ROSEMOUNT ANALYTICAL` ↔ `ROSEMOUNT`
- `PARQUE INDUSTRIAL FINSA QUERETARO` ↔ `PARQUE INDUSTRIAL QUERETARO` (FINSA developer)
- `AIR SYSTEM COMPONENTS` ↔ `SYSTEM COMPONENTS` · `COMERCIAL MEXICANA DE PINTURAS` ↔ `COMERCIAL MEXICANA DE`

**Root cause:** `match_phrase` with slop matches when all *query* terms appear in order in the doc —
a shorter query is a phrase-subset of a longer doc. Violates the precision-first rule (ACME LTD ≠ ACME).
**Fix direction:** enforce bidirectional token_count parity (the TOKEN_COVERAGE multiset principle)
as a PHRASE_SLOP gate, OR require the shorter side to carry ≥1 distinctive (non-generic) core token
and that the master's extra tokens are all generic.

### NOT confirmed — CANONICAL_EXACT "WRONG" (273) are largely ARTIFACT
CANONICAL_EXACT requires an identical canonical multiset, so it matched a **stored variation** of the
master — but this audit compared the variant against the master's **anchor display-name**, which often
carries a branch/plant/office parenthetical. Most CANONICAL "WRONG" are therefore **same-firm**:
`ATC LOGISTICS (LA OFFICE)`↔`ATC LOGISTICS`, `THERM-O DISC (MANSFIELD)`↔`THERM O DISC`,
`UETA LATINOAMERICA INC - DFA`↔`UETA LATINOAMERICA INC`, `SCHNEIDER INDUSTRIAL TLAXCALA`↔`SCHNEIDER INDUSTRIAL`.
A **small genuine subset** exists (e.g. `ENLACE DE COMERCIO INTERNACIONAL`↔`COMERCIO INTERNACIONAL` —
brand ENLACE dropped). **To finish:** re-judge CANONICAL suspects against the actual matched
`variations[].name` (needs the ES index, currently absent after run rotation), not the anchor name.

---

## Coverage & numbers

| Class | Pairs | Judged (Sonnet) | WRONG | Note |
|---|---|---|---|---|
| Deterministically core-identical | ~75,472 | n/a | 0 | correct by construction |
| Suspect — disjoint+partial | 907 | 907 | 48 | PHRASE cluster + ENLACE-type |
| Suspect — subset | 2,730 | 1,430 | 409 | `extra_brand_dropped` dominant |
| **Suspect total** | **3,637** | **2,337** | **457** | 184 PHRASE / 273 CANONICAL(mostly artifact) |

Confirmed actionable over-merges ≈ **184 PHRASE_SLOP** (fuzzy-collision + subset-leak). CANONICAL real
over-merges are a small subset pending variation-level reconfirmation.

---

---

## PASS 2 — EXCLUDED + DIRTY_DATA review (recall loss) — COMPLETE

3,773 rows judged (Sonnet). **3,571 correctly excluded, 186 FALSE EXCLUSIONS, 16 uncertain.**
The false exclusions are almost all **DIRTY_DATA gate firing on real firms** (156 DIRTY + 30 EXCLUDED).
EXCLUDED placeholders (`Sin Razon Social`, `SAME AS CNEE`, `#N/A`, `NULL`) are essentially 100% correct.

**Root-cause patterns (real firms wrongly dropped):**
1. **Spaced-letter brand names** — `H S B C`, `S K F`, `I N S E R T E C`, `F U N D A M E T`,
   `T E R R A M A R M A R M O L`, `P R O D U C T O M A T`. The analyzer tokenizes each letter
   separately → fingerprint non-distinctive → DIRTY gate trips.
2. **`&`-connector names read as initials-only** — `C&A`, `J&S`, `T&N`, `A&H`, `S&T`, `C&S`, `S&P`,
   `G&W`, `F&S`, `R&S`.
3. **2-letter / acronym brand cores** — `SQUARE D`, `VWR`, `SAIC`, `BD`, `HSBC`.
4. **Address-fragment-appended real firms** — `UNIDAL MEXICO (BOULEVARD…)`, `AUTOMOTIVE LOGISTICS S.C.(AV`,
   `THE WEST COMPANY MEXICO S.A. DE C.V.,AV`.
5. Whole real-firm clusters lost: STREIT LOGISTICS (6 variants), THE WEST COMPANY (5), INTERRA
   INTERNATIONAL (5), L.S. STARRETT, PARKWAY PRODUCTS, BALTEK, etc.

**Fix direction (ES-side):** in `es/queries.is_address_dirty` / fingerprint, (a) collapse single-letter
runs (`H S B C`→`HSBC`) before the distinctive-core test; (b) treat `&`-joined initials as a brand
token, not address noise; (c) don't mark DIRTY when a real legal suffix + any alpha core ≥3 chars is
present. File: `qa-artifacts/round9/FINAL_false_exclusions.jsonl`.

## PASS 3 — UNDER-MERGE (recall loss) — sampled, COMPLETE

Deterministic candidate generation: group NEW_MASTER anchors by distinctive-core + legal class.
**38,779 clusters share core+legal across ≥2 separate masters (66,016 extra anchors); 35,861 have a
distinctive core (55,497 anchors).** Sonnet-judged the **top 360 highest-fragmentation clusters**:
**272 real under-merges (76%)**, 50 intentional (geo/sub-brand), 38 uncertain.

**Root-cause patterns (same firm split into many masters):**
- `truncation_split` (192) — same name, one truncated (`BAKER HUGHES DE MEXICO` ×N, `GENERAL MOTORS DE MEXICO`).
- `abbrev_split` (≈33) — **ES/EN not unified: `INTERNACIONAL` vs `INTERNATIONAL`**, `INTL`/`INT`/`INT'S`
  (SINBIOTIK, PALME, PERSONNA, GENOMMA LAB, ALEXAR, CHARLOTTE, SANTINO, GARGON, AIRMAR, SPARBER…).
- `amp_spacing_split` (≈18) — **`&` vs `AND` vs space vs `+`** (`H&M`↔`H M`, `ROHM & HAAS`↔`ROHM AND HAAS`,
  `MANN+HUMMEL`, `LEGGETT & PLATT`, `GMBH & CO`↔`GMBH AND CO`).
- `accent_split` (≈8) — `COMPAÑIA`↔`COMPANIA`, `VEHÍCULOS`↔`VEHICULOS`, Ñ encoding corruption.
- `typo_split` (≈6) — `FRAGRANCES`↔`FRAGANCES`.

**Fix direction (ES-side, high leverage):**
1. Add `internacional ⇄ international` (+ `intl/int`) to the synonym canonical map → unifies dozens of clusters.
2. Normalize `& / AND / + / Y` to one canonical connector in `clean_analyzer_{cc}` (char_filter or synonym).
3. Ensure consistent ASCII/ICU folding (Ñ→N, accents) across clean+canonical+fingerprint chains.
These are recall-only fixes (precision-neutral: they unify spellings of the *same* core).
File: `qa-artifacts/round9/undermerge_candidates.jsonl`, `verdicts/um_*`.

## Bonus finding — sector words missing from MX synonym generic set
The under-merge clustering exposed `cargo`, `supply`, `forwarding`, `logistic`, `business`, `products`
behaving as *distinctive* cores (not in `get_generic_tokens(MX)`). They should be sector synonyms;
their absence also weakens the over-merge gates. See [[synonym-category-name-inconsistency]] /
[[authoring-synonyms]].

---

## Outstanding
1. ~1,300 subset over-merge suspects: now COMPLETE (all sub_* judged).
2. CANONICAL over-merge suspects should be re-judged against the actual matched `variations[].name`
   (ES index `living_companies_mx_v3` is live again) to strip the anchor-name/branch-tag artifact from
   the 493 CANONICAL "WRONG".
3. Under-merge: only top-360 clusters judged; full 35,861 not exhaustively judged (sampling is
   acceptable for under-merge per skill).

## Artifacts
`qa-artifacts/round9/` — `phrase_slop.jsonl`, `canonical_suspect.jsonl`, `ps_core_suspect.jsonl`,
`canon_core_suspect.jsonl`, `excluded.jsonl`, `dirty.jsonl`; `batches/` (om_*/res_*/sub_*/ex_*);
`verdicts/` (res_*, sub_*, subset_sample = reliable; om_* = Haiku, DISCARDED); `WRONG_confirmed.jsonl`.
