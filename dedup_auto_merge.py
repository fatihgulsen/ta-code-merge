# ============================================================================
# dedup_auto_merge.py — ES-side otomatik duplicate-master birleştirme (Option-2)
# ============================================================================
# Aynı KANONİK fingerprint'e (es_manager fingerprint_analyzer: jenerik + yasal-ek
# + geo stripped, sort+dedup) ve aynı country_code'a sahip master'ları tespit edip
# OTOMATİK birleştirir:
#   1. PG: p7_firms_v2.master_code → primary master'a yeniden yönlendir
#   2. ES: secondary'lerin variations'ını primary'e taşı, secondary doc'ları sil
#
# Kimlik kararı %100 ES analyzer'ındadır (fingerprint). Python'da fuzzy/Levenshtein
# veya normalize-ile-sınıflandırma YOKTUR — yalnızca ES'in ürettiği fingerprint
# eşitliği üzerinden gruplama + orkestrasyon. country_code HARD FILTER (grup anahtarı).
#
# Boş fingerprint (yalnız yasal-ek/geo/çöp) → BİRLEŞTİRİLMEZ (garbage magnet önlenir).
# Bkz. docs/audit/2026-06-03-llm-judge-rematch-comparison.md §3.3 / P0-C Option-2.
# ============================================================================

import logging

import psycopg2
import psycopg2.sql
from elasticsearch import Elasticsearch

from config import DB_CONFIG, ES_INDEX, RAW_TABLE_NAME, COLUMN_MAPPING, DEDUP_MIN_FINGERPRINT_TOKEN_LEN, MatchType

logger = logging.getLogger(__name__)

_FINGERPRINT_FIELD = "variations.name.fingerprint"


# ─────────────────────────────────────────────────────────────────────
# SAF PLANLAMA MANTIĞI (ES'siz test edilebilir)
# ─────────────────────────────────────────────────────────────────────

def choose_primary(master_ids: list[str]) -> str:
    """Birleştirmede korunacak master'ı deterministik seçer (sıralı ilk)."""
    return sorted(master_ids)[0]


def _is_distinctive_fingerprint(fp: str, min_token_len: int | None = None) -> bool:
    """Fingerprint dedup ANAHTARI olacak kadar ayırt edici mi?

    En az bir token >= `min_token_len` (config.DEDUP_MIN_FINGERPRINT_TOKEN_LEN) karakter
    olmalı. Aksi halde dejenere kabul edilir: fingerprint_analyzer noktalı-akronim isimleri
    (C.M.S.A.D.C / U M S.A. DE C.V. / A.P.M. S.A.) tek junk harfe ('m') çökertebiliyor →
    alakasız firmalar aynı anahtarda toplanıp magnet oluşuyor (P-R2-1).

    Eşik config'ten ayarlanır: 1 = guard pratikte kapalı (yalnız boş fp engellenir);
    2 = akronim magnet'lerini engeller, gerçek 2-harfli markaları (VF/3M) korur. Ampirik
    sınır ve neden ≥2'nin bile yetmediği: docs/audit/2026-06-03-round2-preliminary-2.9pct.md."""
    if min_token_len is None:
        min_token_len = DEDUP_MIN_FINGERPRINT_TOKEN_LEN
    return any(len(tok) >= min_token_len for tok in fp.split())


def plan_merge(group: dict) -> dict | None:
    """Bir fingerprint grubundan birleştirme planı üretir veya None döner.

    None koşulları (güvenlik):
      - fingerprint boş/whitespace (yalnız yasal-ek/geo/çöp → magnet riski)
      - fingerprint dejenere: yalnızca tek-karakter token'lar (akronim çökmesi → magnet)
      - country_code yok (hard-filter güvenliği)
      - <2 distinct master (birleştirilecek bir şey yok)
    """
    fp = (group.get("fingerprint") or "").strip()
    country = (group.get("country_code") or "").strip()
    masters = list(dict.fromkeys(group.get("master_ids") or []))  # tekilleştir, sıra korunur
    if not fp or not country or len(masters) < 2:
        return None
    if not _is_distinctive_fingerprint(fp):
        # Dejenere fingerprint (akronim çökmesi) → birleştirme. NOT: gerçekten
        # tek-karakterli özdeş firmalar burada under-merge kalır (kabul edilen takas;
        # magnet riski somut, under-merge riski düşük). Kayıp merge'ler denetlenebilsin.
        logger.debug("dejenere fingerprint skip: fp=%r masters=%d", fp, len(masters))
        return None
    primary = choose_primary(masters)
    secondaries = [m for m in masters if m != primary]
    return {"primary": primary, "secondaries": secondaries, "country_code": country, "fingerprint": fp}


