# Round-6 Faz 0: veri hazırlığı — READ-ONLY
import json
import os

import psycopg2
import psycopg2.extras

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config import DB_CONFIG

OUT = os.path.dirname(os.path.abspath(__file__))
BATCH_DIR = os.path.join(OUT, "batches")
os.makedirs(BATCH_DIR, exist_ok=True)

conn = psycopg2.connect(**DB_CONFIG)
conn.set_session(readonly=True)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

diag = {}

# --- Diyagnostik 1: yetim gruplar (NEW_MASTER satırı olmayan master_code) ---
cur.execute("""
SELECT v.master_code, count(*) AS n
FROM p7_firms_v2_ar_pe v
WHERE v.master_code IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM p7_firms_v2_ar_pe m
            WHERE m.master_code = v.master_code AND m.match_type='NEW_MASTER')
GROUP BY v.master_code ORDER BY n DESC
""")
orphans = [dict(r) for r in cur.fetchall()]
diag["orphan_groups"] = {"count": len(orphans), "total_rows": sum(r["n"] for r in orphans), "sample": orphans[:30]}

# --- Diyagnostik 2: self-referans tutarsızlığı ---
cur.execute("""
SELECT ta_code, name, country_code, master_code, match_type
FROM p7_firms_v2_ar_pe
WHERE match_type='NEW_MASTER' AND (master_code IS NULL OR master_code != ta_code)
""")
selfref = [dict(r) for r in cur.fetchall()]
diag["selfref_inconsistent"] = {"count": len(selfref), "sample": selfref[:30]}

# --- Diyagnostik 3: duplike NEW_MASTER ---
cur.execute("""
SELECT master_code, count(*) AS n
FROM p7_firms_v2_ar_pe
WHERE match_type='NEW_MASTER' AND master_code IS NOT NULL
GROUP BY master_code HAVING count(*) > 1 ORDER BY n DESC
""")
dups = [dict(r) for r in cur.fetchall()]
diag["duplicate_new_master"] = {"count": len(dups), "sample": dups[:30]}

# --- Diyagnostik 4: COUNTRY_LEAK (country_count>1 gruplar) ---
cur.execute("""
SELECT master_code, count(DISTINCT country_code) AS cc,
       array_agg(DISTINCT country_code) AS countries, count(*) AS n
FROM p7_firms_v2_ar_pe
WHERE master_code IS NOT NULL
GROUP BY master_code HAVING count(DISTINCT country_code) > 1
""")
leaks = [dict(r) for r in cur.fetchall()]
diag["country_leak_groups"] = {"count": len(leaks), "sample": leaks[:30]}

# --- Diyagnostik 5: NULL match_type ama master_code dolu (ana sorgunun kör noktası) ---
cur.execute("""
SELECT count(*) AS n FROM p7_firms_v2_ar_pe
WHERE master_code IS NOT NULL AND match_type IS NULL
""")
diag["null_matchtype_with_master"] = dict(cur.fetchone())

# --- Ana grup sorgusu ---
cur.execute("""
WITH master_groups AS (
    SELECT master_code,
           count(*) FILTER (WHERE match_type != 'NEW_MASTER') AS variant_count,
           count(DISTINCT country_code) AS country_count,
           array_agg(DISTINCT country_code ORDER BY country_code) AS countries
    FROM p7_firms_v2_ar_pe
    WHERE master_code IS NOT NULL
    GROUP BY master_code
)
SELECT m.ta_code AS master_ta_code, m.name AS master_name, m.country_code AS master_country,
       v.ta_code AS variant_ta_code, v.name AS variant_name, v.country_code AS variant_country,
       v.match_type, v.match_score, v.match_details,
       g.variant_count, g.country_count, g.countries
FROM p7_firms_v2_ar_pe m
JOIN p7_firms_v2_ar_pe v ON v.master_code = m.master_code
                        AND v.ta_code != m.ta_code
                        AND v.match_type != 'NEW_MASTER'
JOIN master_groups g ON g.master_code = m.master_code
WHERE m.match_type = 'NEW_MASTER'
ORDER BY g.country_count DESC, g.variant_count DESC, m.ta_code
""")
rows = [dict(r) for r in cur.fetchall()]
print(f"main query rows: {len(rows)}")

# Grupla (master_ta_code bazında) — grup bütünlüğü için
groups = {}
for r in rows:
    groups.setdefault(r["master_ta_code"], []).append(r)
print(f"distinct master groups: {len(groups)}")

with open(os.path.join(OUT, "groups.jsonl"), "w", encoding="utf-8") as f:
    for mt, items in groups.items():
        f.write(json.dumps({
            "master_ta_code": mt,
            "master_name": items[0]["master_name"],
            "master_country": items[0]["master_country"],
            "variant_count": items[0]["variant_count"],
            "country_count": items[0]["country_count"],
            "countries": items[0]["countries"],
            "variants": [{
                "variant_ta_code": i["variant_ta_code"],
                "variant_name": i["variant_name"],
                "variant_country": i["variant_country"],
                "match_type": i["match_type"],
                "match_score": i["match_score"],
                "match_details": i["match_details"],
            } for i in items],
        }, ensure_ascii=False) + "\n")

# --- Under-merge aday sorgusu ---
cur.execute("SELECT count(*) FROM pg_extension WHERE extname='pg_trgm'")
has_trgm = cur.fetchone()["count"] > 0
diag["pg_trgm_installed"] = has_trgm

undermerge = []
if has_trgm:
    cur.execute("SET pg_trgm.similarity_threshold = 0.55")
    cur.execute("""
    SELECT a.ta_code AS ta_code_a, a.name AS name_a, a.master_code AS master_a,
           b.ta_code AS ta_code_b, b.name AS name_b, b.master_code AS master_b,
           a.country_code, similarity(a.name, b.name) AS sim
    FROM p7_firms_v2_ar_pe a
    JOIN p7_firms_v2_ar_pe b
      ON a.country_code = b.country_code
     AND a.master_code < b.master_code
     AND left(a.name, 4) = left(b.name, 4)
     AND a.name % b.name
    WHERE a.match_type = 'NEW_MASTER' AND b.match_type = 'NEW_MASTER'
      AND similarity(a.name, b.name) > 0.55
    ORDER BY sim DESC
    """)
    undermerge = [dict(r) for r in cur.fetchall()]
    for u in undermerge:
        u["sim"] = round(float(u["sim"]), 4)
print(f"undermerge candidates: {len(undermerge)}")
diag["undermerge_candidate_count"] = len(undermerge)
by_cc = {}
for u in undermerge:
    by_cc[u["country_code"]] = by_cc.get(u["country_code"], 0) + 1
diag["undermerge_by_country"] = by_cc

with open(os.path.join(OUT, "undermerge_candidates.jsonl"), "w", encoding="utf-8") as f:
    for u in undermerge:
        f.write(json.dumps(u, ensure_ascii=False) + "\n")

# --- Batch bölme: over-merge (grup bütünlüğü korunur) ---
group_list = list(groups.items())
N_OVER = 28
per = max(1, -(-len(group_list) // N_OVER))
over_total_rows = 0
nb = 0
for i in range(0, len(group_list), per):
    nb += 1
    chunk = group_list[i:i + per]
    path = os.path.join(BATCH_DIR, f"overmerge_batch_{nb:02d}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for mt, items in chunk:
            for it in items:
                f.write(json.dumps({
                    "master_ta_code": it["master_ta_code"],
                    "master_name": it["master_name"],
                    "master_country": it["master_country"],
                    "variant_ta_code": it["variant_ta_code"],
                    "variant_name": it["variant_name"],
                    "variant_country": it["variant_country"],
                    "match_type": it["match_type"],
                    "match_score": it["match_score"],
                    "match_details": it["match_details"],
                }, ensure_ascii=False) + "\n")
                over_total_rows += 1
print(f"overmerge batches: {nb}, rows written: {over_total_rows} (expected {len(rows)})")
assert over_total_rows == len(rows), "ROW COUNT MISMATCH over-merge!"

# --- Batch bölme: under-merge ---
N_UNDER = 5
per_u = max(1, -(-len(undermerge) // N_UNDER))
nu = 0
under_written = 0
for i in range(0, len(undermerge), per_u):
    nu += 1
    chunk = undermerge[i:i + per_u]
    path = os.path.join(BATCH_DIR, f"undermerge_batch_{nu:02d}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for u in chunk:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
            under_written += 1
print(f"undermerge batches: {nu}, rows written: {under_written} (expected {len(undermerge)})")
assert under_written == len(undermerge), "ROW COUNT MISMATCH under-merge!"

# match_type dağılımı
mt_dist = {}
for r in rows:
    mt_dist[r["match_type"]] = mt_dist.get(r["match_type"], 0) + 1
diag["variant_matchtype_dist"] = mt_dist
diag["main_query_rows"] = len(rows)
diag["distinct_groups"] = len(groups)

with open(os.path.join(OUT, "diagnostics.json"), "w", encoding="utf-8") as f:
    json.dump(diag, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(diag, ensure_ascii=False, indent=2, default=str)[:3000])
conn.close()
