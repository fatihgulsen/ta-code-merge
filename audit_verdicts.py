#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys

def normalize(name):
    return name.upper().strip()

def extract_core_tokens(name):
    generic = {
        'SA', 'S.A', 'S.A.', 'DE', 'C.V', 'CV', 'S', 'C', 'V', 'R.L', 'RL',
        'S.C', 'SC', 'SAPI', 'S.A.P.I', 'DEL', 'LA', 'LOS', 'Y', 'AND', 'CO',
        'INC', 'LTD', 'LLC', 'CORP', 'CORP.', 'COMPANY', 'CORPORATION',
        'MEXICO', 'MEXICALI', 'MONTERREY', 'PUEBLA', 'JALISCO', 'QUERETARO',
        'COMMUNICATIONS', 'OPERATIONS', 'SYSTEMS', 'SERVICES',
        'MANUFACTURING', 'INDUSTRIES', 'SOLUTIONS', 'INTERNATIONAL'
    }

    name = name.replace(',', '').replace('.', '').replace('(', '').replace(')', '')
    tokens = [t for t in name.split() if t not in generic and len(t) > 1]
    return tokens

def audit_match(master, variant, leak_flag):
    if leak_flag == "COUNTRY_LEAK!":
        return "WRONG", "country_leak"

    m_norm = normalize(master)
    v_norm = normalize(variant)

    if m_norm == v_norm:
        return "CORRECT", "exact_match"

    m_tokens = extract_core_tokens(m_norm)
    v_tokens = extract_core_tokens(v_norm)

    m_set = set(m_tokens)
    v_set = set(v_tokens)

    if m_set == v_set:
        return "CORRECT", "variant_ok"

    m_core = ' '.join(m_tokens[:4])
    v_core = ' '.join(v_tokens[:4])

    if m_core == v_core:
        return "CORRECT", "variant_ok"

    return "WRONG", "different_core"

files = [
    ("qa-artifacts/round9/batches/om_09.jsonl", "om_09"),
    ("qa-artifacts/round9/batches/om_10.jsonl", "om_10"),
    ("qa-artifacts/round9/batches/om_11.jsonl", "om_11"),
    ("qa-artifacts/round9/batches/om_12.jsonl", "om_12"),
]

summary = {}
total_wrong = 0

for input_path, batch_name in files:
    output_path = f"qa-artifacts/round9/verdicts/{batch_name}.verdicts.jsonl"

    correct_count = 0
    wrong_count = 0
    uncertain_count = 0
    total_count = 0

    with open(input_path, encoding='utf-8') as inf, open(output_path, 'w', encoding='utf-8') as outf:
        for line in inf:
            if not line.strip():
                continue

            row = json.loads(line)
            m_name = row['master_name']
            v_name = row['variant_name']

            verdict, reason = audit_match(m_name, v_name, row['leak_flag'])

            m_core = ' '.join(extract_core_tokens(normalize(m_name))[:3])
            v_core = ' '.join(extract_core_tokens(normalize(v_name))[:3])

            result = {
                "master_id": row['master_id'],
                "variant_id": row['variant_id'],
                "master_name": m_name,
                "variant_name": v_name,
                "stage": row['stage'],
                "verdict": verdict,
                "reason": reason,
                "distinctive_diff": f"{m_core} vs {v_core}"
            }
            outf.write(json.dumps(result) + '\n')

            total_count += 1
            if verdict == "CORRECT":
                correct_count += 1
            elif verdict == "WRONG":
                wrong_count += 1
            else:
                uncertain_count += 1

    summary[batch_name] = {
        'input': total_count,
        'output': total_count,
        'CORRECT': correct_count,
        'WRONG': wrong_count,
        'UNCERTAIN': uncertain_count
    }
    total_wrong += wrong_count

print("FILE        | INPUT | OUTPUT | CORRECT | WRONG | UNCERTAIN")
print("-" * 60)
for batch in ['om_09', 'om_10', 'om_11', 'om_12']:
    s = summary[batch]
    print(f"{batch:11} | {s['input']:5} | {s['output']:6} | {s['CORRECT']:7} | {s['WRONG']:5} | {s['UNCERTAIN']:9}")

print("-" * 60)
print(f"TOTAL WRONG MATCHES: {total_wrong}")
