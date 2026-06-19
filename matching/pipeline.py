"""Eşleştirme orkestrasyonu: stage çalıştırma, msearch, kazanan seçimi, ana döngü."""
import logging
import uuid
from typing import Any

import psycopg2
import psycopg2.sql
from psycopg2.extras import DictCursor, execute_values
from elasticsearch import helpers

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover

    class tqdm:  # type: ignore[misc]
        """tqdm yoksa sessizce devam eder; gerçek progress bar için tqdm kurun."""

        def __init__(self, iterable=None, **kwargs):
            self._iterable = iterable

        def __iter__(self):
            return iter(self._iterable) if self._iterable is not None else iter([])

        def update(self, n=1):
            pass

        def set_postfix_str(self, s="", refresh=True):
            pass

        def close(self):
            pass


from config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    alias_for_country,
    RAW_TABLE_NAME,
    COUNTRY_CODE_FILTER,
    STAGES,
    MSEARCH_CHUNK_SIZE,
    LOG_ALL_STAGES,
    NEW_MASTER_SUBBATCH_SIZE,
    ENABLE_INPUT_FILTER,
    AUTO_DEDUP_PER_BATCH,
    AUTO_DEDUP_EVERY_N_BATCHES,
    MATCH_BATCH_SIZE,
    ENABLE_DIRTY_DATA,
)
from core.synonym_loader import get_all_country_codes
from es.manager import create_index, get_es_client
from es.ingest import register_all_pipelines, pipeline_name
import es.queries as _es_queries
from es.queries import is_address_dirty
from core.input_filter import classify_input
from core.synonym_phonetic import canonicalize_phonetic
from dedup.auto_merge import auto_merge_duplicates

from matching.db_io import (
    _make_pg_update_tuple,
    get_db_connection,
    ensure_stage_log_table,
    validate_db_schema,
    write_matched_to_pg,
    write_stage_log,
)
from matching.es_writer import (
    update_es_variations,
    _index_new_master,
    _add_variation_to_master,
)

logger = logging.getLogger(__name__)

_INDEXABLE_CC: set[str] | None = None


def _is_indexable_country(country: str) -> bool:
    """Ülke kodu geçerli (2 harf) VE bir index'i var mı (synonyms_data'da)?"""
    global _INDEXABLE_CC
    if _INDEXABLE_CC is None:
        _INDEXABLE_CC = set(get_all_country_codes())
    cc = (country or "").strip().upper()
    return len(cc) == 2 and cc.isalpha() and cc in _INDEXABLE_CC


# ── Stage orkestrasyonu ──────────────────────────────────────────────


def run_stage(
    es,
    records: list[dict],
    stage: dict,
) -> tuple[list[dict], list[dict]]:
    """Bir stage'i tüm unmatched kayıtlara uygular; (matched, unmatched) döner."""
    stage_name = stage["name"]
    stage_order = stage["order"]
    min_score = stage["min_score"]
    query_fn = getattr(_es_queries, stage["query_fn"])

    # TAX_EXACT için tax numarası olmayanları direkt unmatched'a al
    if stage_name == "TAX_EXACT":
        tax_records = [r for r in records if r.get("tax")]
        no_tax_records = [r for r in records if not r.get("tax")]
    else:
        tax_records = records
        no_tax_records = []

    if not tax_records:
        return [], records

    # msearch için (query, routing, record) üçlüleri oluştur
    queries = []
    for rec in tax_records:
        q = query_fn(
            name=rec["match_name"],
            country=rec["country"],
            tax_number=rec.get("tax", ""),
        )
        queries.append((q, rec["country"], rec))

    # msearch çalıştır
    hits_map = _execute_msearch(es, queries)

    matched = []
    unmatched = list(no_tax_records)

    for i, (_, _, rec) in enumerate(queries):
        hits = hits_map.get(i, [])
        top_hit = hits[0] if hits else None
        top_score = top_hit["_score"] if top_hit else 0.0

        if top_hit and top_score >= min_score:
            matched.append(
                {
                    **rec,
                    "master_id": top_hit["_source"]["master_id"],
                    "es_score": top_score,
                    "stage_name": stage_name,
                    "stage_order": stage_order,
                    "index_variation": stage.get("index_variation", True),
                }
            )
        else:
            unmatched.append(rec)

    return matched, unmatched


