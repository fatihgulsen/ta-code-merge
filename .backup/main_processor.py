# ============================================================================
# main_processor.py - Batch Veri İşleme ve Öğrenme Döngüsü
# ============================================================================
# PostgreSQL'den veriyi batch'ler halinde okur,
# matcher_logic ile eşleştirir, ES'e yeni varyasyonları öğretir,
# sonuçları PostgreSQL'e yazar.
# ============================================================================

import psycopg2
from psycopg2.extras import DictCursor, execute_values
from elasticsearch import helpers
import logging
import sys

from config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    DB_CONFIG,
    ES_INDEX,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    RAW_TABLE_NAME,
    AUTO_CREATE_UPDATE_COLUMNS,
)
from es_manager import create_index, get_es_client
from matcher_logic import find_best_match, latinize
from synonym_normalizer import stripped_form

# Logging Konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 3. Parti kütüphanelerin log seviyesini düşür (Çok fazla çıktı vermemesi için)
logging.getLogger("elasticsearch").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_db_connection():
    """PostgreSQL bağlantısı döner."""
    return psycopg2.connect(**DB_CONFIG)


def build_variation_update_script(master_id: str, new_name: str, country: str) -> dict:
    """
    ES'teki mevcut kayda yeni varyasyon ve stripped halini eklemek için bulk update script'i.
    """
    new_stripped = stripped_form(new_name, country)

    return {
        "_op_type": "update",
        "_index": ES_INDEX,
        "_id": master_id,
        "script": {
            "source": """
                if (!ctx._source.variations.contains(params.new_name)) {
                    ctx._source.variations.add(params.new_name);
                }
                if (params.new_stripped != null && params.new_stripped != "" && !ctx._source.variations_stripped.contains(params.new_stripped)) {
                    ctx._source.variations_stripped.add(params.new_stripped);
                }
            """,
            "params": {"new_name": new_name, "new_stripped": new_stripped},
        },
    }


def build_new_master_doc(
    master_id: str,
    name_orig: str,
    name_latin: str,
    country: str,
    tax_number: str = "",
    phone_number: str = "",
) -> dict:
    """Yeni master kayıt dokümanı oluşturur."""
    variations = [name_orig]
    # Latinize hali farklıysa onu da ekle
    if name_latin and name_latin != name_orig:
        variations.append(name_latin)

    # Stripped formları hesapla
    variations_stripped = list(
        set(filter(None, [stripped_form(v, country) for v in variations]))
    )

    doc = {
        "_index": ES_INDEX,
        "_id": master_id,
        "_source": {
            "master_id": master_id,
            "variations": variations,
            "variations_stripped": variations_stripped,
            "country_code": country,
        },
    }
    if tax_number:
        doc["_source"]["tax_number"] = tax_number
    if phone_number:
        doc["_source"]["phone_number"] = phone_number
    return doc


