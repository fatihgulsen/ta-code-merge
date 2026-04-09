# ============================================================================
# es_transform.py - ES Transform ile Sürekli Duplicate Detection
# ============================================================================
# Fingerprint + country_code bazlı continuous transform.
# Aynı fingerprint'e sahip birden fazla master_id'yi tespit eder
# ve potential_duplicates index'ine yazar.
# ============================================================================

import logging

from elasticsearch import Elasticsearch

from config import ES_INDEX

logger = logging.getLogger(__name__)

TRANSFORM_ID = "company_dedup_detector"
DEST_INDEX = "potential_duplicates"


def create_dedup_transform(es: Elasticsearch) -> None:
    """
    Continuous transform oluşturur: aynı fingerprint + country'ye sahip
    birden fazla master kaydı tespit eder.
    """
    # Önce destination index'i oluştur (yoksa)
    if not es.indices.exists(index=DEST_INDEX):
        es.indices.create(
            index=DEST_INDEX,
            body={
                "mappings": {
                    "properties": {
                        "fingerprint": {"type": "keyword"},
                        "country_code": {"type": "keyword"},
                        "master_ids": {"type": "keyword"},
                        "master_count": {"type": "integer"},
                        "sample_names": {"type": "text"},
                        "detected_at": {"type": "date"},
                    }
                }
            },
        )
        logger.info(f"Destination index '{DEST_INDEX}' olusturuldu.")

    transform_body = {
        "source": {
            "index": [ES_INDEX],
        },
        "dest": {
            "index": DEST_INDEX,
        },
        "pivot": {
            "group_by": {
                "fingerprint": {
                    "terms": {
                        "field": "variations.fingerprint",
                    }
                },
                "country_code": {
                    "terms": {
                        "field": "country_code",
                    }
                },
            },
            "aggregations": {
                "master_ids": {
                    "terms": {
                        "field": "master_id",
                        "size": 50,
                    }
                },
                "master_count": {
                    "cardinality": {
                        "field": "master_id",
                    }
                },
                "sample_names": {
                    "terms": {
                        "field": "variations.keyword",
                        "size": 5,
                    }
                },
            },
        },
        "description": "Ayni fingerprint + country altinda birden fazla master_id tespit eder",
        "frequency": "5m",
        "sync": {
            "time": {
                "field": "detected_at",
                "delay": "60s",
            }
        },
    }

    # Transform varsa sil ve yeniden oluştur
    try:
        es.transform.get_transform(transform_id=TRANSFORM_ID)
        es.transform.stop_transform(transform_id=TRANSFORM_ID, wait_for_completion=True)
        es.transform.delete_transform(transform_id=TRANSFORM_ID)
        logger.info(f"Mevcut transform '{TRANSFORM_ID}' silindi.")
    except Exception:
        pass

    es.transform.put_transform(transform_id=TRANSFORM_ID, body=transform_body)
    logger.info(f"Transform '{TRANSFORM_ID}' olusturuldu.")


def start_dedup_transform(es: Elasticsearch) -> None:
    """Transform'u başlatır."""
    es.transform.start_transform(transform_id=TRANSFORM_ID)
    logger.info(f"Transform '{TRANSFORM_ID}' baslatildi.")


def stop_dedup_transform(es: Elasticsearch) -> None:
    """Transform'u durdurur."""
    es.transform.stop_transform(transform_id=TRANSFORM_ID, wait_for_completion=True)
    logger.info(f"Transform '{TRANSFORM_ID}' durduruldu.")


def get_potential_duplicates(es: Elasticsearch, min_count: int = 2, size: int = 100) -> list[dict]:
    """
    Potansiyel duplicate'ları listeler.

    Args:
        min_count: Minimum master_id sayısı (2 = en az 2 farklı master)
        size:      Döndürülecek max kayıt sayısı

    Returns:
        Duplicate aday listesi
    """
    res = es.search(
        index=DEST_INDEX,
        body={
            "query": {
                "range": {
                    "master_count": {"gte": min_count}
                }
            },
            "sort": [{"master_count": "desc"}],
            "size": size,
        },
    )

    results = []
    for hit in res["hits"]["hits"]:
        src = hit["_source"]
        results.append({
            "fingerprint": src.get("fingerprint"),
            "country_code": src.get("country_code"),
            "master_count": src.get("master_count"),
            "master_ids": src.get("master_ids", []),
            "sample_names": src.get("sample_names", []),
        })

    return results


# ============================================================================
if __name__ == "__main__":
    from es_manager import get_es_client

    es = get_es_client()
    create_dedup_transform(es)
    start_dedup_transform(es)
    print(f"Transform '{TRANSFORM_ID}' olusturuldu ve baslatildi.")
