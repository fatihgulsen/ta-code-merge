# Synonym-Based Normalization Design

## Objective
Migrate company name character normalization and suffix typo fixes from Python/Painless regexes to Elasticsearch native `char_filter` and pure synonym maps. Persist parenthesis contents to prevent false data loss. Update the Mexico (`mx.json`) synonym file format to the new `legal_suffixes` and `business_sectors` standard.

## 1. Elasticsearch Analyzer Change (es_manager.py)
**Component**: Custom Analyzers (`base_clean_filters` or a custom `char_filter` section)
- Add a custom `char_filter` of type `pattern_replace`, named `punctuation_remover`.
- **Pattern**: `[.,]+`
- **Replacement**: `" "` (space instead of empty string)
- **Effect**: Punctuation will be stripped and replaced with spaces *before* tokenization (e.g. `S.A. de C.V.` -> `S A de C V` / `L.T.D.` -> `L T D` / `Fatih.Gülşen` -> `Fatih Gülşen`). This prevents dangerous word collisions (like `FatihGülşen`) while maintaining a predictable format. The synonym maps will simply map the space-separated letters to their clean forms (e.g., `l t d => ltd`).
- Include the `punctuation_remover` in all underlying default analysis filters.

## 2. Ingest Pipeline Refactor (es_ingest.py)
**Component**: `company_name_clean` Painless Script Pipeline
- **Removed**:
  - Parenthesis/Bracket removal regexes (`/\([^)]*\)/` and `/\[[^\]]*\]/`). Parentheses and brackets will now safely retain their strings.
  - Regex-based suffix formatting (`L.T.D.` -> `LTD` using matcher loops).
  - Single-letter agglomeration logic (`l t d` -> `ltd`).
  - Fused-suffix separation loops (`fusedMap`, such as `pvtltd` -> `pvt ltd`).
- **Retained**:
  - Lowercasing (`.toLowerCase()`).
  - Zero-width character stripping.
  - Label stripping (e.g. `c/o`, `attn:`).

## 3. MX Synonym Format & Content (synonyms_data/mx.json)
**Component**: Mexican Directory Synonym Map
- Move away from the legacy `company_types` overarching array.
- Structure accurately aligned with `_template.json` (`legal_suffixes`, `business_sectors`, `articles`, `address_terms`).
- Utilize pure alphabet mapping leveraging the new `char_filter` efficiency.
- Logically map typographical variables in `legal_suffixes`: 
  - `sociedad anonima, sa, s a => sa`
  - `s a de c v, sa de cv, sadecv, s a de cv => sa de cv`
  - `sociedad anonima promotora de inversion de capital variable, sapi de cv => sapi de cv`
- This ensures maintenance relies purely on semantic concepts, not infinite regex grammatical patches.