# ─────────────────────────────────────────────────────────────────────
# ES AGGREGATION — aynı fingerprint + country altında >=2 master
# ─────────────────────────────────────────────────────────────────────

def _distinct_countries(es: Elasticsearch) -> list[str]:
    """Index'teki distinct country_code değerleri (root terms agg)."""
    resp = es.search(
        index=ES_INDEX,
        body={"size": 0, "aggs": {"cc": {"terms": {"field": "country_code", "size": 1000}}}},
    )
    return [b["key"] for b in resp["aggregations"]["cc"]["buckets"]]


def iter_duplicate_groups(
    es: Elasticsearch,
    page_size: int = 1000,
    master_cap: int = 200,
    min_count: int = 2,
    restrict_master_ids: list[str] | None = None,
):
    """Aynı kanonik fingerprint'i paylaşan distinct master_id'leri üretir.

    country_code HARD FILTER: her ülke ayrı işlenir (query-level filter). Ülke parent
    alanı olduğundan nested composite içine source olarak KONULAMAZ; bu yüzden ülke dış
    döngüde sabitlenir, fingerprint nested composite ile sayfalanır, master_id'ler
    reverse_nested ile parent'tan toplanır.

    restrict_master_ids verilirse aggregation YALNIZCA bu master'larla sınırlanır
    (batch-içi dedup için → tüm index'i taramaz, iş yükü batch'e ölçeklenir).

    Yields: {"fingerprint", "country_code", "master_ids": [...]}
    """
    for cc in _distinct_countries(es):
        after = None
        while True:
            comp = {"size": page_size, "sources": [{"fp": {"terms": {"field": _FINGERPRINT_FIELD}}}]}
            if after:
                comp["after"] = after
            if restrict_master_ids:
                query = {"bool": {"filter": [
                    {"term": {"country_code": cc}},
                    {"terms": {"master_id": list(restrict_master_ids)}},
                ]}}
            else:
                query = {"term": {"country_code": cc}}
            body = {
                "size": 0,
                "query": query,
                "aggs": {
                    "v": {
                        "nested": {"path": "variations"},
                        "aggs": {
                            "by_fp": {
                                "composite": comp,
                                "aggs": {
                                    "back": {
                                        "reverse_nested": {},
                                        "aggs": {
                                            "mids": {"terms": {"field": "master_id", "size": master_cap}}
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
            }
            resp = es.search(index=ES_INDEX, body=body)
            agg = resp["aggregations"]["v"]["by_fp"]
            buckets = agg["buckets"]
            if not buckets:
                break
            for b in buckets:
                mids = [m["key"] for m in b["back"]["mids"]["buckets"]]
                if len(mids) >= min_count:
                    yield {"fingerprint": b["key"]["fp"], "country_code": cc, "master_ids": mids}
            after = agg.get("after_key")
            if not after:
                break


# ─────────────────────────────────────────────────────────────────────
# UYGULAMA — PG repoint + ES merge/delete (grup-bazlı, hata-toleranslı)
# ─────────────────────────────────────────────────────────────────────

_MERGE_SCRIPT = """
for (v in params.new_vars) { if (!ctx._source.variations.contains(v)) { ctx._source.variations.add(v); } }
if (ctx._source.variations_stripped == null) { ctx._source.variations_stripped = []; }
for (s in params.new_stripped) { if (!ctx._source.variations_stripped.contains(s)) { ctx._source.variations_stripped.add(s); } }
"""


def _repoint_pg(cur, primary: str, secondaries: list[str], country: str) -> int:
    """secondary master'lara işaret eden satırları primary'e yönlendirir.
    country_code = HARD FILTER (parametrik). Etkilenen satır sayısını döner.

    A3: aynı atomik UPDATE'te ikincil NEW_MASTER anchor'ları AUTO_DEDUP'a demote eder
    (CASE) — böylece tek master_code'da >1 NEW_MASTER kalmaz (watch query kör noktası).
    Variant satırları (NEW_MASTER olmayan) tipini korur, sadece master_code'u değişir."""
    col_master = COLUMN_MAPPING["master_code"]
    col_country = COLUMN_MAPPING["country_code"]
    col_mt = COLUMN_MAPPING["match_type"]
    cur.execute(
        psycopg2.sql.SQL(
            "UPDATE {table} SET {master} = %s, "
            "{mt} = CASE WHEN {mt} = %s THEN %s ELSE {mt} END "
            "WHERE {master} = ANY(%s) AND {country} = %s"
        ).format(
            table=psycopg2.sql.Identifier(RAW_TABLE_NAME),
            master=psycopg2.sql.Identifier(col_master),
            mt=psycopg2.sql.Identifier(col_mt),
            country=psycopg2.sql.Identifier(col_country),
        ),
        (primary, MatchType.NEW_MASTER, MatchType.AUTO_DEDUP, secondaries, country),
    )
    return cur.rowcount


def apply_merge(es: Elasticsearch, cur, pg_conn, plan: dict) -> dict:
    """Tek bir birleştirme planını uygular. Hata olursa o grup için PG rollback
    edilir ve istisna yükseltilmeden {ok: False} döner (CLAUDE.md §3: batch durmaz)."""
    primary, secondaries, cc = plan["primary"], plan["secondaries"], plan["country_code"]
    try:
        repointed = _repoint_pg(cur, primary, secondaries, cc)
        # MEDIUM-1 (review): secondary'lere işaret eden satır yoksa (kaskad/zaten-repoint
        # edilmiş) izlenebilir olsun — sessiz no-op olmasın.
        if repointed == 0 and secondaries:
            logger.warning(
                "dedup repoint 0 satır etkiledi (kaskad/stale secondary?) "
                f"fp={plan.get('fingerprint')!r} primary={primary} secondaries={secondaries}"
            )
        for sec_id in secondaries:
            sec = es.get(index=ES_INDEX, id=sec_id, routing=cc)["_source"]
            es.update(
                index=ES_INDEX, id=primary, routing=cc,
                body={"script": {
                    "source": _MERGE_SCRIPT,
                    "params": {
                        "new_vars": sec.get("variations", []),
                        "new_stripped": sec.get("variations_stripped", []),
                    },
                }},
            )
            es.delete(index=ES_INDEX, id=sec_id, routing=cc)
        pg_conn.commit()
        return {"ok": True, "primary": primary, "merged": len(secondaries), "repointed": repointed}
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Merge hatasi fp={plan.get('fingerprint')!r} primary={primary}: {e}")
        return {"ok": False, "primary": primary, "merged": 0, "repointed": 0}


def auto_merge_duplicates(
    es: Elasticsearch,
    pg_conn,
    dry_run: bool = False,
    limit: int | None = None,
    restrict_master_ids: list[str] | None = None,
    refresh: bool = True,
) -> dict:
    """Duplicate fingerprint gruplarını otomatik birleştirir (PG repoint + ES merge).

    dry_run=True → yalnızca planları sayar, hiçbir değişiklik yapmaz.
    limit → en fazla bu kadar grup işle (kademeli rollout için).
    restrict_master_ids → yalnızca bu master'lar arasında dedup (batch-içi kullanım).
    refresh → bitişte ES refresh (batch-içi çağrıda False bırakılabilir; döngü zaten
              bir sonraki batch'te refresh eder).
    """
    cur = pg_conn.cursor()
    stats = {"groups": 0, "merged_masters": 0, "repointed_rows": 0, "skipped": 0, "errors": 0}
    for group in iter_duplicate_groups(es, restrict_master_ids=restrict_master_ids):
        plan = plan_merge(group)
        if not plan:
            stats["skipped"] += 1
            continue
        stats["groups"] += 1
        if dry_run:
            stats["merged_masters"] += len(plan["secondaries"])
        else:
            res = apply_merge(es, cur, pg_conn, plan)
            if res["ok"]:
                stats["merged_masters"] += res["merged"]
                stats["repointed_rows"] += res["repointed"]
            else:
                stats["errors"] += 1
        if limit and stats["groups"] >= limit:
            break
    if refresh and not dry_run:
        es.indices.refresh(index=ES_INDEX)
    cur.close()
    return stats


# ============================================================================
if __name__ == "__main__":
    import sys
    from es_manager import get_es_client

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    dry = "--apply" not in sys.argv
    lim = None
    for a in sys.argv:
        if a.startswith("--limit="):
            lim = int(a.split("=", 1)[1])

    es = get_es_client()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        stats = auto_merge_duplicates(es, conn, dry_run=dry, limit=lim)
        mode = "DRY-RUN (değişiklik yok; --apply ile uygula)" if dry else "UYGULANDI"
        print(f"[{mode}] {stats}")
    finally:
        conn.close()