def validate_db_schema(conn):
    """
    Config dosyasındaki tablo ve sütun ayarlarının
    veritabanı ile uyumlu olup olmadığını kontrol eder.
    """
    cursor = conn.cursor()

    # 1. Tablo var mı?
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = %s
        );
        """,
        (RAW_TABLE_NAME,),
    )
    if not cursor.fetchone()[0]:
        raise RuntimeError(
            f"HATA: '{RAW_TABLE_NAME}' tablosu veritabanında bulunamadı!"
        )

    # 2. Sütunlar var mı?
    cursor.execute(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = %s;
        """,
        (RAW_TABLE_NAME,),
    )
    existing_columns = {row[0] for row in cursor.fetchall()}

    missing_columns = []

    # Zorunlu okuma sütunlarını kontrol et
    for internal_name in MANDATORY_READ_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col:
            raise RuntimeError(
                f"Konfigürasyon Hatası: '{internal_name}' için COLUMN_MAPPING kaydı yok!"
            )
        if db_col not in existing_columns:
            missing_columns.append(f"{db_col} (iç ad: {internal_name})")

    # Zorunlu güncelleme sütunlarını kontrol et
    missing_update_columns = []
    for internal_name in MANDATORY_UPDATE_COLUMNS:
        db_col = COLUMN_MAPPING.get(internal_name)
        if not db_col:
            raise RuntimeError(
                f"Konfigürasyon Hatası: '{internal_name}' için COLUMN_MAPPING kaydı yok!"
            )
        if db_col not in existing_columns:
            missing_update_columns.append((internal_name, db_col))

    if missing_update_columns:
        if AUTO_CREATE_UPDATE_COLUMNS:
            logger.warning(
                f"Uyarı: '{RAW_TABLE_NAME}' tablosunda şu güncelleme sütunları eksik: {[x[1] for x in missing_update_columns]}"
            )
            logger.info(
                "AUTO_CREATE_UPDATE_COLUMNS=True olduğu için sütunlar oluşturuluyor..."
            )

            for internal_name, db_col in missing_update_columns:
                # Veri tipini belirle
                if internal_name == "master_code":
                    col_type = "VARCHAR(50)"
                elif internal_name == "match_score":
                    col_type = "INTEGER"
                elif internal_name == "match_type":
                    col_type = "VARCHAR(20)"
                else:
                    col_type = "TEXT"  # Varsayılan

                logger.info(f"  -> Sütun ekleniyor: {db_col} ({col_type})")
                try:
                    cursor.execute(
                        f"ALTER TABLE {RAW_TABLE_NAME} ADD COLUMN {db_col} {col_type};"
                    )
                    # Değişikliği hemen commit et (DDL transactional olabilir ama emin olmak için)
                    conn.commit()
                except Exception as e:
                    conn.rollback()  # Hata durumunda rollback
                    raise RuntimeError(f"Sütun oluşturma hatası ({db_col}): {e}")

            logger.info("Sütunlar başarıyla oluşturuldu.")
        else:
            # Otomatik oluşturma kapalıysa hata fırlat
            missing_cols_str = [x[1] for x in missing_update_columns]
            raise RuntimeError(
                f"HATA: '{RAW_TABLE_NAME}' tablosunda şu zorunlu güncelleme sütunları eksik: {missing_cols_str}\n"
                f"Ayarlardan AUTO_CREATE_UPDATE_COLUMNS = True yaparak otomatik oluşturulmasını sağlayabilirsiniz."
            )

    cursor.close()
    logger.info(
        f"Schema doğrulama başarılı: Tablo '{RAW_TABLE_NAME}' ve zorunlu sütunlar mevcut."
    )


def ensure_audit_table(conn):
    """
    match_audit tablosunu oluşturur (yoksa).

    Eşleşti ama reddedilen karar logları:
    - input_id, input_name:    Gelen kayıt
    - rejected_candidate:      ES'in önerdiği ama biz reddettiğimiz isim
    - rejected_score:          O anki fuzzy/backstop skoru
    - rejection_reason:        Neden reddedildi (LOW_BACKSTOP_SCORE vs)
    - final_action:            Ne açıldı (NEW_MASTER)
    - created_at:              Zaman damgası
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS match_audit (
            id             SERIAL PRIMARY KEY,
            input_id       INTEGER,
            input_name     TEXT,
            country_code   VARCHAR(10),
            rejected_candidate TEXT,
            rejected_score INTEGER,
            rejection_reason   VARCHAR(50),
            final_action       VARCHAR(20) DEFAULT 'NEW_MASTER',
            created_at         TIMESTAMP DEFAULT NOW()
        );
        """
    )
    conn.commit()
    cursor.close()
    logger.info("Audit tablosu (match_audit) hazır.")


def process_all_data():
    """
    Ana işlem döngüsü.

    Akış:
    1. PostgreSQL'den master_code'u NULL olan kayıtları batch olarak oku.
    2. Her kayıt için find_best_match() çağır.
    3. Yeni kayıtları ES'e ekle, mevcut kayıtlara yeni varyasyon öğret.
    4. Sonuçları PostgreSQL'e yaz.
    """
    es = get_es_client()

    # Index'in var olduğundan emin ol (yoksa oluşturur)
    logger.info("Elasticsearch index kontrol ediliyor...")
    create_index(es)

    logger.info("Elasticsearch index kontrol ediliyor...")
    create_index(es)

    logger.info("Veritabanına bağlanılıyor (Okuma ve Yazma için ayrı bağlantılar)...")
    read_conn = get_db_connection()
    write_conn = get_db_connection()

    try:
        # Şema doğrulama (Herhangi bir bağlantı ile yapılabilir)
        validate_db_schema(read_conn)
        ensure_audit_table(write_conn)

        # Okuma cursor'ı (Named cursor - Server side)
        read_cursor = read_conn.cursor(
            name="matching_cursor", cursor_factory=DictCursor
        )

        # Yazma cursor'ı (Normal cursor)
        write_cursor = write_conn.cursor()

        # Dinamik SELECT sorgusu oluşturma
        # İhtiyacımız olanlar: id, company_name, country, tax, phone
        # Bunların DB'deki karşılıklarını mapping'den alıyoruz.
        col_id = COLUMN_MAPPING["id"]
        col_name = COLUMN_MAPPING["company_name"]
        col_country = COLUMN_MAPPING["country_code"]
        col_tax = COLUMN_MAPPING.get("tax_number")
        col_phone = COLUMN_MAPPING.get("phone_number")
        col_master = COLUMN_MAPPING["master_code"]
        col_match_type = COLUMN_MAPPING["match_type"]

        # Select listesini oluştur
        select_cols = [col_id, col_name, col_country]
        if col_tax:
            select_cols.append(col_tax)
        if col_phone:
            select_cols.append(col_phone)

        select_str = ", ".join(select_cols)

        read_cursor.execute(
            f"""
            SELECT {select_str}
            FROM {RAW_TABLE_NAME}
            WHERE {col_master} IS NULL
            ORDER BY {col_id}
            """
        )

        logger.info("İşlem döngüsü başlıyor...")
        batch_num = 0

        while True:
            logger.info(
                f"Batch #{batch_num + 1} verisi okunuyor (Limit: {BATCH_SIZE})..."
            )
            rows = read_cursor.fetchmany(BATCH_SIZE)
            if not rows:
                logger.info("İşlenecek veri kalmadı.")
                break

            batch_num += 1
            logger.info(
                f"Batch #{batch_num}: {len(rows)} kayıt okundu. Eşleştirme yapılıyor..."
            )
            sql_updates = []
            new_es_docs = []
            es_variation_updates = []
            audit_logs = []  # Reddedilen eşleşme logları

            for row in rows:
                # DictCursor olduğu için sütun isimleriyle erişebiliriz (DB'deki isimlerle)
                row_id = row[col_id]
                raw_name = row[col_name]
                country = row[col_country] or "DEFAULT"

                tax = row.get(col_tax, "") if col_tax else ""
                phone = row.get(col_phone, "") if col_phone else ""

                # ── Eşleştirme ──
                result = find_best_match(
                    es=es,
                    raw_name=raw_name,
                    country=country,
                    tax_number=tax or "",
                    phone_number=phone or "",
                )

                master_id = result["master_id"]
                score = result["score"]
                match_type = result["match_type"]
                name_orig = result["name_orig"]

                if result["is_new"]:
                    # ── Yeni Master -> ES'e ekle ──
                    name_latin = latinize(name_orig)
                    new_es_docs.append(
                        build_new_master_doc(
                            master_id=master_id,
                            name_orig=name_orig,
                            name_latin=name_latin,
                            country=country,
                            tax_number=tax or "",
                            phone_number=phone or "",
                        )
                    )
                else:
                    # ── Mevcut eşleşme, skor %100 değilse varyasyon öğret ──
                    if score < 100 and name_orig:
                        es_variation_updates.append(
                            build_variation_update_script(master_id, name_orig, country)
                        )

                # PostgreSQL güncelleme listesine ekle
                sql_updates.append((master_id, int(score), match_type, row_id))

                # Reddedilen eşleşme varsa audit'e yaz
                if result.get("rejected_candidate"):
                    audit_logs.append(
                        (
                            row_id,
                            raw_name,
                            country,
                            result["rejected_candidate"],
                            result["rejected_score"],
                            result["rejection_reason"],
                            match_type,
                        )
                    )

            # ── YAZMA İŞLEMLERİ ──

            # 1. Yeni kayıtları ES'e ekle
            if new_es_docs:
                helpers.bulk(es, new_es_docs, raise_on_error=True)

            # 2. Mevcut kayıtlara yeni varyasyonları öğret
            if es_variation_updates:
                helpers.bulk(es, es_variation_updates, raise_on_error=False)

            # 3. Refresh: Yeni eklenenler hemen aranabilir olsun
            if new_es_docs or es_variation_updates:
                es.indices.refresh(index=ES_INDEX)

            # 4. PostgreSQL güncellemesi
            if sql_updates:
                # Dinamik UPDATE sorgusu
                # Güncellenecek sütunlar: master_code, match_score, match_type
                col_score = COLUMN_MAPPING["match_score"]
                col_type_db = COLUMN_MAPPING["match_type"]

                execute_values(
                    write_cursor,
                    f"""
                    UPDATE {RAW_TABLE_NAME} AS t
                    SET {col_master} = d.master_code,
                        {col_score} = d.match_score,
                        {col_type_db} = d.match_type
                    FROM (VALUES %s) AS d(master_code, match_score, match_type, id)
                    WHERE t.{col_id} = d.id
                    """,
                    sql_updates,
                )
                write_conn.commit()

            # 5. Audit log yazımı (Reddedilen eşleşmeler)
            if audit_logs:
                execute_values(
                    write_cursor,
                    """
                    INSERT INTO match_audit 
                        (input_id, input_name, country_code, rejected_candidate, 
                         rejected_score, rejection_reason, final_action)
                    VALUES %s
                    """,
                    audit_logs,
                )
                write_conn.commit()
                logger.info(
                    f"  -> {len(audit_logs)} reddedilmiş eşleşme audit tablosuna yazıldı."
                )

            stats_new = len(new_es_docs)
            stats_learned = len(es_variation_updates)
            stats_total = len(sql_updates)
            logger.info(
                f"Batch #{batch_num} Tamamlandı: "
                f"{stats_total} kayıt işlendi, "
                f"{stats_new} yeni firma, "
                f"{stats_learned} varyasyon öğrenildi."
                f"{len(audit_logs)} reddedilmiş eşleşme audit tablosuna yazıldı."
            )

        read_cursor.close()
        write_cursor.close()
        logger.info("Tüm veriler başarıyla işlendi ve kaydedildi.")

    except Exception as e:
        # İki bağlantıyı da rollback yapalım
        if "read_conn" in locals() and read_conn:
            read_conn.rollback()
        if "write_conn" in locals() and write_conn:
            write_conn.rollback()

        logger.error(f"BEKLENMEYEN HATA: {e}", exc_info=True)
        raise
    finally:
        if "read_conn" in locals() and read_conn:
            read_conn.close()
        if "write_conn" in locals() and write_conn:
            write_conn.close()
        logger.info("Veritabanı bağlantıları kapatıldı.")


# ============================================================================
# Doğrudan çalıştırılabilir: python main_processor.py
# ============================================================================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Firma Eşleştirme Sistemi başlatılıyor...")
    logger.info("=" * 60)
    process_all_data()
