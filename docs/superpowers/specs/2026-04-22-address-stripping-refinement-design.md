# Address Stripping Refinement Design (Suffix Anchoring)

## Overview
Currently, the company matching system strips address keywords (like "S", "North", "Calle") from names using a regex. This process is too aggressive, as it often mistakes parts of the core company name (e.g., "S." in "S. de R.L." or "North" in "North Face") for address components, leading to false-positive matches (Match Type: `ADDRESS_CLEAN_MATCH`).

This design implements **Suffix Anchoring**, restricting address searches to the portion of the string that follows a recognized legal suffix.

## Goals
- Eliminate false-positive address stripping for names containing directional tokens (S, N, E, W) or name-integrated address terms.
- Protect brands like "North Face" or "South Central" from being truncated.
- Ensure that valid addresses appended to names (e.g., "Acme Ltd 123 Main St") are still correctly identified and removed.

## Proposed Logic: Suffix Anchoring

### 1. Anchor Identification
The system will first identify all legal suffixes (e.g., `S.A. de C.V.`, `Ltd`, `LLC`, `GmbH`) present in the normalized name. 
- It will find the **last** occurrence of any legal suffix.
- The end index of this suffix becomes the **Anchor Point**.

### 2. Contextual Stripping
Address stripping (via regex and dictionary tokens) will only be applied to the substring **after** the Anchor Point.
- **Example:** `HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V. CUAUTEMOC 2`
  - Suffix found: `S. DE R.L. DE C.V.`
  - Search Zone: ` CUAUTEMOC 2` (Safe to strip!)
  - Core Zone: `HOG SLAT INTERNATIONAL` (Protected!)

### 3. Safe Fallback
If **no legal suffix** is identified in the name:
- The system will **not** attempt any address stripping.
- Rationale: Most structured names with appended addresses include a legal form. Names without a legal form are more likely to be trademarks/brands where directional tokens (North, South) are part of the identity.

## Components Affected

### [MODIFY] `synonym_loader.py`
- Correct the key mismatch: Ensure Mexico-specific address terms are loaded from `address_terms` if `address_abbreviations` is missing.
- Add a new function `get_all_suffix_regex(country_code)` to generate a regex that finds legal suffixes.

### [MODIFY] `es_queries.py`
- Update `_strip_address_python` to implement the Anchor logic.
- Ensure it uses the per-country suffix dictionary to find the split point.

### [MODIFY] `es_ingest.py`
- Update the Painless script in the ingest pipeline (`_build_address_clean_script`) to perform identical Suffix Anchoring logic.
- This ensures that both the ingestion time and query time cleaning remain symmetric.

## Verification Plan
1. **Unit Test:** `HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V.` must NOT be stripped of its suffix-integrated `S.` but SHOULD be stripped of trailing address tokens.
2. **Regression Test:** `North Face Intl` must be preserved as `North Face` (Intl stripped, North kept).
3. **Integration Test:** Verify that `ADDRESS_CLEAN_MATCH` is no longer triggered for the HOG SLAT example in the user's report.
