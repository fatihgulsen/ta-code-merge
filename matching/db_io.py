"""PostgreSQL I/O: bağlantı, şema doğrulama, eşleşme/stage-log yazımı."""
import logging
from typing import Any

import psycopg2
import psycopg2.sql
from psycopg2.extras import execute_values

from config import (
    RAW_TABLE_NAME,
    DB_CONFIG,
    COLUMN_MAPPING,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    AUTO_CREATE_UPDATE_COLUMNS,
)

logger = logging.getLogger(__name__)


def _make_pg_update_tuple(master_id: str, score: float, stage_name: str, details: str | None, row_id: Any) -> tuple:
    """5-element tuple matching execute_values bind order: (master_id, score, stage_name, details, row_id).

    Enforces consistent shape for pg_updates list — prevents DataError/IndexError when
    execute_values SQL template expects 5 columns (mc, ms, mt, md, id).
    """
    return (master_id, float(score), stage_name, details, row_id)


# ── DB yardımcıları ──────────────────────────────────────────────────


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


def write_matched_to_pg(write_cursor, write_conn, matched: list[dict]) -> None:
    if not matched:
        return
    col_id = COLUMN_MAPPING["id"]
    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]

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