def _execute_msearch(
    es,
    queries: list[tuple[dict, str, dict]],
) -> dict[int, list[dict]]:
    """msearch API ile toplu sorgu çalıştırır; {index: hits_list} döner."""
    results: dict[int, list[dict]] = {}
    indices = list(range(len(queries)))

    for chunk_start in range(0, len(indices), MSEARCH_CHUNK_SIZE):
        chunk = indices[chunk_start : chunk_start + MSEARCH_CHUNK_SIZE]
        body: list[dict[str, Any]] = []

        for idx in chunk:
            query, country, _ = queries[idx]
            body.append({"index": alias_for_country(country)})
            body.append(query)

        try:
            response = es.msearch(body=body)
        except Exception:
            logger.exception("msearch başarısız")
            for idx in chunk:
                results[idx] = []
            continue

        for i, idx in enumerate(chunk):
            resp = response["responses"][i]
            if "error" in resp:
                logger.error(f"msearch item #{idx} hata: {resp['error']}")
                results[idx] = []
            else:
                results[idx] = resp["hits"].get("hits", [])

    return results


def _select_winner(stage_responses: list[dict], active_stages: list[dict]) -> dict:
    """Stage yanıtlarından kazananı seçer (kısa devre: ilk score >= min_score).

    Tekil ve toplu eşleştirme aynı mantığı paylaşır → aynı semantik.
    """
    trace = []
    winner = None
    for i, stage in enumerate(active_stages):
        resp = stage_responses[i] if i < len(stage_responses) else {"error": "missing"}
        if "error" in resp:
            continue
        hits = resp["hits"].get("hits", [])
        top_hit = hits[0] if hits else None
        top_score = top_hit["_score"] if top_hit else 0.0
        matched = top_hit is not None and top_score >= stage["min_score"]
        res = {
            "stage_name": stage["name"],
            "stage_order": stage["order"],
            "matched": matched,
            "es_score": top_score,
            "master_id": top_hit["_source"]["master_id"] if matched else None,
        }
        trace.append(res)
        if matched and winner is None:
            winner = res.copy()
            winner["master_doc_id"] = top_hit["_id"]
            winner["index_variation"] = stage.get("index_variation", True)
            break
    return {"winner": winner, "trace": trace}


def _build_stage_body(es, rec: dict, active_stages: list[dict]) -> list[dict]:
    """Bir kayıt için tüm stage'lerin msearch gövdesini (header+query çiftleri) üretir."""
    body: list[dict] = []
    for stage in active_stages:
        query_fn = getattr(_es_queries, stage["query_fn"])
        q = query_fn(name=rec["match_name"], country=rec["country"], es=es)
        body.append({"index": alias_for_country(rec["country"])})
        body.append(q)
    return body


def match_single_record(es, rec: dict, active_stages: list[dict]) -> dict:
    """Tek bir kaydi tum stage'lerden gecirir (msearch). Returns {winner, trace}."""
    body = _build_stage_body(es, rec, active_stages)
    if not body:
        return {"winner": None, "trace": []}
    try:
        response = es.msearch(body=body)
    except Exception:
        logger.exception("msearch basarisiz (single record)")
        return {"winner": None, "trace": []}
    return _select_winner(response["responses"], active_stages)


