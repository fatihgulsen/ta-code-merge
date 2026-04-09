# ============================================================================
# es_manager.py - Elasticsearch Index Yönetimi (v3)
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
#
# v3 Eklemeler:
#   - Country routing (_routing.required = true)
#   - ICU analyzer (icu_tokenizer + icu_folding) → variations.unidecode
#   - Fingerprint analyzer → variations.fingerprint
#   - N-gram analyzer (3-4) → variations.ngram
#   - Phonetic analyzer (double_metaphone) → variations.phonetic
# ============================================================================

import logging

from elasticsearch import Elasticsearch

from config import ES_HOST, ES_INDEX
from synonym_loader import get_all_country_codes, load_synonyms_for_country

logger = logging.getLogger(__name__)


def get_es_client() -> Elasticsearch:
    """Elasticsearch client döner.

    request_timeout: Varsayılan 10s, synonym-heavy index create için 120s.
    """
    return Elasticsearch(ES_HOST, request_timeout=120)


def _check_plugin_installed(es: Elasticsearch, plugin_name: str) -> bool:
    """ES cluster'da belirtli plugin'in kurulu olup olmadığını kontrol eder."""
    try:
        plugins = es.cat.plugins(format="json")
        installed = {p["component"] for p in plugins}
        return plugin_name in installed
    except Exception:
        return False


def build_index_settings(es: Elasticsearch | None = None) -> dict:
    """
    Index ayarlarını (per-country synonym filter + analyzer + mapping) oluşturur.

    ── Analyzer Stratejisi ─────────────────────────────────────────────────────
    clean_analyzer_common   : ortak synonym (common + countries + other)
                                → Index-time default analyzer
                                → Ülke dosyası olmayan ülkeler için search-time
    clean_analyzer_{CC}     : ülkeye özgü + ortak
                                → Search-time, country_code bilindiğinde kullanılır

    v3 Ek Analyzer'lar:
    icu_analyzer            : ICU tokenizer + folding (latinize)
    fingerprint             : built-in (token sort + dedup)
    ngram_analyzer          : trigram tokenization (index-time fuzzy)
    ngram_search_analyzer   : standard tokenizer (search-time for ngram field)
    phonetic_analyzer       : double_metaphone (fonetik benzerlik)
    ───────────────────────────────────────────────────────────────────────────
    """
    filters = {}
    analyzers = {}
    tokenizers = {}

    # ── Plugin kontrolü ──
    has_icu = _check_plugin_installed(es, "analysis-icu") if es else False
    has_phonetic = _check_plugin_installed(es, "analysis-phonetic") if es else False

    if not has_icu:
        logger.warning(
            "analysis-icu plugin kurulu degil. ICU analyzer devre disi. "
            "Kurmak icin: elasticsearch-plugin install analysis-icu"
        )
    if not has_phonetic:
        logger.warning(
            "analysis-phonetic plugin kurulu degil. Phonetic analyzer devre disi. "
            "Kurmak icin: elasticsearch-plugin install analysis-phonetic"
        )

    # ── Ortak (common) filter ve analyzer ──
    common_synonyms = list(load_synonyms_for_country("__common__"))
    filters["synonym_filter_common"] = {
        "type": "synonym_graph",
        "synonyms": common_synonyms,
        "lenient": True,
    }
    analyzers["clean_analyzer_common"] = {
        "tokenizer": "standard",
        "filter": ["lowercase", "synonym_filter_common"],
    }

    # ── Stripped Search Analyzer (variations_stripped sorgu zamanı için) ──
    # Generic company suffix'lerini stopword olarak kaldırır.
    # variations_stripped alanının search_analyzer'ı olarak kullanılır.
    common_generic_tokens = [
        "ltd", "limited", "inc", "incorporated", "corp", "corporation",
        "llc", "gmbh", "ag", "sa", "srl", "bv", "nv", "plc", "co",
        "company", "pty", "pvt", "private", "public", "holding",
        "holdings", "group", "international", "intl", "and",
        "the", "of", "a", "an",
    ]
    filters["generic_stopwords"] = {
        "type": "stop",
        "stopwords": common_generic_tokens,
    }
    analyzers["stripped_search_analyzer"] = {
        "tokenizer": "standard",
        "filter": ["lowercase", "generic_stopwords"],
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

    # ── ICU Analyzer (plugin varsa) ──
    if has_icu:
        analyzers["icu_analyzer"] = {
            "tokenizer": "icu_tokenizer",
            "filter": ["icu_normalizer", "icu_folding", "lowercase"],
        }

    # ── N-gram Analyzer (index-time fuzzy) ──
    tokenizers["ngram_tokenizer"] = {
        "type": "ngram",
        "min_gram": 3,
        "max_gram": 4,
        "token_chars": ["letter", "digit"],
    }
    analyzers["ngram_analyzer"] = {
        "tokenizer": "ngram_tokenizer",
        "filter": ["lowercase"],
    }
    analyzers["ngram_search_analyzer"] = {
        "tokenizer": "standard",
        "filter": ["lowercase"],
    }

    # ── Phonetic Analyzer (plugin varsa) ──
    if has_phonetic:
        filters["phonetic_filter"] = {
            "type": "phonetic",
            "encoder": "double_metaphone",
            "replace": False,
        }
        analyzers["phonetic_analyzer"] = {
            "tokenizer": "standard",
            "filter": ["lowercase", "phonetic_filter"],
        }

    # ── Mapping: variations subfield'ları ──
    variations_fields = {
        # Tam eşleşme kontrolü (synonym uygulanmaz)
        "keyword": {"type": "keyword", "ignore_above": 512},
        # Fingerprint: token sort + dedup (sırasız eşleşme)
        "fingerprint": {
            "type": "text",
            "analyzer": "fingerprint",
        },
        # N-gram: index-time fuzzy matching
        "ngram": {
            "type": "text",
            "analyzer": "ngram_analyzer",
            "search_analyzer": "ngram_search_analyzer",
        },
    }

    # ICU varsa → icu_analyzer, yoksa → standard (fallback)
    variations_fields["unidecode"] = {
        "type": "text",
        "analyzer": "icu_analyzer" if has_icu else "standard",
    }

    # Phonetic varsa ekle
    if has_phonetic:
        variations_fields["phonetic"] = {
            "type": "text",
            "analyzer": "phonetic_analyzer",
        }

    settings = {
        "settings": {
            "number_of_shards": 5,
            "number_of_replicas": 0,
            "index.max_ngram_diff": 1,
            "analysis": {
                "tokenizer": tokenizers,
                "filter": filters,
                "analyzer": analyzers,
            },
        },
        "mappings": {
            # Country routing: shard-level country isolation
            "_routing": {"required": True},
            "properties": {
                "master_id": {"type": "keyword"},
                "country_code": {"type": "keyword"},
                "tax_number": {"type": "keyword"},
                "phone_number": {"type": "keyword"},
                "variations": {
                    "type": "text",
                    "analyzer": "clean_analyzer_common",
                    "fields": variations_fields,
                },
                "variations_stripped": {
                    "type": "text",
                    "analyzer": "standard",
                    "search_analyzer": "stripped_search_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                        "ngram": {
                            "type": "text",
                            "analyzer": "ngram_analyzer",
                            "search_analyzer": "ngram_search_analyzer",
                        },
                    },
                },
            },
        },
    }

    return settings


def create_index(es: Elasticsearch, force_recreate: bool = False) -> None:
    """
    ES index'ini oluşturur.
    force_recreate=True ise mevcut index silinip yeniden oluşturulur.
    """
    if es.indices.exists(index=ES_INDEX):
        if force_recreate:
            es.indices.delete(index=ES_INDEX, ignore=[404])
            # ES'in delete'i tamamlamasini bekle
            import time
            for _ in range(30):
                if not es.indices.exists(index=ES_INDEX):
                    break
                time.sleep(1)
            print(f"Index '{ES_INDEX}' silindi.")
        else:
            print(f"Index '{ES_INDEX}' zaten mevcut. Atlanıyor.")
            return

    settings = build_index_settings(es)

    cc_count = len(get_all_country_codes())
    print(f"{cc_count} ulke icin per-country analyzer olusturuluyor...")

    es.options(request_timeout=120).indices.create(index=ES_INDEX, body=settings)

    features = ["synonym", "fingerprint", "ngram"]
    if _check_plugin_installed(es, "analysis-icu"):
        features.append("ICU")
    if _check_plugin_installed(es, "analysis-phonetic"):
        features.append("phonetic")

    print(
        f"Index '{ES_INDEX}' olusturuldu: "
        f"{cc_count} ulke analyzer, routing=country_code, "
        f"ozellikler: {', '.join(features)}"
    )


# ============================================================================
# Doğrudan çalıştırılabilir: python es_manager.py [--force]
# ============================================================================
if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    es = get_es_client()
    create_index(es, force_recreate=force)
