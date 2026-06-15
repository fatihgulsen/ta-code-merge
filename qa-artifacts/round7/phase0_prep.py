# Round-7 Faz 0: GUNCEL veri hazirligi — READ-ONLY (R6 ile karsilastirma)
import json
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config import DB_CONFIG

OUT = os.path.dirname(os.path.abspath(__file__))
BATCH_DIR = os.path.join(OUT, "batches")
os.makedirs(BATCH_DIR, exist_ok=True)
os.makedirs(os.path.join(OUT, "verdicts"), exist_ok=True)

conn = psycopg2.connect(**DB_CONFIG)
conn.set_session(readonly=True)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

diag = {}

# progress / completeness
cur.execute("SELECT country_code, count(*) FILTER (WHERE match_type IS NULL) AS null_n, count(*) AS total FROM p7_firms_v2_ar_pe GROUP BY 1")
diag["completeness"] = {r["country_code"]: {"unprocessed": r["null_n"], "total": r["total"],
                                             "pct_done": round(100 * (r["total"] - r["null_n"]) / r["total"], 1)}
                        for r in cur.fetchall()}

# duplicate NEW_MASTER
cur.execute("""SELECT count(*) AS n FROM (SELECT master_code FROM p7_firms_v2_ar_pe
  WHERE match_type='NEW_MASTER' AND master_code IS NOT NULL GROUP BY master_code HAVING count(*)>1) t""")
diag["duplicate_new_master_groups"] = cur.fetchone()["n"]

# country leak
cur.execute("""SELECT count(*) AS n FROM (SELECT master_code FROM p7_firms_v2_ar_pe
  WHERE master_code IS NOT NULL GROUP BY master_code HAVING count(DISTINCT country_code)>1) t""")
diag["country_leak_groups"] = cur.fetchone()["n"]

# main group query (AR has all variants; PE has none — but query is country-agnostic)
cur.execute("""
WITH master_groups AS (
    SELECT master_code,
           count(*) FILTER (WHERE match_type != 'NEW_MASTER') AS variant_count,
           count(DISTINCT country_code) AS country_count,
           array_agg(DISTINCT country_code ORDER BY country_code) AS countries
    FROM p7_firms_v2_ar_pe WHERE master_code IS NOT NULL GROUP BY master_code)
SELECT m.ta_code AS master_ta_code, m.name AS master_name, m.country_code AS master_country,
       v.ta_code AS variant_ta_code, v.name AS variant_name, v.country_code AS variant_country,
       v.match_type, v.match_score, v.match_details, g.variant_count, g.country_count
FROM p7_firms_v2_ar_pe m
JOIN p7_firms_v2_ar_pe v ON v.master_code = m.master_code AND v.ta_code != m.ta_code AND v.match_type != 'NEW_MASTER'
JOIN master_groups g ON g.master_code = m.master_code
WHERE m.match_type = 'NEW_MASTER'
ORDER BY g.country_count DESC, g.variant_count DESC, m.ta_code
""")
rows = [dict(r) for r in cur.fetchall()]
groups = {}
for r in rows:
    groups.setdefault(r["master_ta_code"], []).append(r)
diag["main_query_rows"] = len(rows)
diag["distinct_groups"] = len(groups)
from collections import Counter
mt_dist = Counter(r["match_type"] for r in rows)
diag["variant_matchtype_dist"] = dict(mt_dist)

with open(os.path.join(OUT, "groups.jsonl"), "w", encoding="utf-8") as f:
    for mt, items in groups.items():
        f.write(json.dumps({"master_ta_code": mt, "master_name": items[0]["master_name"],
                            "master_country": items[0]["master_country"],
                            "variants": [{"variant_ta_code": i["variant_ta_code"], "variant_name": i["variant_name"],
                                          "variant_country": i["variant_country"], "match_type": i["match_type"],
                                          "match_score": i["match_score"]} for i in items]}, ensure_ascii=False) + "\n")

# batch split — grup butunlugu korunur, hedef ~100 satir/batch
group_list = list(groups.items())
N = 40
per = max(1, -(-len(group_list) // N))
nb = 0
written = 0
for i in range(0, len(group_list), per):
    nb += 1
    chunk = group_list[i:i + per]
    with open(os.path.join(BATCH_DIR, f"overmerge_batch_{nb:02d}.jsonl"), "w", encoding="utf-8") as f:
        for mt, items in chunk:
            for it in items:
                f.write(json.dumps({"master_ta_code": it["master_ta_code"], "master_name": it["master_name"],
                                    "master_country": it["master_country"], "variant_ta_code": it["variant_ta_code"],
                                    "variant_name": it["variant_name"], "variant_country": it["variant_country"],
                                    "match_type": it["match_type"], "match_score": it["match_score"],
                                    "match_details": it["match_details"]}, ensure_ascii=False) + "\n")
                written += 1
diag["overmerge_batches"] = nb
diag["rows_written"] = written
assert written == len(rows), f"MISMATCH {written} != {len(rows)}"

# PE under-merge sizing (no scan — just count, since PE has 0 matches)
cur.execute("SET pg_trgm.similarity_threshold = 0.9")
cur.execute("""SELECT count(*) AS n FROM p7_firms_v2_ar_pe a JOIN p7_firms_v2_ar_pe b
  ON a.country_code=b.country_code AND a.master_code < b.master_code AND left(a.name,4)=left(b.name,4) AND a.name % b.name
  WHERE a.match_type='NEW_MASTER' AND b.match_type='NEW_MASTER' AND a.country_code='PE' AND similarity(a.name,b.name)>0.9""")
diag["pe_undermerge_high_sim_pairs"] = cur.fetchone()["n"]

with open(os.path.join(OUT, "diagnostics.json"), "w", encoding="utf-8") as f:
    json.dump(diag, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(diag, ensure_ascii=False, indent=2, default=str))
conn.close()
