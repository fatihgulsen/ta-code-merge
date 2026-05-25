# ============================================================================
# es_queries.py - Stage Sorgu Fonksiyonları
# ============================================================================
# Her fonksiyon bir ES query body döner.
# Fonksiyon adı config.STAGES[*]["query_fn"] ile birebir eşleşmeli.
#
# Stage eklemek için:
#   1. Bu dosyaya yeni fonksiyon ekle (aynı imza: name, country, **kwargs)
#   2. config.STAGES listesine yeni dict ekle (query_fn = fonksiyon adı)
# ============================================================================

import logging
import re
from elasticsearch import Elasticsearch
from synonym_loader import get_all_country_codes

logger = logging.getLogger(__name__)

_KNOWN_COUNTRY_CODES = None
_WARNED_COUNTRIES: set[str] = set()


def _get_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"clean_analyzer_{cc}"
    if cc not in _WARNED_COUNTRIES:
        _WARNED_COUNTRIES.add(cc)
        logger.warning(
            "Ulke '%s' icin ozgul analyzer bulunamadi (synonym dosyasi eksik). "
            "clean_analyzer_common kullaniliyor.",
            cc,
        )
    return "clean_analyzer_common"


def _get_stripped_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"stripped_search_analyzer_{cc.lower()}"
    return "stripped_search_analyzer"


def _get_token_count(es: Elasticsearch, text: str, analyzer: str) -> int:
    """Elasticsearch _analyze API kullanarak metnin kaç token ürettiğini hesaplar."""
    if not es or not text:
        return 0
    try:
        # Circular import önlemek için local import
        from config import ES_INDEX
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": analyzer, "text": text})
        return len(res.get("tokens", []))
    except Exception:
        # Hata durumunda (index henüz oluşmamış vb.) 0 döner, match engellenmez (faydalı değil ama güvenli)
        return 0


def CANONICAL_EXACT(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """
    Synonym-aware canonical form tam phrase eşleşmesi.
    Ülkeye özel analyzer arama zamanında canonical form üretir.
    Nested structure ve token_count filtresi ile 1-1 birebir (identity) eşleşme zorlanır.
    """
    analyzer = _get_analyzer(country)
    expected_count = _get_token_count(es, name, analyzer)

    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations",
                            "query": {
                                "bool": {
                                    "must": [
                                        {
                                            "match_phrase": {
                                                "variations.name": {
                                                    "query": name,
                                                    "analyzer": analyzer,
                                                }
                                            }
                                        }
                                    ],
                                    "filter": [
                                        {"term": {"variations.token_count": expected_count}}
                                    ]
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def STRIPPED_EXACT(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """
    Suffix temizlenmiş tam phrase eşleşmesi.
    variations_stripped alanı ingest pipeline tarafından doldurulur.
    Nested structure ve token_count filtresi ile 1-1 birebir (identity) eşleşme zorlanır.
    """
    analyzer = _get_stripped_analyzer(country)
    expected_count = _get_token_count(es, name, analyzer)

    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "bool": {
                                    "must": [
                                        {
                                            "match_phrase": {
                                                "variations_stripped.name": {
                                                    "query": name,
                                                    "analyzer": analyzer,
                                                }
                                            }
                                        }
                                    ],
                                    "filter": (
                                        [{"term": {"variations_stripped.name.token_count": expected_count}}]
                                        if expected_count > 0 else []
                                    )
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def SUFFIX_FUZZY(name: str, country: str, **kwargs) -> dict:
    """
    Suffix fuzzy eşleştirme:
      - must: variations_stripped'a match_phrase (Ana isim tam eslesmeli)
      - should: variations_suffix'e fuzziness AUTO:4,7 (suffix typo'larını yakalar)
    """
    analyzer = _get_stripped_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "match_phrase": {
                                    "variations_stripped.name": {
                                        "query": name,
                                        "analyzer": analyzer,
                                    }
                                }
                            }
                        }
                    }
                ],
                "should": [
                    {
                        "match": {
                            "variations_suffix": {
                                "query": name,
                                "fuzziness": "AUTO:4,7",
                                "operator": "or",
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
                "minimum_should_match": 1,
            }
        },
        "size": 1,
    }


def TOKEN_COVERAGE(name: str, country: str, **kwargs) -> dict:
    """
    Tüm anlamlı token'ların presence kontrolü (operator:and).
    Kelime sırası önemsiz, tüm token'lar bulunmalı.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations",
                            "query": {
                                "match": {
                                    "variations.name": {
                                        "query": name,
                                        "analyzer": analyzer,
                                        "operator": "and",
                                    }
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def FUZZY_PHRASE(name: str, country: str, **kwargs) -> dict:
    """
    Kelime sırası toleranslı phrase eşleşmesi (slop=1).
    Aynı kelimeler ama farklı sırada veya araya kelime girmiş durumları yakalar.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations",
                            "query": {
                                "match_phrase": {
                                    "variations.name": {
                                        "query": name,
                                        "analyzer": analyzer,
                                        "slop": 1,
                                    }
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def NGRAM_MATCH(name: str, country: str, **kwargs) -> dict:
    """
    Trigram index-time fuzzy eslesmesi — suffix'ler cikarilmis form uzerinden.
    minimum_should_match: "75%" eklenerek hatalı kısa eşleşmeler önlenir.
    Ülkeye özel analyzer arama zamanında ngram field'ı işlemek için kullanılır.
    """
    analyzer = _get_stripped_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "match": {
                                    "variations_stripped.name.ngram": {
                                        "query": name,
                                        "analyzer": analyzer,
                                        "minimum_should_match": "75%",
                                    }
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def PHONETIC_MATCH(name: str, country: str, **kwargs) -> dict:
    """
    Sestese dayalı (phonetic) eşleşme — sadece ana isim üzerinden.
    Double Metaphone algoritması ile suffix gürültüsü olmadan eşleşir.
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "match": {
                                    "variations_stripped.name.phonetic": {
                                        "query": name,
                                        "operator": "and",
                                    }
                                }
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }
