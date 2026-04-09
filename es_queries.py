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

import re
from synonym_loader import get_all_country_codes

_KNOWN_COUNTRY_CODES = None


def _get_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"clean_analyzer_{cc}"
    return "clean_analyzer_common"


def _get_stripped_analyzer(country: str) -> str:
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"stripped_search_analyzer_{cc.lower()}"
    return "stripped_search_analyzer"


def _normalize_tax(tax: str) -> str:
    return re.sub(r"[^\w]", "", tax).upper()


def TAX_EXACT(name: str, country: str, tax_number: str = "", **kwargs) -> dict:
    """
    Vergi no birebir eşleşme — deterministik.
    tax_number boşsa bu stage atlanır (main_processor tarafından skip edilir).
    """
    return {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"tax_number": _normalize_tax(tax_number)}},
                    {"term": {"country_code": country.upper()}},
                ]
            }
        },
        "size": 1,
    }


def CANONICAL_EXACT(name: str, country: str, **kwargs) -> dict:
    """
    Synonym-aware canonical form tam phrase eşleşmesi.
    Ülkeye özel analyzer arama zamanında canonical form üretir.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def STRIPPED_EXACT(name: str, country: str, **kwargs) -> dict:
    """
    Suffix temizlenmiş tam phrase eşleşmesi.
    variations_stripped alanı ingest pipeline tarafından doldurulur.
    Sorgu search_analyzer ile query-time'da da stripped forma dönüştürülür.
    """
    analyzer = _get_stripped_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations_stripped": {
                                "query": name,
                                "analyzer": analyzer,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
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
                        "match": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                                "operator": "and",
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
    Kelime sırası toleranslı phrase eşleşmesi (slop=3).
    Aynı kelimeler ama farklı sırada veya araya kelime girmiş durumları yakalar.
    """
    analyzer = _get_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "variations": {
                                "query": name,
                                "analyzer": analyzer,
                                "slop": 3,
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
    variations_stripped.ngram alani kullanilir, boylece "dye chem pvt ltd"
    gibi suffix token'lari ngram skorunu artifak olarak yukseltmez.
    """
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "variations_stripped.ngram": {
                                "query": name,
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }
