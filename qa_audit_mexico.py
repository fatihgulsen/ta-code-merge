#!/usr/bin/env python3
"""
QA Audit Script for Mexican Company Matches
Applies rubric to judge if master_name and variant_name represent the SAME FIRM
Outputs JSONL verdicts file per batch
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

# Mexican legal suffixes and articles (both with and without dots)
LEGAL_SUFFIXES = {
    'SA', 'SA DE CV', 'SC', 'LLC', 'SRL', 'DE CV', 'SPR', 'SAC', 'SAPI', 'SAB',
    'S.A.', 'S.A. DE C.V.', 'S.C.', 'L.L.C.', 'S.R.L.', 'S.P.R.', 'S.A.C.',
    'S.A.P.I.', 'S.A.B.', 'DE C.V.', 'A.C.',
    'C.V.', 'CV', 'C.V', 'S.A', 'S.A. DE', 'S.A DE', 'SAC'
}

ARTICLES = {'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y', 'E', 'AND'}

# Common geo/sector words that don't distinguish firms
GEO_SECTOR_WORDS = {
    'MEXICO', 'MEXICANA', 'MEXICANO', 'COMERCIAL', 'DISTRIBUIDORA', 'DISTRIBUIDOR',
    'IMPORTADORA', 'IMPORTADOR', 'EXPORTADORA', 'EXPORTADOR', 'FABRICANTE', 'FABRICA',
    'INDUSTRIA', 'INDUSTRIAL', 'EMPRESA', 'SOCIEDAD', 'COMPANIA', 'HOLDINGS',
    'GROUP', 'GRUPO', 'SERVICIOS', 'SERVICE', 'CONSULTORIA', 'CONSULTORES',
    'ASESOR', 'ASESORIA', 'TRADING', 'PRODUCTOS', 'PRODUCTO', 'MANUFACTURER',
    'SUPPLY', 'SUPPLIES', 'LOGISTICS', 'LOGISTICA', 'NACIONAL', 'INTERNACIONAL'
}

GENERIC_WORDS = GEO_SECTOR_WORDS | {'SOCIEDAD', 'EMPRESA', 'COMERCIAL', 'INDUSTRIAL'}


def normalize_name(name: str) -> str:
    """Normalize company name: uppercase, remove extra spaces."""
    return ' '.join(name.upper().split())


def tokenize_name(name: str) -> List[str]:
    """Split name into tokens."""
    return name.split()


def is_generic_token(token: str) -> bool:
    """Check if token is generic (legal suffix, article, common sector word)."""
    token_clean = token.rstrip('.,;')
    return token_clean in (LEGAL_SUFFIXES | ARTICLES | GENERIC_WORDS)


def extract_distinctive_core(name: str) -> str:
    """
    Extract distinctive core by stripping legal suffixes, articles, geo/sector words.
    Returns the remaining meaningful tokens.
    """
    normalized = normalize_name(name)
    tokens = tokenize_name(normalized)

    # Filter out generic tokens
    # Need to check combinations like "S.A. DE C.V." or "DE C.V."
    distinctive_tokens = []
    i = 0
    while i < len(tokens):
        t = tokens[i]

        # Remove trailing punctuation for generic check
        t_check = t.rstrip('.,;:')

        # Check for multi-token suffixes like "S.A. DE C.V."
        is_suffix = False
        if i + 2 < len(tokens):
            three_token = ' '.join([t_check, tokens[i+1].rstrip('.,;:'), tokens[i+2].rstrip('.,;:')])
            if three_token in LEGAL_SUFFIXES:
                is_suffix = True
                i += 3
                continue

        # Check for two-token suffixes like "DE C.V." or "S.A. DE"
        if not is_suffix and i + 1 < len(tokens):
            two_token = ' '.join([t_check, tokens[i+1].rstrip('.,;:')])
            if two_token in LEGAL_SUFFIXES:
                is_suffix = True
                i += 2
                continue

        # Check single token
        if not is_suffix and t_check and not is_generic_token(t_check):
            distinctive_tokens.append(t)

        i += 1

    return ' '.join(distinctive_tokens) if distinctive_tokens else ''


def normalize_for_comparison(s: str) -> str:
    """
    Normalize string for comparison by:
    1. Replacing "AND" or "Y" with "&"
    2. Removing punctuation, spaces, special chars
    Allows proper matching of "M AND A" vs "M&A"
    """
    # Replace AND/Y with & for comparison
    s_normalized = re.sub(r'\bAND\b|\bY\b', '&', s, flags=re.IGNORECASE)
    # Remove punctuation, spaces, and other special chars (but keep letters and numbers)
    s_normalized = re.sub(r'[\s&\-+\.,;:/]', '', s_normalized).lower()
    return s_normalized


def is_spelling_variant(s1: str, s2: str) -> bool:
    """
    Check if s1 and s2 are spelling/punctuation/spacing variants.
    Allows: J & K vs J&K, TECHNIMARK-REYNOSA vs TECHNIMARK REYNOSA, AND vs &, etc.
    """
    return normalize_for_comparison(s1) == normalize_for_comparison(s2)


def is_abbreviation_variant(long_form: str, short_form: str) -> bool:
    """
    Check if short_form is an abbreviation of long_form.
    Examples: S.A. DE C.V. vs S.A., ELECTRONICA ELTEC vs ELTEC
    """
    # Simple heuristic: if one is prefix of the other, likely abbreviation
    long_tokens = long_form.split()
    short_tokens = short_form.split()

    if len(short_tokens) >= len(long_tokens):
        return False

    # Check if short tokens form a subsequence of long tokens
    long_str = ' '.join(long_tokens)
    short_str = ' '.join(short_tokens)

    return short_str in long_str or any(
        lt.startswith(st) for st, lt in zip(short_tokens, long_tokens)
    )


def audit_match(master_name: str, variant_name: str, leak_flag: str) -> Tuple[str, str, str]:
    """
    Apply rubric to judge if master_name and variant_name represent SAME FIRM.

    Returns: (verdict, reason, distinctive_diff)
    verdict: CORRECT, WRONG, or UNCERTAIN
    reason: category explaining the verdict
    distinctive_diff: shows core comparison
    """

    # Check for country leak first
    if leak_flag == "COUNTRY_LEAK!":
        return "WRONG", "country_leak", ""

    master_norm = normalize_name(master_name)
    variant_norm = normalize_name(variant_name)

    # Exact match (unlikely at this stage but check anyway)
    if master_norm == variant_norm:
        return "CORRECT", "exact_match", ""

    # Extract distinctive cores
    master_core = extract_distinctive_core(master_norm)
    variant_core = extract_distinctive_core(variant_norm)

    distinctive_diff = f"{master_core} vs {variant_core}"

    # Split into tokens early for later use
    master_tokens = master_core.split()
    variant_tokens = variant_core.split()

    # If cores are empty (all generic), this is WRONG
    if not master_core or not variant_core:
        return "WRONG", "subset_truncation", distinctive_diff

    # Check if cores are identical
    if master_core == variant_core:
        return "CORRECT", "variant_ok", distinctive_diff

    # Check if one is a spelling variant of the other (punctuation/spacing/hyphen/AND vs &)
    if is_spelling_variant(master_core, variant_core):
        return "CORRECT", "spelling_variant", distinctive_diff

    # Check if one is abbreviation of the other
    if is_abbreviation_variant(master_core, variant_core):
        return "CORRECT", "abbreviation_ok", distinctive_diff

    if is_abbreviation_variant(variant_core, master_core):
        return "CORRECT", "abbreviation_ok", distinctive_diff

    # Check for clear typo (single character difference in one token)
    if len(master_tokens) == len(variant_tokens):
        typo_matches = 0
        for mt, vt in zip(master_tokens, variant_tokens):
            if mt == vt:
                typo_matches += 1
            elif len(mt) > 2 and len(vt) > 2:
                # Simple typo check: <= 1 char difference
                if abs(len(mt) - len(vt)) <= 1:
                    # Count character differences
                    diff_count = sum(1 for a, b in zip(mt, vt) if a != b)
                    if diff_count <= 1:
                        typo_matches += 1

        if typo_matches == len(master_tokens) and typo_matches >= len(master_tokens) - 1:
            return "CORRECT", "typo_ok", distinctive_diff

    # Check for subset cases (one is subset of the other in core)
    master_set = set(master_tokens)
    variant_set = set(variant_tokens)

    # If one is a pure subset of the other, likely CORRECT (e.g., ACME MEXICO vs ACME)
    if variant_set.issubset(master_set) or master_set.issubset(variant_set):
        return "CORRECT", "subset_ok", distinctive_diff

    # Check shared tokens
    shared_tokens = master_set & variant_set

    # If there's no overlap in distinctive tokens → WRONG
    if not shared_tokens:
        return "WRONG", "different_core", distinctive_diff

    # If cores are completely different and no word similarity → WRONG
    if not any(mt.startswith(vt) or vt.startswith(mt)
               for mt in master_tokens for vt in variant_tokens):
        return "WRONG", "different_core", distinctive_diff

    # Default to UNCERTAIN if no rule matches
    return "UNCERTAIN", "unclear", distinctive_diff


def process_batch(input_file: Path, output_file: Path) -> Dict[str, int]:
    """
    Process one JSONL batch file.
    Returns stats: {correct, wrong, uncertain, total}
    """
    stats = {'correct': 0, 'wrong': 0, 'uncertain': 0, 'total': 0}
    verdicts = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue

            stats['total'] += 1
            row = json.loads(line)

            master_id = row.get('master_id', '')
            variant_id = row.get('variant_id', '')
            master_name = row.get('master_name', '')
            variant_name = row.get('variant_name', '')
            stage = row.get('stage', 'UNKNOWN')
            leak_flag = row.get('leak_flag', 'OK')

            verdict, reason, distinctive_diff = audit_match(master_name, variant_name, leak_flag)

            # Track stats
            if verdict == "CORRECT":
                stats['correct'] += 1
            elif verdict == "WRONG":
                stats['wrong'] += 1
            else:
                stats['uncertain'] += 1

            # Build verdict object
            verdict_obj = {
                "master_id": master_id,
                "variant_id": variant_id,
                "master_name": master_name,
                "variant_name": variant_name,
                "stage": stage,
                "verdict": verdict,
                "reason": reason,
                "distinctive_diff": distinctive_diff
            }

            verdicts.append(verdict_obj)

    # Write verdicts to output file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        for verdict in verdicts:
            f.write(json.dumps(verdict) + '\n')

    return stats


def main():
    base_path = Path("C:/All-project/ta-code-merge/qa-artifacts/round9")

    batches = ['om_17', 'om_18', 'om_19', 'om_20']
    all_stats = {}
    total_wrong = 0

    for batch in batches:
        input_file = base_path / "batches" / f"{batch}.jsonl"
        output_file = base_path / "verdicts" / f"{batch}.verdicts.jsonl"

        print(f"\nProcessing {batch}...")
        stats = process_batch(input_file, output_file)
        all_stats[batch] = stats

        print(f"  Input lines: {stats['total']}")
        print(f"  Output lines: {stats['total']}")
        print(f"  CORRECT: {stats['correct']}")
        print(f"  WRONG: {stats['wrong']}")
        print(f"  UNCERTAIN: {stats['uncertain']}")

        total_wrong += stats['wrong']

    print("\n" + "="*60)
    print("SUMMARY ACROSS ALL 4 FILES")
    print("="*60)
    for batch, stats in all_stats.items():
        print(f"{batch}: {stats['correct']} CORRECT, {stats['wrong']} WRONG, {stats['uncertain']} UNCERTAIN")

    print(f"\nTOTAL WRONG ACROSS ALL FILES: {total_wrong}")
    print(f"Verdicts written to: C:/All-project/ta-code-merge/qa-artifacts/round9/verdicts/om_*.verdicts.jsonl")


if __name__ == '__main__':
    main()