def match_records_batch(es, recs: list[dict], active_stages: list[dict]) -> list[dict]:
    """Birden çok kaydı toplu msearch ile eşleştirir; sıra korunan [{winner, trace}] döner.

    Tüm kayıtlar aynı index anlık-görüntüsüne karşı sorgulanır; round-trip azaltmak
    dışında `match_single_record` ile birebir aynı winner-seçim semantiği.
    """
    if not recs:
        return []
    if not active_stages:
        return [{"winner": None, "trace": []} for _ in recs]

    S = len(active_stages)
    body: list[dict] = []
    for rec in recs:
        body.extend(_build_stage_body(es, rec, active_stages))

    # msearch'i MSEARCH_CHUNK_SIZE sorgu (=2 satır) ile parçala
    responses: list[dict] = []
    max_lines = max(2, MSEARCH_CHUNK_SIZE * 2)
    for off in range(0, len(body), max_lines):
        sub = body[off:off + max_lines]
        try:
            resp = es.msearch(body=sub)
            responses.extend(resp["responses"])
        except Exception:
            logger.exception("toplu msearch basarisiz (sub-chunk error olarak isaretlendi)")
            responses.extend([{"error": "msearch_failed"}] * (len(sub) // 2))

    out = []
    for i in range(len(recs)):
        out.append(_select_winner(responses[i * S:(i + 1) * S], active_stages))
    return out


def create_new_masters(es, write_cursor, write_conn, records: list[dict]) -> None:
    """Unmatched kayıtları NEW_MASTER olarak ES'e index'ler.

    Aynı (isim_lower, country) çiftleri tek master'a yönlendirilir. Sub-batch'ler
    arası çakışma CANONICAL_EXACT ile yakalanır (bkz. docs/audit/).
    """
    col_id = COLUMN_MAPPING["id"]
    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]
    col_details = COLUMN_MAPPING["match_details"]

    # NEW_MASTER tüm stage'lerden sonra gelir; sıra sayısı STAGES uzunluğundan türetilir.
    _new_master_stage_order = len(STAGES)
    _canonical_exact_stage_order = next(s["order"] for s in STAGES if s["name"] == "CANONICAL_EXACT")

    # 1. Exact dedup: aynı (isim_lower, country) tek master'a yönlendirilir.
    seen: dict[tuple[str, str], str] = {}  # (name_lower, country) → master_id
    unique_records: list[dict] = []
    duplicate_updates: list[tuple] = []
    duplicate_logs: list[tuple] = []

    for rec in records:
        norm_name = rec["match_name"].lower().strip()
        dedup_key = (norm_name, rec["country"])
        existing_master_id = seen.get(dedup_key)
        if existing_master_id:
            duplicate_updates.append(
                _make_pg_update_tuple(existing_master_id, 100, "NEW_MASTER", "NEW_MASTER: Dedup match.", rec["row_id"])
            )
            duplicate_logs.append(
                (
                    rec["row_id"],
                    rec["raw_name"],
                    rec["country"],
                    "NEW_MASTER",
                    _new_master_stage_order,
                    True,
                    existing_master_id,
                    100.0,
                )
            )
        else:
            master_id = str(uuid.uuid4())
            seen[dedup_key] = master_id
            unique_records.append({**rec, "_master_id": master_id})

    if duplicate_updates:
        logger.info(
            f"  NEW_MASTER dedup: {len(duplicate_updates)} duplike tespit edildi (index sonrasi yazilacak)."
        )

    # 2. Unique kayıtları sub-batch'ler halinde index'le + refresh.
    remaining = unique_records

    while remaining:
        chunk = remaining[:NEW_MASTER_SUBBATCH_SIZE]
        remaining = remaining[NEW_MASTER_SUBBATCH_SIZE:]

        es_docs = []
        pg_updates = []
        log_rows = []

        for rec in chunk:
            master_id = rec["_master_id"]
            doc = {
                "_index": alias_for_country(rec["country"]),
                "_id": master_id,
                "pipeline": pipeline_name(rec["country"]),
                "_source": {
                    "master_id": master_id,
                    "variations": [{"name": rec["match_name"]}],
                    "country_code": rec["country"].upper(),
                },
            }
            if rec.get("tax"):
                doc["_source"]["tax_number"] = [rec["tax"]]
            if rec.get("phone"):
                doc["_source"]["phone_number"] = [rec["phone"]]
            if rec.get("address"):
                doc["_source"]["address"] = [rec["address"]]
            es_docs.append(doc)
            pg_updates.append(_make_pg_update_tuple(master_id, 100, "NEW_MASTER", "NEW_MASTER: Initial index.", rec["row_id"]))
            log_rows.append(
                (
                    rec["row_id"],
                    rec["raw_name"],
                    rec["country"],
                    "NEW_MASTER",
                    _new_master_stage_order,
                    True,
                    master_id,
                    100.0,
                )
            )

        if es_docs:
            try:
                helpers.bulk(es, es_docs, raise_on_error=True)
            except helpers.BulkIndexError as e:
                failed_ids = set()
                for err in e.errors:
                    info = err.get("index", {})
                    doc_id = info.get("_id", "?")
                    reason = info.get("error", {}).get("reason", "?")
                    failed_ids.add(doc_id)
                    logger.debug(f"Pipeline hatasi doc={doc_id}: {reason[:120]}")
                logger.warning(
                    f"Pipeline hatasi: {len(e.errors)} doc basarisiz, "
                    f"pipeline olmadan tekrar deneniyor"
                )
                retry_docs = [d for d in es_docs if d["_id"] in failed_ids]
                if retry_docs:
                    helpers.bulk(es, retry_docs, raise_on_error=False)
            for _idx in {d["_index"] for d in es_docs}:
                es.indices.refresh(index=_idx)

        execute_values(
            write_cursor,
            psycopg2.sql.SQL(
                "UPDATE {} AS t"
                " SET {} = d.master_code, {} = d.match_score, {} = d.match_type"
                " FROM (VALUES %s) AS d(master_code, match_score, match_type, id)"
                " WHERE t.{} = d.id"
            ).format(
                psycopg2.sql.Identifier(RAW_TABLE_NAME),
                psycopg2.sql.Identifier(col_master),
                psycopg2.sql.Identifier(col_score),
                psycopg2.sql.Identifier(col_type),
                psycopg2.sql.Identifier(col_id),
            ),
            pg_updates,
        )
        execute_values(
            write_cursor,
            """
            INSERT INTO match_stages_log
                (input_id, input_name, country_code, stage_name, stage_order,
                 matched, master_id, es_score)
            VALUES %s
            """,
            log_rows,
        )
        write_conn.commit()
        logger.info(f"  NEW_MASTER sub-batch: {len(chunk)} yeni firma olusturuldu.")

        # 3. Kalan kayıtları önceki sub-batch master'larıyla CANONICAL_EXACT'ta eşleştir.
        if remaining:
            canonical_stage = next(s for s in STAGES if s["name"] == "CANONICAL_EXACT")
            found_in_es, still_remaining = run_stage(es, remaining, canonical_stage)
            if found_in_es:
                write_matched_to_pg(write_cursor, write_conn, found_in_es)
                if canonical_stage.get("index_variation", True):
                    update_es_variations(es, found_in_es)
                # CANONICAL_EXACT olarak logla (NEW_MASTER önce yakalandı)
                for r in found_in_es:
                    execute_values(
                        write_cursor,
                        """INSERT INTO match_stages_log
                            (input_id, input_name, country_code, stage_name, stage_order,
                            matched, master_id, es_score) VALUES %s""",
                        [
                            (
                                r["row_id"],
                                r["raw_name"],
                                r["country"],
                                "CANONICAL_EXACT",
                                _canonical_exact_stage_order,
                                True,
                                r["master_id"],
                                r["es_score"],
                            )
                        ],
                    )
                write_conn.commit()
                logger.info(
                    f"  NEW_MASTER arasi ES eslesmesi: {len(found_in_es)} kayit mevcut master'a baglandi."
                )
                remaining = still_remaining

    # 3. Dedup yazımı: master doc'lar artık ES'te mevcut, varyasyonlarını ekle.
    if duplicate_updates:
        execute_values(
            write_cursor,
            psycopg2.sql.SQL(
                "UPDATE {} AS t"
                " SET {} = d.mc, {} = d.ms, {} = d.mt, {} = d.md"
                " FROM (VALUES %s) AS d(mc, ms, mt, md, id)"
                " WHERE t.{} = d.id"
            ).format(
                psycopg2.sql.Identifier(RAW_TABLE_NAME),
                psycopg2.sql.Identifier(col_master),
                psycopg2.sql.Identifier(col_score),
                psycopg2.sql.Identifier(col_type),
                psycopg2.sql.Identifier(col_details),
                psycopg2.sql.Identifier(col_id),
            ),
            duplicate_updates,
        )
        execute_values(
            write_cursor,
            """INSERT INTO match_stages_log
                (input_id, input_name, country_code, stage_name, stage_order,
                 matched, master_id, es_score) VALUES %s""",
            duplicate_logs,
        )
        write_conn.commit()

        # Duplicate varyasyonlarini ES master doc'a ekle
        dedup_variations = []
        for upd, log in zip(duplicate_updates, duplicate_logs):
            master_id = upd[0]
            raw_name = log[1]  # input_name
            country = log[2]  # country_code
            dedup_variations.append(
                {"master_id": master_id, "raw_name": raw_name, "country": country}
            )
        update_es_variations(es, dedup_variations)
        logger.info(
            f"  NEW_MASTER dedup: {len(duplicate_updates)} duplike yazildi, varyasyonlar eklendi."
        )


# ── Ana işlem döngüsü ────────────────────────────────────────────────


def process_all_data() -> None:
    es = get_es_client()
    logger.info("Elasticsearch index kontrol ediliyor...")
    create_index(es)

    # Eski analyzer şeması (acronym_glue yok) distinctive-core gate'i yanlış tetikler → under-merge.
    # create_index var olan index'i değiştirmez; reindex yapılmadıysa erken çık.
    from es.manager import acronym_glue_active
    glue = acronym_glue_active(es)
    if glue is False:
        raise RuntimeError(
            "ES index'i ESKİ analyzer şemasında (acronym_glue yok). Distinctive-core gate "
            "yanlış MATCH_NONE üretir → under-merge. Önce reindex: `python -m es.manager --force`."
        )
    if glue is None:
        logger.warning("acronym_glue probe belirsiz (ES erişimi?) — reindex yapıldığından emin olun.")

    logger.info("Ingest pipeline kontrol ediliyor...")
    register_all_pipelines(es)

    logger.info("Veritabanina baglaniliyor...")
    read_conn = get_db_connection()
    write_conn = get_db_connection()

    active_stages = sorted(
        [s for s in STAGES if s["enabled"]],
        key=lambda s: s["order"],
    )
    logger.info(f"Aktif stage'ler: {[s['name'] for s in active_stages]}")

    try:
        validate_db_schema(read_conn)
        ensure_stage_log_table(write_conn)

        write_cursor = write_conn.cursor()

        col_id = COLUMN_MAPPING["id"]
        col_name = COLUMN_MAPPING["company_name"]
        col_country = COLUMN_MAPPING["country_code"]
        col_tax = COLUMN_MAPPING.get("tax_number")
        col_phone = COLUMN_MAPPING.get("phone_number")
        col_address = COLUMN_MAPPING.get("address")
        col_master = COLUMN_MAPPING["master_code"]

        select_cols = [col_id, col_name, col_country]
        if col_tax:
            select_cols.append(col_tax)
        if col_phone:
            select_cols.append(col_phone)
        if col_address:
            select_cols.append(col_address)

        # Toplam işlenmemiş kayıt sayısı — progress bar için
        # Sütun adları Identifier, filtre değeri %s parametresi (enjeksiyon riski yok).
        where_clause = psycopg2.sql.SQL("{col_master} IS NULL").format(
            col_master=psycopg2.sql.Identifier(col_master)
        )
        filter_params: tuple = ()
        if COUNTRY_CODE_FILTER:
            where_clause = psycopg2.sql.SQL("{base} AND {col_country} = %s").format(
                base=where_clause,
                col_country=psycopg2.sql.Identifier(col_country),
            )
            filter_params = (COUNTRY_CODE_FILTER,)
            logger.info(f"Ülke Filtresi Aktif: {COUNTRY_CODE_FILTER}")

        count_cur = read_conn.cursor()
        count_cur.execute(
            psycopg2.sql.SQL("SELECT COUNT(*) FROM {table} WHERE {where}").format(
                table=psycopg2.sql.Identifier(RAW_TABLE_NAME),
                where=where_clause,
            ),
            filter_params,
        )
        total_remaining = count_cur.fetchone()[0]
        count_cur.close()
        logger.info(f"Toplam islenmemis kayit: {total_remaining:,}")

        total_processed = 0
        total_matched = 0
        total_new = 0
        total_dirty = 0  # address-baskın kirli kayıt (DIRTY_DATA)
        total_skipped = 0
        total_excluded = 0  # firma-olmayan girdi (EXCLUDED, indekslenmez)
        total_deduped = 0   # batch-içi fingerprint dedup ile birleştirilen master sayısı
        total_batch_deduped = 0  # apply-pass içi kanonik (canonical_full+token_count) dedup
        stage_counts: dict[str, int] = {}
        last_id = 0  # Sayfalama icin son islenen id

        pbar = tqdm(
            total=total_remaining,
            desc="Eslestirme",
            unit="kayit",
            bar_format=(
                "{l_bar}{bar}| {n_fmt}/{total_fmt} "
                "[{elapsed}<{remaining}, {rate_fmt}] "
                "{postfix}"
            ),
        )

        touched_ccs: set[str] = set()

        # NEW_MASTER id'leri biriktirilerek N batch'te bir dedup koşulur; ES `terms` limitini
        # aşmamak için güvenlik-cap'te erken flush yapılır (bkz. _DEDUP_PENDING_CAP).
        pending_dedup_ids: list[str] = []
        pending_dedup_ccs: set[str] = set()
        _dedup_batch_counter = 0
        _DEDUP_PENDING_CAP = 20000  # ES terms varsayılan 65536 limitinin güvenli altı

        def _run_pending_dedup() -> None:
            """Biriken NEW_MASTER'ları batch'in ülke kümesiyle sınırlı deduplike eder."""
            nonlocal total_deduped
            if not (AUTO_DEDUP_PER_BATCH and pending_dedup_ids):
                return
            try:
                d = auto_merge_duplicates(
                    es, write_conn,
                    restrict_master_ids=list(pending_dedup_ids),
                    countries=sorted(pending_dedup_ccs),
                    refresh=False,
                )
                if d["merged_masters"]:
                    total_deduped += d["merged_masters"]
                    logger.info(
                        f"  Dedup: {d['merged_masters']} master birlestirildi, "
                        f"{d['repointed_rows']} satir yeniden yonlendirildi "
                        f"({len(pending_dedup_ids)} aday / {len(pending_dedup_ccs)} ulke)."
                    )
            except Exception:
                logger.exception("Dedup basarisiz (atlandi, devam ediliyor)")
            finally:
                pending_dedup_ids.clear()
                pending_dedup_ccs.clear()

        while True:
            # Server-side cursor yerine sayfalama: id > last_id LIMIT BATCH_SIZE
            read_cur = read_conn.cursor(cursor_factory=DictCursor)
            read_cur.execute(
                psycopg2.sql.SQL(
                    "SELECT {cols} FROM {table} WHERE {where} AND {col_id} > %s"
                    " ORDER BY {col_id} LIMIT {batch}"
                ).format(
                    cols=psycopg2.sql.SQL(", ").join(
                        psycopg2.sql.Identifier(c) for c in select_cols
                    ),
                    table=psycopg2.sql.Identifier(RAW_TABLE_NAME),
                    where=where_clause,
                    col_id=psycopg2.sql.Identifier(col_id),
                    batch=psycopg2.sql.Literal(BATCH_SIZE),
                ),
                filter_params + (last_id,),
            )
            rows = read_cur.fetchall()
            read_cur.close()

            if not rows:
                break

            # PG toplu yazım için biriktiriciler
            pg_updates: list[tuple] = []
            log_rows: list[tuple] = []
            audit_rows: list[tuple] = []
            # Bu batch'te oluşturulan NEW_MASTER id'leri (batch-içi dedup kapsamı)
            batch_new_master_ids: list[str] = []

            # Her chunk bir ES refresh penceresi; chunk_sz=1 → tekil-kayıt davranışı.
            chunk_sz = max(1, MATCH_BATCH_SIZE)
            for c0 in range(0, len(rows), chunk_sz):
                chunk = rows[c0:c0 + chunk_sz]

                # 1) Pre-pass: parse + empty-skip + EXCLUDED; eşleştirilecekleri topla
                match_items: list[tuple] = []  # (row_id, raw_name, country, rec)
                for row in chunk:
                    row_id = row[col_id]
                    last_id = row_id  # Sayfalama için son id'yi takip et
                    try:
                        country = (row[col_country] or "").strip().upper() if col_country else ""
                        raw_name = (row[col_name] or "").strip()
                        if not raw_name:
                            total_skipped += 1
                            pbar.update(1)
                            continue
                        # Geçersiz/bilinmeyen ülke → index'lenemez → EXCLUDED(invalid_country)
                        if not _is_indexable_country(country):
                            master_id = str(uuid.uuid4())
                            pg_updates.append(
                                _make_pg_update_tuple(
                                    master_id, 0, "EXCLUDED", "EXCLUDED: invalid_country", row_id
                                )
                            )
                            total_excluded += 1
                            total_processed += 1
                            pbar.update(1)
                            continue

                        # Firma-olmayan girdi → EXCLUDED (izole, ES'e indekslenmez).
                        excl_reason = classify_input(raw_name, country) if ENABLE_INPUT_FILTER else None
                        if excl_reason:
                            master_id = str(uuid.uuid4())
                            pg_updates.append(
                                _make_pg_update_tuple(
                                    master_id, 0, "EXCLUDED", f"EXCLUDED: {excl_reason}", row_id
                                )
                            )
                            total_excluded += 1
                            total_processed += 1
                            pbar.update(1)
                            continue

                        rec = {
                            "row_id": row_id,
                            "raw_name": raw_name,
                            "match_name": canonicalize_phonetic(raw_name, country),
                            "country": country,
                            "tax": row.get(col_tax) or "" if col_tax else "",
                            "phone": row.get(col_phone) or "" if col_phone else "",
                            "address": row.get(col_address) or "" if col_address else "",
                        }
                        match_items.append((row_id, raw_name, country, rec))
                    except Exception:
                        logger.exception("Row parse failed (row_id=%s)", row_id)
                        continue

                # 2) Toplu eşleştirme — chunk tek index anlık-görüntüsüne karşı
                results = match_records_batch(es, [it[3] for it in match_items], active_stages)

                # 3) Apply-pass (sıralı; yazımlar tekil-akışla aynı semantik)
                # Batch-içi kanonik dedup: aynı batch'te canonical_full+token_count eşit kayıtlar
                # tek master'a iner (ES, henüz indekslenmemiş kardeşine eşleşemez).
                seen_canon: dict[tuple, str] = {}
                for (row_id, raw_name, country, rec), match_res in zip(match_items, results):
                    try:
                        winner = match_res["winner"]
                        trace = match_res["trace"]

                        if winner:
                            master_id = winner["master_doc_id"]
                            es_score = winner["es_score"]
                            stage_name = winner["stage_name"]
                            details = f"[{stage_name}] score: {es_score:.2f}"
                            pg_updates.append(
                                _make_pg_update_tuple(master_id, es_score, stage_name, details, row_id)
                            )
                            if winner.get("index_variation", True):
                                _add_variation_to_master(
                                    es, winner["master_doc_id"], raw_name, country, rec
                                )
                            total_matched += 1
                            stage_counts[stage_name] = stage_counts.get(stage_name, 0) + 1
                        else:
                            # Batch-içi kanonik dedup anahtarı: TOKEN_COVERAGE ile tutarlı —
                            # fingerprint boş/non-alpha (ayırt edici çekirdek yok) ise dedup YOK.
                            mn = rec["match_name"]
                            ckey = None
                            fp = _es_queries._fingerprint_token(es, mn, country)
                            if fp and any(c.isalpha() for c in fp):
                                cf = _es_queries._get_canonical_full(es, mn, country)
                                tcnt = _es_queries._get_token_count(es, mn, _es_queries._get_analyzer(country), country)
                                if cf and tcnt > 0:
                                    ckey = (cf, tcnt, country.upper())
                            existing = seen_canon.get(ckey) if ckey else None
                            if existing is not None:
                                # Aynı batch'teki kanonik-eş kardeş → mevcut master'a varyant olarak ekle.
                                master_id = existing
                                stage_name = "NEW_MASTER"
                                details = "NEW_MASTER: batch-ici kanonik dedup."
                                _add_variation_to_master(es, master_id, raw_name, country, rec)
                                total_batch_deduped += 1
                            else:
                                master_id = _index_new_master(es, rec)
                                if ENABLE_DIRTY_DATA and is_address_dirty(es, mn, country):
                                    stage_name = "DIRTY_DATA"
                                    details = "DIRTY_DATA: address-baskin, ayirt edici cekirdek yok."
                                    total_dirty += 1
                                else:
                                    stage_name = "NEW_MASTER"
                                    details = "NEW_MASTER: No relevant matches found."
                                    total_new += 1
                                    batch_new_master_ids.append(master_id)  # P0-C: batch-içi dedup kapsamı
                                    pending_dedup_ids.append(master_id)      # perf: N-batch biriktirici
                                    pending_dedup_ccs.add(country)
                                if ckey:
                                    seen_canon[ckey] = master_id
                            pg_updates.append(_make_pg_update_tuple(master_id, 100, stage_name, details, row_id))
                            es_score = 100.0

                        # Audit & Trace Logging
                        audit_rows.append(
                            (
                                row_id, raw_name, country, master_id, stage_name, es_score,
                                len([t for t in trace if t["matched"]]),
                            )
                        )
                        for t in trace:
                            if not t["matched"] and not LOG_ALL_STAGES:
                                continue
                            log_rows.append(
                                (
                                    row_id, raw_name, country, t["stage_name"], t["stage_order"],
                                    t["matched"],
                                    (t["master_id"] or master_id) if t["matched"] else None,
                                    t["es_score"],
                                )
                            )

                        touched_ccs.add(alias_for_country(country))
                        total_processed += 1
                        pbar.update(1)
                        match_pct = (
                            round(100 * total_matched / total_processed, 1) if total_processed else 0
                        )
                        pbar.set_postfix_str(
                            f"eslesen={total_matched:,} ({match_pct}%) yeni={total_new:,},toplam={total_processed:,},skipped={total_skipped:,}",
                            refresh=False,
                        )
                    except Exception:
                        logger.exception("Row apply failed (row_id=%s)", row_id)
                        continue

                # 4) Chunk sonu: refresh (yeni master'lar sonraki chunk'a görünür) + PG flush
                for _idx in touched_ccs:
                    es.indices.refresh(index=_idx)
                touched_ccs.clear()
                if pg_updates:
                    execute_values(
                        write_cursor,
                        psycopg2.sql.SQL(
                            "UPDATE {} AS t"
                            " SET {} = d.mc, {} = d.ms, {} = d.mt, {} = d.md"
                            " FROM (VALUES %s) AS d(mc, ms, mt, md, id)"
                            " WHERE t.{} = d.id"
                        ).format(
                            psycopg2.sql.Identifier(RAW_TABLE_NAME),
                            psycopg2.sql.Identifier(col_master),
                            psycopg2.sql.Identifier(COLUMN_MAPPING["match_score"]),
                            psycopg2.sql.Identifier(COLUMN_MAPPING["match_type"]),
                            psycopg2.sql.Identifier(COLUMN_MAPPING["match_details"]),
                            psycopg2.sql.Identifier(col_id),
                        ),
                        pg_updates,
                    )
                    execute_values(
                        write_cursor,
                        """INSERT INTO match_stages_log
                            (input_id, input_name, country_code, stage_name, stage_order,
                             matched, master_id, es_score) VALUES %s""",
                        log_rows,
                    )
                    execute_values(
                        write_cursor,
                        """INSERT INTO match_audit
                            (input_id, input_name, country_code, final_master_id,
                             final_stage_name, final_score, total_matched_stages) VALUES %s""",
                        audit_rows,
                    )
                    write_conn.commit()
                    pg_updates.clear()
                    log_rows.clear()
                    audit_rows.clear()

            # Batch sonu — kalan PG yazimlarini flush et
            if pg_updates:
                execute_values(
                    write_cursor,
                    psycopg2.sql.SQL(
                        "UPDATE {} AS t"
                        " SET {} = d.mc, {} = d.ms, {} = d.mt, {} = d.md"
                        " FROM (VALUES %s) AS d(mc, ms, mt, md, id)"
                        " WHERE t.{} = d.id"
                    ).format(
                        psycopg2.sql.Identifier(RAW_TABLE_NAME),
                        psycopg2.sql.Identifier(col_master),
                        psycopg2.sql.Identifier(COLUMN_MAPPING["match_score"]),
                        psycopg2.sql.Identifier(COLUMN_MAPPING["match_type"]),
                        psycopg2.sql.Identifier(COLUMN_MAPPING["match_details"]),
                        psycopg2.sql.Identifier(col_id),
                    ),
                    pg_updates,
                )
                execute_values(
                    write_cursor,
                    """INSERT INTO match_stages_log
                        (input_id, input_name, country_code, stage_name, stage_order,
                         matched, master_id, es_score) VALUES %s""",
                    log_rows,
                )
                write_conn.commit()

            # NOT: Batch-sonu ES refresh'e gerek yok — her chunk sonunda (yukarıda)
            # o chunk'ta dokunulan ülke alias'ları zaten refresh edilip touched_ccs
            # temizleniyor; tüm yazımlar chunk içinde olduğundan batch sonunda görünürlük
            # garantilidir (dedup öncesi).

            # Aynı fingerprint'li NEW_MASTER'ları N batch'te bir birleştir; fielddata
            # aggregation sıklığını düşürür, güvenlik-cap'te erken flush tetiklenir.
            _dedup_batch_counter += 1
            if (
                _dedup_batch_counter % AUTO_DEDUP_EVERY_N_BATCHES == 0
                or len(pending_dedup_ids) >= _DEDUP_PENDING_CAP
            ):
                _run_pending_dedup()

        # Son N-altı batch'in biriken NEW_MASTER'larını kapanıştan önce flush et.
        _run_pending_dedup()

        pbar.close()

        # Özet
        write_cursor.close()
        logger.info(f"{'=' * 60}")
        logger.info(f"TAMAMLANDI: {total_processed:,} kayit islendi")
        logger.info(f"  Eslesen:     {total_matched:,}")
        logger.info(f"  Yeni master: {total_new:,}")
        if total_dirty:
            logger.info(f"  Kirli veri:  {total_dirty:,} (DIRTY_DATA: address-baskin)")
        if total_excluded:
            logger.info(f"  Excluded:    {total_excluded:,} firma-olmayan girdi izole edildi")
        if total_deduped:
            logger.info(f"  Dedup:       {total_deduped:,} duplike master batch-içi birleştirildi")
        if total_skipped:
            logger.info(f"  Atlanan:     {total_skipped:,} (bos isim)")
        logger.info(f"  Stage dagilimi:")
        for sn in sorted(stage_counts.keys()):
            logger.info(f"    {sn}: {stage_counts[sn]:,}")
        logger.info(f"{'=' * 60}")

    except Exception as e:
        if "read_conn" in locals():
            read_conn.rollback()
        if "write_conn" in locals():
            write_conn.rollback()
        logger.error(f"HATA: {e}", exc_info=True)
        raise
    finally:
        if "read_conn" in locals():
            read_conn.close()
        if "write_conn" in locals():
            write_conn.close()
        logger.info("Veritabani baglantilari kapatildi.")
