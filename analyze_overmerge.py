#!/usr/bin/env python3
import json
import re
from typing import List, Set

def tokenize_name(name: str) -> List[str]:
    """Tokenize a firm name by removing punctuation and splitting on whitespace."""
    name = re.sub(r'[.,;:/()&\-]', ' ', name)
    tokens = name.split()
    return [t.upper() for t in tokens if t]

def is_generic_word(token: str) -> bool:
    """Check if a token is a generic business word (not distinctive)."""
    generic_words = {
        'IMPORTADORA', 'COMERCIAL', 'DISTRIBUIDORA', 'SERVICIOS', 'COMPANIA',
        'TRADING', 'GENERAL', 'GLOBAL', 'GRUPO', 'INVERSIONES', 'CORPORACION',
        'EMPRESA', 'LTDA', 'LLC', 'LTD', 'INC', 'LLP', 'PARTNERS', 'COMPANY',
        'GROUP', 'SUPPLY', 'CHAIN', 'MANAGEMENT', 'SOLUTIONS', 'SYSTEMS',
        'TECHNOLOGY', 'CONSULTING', 'ENGINEERING', 'CONSTRUCTION',
        'MANUFACTURING', 'PRODUCTS', 'INDUSTRIES', 'INTERNATIONAL', 'NACIONAL',
        'ARGENTINA', 'AUSTRAL', 'AMERICAN', 'EUROPE', 'EUROPEAN', 'LATINO',
        'LOGISTICA', 'LOGISTIC', 'INDUSTRIAL', 'RETAIL',
        'EXTERIOR', 'DEVELOPMENT', 'MATERIAL', 'CARGO',
        'TRANSPORT', 'FREIGHT', 'SHIPPING', 'BUSINESS',
        'FINANCIAL', 'CREDIT', 'BANK', 'INSURANCE',
        'SUC', 'SUCURSAL'
    }
    return token in generic_words

def is_legal_suffix(token: str) -> bool:
    """Check if a token is a legal entity suffix."""
    legal_suffixes = {
        'S.A', 'SA', 'SRL', 'S.R.L', 'EIRL', 'SAC', 'S.A.C', 'S.A.S', 'S.C.A',
        'S.H', 'A.U', 'S.A.U', 'U.T.E', 'HNOS', 'HERMANOS', 'SARL', 'E.I.R.L',
        'C.V', 'SOCIEDAD', 'ANONIMA', 'RESPONSABILIDAD', 'LIMITADA',
        'INCORPORATION', 'CORP', 'CORPORATION', 'Y', 'E', 'LA', 'EL', 'DE',
        'THE', 'AND', 'OR', 'BY', 'FOR', 'AT', 'IN', 'ON', 'TO', 'WITH'
    }
    return token in legal_suffixes or len(token) == 1

def extract_core_tokens(tokens: List[str]) -> List[str]:
    """Extract core distinctive tokens by removing generic/legal suffix words."""
    core = [t for t in tokens if not is_generic_word(t) and not is_legal_suffix(t)]
    return core

def levenshtein_ratio(s1: str, s2: str) -> float:
    """Simple character-level similarity (0.0 to 1.0)."""
    if len(s1) == 0 and len(s2) == 0:
        return 1.0
    if len(s1) == 0 or len(s2) == 0:
        return 0.0

    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_len = dp[m][n]
    return 2.0 * lcs_len / (m + n)

