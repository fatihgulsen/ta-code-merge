"""Her stage için Elasticsearch Query DSL üretici fonksiyonları.

Her fonksiyon bir ES query body döner ve adı config.STAGES[*]["query_fn"] ile birebir eşleşir.
Stage eklemek için: (1) bu dosyaya aynı imzada (name, country, **kwargs) fonksiyon ekle,
(2) config.STAGES listesine ilgili dict'i ekle.
"""

import logging
from elasticsearch import Elasticsearch
from core.synonym_loader import get_all_country_codes, get_business_sector_tokens, get_address_tokens
from core.core_name import normalize_core
from config import (
    PHONETIC_MIN_CORE_TOKENS,
    NGRAM_MIN_CORE_TOKENS,
    ENABLE_CORE_GATE,
    ENABLE_GENERIC_CORE_GATE,
    MATCH_CORE_MIN_TOKEN_LEN,
    MATCH_CORE_FUZZY_REQUIRE_ALPHA,
    ENABLE_CORE_COVERAGE_GATE,
    ENABLE_DIRTY_DATA,
)

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
    """Ülkeye özel stripped analyzer adını döner; bilinmeyen ülkede global fallback kullanılır."""
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"stripped_search_analyzer_{cc.lower()}"
    return "stripped_search_analyzer"


# Perf: (analyzer, text) → token sayısı bir koşu boyunca değişmez; tekrarlı ES round-trip'lerini
# önlemek için memoize edilir. Hata sonuçları cache'lenmez (zehirlenmeyi önler).
_TOKEN_COUNT_CACHE: dict[tuple[str, str], int] = {}
_TOKEN_COUNT_CACHE_MAX = 200_000

# Perf: (analyzer, name, require_alpha) → bool; token-count cache ile aynı gerekçe.
_DISTINCTIVE_CORE_CACHE: dict[tuple[str, str, bool], bool] = {}


def _analyze_index(country: str) -> str:
    """`_analyze` çağrıları için hedef index: override varsa o, yoksa ülke alias'ı."""
    from config import ES_ANALYZE_INDEX_OVERRIDE, alias_for_country
    return ES_ANALYZE_INDEX_OVERRIDE or alias_for_country(country)


def clear_token_count_cache() -> None:
    """Token-count + çekirdek-gate cache'lerini temizler (test izolasyonu / reindex sonrası)."""
    _TOKEN_COUNT_CACHE.clear()
    _DISTINCTIVE_CORE_CACHE.clear()


def _has_distinctive_core(es: Elasticsearch, name: str, country: str, require_alpha: bool) -> bool:
    """İsim, ES STRIPPED analyzer çıktısında ayırt edici bir çekirdek taşıyor mu?

    Ayırt edici = en az bir token uzunluğu >= MATCH_CORE_MIN_TOKEN_LEN (require_alpha ise
    ayrıca alfabetik — salt-sayı değil) VE (ENABLE_GENERIC_CORE_GATE ise) o token jenerik
    bir iş/sektör kelimesi DEĞİL (business_sectors). Salt-jenerik çekirdek ('trading',
    'importaciones') alakasız firmaları tek token'a çöküp magnet üretir → ayırt edici sayılmaz.
    Karar %100 ES analyzer çıktısından + JSON business_sectors'tan gelir (hardcode yok,
    ülke-bilinçli). Bu bir GUARD'dır (stage çalışsın mı), eşleşme doğrulaması değil. es yoksa,
    gate kapalıysa veya _analyze hata verirse True döner (mevcut davranışı bozma).

    Args:
        es: Elasticsearch istemcisi (None ise guard devre dışı).
        name: Sorgu firma adı.
        country: Ülke kodu (büyük/küçük harf fark etmez).
        require_alpha: True ise salt-sayı token'lar ayırt edici sayılmaz.

    Returns:
        True → stage çalışabilir; False → MATCH_NONE sentinel döndür.
    """
    if not ENABLE_CORE_GATE or es is None or not name:
        return True
    analyzer = _get_stripped_analyzer(country)
    key = (analyzer, name, require_alpha)
    cached = _DISTINCTIVE_CORE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": name})
        tokens = [t.get("token", "") for t in res.get("tokens", [])]
    except Exception:
        return True  # analyzer erişilemiyor → guard'ı atla (cache'leme)
    # Jenerik-çekirdek gate: salt-jenerik (business_sector) token'lar ayırt edici sayılmaz.
    generic = get_business_sector_tokens(country) if ENABLE_GENERIC_CORE_GATE else frozenset()
    result = any(
        len(tok) >= MATCH_CORE_MIN_TOKEN_LEN
        and (not require_alpha or any(c.isalpha() for c in tok))
        and tok not in generic
        for tok in tokens
    )
    if len(_DISTINCTIVE_CORE_CACHE) < _TOKEN_COUNT_CACHE_MAX:
        _DISTINCTIVE_CORE_CACHE[key] = result
    return result


