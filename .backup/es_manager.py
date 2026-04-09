# ============================================================================
# es_manager.py - Elasticsearch Index Yönetimi
# ============================================================================
# Index oluşturma, mapping tanımlama, ülke bazlı synonym yönetimi.
#
# Her ülke için ayrı bir analyzer tanımlanır:
#   clean_analyzer_common  → common + countries + other synonymleri
#   clean_analyzer_TR      → TR synonymleri + common + countries + other
#   clean_analyzer_DE      → DE synonymleri + common + countries + other
#   ...
#
# "variations" alanı INDEX-TIME'da clean_analyzer_common ile analiz edilir.
# SEARCH-TIME'da sorguya clean_analyzer_{CC} eklenerek ülkeye özgü expand yapılır.
# ============================================================================

from elasticsearch import Elasticsearch
from config import ES_HOST, ES_INDEX
from synonym_loader import get_all_country_codes, load_synonyms_for_country


def get_es_client() -> Elasticsearch:
    """Elasticsearch client döner.

    request_timeout: Varsayılan 10s, synonym-heavy index create için 120s.
    """
    return Elasticsearch(ES_HOST, request_timeout=120)


def build_index_settings() -> dict:
    """
    Index ayarlarını (per-country synonym filter + analyzer + mapping) oluşturur.

    ── Analyzer Stratejisi ─────────────────────────────────────────────────────
    clean_analyzer_common   : ortak synonym (common + countries + other)
                                → Index-time default analyzer
                                → Ülke dosyası olmayan ülkeler için search-time
    clean_analyzer_{CC}     : ülkeye özgü + ortak
                                → Search-time, country_code bilindiğinde kullanılır
    ───────────────────────────────────────────────────────────────────────────

    Dönüş mapping yapısı:
    - master_id   : keyword  (UUID)
    - country_code: keyword  (HARD FILTER)
    - tax_number  : keyword  (Kesin eşleme)
    - phone_number: keyword  (Destek eşleme)
    - variations  : text     (clean_analyzer_common @ index-time)
        .keyword  : keyword  (Tam eşleşme)
        .unidecode: text     (Latinize arama)
    """
    filters = {}
    analyzers = {}

    # ── Ortak (common) filter ve analyzer ──
    common_synonyms = list(load_synonyms_for_country("__common__"))
    filters["synonym_filter_common"] = {
        "type": "synonym_graph",
        "synonyms": common_synonyms,
        "lenient": True,  # Hatalı kurallarda crash etme
    }
    analyzers["clean_analyzer_common"] = {
        "tokenizer": "standard",
        "filter": ["lowercase", "synonym_filter_common"],
    }

    # ── Ülkeye özgü filter ve analyzer (varsa) ──
    for cc in get_all_country_codes():
        country_synonyms = list(load_synonyms_for_country(cc))
        filter_name = f"synonym_filter_{cc}"
        analyzer_name = f"clean_analyzer_{cc}"

        filters[filter_name] = {
            "type": "synonym_graph",
            "synonyms": country_synonyms,
            "lenient": True,
        }
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "filter": ["lowercase", filter_name],
        }

    return {
        "settings": {
            "number_of_shards": 5,
            "number_of_replicas": 0,
            "analysis": {
                "filter": filters,
                "analyzer": analyzers,
            },
        },
        "mappings": {
            "properties": {
                "master_id": {"type": "keyword"},
                "country_code": {"type": "keyword"},
                "tax_number": {"type": "keyword"},
                "phone_number": {"type": "keyword"},
                "variations": {
                    "type": "text",
                    # Index-time: ortak analyzer (tüm firmalar için tutarlı)
                    "analyzer": "clean_analyzer_common",
                    # Search-time: override edilmez burada, sorgu anında belirlenir
                    "fields": {
                        # Tam eşleşme kontrolü (synonym uygulanmaz)
                        "keyword": {"type": "keyword"},
                        # Latinize edilmiş sorgular için
                        "unidecode": {
                            "type": "text",
                            "analyzer": "standard",
                        },
                    },
                },
                "variations_stripped": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {"keyword": {"type": "keyword"}},
                },
            }
        },
    }


def create_index(es: Elasticsearch, force_recreate: bool = False) -> None:
    """
    ES index'ini oluşturur.
    force_recreate=True ise mevcut index silinip yeniden oluşturulur.
    """
    if es.indices.exists(index=ES_INDEX):
        if force_recreate:
            es.indices.delete(index=ES_INDEX)
            print(f"Index '{ES_INDEX}' silindi.")
        else:
            print(f"Index '{ES_INDEX}' zaten mevcut. Atlanıyor.")
            return

    settings = build_index_settings()

    # Kaç ülke için analyzer oluşturulduğunu raporla
    cc_count = len(get_all_country_codes())
    print(f"{cc_count} ülke için per-country analyzer oluşturuluyor...")

    es.options(request_timeout=120).indices.create(index=ES_INDEX, body=settings)
    print(
        f"Index '{ES_INDEX}' oluşturuldu: "
        f"clean_analyzer_common + {cc_count} ülke analyzer'ı."
    )


# ============================================================================
# Doğrudan çalıştırılabilir: python es_manager.py [--force]
# ============================================================================
if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    es = get_es_client()
    create_index(es, force_recreate=force)