def analyze_names(master_name: str, variant_name: str) -> dict:
    """Analyze if master and variant are the same firm."""

    master_tokens = tokenize_name(master_name)
    variant_tokens = tokenize_name(variant_name)

    shared = sorted(list(set(master_tokens) & set(variant_tokens)))
    master_core = extract_core_tokens(master_tokens)
    variant_core = extract_core_tokens(variant_tokens)
    shared_core = list(set(master_core) & set(variant_core))

    verdict = 'UNCERTAIN'
    reason = 'unclear'

    # Rule 1: Completely identical
    if master_tokens == variant_tokens:
        return {
            'verdict': 'CORRECT', 'reason': 'identical',
            'shared_tokens': shared, 'distinctive_diff': '',
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 2: Identical core (only differ by legal suffix/location)
    if master_core == variant_core:
        return {
            'verdict': 'CORRECT', 'reason': 'suffix_only',
            'shared_tokens': shared, 'distinctive_diff': '',
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 3: One core is subset of other with small difference
    if len(master_core) > 0 and len(variant_core) > 0:
        if set(master_core).issubset(set(variant_core)) or set(variant_core).issubset(set(master_core)):
            diff_count = abs(len(master_core) - len(variant_core))
            if diff_count == 1:
                diff_tokens = set(master_core) ^ set(variant_core)
                diff_token = list(diff_tokens)[0] if diff_tokens else None
                if diff_token and (len(diff_token) <= 1 or is_generic_word(diff_token)):
                    return {
                        'verdict': 'CORRECT', 'reason': 'subset_ok',
                        'shared_tokens': shared,
                        'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
                        'master_core': master_core, 'variant_core': variant_core
                    }
                else:
                    # Different distinctive core token
                    return {
                        'verdict': 'WRONG', 'reason': 'different_core',
                        'shared_tokens': shared,
                        'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
                        'master_core': master_core, 'variant_core': variant_core
                    }

    # Rule 4: Check for clear typo (same length, high similarity)
    if len(shared_core) > 0 and len(master_core) == len(variant_core) and len(master_core) >= 2:
        master_core_str = ''.join(master_core)
        variant_core_str = ''.join(variant_core)
        sim = levenshtein_ratio(master_core_str, variant_core_str)
        if sim >= 0.9:
            return {
                'verdict': 'CORRECT', 'reason': 'typo_ok',
                'shared_tokens': shared,
                'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
                'master_core': master_core, 'variant_core': variant_core
            }

    # Rule 5: If cores have different sizes, return WRONG
    if len(master_core) != len(variant_core):
        return {
            'verdict': 'WRONG', 'reason': 'different_core',
            'shared_tokens': shared,
            'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 6: No shared core tokens at all
    if len(shared_core) == 0:
        return {
            'verdict': 'WRONG', 'reason': 'different_core',
            'shared_tokens': shared,
            'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 7: Only shared by generic/legal words
    if len(shared) > 0 and len(shared_core) == 0:
        return {
            'verdict': 'WRONG', 'reason': 'generic_word_only',
            'shared_tokens': shared,
            'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 8: 2+ shared core tokens = likely CORRECT variant
    if len(shared_core) >= 2:
        return {
            'verdict': 'CORRECT', 'reason': 'variant_ok',
            'shared_tokens': shared,
            'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
            'master_core': master_core, 'variant_core': variant_core
        }

    # Rule 9: 1 shared core with same length and same size - could be renamed variant
    # But if the non-shared tokens are very different (EXPORT vs IMPORT), it's WRONG
    if len(shared_core) == 1 and len(master_core) == len(variant_core) == 2:
        # Both have exactly 2 core tokens, 1 shared, 1 different
        # This is a rename case - potentially different companies
        return {
            'verdict': 'WRONG', 'reason': 'different_core',
            'shared_tokens': shared,
            'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
            'master_core': master_core, 'variant_core': variant_core
        }

    return {
        'verdict': 'UNCERTAIN', 'reason': 'unclear',
        'shared_tokens': shared,
        'distinctive_diff': f"{' '.join(master_core)} vs {' '.join(variant_core)}",
        'master_core': master_core, 'variant_core': variant_core
    }

# Main processing
input_file = r'C:\All-project\ta-code-merge\qa-artifacts\round8\batches\overmerge_batch_36.jsonl'
output_file = r'C:\All-project\ta-code-merge\qa-artifacts\round8\verdicts\overmerge_batch_36.verdicts.jsonl'

verdicts_list = []
input_count = 0
correct_count = 0
wrong_count = 0
uncertain_count = 0

with open(input_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue

        data = json.loads(line)
        input_count += 1

        master_country = data['master_country']
        variant_country = data['variant_country']
        leak_flag = data['leak_flag']

        if leak_flag == 'COUNTRY_LEAK!' or master_country != variant_country:
            verdict = 'WRONG'
            reason = 'country_leak'
            shared_tokens = []
            distinctive_diff = ''
        else:
            analysis = analyze_names(data['master_name'], data['variant_name'])
            verdict = analysis['verdict']
            reason = analysis['reason']
            shared_tokens = analysis['shared_tokens']
            distinctive_diff = analysis['distinctive_diff']

        if verdict == 'CORRECT':
            correct_count += 1
        elif verdict == 'WRONG':
            wrong_count += 1
        else:
            uncertain_count += 1

        output_obj = {
            'master_ta_code': data['master_ta_code'],
            'variant_ta_code': data['variant_ta_code'],
            'master_name': data['master_name'],
            'variant_name': data['variant_name'],
            'verdict': verdict,
            'reason': reason,
            'shared_tokens': shared_tokens,
            'distinctive_diff': distinctive_diff
        }
        verdicts_list.append(output_obj)

output_count = 0
with open(output_file, 'w', encoding='utf-8') as f:
    for obj in verdicts_list:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        output_count += 1

print(f"Input count: {input_count}")
print(f"Output count: {output_count}")
print(f"CORRECT: {correct_count}")
print(f"WRONG: {wrong_count}")
print(f"UNCERTAIN: {uncertain_count}")
print(f"Output file: {output_file}")
