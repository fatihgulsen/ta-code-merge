"""ES tarafındaki fingerprint eşitliğine dayanarak aynı ülkedeki duplicate master'ları otomatik birleştirir.

Karar tamamen ES analyzer'ının ürettiği fingerprint'e aittir; Python'da fuzzy/string
benzerliği yapılmaz. country_code HARD FILTER'dır. Boş/dejenere fingerprint'ler
magnet riski nedeniyle atlanır. Bkz. docs/audit/ raporları.
"""

import logging

import psycopg2
import psycopg2.sql
from elasticsearch import Elasticsearch

from config import DB_CONFIG, alias_for_country, RAW_TABLE_NAME, COLUMN_MAPPING, DEDUP_MIN_FINGERPRINT_TOKEN_LEN, MatchType
from core.synonym_loader import get_all_country_codes
from matching.db_io import table_identifier

logger = logging.getLogger(__name__)

# Fingerprint, variations.name multi-field'ında üretilir (per-country geo izole):
# girdi ZATEN kendi ülke adı sıyrılmış stripped içeriktir → fingerprint per-country.
_FINGERPRINT_FIELD = "variations.name.fingerprint"
_FINGERPRINT_NESTED_PATH = "variations"


# ─────────────────────────────────────────────────────────────────────
# SAF PLANLAMA MANTIĞI (ES'siz test edilebilir)
# ─────────────────────────────────────────────────────────────────────

def choose_primary(master_ids: list[str]) -> str:
    """Birleştirmede korunacak master'ı deterministik seçer (sıralı ilk)."""
    return sorted(master_ids)[0]


def _is_distinctive_fingerprint(fp: str, min_token_len: int | None = None) -> bool:
    """Fingerprint'in dedup anahtarı olacak kadar ayırt edici olup olmadığını döner.

    Noktalı-akronim isimleri fingerprint_analyzer'da tek karaktere çöküp alakasız firmaları
    aynı grup altında toplayabilir (magnet riski). En az bir token min_token_len karakter
    uzunluğunda olmalıdır. Eşik gerekçesi için bkz. docs/audit/.
    """
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
        # Magnet riskine karşı atlanır; nadir under-merge kabul edilmiş bir takas.
        logger.debug("dejenere fingerprint skip: fp=%r masters=%d", fp, len(masters))
        return None
    primary = choose_primary(masters)
    secondaries = [m for m in masters if m != primary]
    return {"primary": primary, "secondaries": secondaries, "country_code": country, "fingerprint": fp}


# ─────────────────────────────────────────────────────────────────────
# ES AGGREGATION — aynı fingerprint + country altında >=2 master
# ─────────────────────────────────────────────────────────────────────

def iter_duplicate_groups(
    es: Elasticsearch,
    page_size: int = 1000,
    master_cap: int = 200,
    min_count: int = 2,
    restrict_master_ids: list[str] | None = None,
    countries: list[str] | None = None,
):
    """Aynı kanonik fingerprint'i paylaşan distinct master_id'lerini üretir (generator).

    country_code dış döngüde sabitlenir; nested composite ile fingerprint sayfalanır,
    master_id'ler reverse_nested ile toplanır. restrict_master_ids verilirse yalnızca bu
    master'lar sorgulanır (batch-içi kullanım). countries verilirse fielddata agg atlanır.

    Yields: {"fingerprint", "country_code", "master_ids": [...]}
    """
    for cc in (countries if countries is not None else get_all_country_codes()):
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
                        "nested": {"path": _FINGERPRINT_NESTED_PATH},
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
            resp = es.search(index=alias_for_country(cc), body=body)
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
"""


def _repoint_pg(cur, primary: str, secondaries: list[str], country: str) -> int:
    """Secondary master'lara işaret eden satırları primary'e yönlendirir; etkilenen satır sayısını döner.

    Aynı UPDATE'te ikincil NEW_MASTER anchor'ları AUTO_DEDUP'a demote edilir; böylece
    tek master_code altında >1 NEW_MASTER kalmasının yol açtığı izleme kör noktası önlenir.
    """
    col_master = COLUMN_MAPPING["master_code"]
    col_country = COLUMN_MAPPING["country_code"]
    col_mt = COLUMN_MAPPING["match_type"]
    cur.execute(
        psycopg2.sql.SQL(
            "UPDATE {table} SET {master} = %s, "
            "{mt} = CASE WHEN {mt} = %s THEN %s ELSE {mt} END "
            "WHERE {master} = ANY(%s) AND {country} = %s"
        ).format(
            table=table_identifier(RAW_TABLE_NAME),
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
        # Satır etkilenmemişse (kaskad/önceden repoint) sessiz geçilmemesi için uyarı.
        if repointed == 0 and secondaries:
            logger.warning(
                "dedup repoint 0 satır etkiledi (kaskad/stale secondary?) "
                f"fp={plan.get('fingerprint')!r} primary={primary} secondaries={secondaries}"
            )
        for sec_id in secondaries:
            sec = es.get(index=alias_for_country(cc), id=sec_id)["_source"]
            es.update(
                index=alias_for_country(cc), id=primary,
                body={"script": {
                    "source": _MERGE_SCRIPT,
                    "params": {
                        "new_vars": sec.get("variations", []),
                    },
                }},
            )
            es.delete(index=alias_for_country(cc), id=sec_id)
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
    countries: list[str] | None = None,
) -> dict:
    """Duplicate fingerprint gruplarını otomatik birleştirir (PG repoint + ES merge).

    dry_run=True → yalnızca planları sayar, değişiklik yapmaz.
    limit → en fazla bu kadar grup işle.
    restrict_master_ids → yalnızca bu master'lar arasında dedup (batch-içi kullanım).
    refresh → bitişte ES refresh; batch-içi çağrıda False bırakılabilir.
    """
    cur = pg_conn.cursor()
    stats = {"groups": 0, "merged_masters": 0, "repointed_rows": 0, "skipped": 0, "errors": 0}
    for group in iter_duplicate_groups(es, restrict_master_ids=restrict_master_ids, countries=countries):
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
        for cc in (countries if countries is not None else get_all_country_codes()):
            try:
                es.indices.refresh(index=alias_for_country(cc))
            except Exception:
                pass
    cur.close()
    return stats


# Kullanım: python -m dedup.auto_merge [--apply] [--limit=N]
# Varsayılan dry-run; --apply ile değişiklikler uygulanır.
if __name__ == "__main__":
    import sys
    from es.manager import get_es_client

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
