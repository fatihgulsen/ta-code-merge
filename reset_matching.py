"""Eşleştirme verilerini sıfırlar: PG match alanlarını NULL'a çeker ve/veya ES index'i yeniden oluşturur.

Kullanım:
  python reset_matching.py          # PG + ES sıfırla
  python reset_matching.py --pg     # Yalnızca PG sıfırla
  python reset_matching.py --es     # Yalnızca ES sıfırla
  python reset_matching.py --audit  # Yalnızca audit tabloları sıfırla
"""

import logging
import sys

import psycopg2

from config import (
    COLUMN_MAPPING,
    DB_CONFIG,
    RAW_TABLE_NAME,
)
from es_manager import create_index, get_es_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def reset_audit_tables() -> None:
    """match_audit ve match_stages_log tablolarını TRUNCATE eder."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        cursor.execute("TRUNCATE TABLE match_audit")
        cursor.execute("TRUNCATE TABLE match_stages_log")
        conn.commit()
        logger.info("PG: match_audit ve match_stages_log tablolari temizlendi.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Audit log temizleme hatasi: {e}")
    finally:
        cursor.close()
        conn.close()

def reset_postgres() -> None:
    """PG'deki master_code, match_score, match_type, match_details alanlarını NULL'a çeker."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    col_master = COLUMN_MAPPING["master_code"]
    col_score = COLUMN_MAPPING["match_score"]
    col_type = COLUMN_MAPPING["match_type"]
    col_details = COLUMN_MAPPING.get("match_details", "match_details")

    cursor.execute(
        f"SELECT COUNT(*) FROM {RAW_TABLE_NAME} WHERE {col_master} IS NOT NULL"
    )
    count = cursor.fetchone()[0]

    if count == 0:
        logger.info("PG: Sifirlanacak kayit yok (tum master_code zaten NULL).")
        cursor.close()
        conn.close()
        reset_audit_tables()
        return

    logger.info(f"PG: {count} kayit sifirlanacak...")

    try:
        # match_details kolonu opsiyonel; varlığını kontrol et
        cursor.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (RAW_TABLE_NAME, col_details)
        )
        has_details = cursor.fetchone() is not None

        if has_details:
            cursor.execute(
                f"""
                UPDATE {RAW_TABLE_NAME}
                SET {col_master} = NULL,
                    {col_score} = NULL,
                    {col_type} = NULL,
                    {col_details} = NULL
                WHERE {col_master} IS NOT NULL
                """
            )
            logger.info(f"PG: {count} kayit sifirlandi (master_code, match_score, match_type, match_details = NULL).")
        else:
            cursor.execute(
                f"""
                UPDATE {RAW_TABLE_NAME}
                SET {col_master} = NULL,
                    {col_score} = NULL,
                    {col_type} = NULL
                WHERE {col_master} IS NOT NULL
                """
            )
            logger.info(f"PG: {count} kayit sifirlandi (master_code, match_score, match_type = NULL).")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"PG Sifirlama hatasi: {e}")
        
    cursor.close()
    conn.close()
    
    reset_audit_tables()


def reset_elasticsearch() -> None:
    """ES index'i siler ve mapping'leriyle birlikte yeniden oluşturur."""
    es = get_es_client()
    logger.info("ES: Index yeniden olusturuluyor (--force)...")
    create_index(es, force_recreate=True)
    logger.info("ES: Index yeniden olusturuldu.")


if __name__ == "__main__":
    args = set(sys.argv[1:])

    if not args or args == {"--all"}:
        reset_postgres()
        reset_elasticsearch()
        logger.info("Tamamlandi. Simdi 'python main_processor.py' ile yeniden eslestirme yapabilirsiniz.")
    elif "--pg" in args:
        reset_postgres()
    elif "--es" in args:
        reset_elasticsearch()
    elif "--audit" in args:
        reset_audit_tables()
    else:
        print("Kullanim:")
        print("  python reset_matching.py          # PG + ES sifirla")
        print("  python reset_matching.py --pg     # Sadece PG sifirla")
        print("  python reset_matching.py --es     # Sadece ES sifirla")
        print("  python reset_matching.py --audit  # Sadece audit tablolarini sifirla")
