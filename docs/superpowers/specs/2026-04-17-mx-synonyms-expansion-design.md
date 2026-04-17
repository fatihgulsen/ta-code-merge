# MX Synonyms Typo Expansion Design

## Context
The goal is to expand the Mexican synonym dictionary (`mx.json`) to capture a much broader array of typographical and spelling errors, increasing match rates in Elasticsearch. 
Since the system handles phonetic fallback (via the Double Metaphone) and N-gram fuzzy matching, the expansion should focus specifically on blind spots where algorithmic matching fails.

## Strategy

1. **Targeting Middle-Ground Abbreviations (Safe length)**
   - Algorithmic matching falls apart on short abbreviations.
   - We will expand multi-part suffixes like `sa de cv` safely without touching standalone short tokens like `sc` or `ac` to prevent False Positives.
   - Selected additions: `sa d cv`, `s a d cv`, `sade cv`, `sa de_cv`, `sa cv`.

2. **Common Long-Word Spelling Typos (Deterministic)**
   - High-value long words will receive their most common structural keyboard typos:
   - `sociedad` -> `socidad`, `socieda`, `soceidad`
   - `limitada` -> `limtada`, `limitda`
   - `anonima` -> `annima`, `anionima`
   - `responsabilidad` -> `responsavilidad`, `responsablidad`
   - `cooperativa` -> `coperativa`, `coopperativa`

3. **Address & City Enrichments**
   - Address tokens provide massive signal boosts.
   - Enhancements: `fraccionamiento` -> `fracionamiento`, `monterrey` -> `monterey`, `guadalajara` -> `gudalajara`, `guadalaraja`.

## Trade-offs and Constraints
- **Constraint:** Do not add single-letter abbreviations or heavily overload 2-letter associations (e.g. `sc -> sociedad cooperativa` is existing and safe, but we won't add `sd` or `srv` recklessly). 
- **Constraint:** All additions must account for the `punctuation_remover` character filter (so we use spaces, not periods).

## Outcomes
`mx.json` will grow in depth but remain purely structured within `legal_suffixes`, `business_sectors`, `articles`, `address_terms` and `cities`. No programmatic complexity is added; it seamlessly integrates into the current ingestion flow.
