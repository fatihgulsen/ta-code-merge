"""Giriş noktası: Firma Eşleştirme orkestrasyonunu başlatır.

Gerçek mantık matching/ paketindedir (db_io, es_writer, pipeline).
"""
import logging
import sys

from matching.pipeline import process_all_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("elasticsearch").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Firma Eşleştirme Sistemi başlatılıyor...")
    logger.info("=" * 60)
    process_all_data()
