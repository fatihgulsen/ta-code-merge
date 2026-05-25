# ============================================================================
# main_processor.py - Stage-by-Stage Batch Eşleştirme Orkestrasyonu
# ============================================================================
# Mimari:
#   1. PostgreSQL'den master_code IS NULL kayıtları batch olarak oku
#   2. config.STAGES listesindeki her aktif stage için:
#      a. Tüm unmatched kayıtlara msearch ile stage sorgusu gönder
#      b. Eşleşenleri PG'ye yaz, match_stages_log'a kaydet, unmatched'dan çıkar
#      c. Eşleşmeyenleri match_stages_log'a kaydet (matched=False)
#      d. ES refresh (yeni master'lar varsa)
#   3. Tüm stage'lerden sonra hala unmatched → NEW_MASTER
#      Sub-batch'ler halinde index'le + refresh (within-batch duplike minimizasyonu)
# ============================================================================

import logging
import sys
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
        """No-op tqdm stub — install tqdm for a real progress bar."""

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
    DB_CONFIG,
    ES_INDEX,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    AUTO_CREATE_UPDATE_COLUMNS,
    RAW_TABLE_NAME,
    COUNTRY_CODE_FILTER,
    STAGES,
    MSEARCH_CHUNK_SIZE,
    SUFFIX_FUZZY_SCORE,
    LOG_ALL_STAGES,
)
from es_manager import create_index, get_es_client
from es_ingest import register_all_pipelines, pipeline_name
import es_queries as _es_queries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("elasticsearch").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# NEW_MASTER oluştururken sub-batch boyutu (within-batch duplicate minimizasyonu)
NEW_MASTER_SUBBATCH_SIZE = 200


# ─────────────────────────────────────────────────────────────────────
# DB YARDIMCILARI
# ─────────────────────────────────────────────────────────────────────


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def ensure_stage_log_table(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_stages_log (
            id               SERIAL PRIMARY KEY,
            input_id         TEXT,
            input_name       TEXT,
            country_code     VARCHAR(10),
            stage_name       VARCHAR(30),
            stage_order      INTEGER,
            matched          BOOLEAN,
            master_id        TEXT,
            es_score         FLOAT,
            created_at       TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_msl_input_id ON match_stages_log (input_id);
        CREATE INDEX IF NOT EXISTS idx_msl_stage_name ON match_stages_log (stage_name);
        CREATE INDEX IF NOT EXISTS idx_msl_matched ON match_stages_log (matched);
    """)
    conn.commit()
    cursor.close()
    logger.info("match_stages_log tablosu hazır.")


def validate_db_schema(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s);",
        (RAW_TABLE_NAME,),
    )
    if not cursor.fetchone()[0]:
        raise RuntimeError(f"HATA: '{RAW_TABLE_NAME}' tablosu bulunamadı!")

    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s;",
        (RAW_TABLE_NAME,),
    )
    existing_columns = {row[0] for row in cursor.fetchall()}

    for internal_name in MANDATORY_READ_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col or db_col not in existing_columns:
            raise RuntimeError(
                f"Zorunlu okuma sütunu eksik: {internal_name} → {db_col}"
            )

    missing_update = []
    for internal_name in MANDATORY_UPDATE_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col or db_col not in existing_columns:
            missing_update.append((internal_name, db_col))

    _ALLOWED_COL_TYPES = {"VARCHAR(50)", "INTEGER", "TEXT"}

    if missing_update and AUTO_CREATE_UPDATE_COLUMNS:
        for internal_name, db_col in missing_update:
            col_type = {"master_code": "VARCHAR(50)", "match_score": "INTEGER"}.get(
                internal_name, "TEXT"
            )
            if col_type not in _ALLOWED_COL_TYPES:
                raise ValueError(f"Bilinmeyen sütun tipi: {col_type!r}")
            cursor.execute(
                psycopg2.sql.SQL("ALTER TABLE {} ADD COLUMN {} {};").format(
                    psycopg2.sql.Identifier(RAW_TABLE_NAME),
                    psycopg2.sql.Identifier(db_col),
                    psycopg2.sql.SQL(col_type),
                )
            )
            conn.commit()
            logger.info(f"Sütun oluşturuldu: {db_col} ({col_type})")
    elif missing_update:
        raise RuntimeError(
            f"Eksik güncelleme sütunları: {[x[1] for x in missing_update]}"
        )

    cursor.close()
    logger.info(f"Schema doğrulama başarılı: '{RAW_TABLE_NAME}'")


# ─────────────────────────────────────────────────────────────────────
# STAGE ORKESTRASYONU
# ─────────────────────────────────────────────────────────────────────


def run_stage(
    es,
    records: list[dict],
    stage: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Bir stage'i tüm unmatched kayıtlara uygular.

    Args:
        es:      Elasticsearch client
        records: [{"row_id", "raw_name", "country", "tax", "phone"}, ...]
        stage:   config.STAGES'den bir stage dict'i

    Returns:
        (matched, unmatched)
        matched:   [{"row_id", "raw_name", "country", "master_id", "es_score",
                     "stage_name", "stage_order"}, ...]
        unmatched: records ile aynı format, eşleşmeyenler
    """
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
            name=rec["raw_name"],
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
                    "es_score": SUFFIX_FUZZY_SCORE
                    if stage_name == "SUFFIX_FUZZY"
                    else top_score,
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
    """
    msearch API ile toplu sorgu çalıştırır.

    Args:
        queries: [(query_body, routing_country, record), ...]

    Returns:
        {index: hits_list} mapping
    """
    results: dict[int, list[dict]] = {}
    indices = list(range(len(queries)))

    for chunk_start in range(0, len(indices), MSEARCH_CHUNK_SIZE):
        chunk = indices[chunk_start : chunk_start + MSEARCH_CHUNK_SIZE]
        body: list[dict[str, Any]] = []

        for idx in chunk:
            query, country, _ = queries[idx]
            body.append({"index": ES_INDEX, "routing": country.upper()})
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


# ─────────────────────────────────────────────────────────────────────
# YAZMA İŞLEMLERİ
# ─────────────────────────────────────────────────────────────────────


def update_es_variations(es, matched: list[dict]) -> None:
    """Eslesen kayitlarin varyasyonlarini ve meta bilgilerini master ES doc'a ekler.

    Her eslesen kaydin raw_name'i variations listesine,
    tax/phone/address degerleri ilgili listelere eklenir (zaten yoksa).
    """
    if not matched:
        return

    # Master bazinda gruplayarak toplu update yap
    master_updates: dict[str, dict] = {}
    for r in matched:
        mid = r["master_id"]
        if mid not in master_updates:
            master_updates[mid] = {
                "variations": set(),
                "tax_numbers": set(),
                "phone_numbers": set(),
                "addresses": set(),
                "country": r["country"],
            }
        master_updates[mid]["variations"].add(r["raw_name"])
        if r.get("tax"):
            master_updates[mid]["tax_numbers"].add(r["tax"])
        if r.get("phone"):
            master_updates[mid]["phone_numbers"].add(r["phone"])
        if r.get("address"):
            master_updates[mid]["addresses"].add(r["address"])

    bulk_body = []
    for master_id, info in master_updates.items():
        # Variations update
        for variation in info["variations"]:
            v_clean = variation.strip().rstrip(".,")
            bulk_body.append(
                {
                    "update": {
                        "_index": ES_INDEX,
                        "_id": master_id,
                        "routing": info["country"].upper(),
                    }
                }
            )
            bulk_body.append(
                {
                    "script": {
                        "source": (
                            "String v = params.v; "
                            "if (!ctx._source.variations.contains(v)) { "
                            "  ctx._source.variations.add(v); "
                            "}"
                        ),
                        "lang": "painless",
                        "params": {"v": v_clean},
                    },
                }
            )

        # Tax, phone, address listelerine ekleme (duplicate kontrollu)
        _append_list_fields(bulk_body, master_id, info)

    if bulk_body:
        try:
            es.bulk(body=bulk_body, refresh=False)
        except Exception:
            logger.debug("ES variations update basarisiz, devam ediliyor")


def _append_list_fields(bulk_body: list[dict], master_id: str, info: dict) -> None:
    """tax_number, phone_number, address listelerine yeni degerleri ekler."""
    field_map = {
        "tax_number": info["tax_numbers"],
        "phone_number": info["phone_numbers"],
        "address": info["addresses"],
    }
    country = info["country"].upper()

    for field_name, values in field_map.items():
        for val in values:
            val_clean = val.strip()
            if not val_clean:
                continue
            bulk_body.append(
                {
                    "update": {
                        "_index": ES_INDEX,
                        "_id": master_id,
                        "routing": country,
                    }
                }
            )
            bulk_body.append(
                {
                    "script": {
                        "source": (
                            "String v = params.v; "
                            "String field = params.field; "
                            "if (ctx._source[field] == null) { "
                            "  ctx._source[field] = [v]; "
                            "} else if (!ctx._source[field].contains(v)) { "
                            "  ctx._source[field].add(v); "
                            "}"
                        ),
                        "lang": "painless",
                        "params": {"v": val_clean, "field": field_name},
                    },
                }
            )


def write_matched_to_pg(write_cursor, write_conn, matched: list[dict]) -> None:
    if not matched:
        return
    col_id = COLUMN_MAPPING["id"]
    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]

    execute_values(
        write_cursor,
        f"""
        UPDATE {RAW_TABLE_NAME} AS t
        SET {col_master} = d.master_code,
            {col_score}  = d.match_score,
            {col_type}   = d.match_type
        FROM (VALUES %s) AS d(master_code, match_score, match_type, id)
        WHERE t.{col_id} = d.id
        """,
        [
            (r["master_id"], int(r["es_score"]), r["stage_name"], r["row_id"])
            for r in matched
        ],
    )
    write_conn.commit()


def write_stage_log(
    write_cursor,
    write_conn,
    matched: list[dict],
    unmatched: list[dict],
    stage: dict,
) -> None:
    """matched ve unmatched kayıtları match_stages_log'a yazar."""
    rows = []
    for r in matched:
        rows.append(
            (
                r["row_id"],
                r["raw_name"],
                r["country"],
                stage["name"],
                stage["order"],
                True,
                r["master_id"],
                r["es_score"],
            )
        )
    for r in unmatched:
        rows.append(
            (
                r["row_id"],
                r["raw_name"],
                r["country"],
                stage["name"],
                stage["order"],
                False,
                None,
                None,
            )
        )

    if not rows:
        return

    execute_values(
        write_cursor,
        """
        INSERT INTO match_stages_log
            (input_id, input_name, country_code, stage_name, stage_order,
             matched, master_id, es_score)
        VALUES %s
        """,
        rows,
    )
    write_conn.commit()


def build_new_master_doc(
    name: str, country: str, tax: str, phone: str, address: str = ""
) -> tuple[dict, str]:
    master_id = str(uuid.uuid4())
    doc = {
        "_index": ES_INDEX,
        "_id": master_id,
        "_routing": country.upper(),
        "_source": {
            "master_id": master_id,
            "variations": [name],
            "variations_stripped": [],
            "country_code": country.upper(),
        },
    }
    if tax:
        doc["_source"]["tax_number"] = [tax]
    if phone:
        doc["_source"]["phone_number"] = [phone]
    if address:
        doc["_source"]["address"] = [address]
    return doc, master_id


def create_new_masters(es, write_cursor, write_conn, records: list[dict]) -> None:
    """
    Unmatched kayitlari NEW_MASTER olarak ES'e index'ler.

    Akis:
    1. Tum kayitlar icinde exact dedup: ayni (isim_lower, country) tek master
    2. Sub-batch'ler halinde ES'e index + refresh
    3. Her sub-batch sonrasi kalan kayitlari CANONICAL_EXACT ile ES'te arat
       (onceki sub-batch'te olusturulan master'larla eslesebilirler)
    """
    col_id = COLUMN_MAPPING["id"]
    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]

    # Adim 1: Tum kayitlar icinde exact dedup
    seen: dict[tuple[str, str], str] = {}  # (name_lower, country) → master_id
    unique_records: list[dict] = []  # ES'e index'lenecek (ilk gorulen)
    duplicate_updates: list[tuple] = []  # PG update (seen'deki master'a bagla)
    duplicate_logs: list[tuple] = []

    for rec in records:
        # Basit dedup: lower + strip
        norm_name = rec["raw_name"].lower().strip()
        dedup_key = (norm_name, rec["country"])
        existing_master_id = seen.get(dedup_key)
        if existing_master_id:
            duplicate_updates.append(
                (existing_master_id, 100, "NEW_MASTER", rec["row_id"])
            )
            duplicate_logs.append(
                (
                    rec["row_id"],
                    rec["raw_name"],
                    rec["country"],
                    "NEW_MASTER",
                    7,
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

    # Adim 2: Unique kayitlari sub-batch'ler halinde index'le
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
                "_index": ES_INDEX,
                "_id": master_id,
                "_routing": rec["country"].upper(),
                "pipeline": pipeline_name(rec["country"]),
                "_source": {
                    "master_id": master_id,
                    "variations": [{"name": rec["raw_name"]}],
                    "variations_stripped": [],
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
            pg_updates.append((master_id, 100, "NEW_MASTER", rec["row_id"]))
            log_rows.append(
                (
                    rec["row_id"],
                    rec["raw_name"],
                    rec["country"],
                    "NEW_MASTER",
                    7,
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
            es.indices.refresh(index=ES_INDEX)

        execute_values(
            write_cursor,
            f"""
            UPDATE {RAW_TABLE_NAME} AS t
            SET {col_master} = d.master_code,
                {col_score}  = d.match_score,
                {col_type}   = d.match_type
            FROM (VALUES %s) AS d(master_code, match_score, match_type, id)
            WHERE t.{col_id} = d.id
            """,
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

        # Adim 3: Kalan kayitlari ES'te arat — onceki sub-batch'lerle eslesiyor mu?
        if remaining:
            canonical_stage = next(s for s in STAGES if s["name"] == "CANONICAL_EXACT")
            found_in_es, still_remaining = run_stage(es, remaining, canonical_stage)
            if found_in_es:
                write_matched_to_pg(write_cursor, write_conn, found_in_es)
                if canonical_stage.get("index_variation", True):
                    update_es_variations(es, found_in_es)
                # Stage log'a CANONICAL_EXACT olarak yaz (NEW_MASTER'dan once yakalandi)
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
                                2,
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

    # Adim 3: Duplicate'larin PG yazimi + ES varyasyon update
    # (ES'te master doc'lar artik mevcut)
    if duplicate_updates:
        execute_values(
            write_cursor,
            f"""
            UPDATE {RAW_TABLE_NAME} AS t
            SET {col_master} = d.mc, {col_score} = d.ms, {col_type} = d.mt
            FROM (VALUES %s) AS d(mc, ms, mt, id)
            WHERE t.{col_id} = d.id
            """,
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


# ─────────────────────────────────────────────────────────────────────
# TEKIL KAYIT ESLESTIRME (ES-Authority)
# ─────────────────────────────────────────────────────────────────────

# ES refresh araligi — her N kayitta bir refresh yapilir
ES_REFRESH_INTERVAL = 50


def match_single_record(es, rec: dict, active_stages: list[dict]) -> dict:
    """Tek bir kaydi tum stage'lerden gecirir (msearch ile performansli).
    Sonuclari islerken ilk eslesenden sonrasini kisa devre yapar (loglamaz).
    Returns:
        {"winner": dict or None, "trace": list}
    """
    body: list[dict] = []
    stage_indices: list[dict] = []

    for stage in active_stages:
        query_fn = getattr(_es_queries, stage["query_fn"])
        q = query_fn(name=rec["raw_name"], country=rec["country"], es=es)
        body.append({"index": ES_INDEX, "routing": rec["country"].upper()})
        body.append(q)
        stage_indices.append(stage)

    if not body:
        return {"winner": None, "trace": []}

    try:
        response = es.msearch(body=body)
    except Exception:
        logger.exception("msearch basarisiz (single record)")
        return {"winner": None, "trace": []}

    trace = []
    winner = None

    for i, stage in enumerate(stage_indices):
        resp = response["responses"][i]
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
            "master_id": top_hit["_source"]["master_id"] if matched else None
        }
        trace.append(res)
        
        if matched and winner is None:
            winner = res.copy()
            winner["master_doc_id"] = top_hit["_id"]
            winner["index_variation"] = stage.get("index_variation", True)
            # Kisa devre: Ilk kazanan stage'den sonraki sonuclari (msearch icinden gelmis olsa bile) cope at.
            break
            
    return {"winner": winner, "trace": trace}


def _index_new_master(es, rec: dict) -> str:
    """Yeni master olusturur, ES'e index'ler (pipeline ile), master_id doner."""
    master_id = str(uuid.uuid4())
    doc = {
        "master_id": master_id,
        "variations": [{"name": rec["raw_name"]}],
        "variations_stripped": [],
        "country_code": rec["country"].upper(),
    }
    if rec.get("phone"):
        doc["phone_number"] = [rec["phone"]]
    if rec.get("address"):
        doc["address"] = [rec["address"]]

    try:
        es.index(
            index=ES_INDEX,
            id=master_id,
            routing=rec["country"].upper(),
            body=doc,
            pipeline=pipeline_name(rec["country"]),
        )
    except Exception as exc:
        # Pipeline hatasi — pipeline olmadan dene
        logger.warning(
            f"Pipeline ile index hatasi ({exc!r}), pipeline olmadan deneniyor: {rec['raw_name'][:50]}"
        )
        es.index(
            index=ES_INDEX,
            id=master_id,
            routing=rec["country"].upper(),
            body=doc,
        )
    return master_id


def _add_variation_to_master(
    es, master_doc_id: str, variation: str, country: str, rec: dict | None = None
) -> None:
    """Eslesen kaydin varyasyonunu ve meta bilgilerini master doc'a ekler.

    Doc'u okur → variations listesine yeni varyasyonu ekler →
    tax/phone/address listelerine yeni degerleri ekler →
    pipeline ile yeniden index'ler.
    """
    v_lower = variation.lower().strip().rstrip(".,")
    cc = country.upper()
    try:
        doc = es.get(index=ES_INDEX, id=master_doc_id, routing=cc)
        source = doc["_source"]
        existing_variations = source.get("variations", [])

        changed = False
        existing_names = [
            v.get("name", "").lower()
            for v in existing_variations
            if isinstance(v, dict)
        ]
        if v_lower not in existing_names:
            existing_variations.append({"name": variation})
            source["variations"] = existing_variations
            source["variations_stripped"] = []
            source["variations_suffix"] = []
            changed = True

        # tax/phone/address listelerine yeni degerleri ekle
        if rec:
            for field, key in [
                ("phone_number", "phone"),
                ("address", "address"),
            ]:
                val = (rec.get(key) or "").strip()
                if val:
                    existing = source.get(field, [])
                    if not isinstance(existing, list):
                        existing = [existing] if existing else []
                    if val not in existing:
                        existing.append(val)
                        source[field] = existing
                        changed = True

        if not changed:
            return

        pipe = pipeline_name(cc)
        es.index(
            index=ES_INDEX,
            id=master_doc_id,
            routing=cc,
            body=source,
            pipeline=pipe,
        )
    except Exception:
        logger.debug(f"Varyasyon ekleme basarisiz: {v_lower[:50]}")


# ─────────────────────────────────────────────────────────────────────
# ANA ISLEM DONGUSU (Row-by-Row, ES-Authority)
# ─────────────────────────────────────────────────────────────────────


def process_all_data() -> None:
    es = get_es_client()
    logger.info("Elasticsearch index kontrol ediliyor...")
    create_index(es)

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

        # Toplam islenmemis kayit sayisi — progress bar icin
        # Identifiers (table/column names) use psycopg2.sql.Identifier for safety.
        # The COUNTRY_CODE_FILTER value is passed as a %s parameter — never interpolated.
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
        total_skipped = 0
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

        while True:
            # Server-side cursor yerine basit SELECT + LIMIT
            # Her seferinde master_code IS NULL olan sonraki BATCH_SIZE kaydi cek
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

            # PG toplu yazim icin biriktiriciler
            pg_updates: list[tuple] = []
            log_rows: list[tuple] = []
            audit_rows: list[tuple] = []
            records_since_refresh = 0

            for row in rows:
                row_id = row[col_id]
                last_id = row_id  # Sayfalama icin son id'yi takip et
                country = (
                    (row[col_country] or "").strip().upper()
                    if col_country
                    else "DEFAULT"
                )
                if len(country) != 2 or not country.isalpha():
                    country = "DEFAULT"
                raw_name = (row[col_name] or "").strip()
                if not raw_name:
                    total_skipped += 1
                    pbar.update(1)
                    continue

                rec = {
                    "row_id": row_id,
                    "raw_name": raw_name,
                    "country": country,
                    "tax": row.get(col_tax) or "" if col_tax else "",
                    "phone": row.get(col_phone) or "" if col_phone else "",
                    "address": row.get(col_address) or "" if col_address else "",
                }

                # --- Tek kayit eslestirme ---
                match_res = match_single_record(es, rec, active_stages)
                winner = match_res["winner"]
                trace = match_res["trace"]

                if winner:
                    master_id = winner["master_doc_id"]
                    es_score = winner["es_score"]
                    stage_name = winner["stage_name"]

                    details = f"[{stage_name}] score: {es_score:.2f}"
                    pg_updates.append(
                        (master_id, int(es_score), stage_name, details, row_id)
                    )

                    if winner.get("index_variation", True):
                        _add_variation_to_master(
                            es, winner["master_doc_id"], raw_name, country, rec
                        )

                    total_matched += 1
                    stage_counts[stage_name] = stage_counts.get(stage_name, 0) + 1
                else:
                    master_id = _index_new_master(es, rec)
                    details = "NEW_MASTER: No relevant matches found."
                    pg_updates.append((master_id, 100, "NEW_MASTER", details, row_id))
                    total_new += 1
                    stage_name = "NEW_MASTER"
                    es_score = 100.0

                # --- Audit & Trace Logging ---
                # 1. match_audit (özet)
                audit_rows.append(
                    (
                        row_id,
                        raw_name,
                        country,
                        master_id,
                        stage_name,
                        es_score,
                        len([t for t in trace if t["matched"]]),
                    )
                )

                # 2. match_stages_log (ayrıntı - Tüm stage'leri logla)
                for t in trace:
                    if not t["matched"] and not LOG_ALL_STAGES:
                        continue
                    log_rows.append(
                        (
                            row_id,
                            raw_name,
                            country,
                            t["stage_name"],
                            t["stage_order"],
                            t["matched"],
                            (t["master_id"] or master_id) if t["matched"] else None,
                            t["es_score"],
                        )
                    )

                records_since_refresh += 1
                total_processed += 1
                pbar.update(1)

                # Progress bar postfix guncelle
                match_pct = (
                    round(100 * total_matched / total_processed, 1)
                    if total_processed
                    else 0
                )
                pbar.set_postfix_str(
                    f"eslesen={total_matched:,} ({match_pct}%) yeni={total_new:,},toplam={total_processed:,},skipped={total_skipped:,}",
                    refresh=False,
                )

                # Periyodik ES refresh — yeni master'lar gorunur olsun
                if records_since_refresh >= ES_REFRESH_INTERVAL:
                    es.indices.refresh(index=ES_INDEX)
                    records_since_refresh = 0

                    # Periyodik PG flush
                    if pg_updates:
                        execute_values(
                            write_cursor,
                            f"""
                            UPDATE {RAW_TABLE_NAME} AS t
                            SET {col_master} = d.mc, {COLUMN_MAPPING["match_score"]} = d.ms,
                                {COLUMN_MAPPING["match_type"]} = d.mt, {COLUMN_MAPPING["match_details"]} = d.md
                            FROM (VALUES %s) AS d(mc, ms, mt, md, id)
                            WHERE t.{col_id} = d.id
                            """,
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
                    f"""
                    UPDATE {RAW_TABLE_NAME} AS t
                    SET {col_master} = d.mc, {COLUMN_MAPPING["match_score"]} = d.ms,
                        {COLUMN_MAPPING["match_type"]} = d.mt
                    FROM (VALUES %s) AS d(mc, ms, mt, id)
                    WHERE t.{col_id} = d.id
                    """,
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

            es.indices.refresh(index=ES_INDEX)

        pbar.close()

        # Final ozet
        write_cursor.close()
        logger.info(f"{'=' * 60}")
        logger.info(f"TAMAMLANDI: {total_processed:,} kayit islendi")
        logger.info(f"  Eslesen:     {total_matched:,}")
        logger.info(f"  Yeni master: {total_new:,}")
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


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Firma Eşleştirme Sistemi başlatılıyor...")
    logger.info("=" * 60)
    process_all_data()