def is_address_dirty(es: Elasticsearch, name: str, country: str) -> bool:
    """İsim address synonym'i içeriyor AMA address çıkarılınca ayırt edici çekirdek YOK → kirli.

    Tokenizasyon ES STRIPPED analyzer'ından gelir (legal/article/geo sıyrılmış; address +
    sector + marka çekirdekte kalır). Address membership + distinctiveness Python set
    kontrolüdür (fuzzy DEĞİL — input_filter ile aynı boundary sınıfı). es yoksa / gate
    kapalıysa / _analyze hata verirse False (mevcut NEW_MASTER davranışını bozma).

    Args:
        es: Elasticsearch istemcisi (None ise False).
        name: Sorgu firma adı (fonetik-kanonik match_name beklenir).
        country: Ülke kodu.

    Returns:
        True → DIRTY_DATA; False → normal NEW_MASTER yolu.
    """
    if not ENABLE_DIRTY_DATA or es is None or not name:
        return False
    analyzer = _get_stripped_analyzer(country)
    try:
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": name})
        tokens = [t.get("token", "") for t in res.get("tokens", [])]
    except Exception:
        return False
    address = get_address_tokens(country)
    if not any(tok in address for tok in tokens):
        return False
    generic = get_business_sector_tokens(country)
    distinctive = any(
        len(tok) >= MATCH_CORE_MIN_TOKEN_LEN
        and any(c.isalpha() for c in tok)
        and tok not in address
        and tok not in generic
        for tok in tokens
    )
    return not distinctive


def _get_token_count(es: Elasticsearch, text: str, analyzer: str, country: str) -> int:
    """ES _analyze API ile metnin token sayısını döner; (analyzer, text) ile memoize edilir.

    Args:
        es: Elasticsearch istemcisi.
        text: Analiz edilecek metin.
        analyzer: Kullanılacak ES analyzer adı.
        country: Ülke kodu (_analyze hedef index'ini belirler).

    Returns:
        Token sayısı; es/text boşsa veya hata olursa 0 (cache'lenmez).
    """
    if not es or not text:
        return 0
    key = (analyzer, text)
    cached = _TOKEN_COUNT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": text})
        count = len(res.get("tokens", []))
    except Exception:
        # Index henüz oluşmamış vb. → 0 döner, cache'lenmez (sonra tekrar denenir).
        return 0
    if len(_TOKEN_COUNT_CACHE) < _TOKEN_COUNT_CACHE_MAX:
        _TOKEN_COUNT_CACHE[key] = count
    return count


def _core_coverage_filter(es: Elasticsearch, name: str, country: str) -> list:
    """Loose stage'ler için ES-side ayırt-edici-çekirdek coverage filtresi.

    Eşleşen master, sorgunun STRIPPED çekirdek token sayısına eşit bir variations_stripped
    varyantı taşımak zorundadır → kısa/kesik isim (subset over-merge) ES'de elenir.
    STRIPPED analyzer kullanılır (synonym yok); clean_analyzer token_count eşitliği
    synonym_graph genişlemesi nedeniyle indeks/sorgu sayısını tutarsız kıldığından geri alınmıştır
    (bkz. docs/audit/). es yoksa veya count=0 ise filtre eklenmez (graceful).

    Args:
        es: Elasticsearch istemcisi.
        name: Sorgu firma adı.
        country: Ülke kodu.

    Returns:
        Nested must clause listesi (boş olabilir).
    """
    if not ENABLE_CORE_COVERAGE_GATE or es is None:
        return []
    count = _get_token_count(es, name, "stripped_search_analyzer", country)
    if count <= 0:
        return []
    return [{
        "nested": {
            "path": "variations_stripped",
            "query": {"bool": {"filter": [
                {"term": {"variations_stripped.name.token_count": count}}
            ]}},
        }
    }]


# Hiçbir dokümanla eşleşmeyen sentinel query — guard'lar tarafından kullanılır.
MATCH_NONE = {"query": {"bool": {"must_not": [{"match_all": {}}]}}, "size": 0}


def CANONICAL_EXACT(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Synonym-aware canonical form tam phrase eşleşmesi.

    Ülkeye özel analyzer arama zamanında canonical form üretir. Nested yapı ve token_count
    filtresi ile 1-1 birebir (identity) eşleşme zorlanır. GATE: ayırt edici çekirdek yoksa
    (tek-harf akronim artığı) MATCH_NONE döner. require_alpha=False → salt-sayı exact dedup korunur.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate + token_count için).

    Returns:
        ES query body dict.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=False):
        return MATCH_NONE
    analyzer = _get_analyzer(country)
    expected_count = _get_token_count(es, name, analyzer, country)

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
    """Suffix temizlenmiş tam phrase eşleşmesi.

    variations_stripped alanı ingest pipeline tarafından doldurulur. Nested yapı ve token_count
    filtresi ile 1-1 birebir (identity) eşleşme zorlanır. GATE: ayırt edici çekirdek yoksa
    (örn. 'M S.A.' → 'm') MATCH_NONE döner. require_alpha=False → salt-sayı exact dedup korunur.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate + token_count için).

    Returns:
        ES query body dict.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=False):
        return MATCH_NONE
    analyzer = _get_stripped_analyzer(country)
    expected_count = _get_token_count(es, name, analyzer, country)

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


def SUFFIX_FUZZY(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Suffix fuzzy eşleştirme: çekirdek tam, suffix typo toleranslı.

    must: variations_stripped'a match_phrase (ana isim tam eşleşmeli).
    should: variations_suffix'e fuzziness AUTO:4,7 (suffix typo'larını yakalar).
    GATE: ayırt edici alfabetik çekirdek yoksa MATCH_NONE döner.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate için).

    Returns:
        ES query body dict.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE
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


def TOKEN_COVERAGE(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Tüm anlamlı token'ların presence kontrolü (operator:and), kelime sırası önemsiz.

    En düşük-precision stage. GATE: ayırt edici alfabetik çekirdek yoksa ('#N/A 300' → salt-sayı;
    'I.I.Q' → tek-harf) MATCH_NONE döner. Token_count eşitliği bu stage'de synonym_graph
    genişlemesi nedeniyle recall'ı kırdığından uygulanmaz (bkz. docs/audit/); subset over-merge
    _core_coverage_filter (STRIPPED token_count, ES-side) ile engellenir.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate + coverage filtresi için).

    Returns:
        ES query body dict.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE
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
                    },
                    # Çözüm A: ayırt-edici-çekirdek coverage (STRIPPED token_count eşitliği, ES-side)
                    *_core_coverage_filter(es, name, country),
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def FUZZY_PHRASE(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Kelime sırası toleranslı phrase eşleşmesi (slop=1).

    Aynı kelimeler farklı sırada veya araya bir kelime girmiş durumları yakalar.
    GATE: ayırt edici alfabetik çekirdek yoksa MATCH_NONE döner (çöp/akronim seed engeli).
    Subset over-merge _core_coverage_filter ile ES-side engellenir.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate + coverage filtresi için).

    Returns:
        ES query body dict.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE
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
                    },
                    # Çözüm A: ayırt-edici-çekirdek coverage (STRIPPED token_count eşitliği, ES-side)
                    *_core_coverage_filter(es, name, country),
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }


def NGRAM_MATCH(name: str, country: str, **kwargs) -> dict:
    """Trigram index-time fuzzy eşleşmesi — suffix temizlenmiş form üzerinden.

    minimum_should_match "75%" ile hatalı kısa eşleşmeler önlenir. GATE: çekirdek token sayısı
    NGRAM_MIN_CORE_TOKENS'in altındaysa (yalnızca yasal ek / ülke adı / çöp) trigram'lar
    paylaşılan suffix parçaları üzerinden farklı firmaları birleştirebilir → sentinel ile bloklanır.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.

    Returns:
        ES query body dict.
    """
    if len(normalize_core(name, country, drop_geo=True)) < NGRAM_MIN_CORE_TOKENS:
        return MATCH_NONE
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


def PHONETIC_MATCH(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Sese dayalı (Double Metaphone) eşleşme — suffix gürültüsü olmadan.

    Coverage güvencesi tamamen ES tarafındadır: nested query'ye token_count filtresi eklenir →
    kazanan dokümanın stripped token sayısı sorgununkiyle eşit olmalı. Böylece subset over-merge
    (ALCATEL ⊂ ALCATEL-LUCENT: 5≠6 token) ES eler; typo varyantları (aynı token sayısı) korunur.
    GATE: çekirdek token sayısı PHONETIC_MIN_CORE_TOKENS'in altındaysa (yalnızca-suffix /
    yalnızca-ülke-adı / çöp) MATCH_NONE döner; gerçek tek-marka firmalar elenmez çünkü fonetik
    alandan yasal-ek parçaları es_manager'da temizlenir (bkz. docs/audit/).

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (token_count için).

    Returns:
        ES query body dict.
    """
    core = normalize_core(name, country, drop_geo=True)
    if len(core) < PHONETIC_MIN_CORE_TOKENS:
        return MATCH_NONE
    expected_count = _get_token_count(es, name, _get_stripped_analyzer(country), country)
    nested_filter = (
        [{"term": {"variations_stripped.name.token_count": expected_count}}]
        if expected_count > 0 else []
    )
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
                                            "match": {
                                                "variations_stripped.name.phonetic": {
                                                    "query": name,
                                                    "operator": "and",
                                                }
                                            }
                                        }
                                    ],
                                    "filter": nested_filter,
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
