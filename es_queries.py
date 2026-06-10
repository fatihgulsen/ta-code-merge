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
from core_name import normalize_core
from config import (
    PHONETIC_MIN_CORE_TOKENS,
    NGRAM_MIN_CORE_TOKENS,
    ENABLE_CORE_GATE,
    MATCH_CORE_MIN_TOKEN_LEN,
    MATCH_CORE_FUZZY_REQUIRE_ALPHA,
    ENABLE_CORE_COVERAGE_GATE,
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
    global _KNOWN_COUNTRY_CODES
    if _KNOWN_COUNTRY_CODES is None:
        _KNOWN_COUNTRY_CODES = get_all_country_codes()
    cc = country.upper()
    if cc in _KNOWN_COUNTRY_CODES:
        return f"stripped_search_analyzer_{cc.lower()}"
    return "stripped_search_analyzer"


# Token-count memoization (perf): analyzer index'e sabit olduğundan bir koşu boyunca
# (analyzer, text) → token sayısı DEĞİŞMEZ. Tekrarlı isimlerde es.indices.analyze
# round-trip'lerini eler. Hata sonuçları CACHE'LENMEZ (zehirlenmeyi önler). Bellek için
# basit cap (dolunca yeni anahtar eklenmez; mevcutlar yine hızlı döner).
_TOKEN_COUNT_CACHE: dict[tuple[str, str], int] = {}
_TOKEN_COUNT_CACHE_MAX = 200_000

# Ayırt-edici çekirdek GATE cache'i (perf): (analyzer, name, require_alpha) → bool.
# Token-count cache ile aynı gerekçe (analyzer bir koşu boyunca sabit). Hatalar cache'lenmez.
_DISTINCTIVE_CORE_CACHE: dict[tuple[str, str, bool], bool] = {}


def clear_token_count_cache() -> None:
    """Token-count + çekirdek-gate cache'lerini temizler (test izolasyonu / reindex sonrası)."""
    _TOKEN_COUNT_CACHE.clear()
    _DISTINCTIVE_CORE_CACHE.clear()


def _has_distinctive_core(es: Elasticsearch, name: str, country: str, require_alpha: bool) -> bool:
    """İsim, ES STRIPPED analyzer çıktısında AYIRT EDİCİ bir çekirdek taşıyor mu?

    Ayırt edici = en az bir token uzunluğu >= MATCH_CORE_MIN_TOKEN_LEN (require_alpha ise
    ayrıca alfabetik — salt-sayı değil). Karar %100 ES analyzer çıktısından gelir (gerçek
    index analyzer'ı; acronym_glue dahil) → Python fuzzy/normalize YOK, reindex sonrası
    tutarlı. Bu bir GUARD'dır (stage çalışsın mı), eşleşme DOĞRULAMASI değil.

    es yoksa (ör. unit test) veya gate kapalıysa True döner (guard devre dışı). _analyze
    hatasında True döner (mevcut davranışı bozma) ve CACHE'LENMEZ."""
    if not ENABLE_CORE_GATE or es is None or not name:
        return True
    analyzer = _get_stripped_analyzer(country)
    key = (analyzer, name, require_alpha)
    cached = _DISTINCTIVE_CORE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from config import ES_INDEX
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": analyzer, "text": name})
        tokens = [t.get("token", "") for t in res.get("tokens", [])]
    except Exception:
        return True  # analyzer erişilemiyor → guard'ı atla (cache'leme)
    result = any(
        len(tok) >= MATCH_CORE_MIN_TOKEN_LEN and (not require_alpha or any(c.isalpha() for c in tok))
        for tok in tokens
    )
    if len(_DISTINCTIVE_CORE_CACHE) < _TOKEN_COUNT_CACHE_MAX:
        _DISTINCTIVE_CORE_CACHE[key] = result
    return result


def _get_token_count(es: Elasticsearch, text: str, analyzer: str) -> int:
    """Elasticsearch _analyze API kullanarak metnin kaç token ürettiğini hesaplar.
    (analyzer, text) anahtarıyla memoize edilir; hatalar cache'lenmez."""
    if not es or not text:
        return 0
    key = (analyzer, text)
    cached = _TOKEN_COUNT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        # Circular import önlemek için local import
        from config import ES_INDEX
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": analyzer, "text": text})
        count = len(res.get("tokens", []))
    except Exception:
        # Hata durumunda (index henüz oluşmamış vb.) 0 döner, CACHE'LENMEZ → sonra tekrar denenir.
        return 0
    if len(_TOKEN_COUNT_CACHE) < _TOKEN_COUNT_CACHE_MAX:
        _TOKEN_COUNT_CACHE[key] = count
    return count


def _core_coverage_filter(es: Elasticsearch, name: str, country: str) -> list:
    """Çözüm A (Round-4): ES-side ayırt-edici-çekirdek COVERAGE filtresi (loose stage'ler için).

    Eşleşen master, sorgunun STRIPPED ayırt-edici çekirdek token SAYISINA eşit bir
    variations_stripped varyantı taşımak ZORUNDA → kısa/kesik isim (SPM ⊂ SPM FLOW CONTROL)
    farklı core-count taşıdığı için master'a giremez (subset/truncation over-merge ES'de elenir).

    STRIPPED analyzer kullanılır (synonym YOK) — clean_analyzer token_count eşitliği Round-3'te
    recall'ı kırıp geri alınmıştı. Karar ES analyzer çıktısından (_get_token_count); Python fuzzy/
    doğrulama YOK. es yoksa veya sayı 0 ise (çekirdeksiz) filtre eklenmez (graceful).

    NOT (analyzer hizası): sayı, indekslenen alanın (variations_stripped.name.token_count,
    es_manager: "stripped_search_analyzer" GLOBAL) analyzer'ıyla TUTARLI olmak için global
    stripped analyzer ile hesaplanır (ülke-özel değil). 100% MX veride ikisi aynı token sayısını
    üretir; global kullanmak çok-ülkeli durumda da stored count ile birebir eşleşmeyi garantiler.

    NOT (korelasyon): bu, `variations` eşleşmesinden AYRI bir nested clause'tur — guard/defans
    amaçlıdır (subset/truncation seed'i master'a girmesin). Tek-firma master'larında varyant
    çekirdekleri aynı sayıda kümelendiğinden ve gate kısa-isim sızıntısını zaten engellediğinden
    (kendini-pekiştiren), bir master'ın alâkasız kısa varyantı üzerinden sayıyı sağlaması ikincil
    bir durumdur; STRIPPED_EXACT'in birebir token_count'u + fingerprint dedup bunu tamamlar."""
    if not ENABLE_CORE_COVERAGE_GATE or es is None:
        return []
    count = _get_token_count(es, name, "stripped_search_analyzer")
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
    """
    Synonym-aware canonical form tam phrase eşleşmesi.
    Ülkeye özel analyzer arama zamanında canonical form üretir.
    Nested structure ve token_count filtresi ile 1-1 birebir (identity) eşleşme zorlanır.

    GATE (#3): ayırt edici çekirdek yoksa (tek-harf akronim artığı) eşleşmez → NEW_MASTER.
    STRIPPED_EXACT ile simetrik (require_alpha=False → salt-sayı exact dedup korunur).
    """
    if not _has_distinctive_core(es, name, country, require_alpha=False):
        return MATCH_NONE
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

    GATE (#3): ayırt edici çekirdek yoksa (tek-harf akronim artığı 'M S.A.'→'m') eşleşmez →
    NEW_MASTER. Tam eşleşme güvenli olduğundan salt-sayı çekirdek (require_alpha=False) korunur.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=False):
        return MATCH_NONE
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


def SUFFIX_FUZZY(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """
    Suffix fuzzy eşleştirme:
      - must: variations_stripped'a match_phrase (Ana isim tam eslesmeli)
      - should: variations_suffix'e fuzziness AUTO:4,7 (suffix typo'larını yakalar)

    GATE (#3): ayırt edici alfabetik çekirdek yoksa eşleşmez → NEW_MASTER.
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
    """
    Tüm anlamlı token'ların presence kontrolü (operator:and).
    Kelime sırası önemsiz, tüm token'lar bulunmalı.

    GATE (#3): en düşük-precision stage. Ayırt edici alfabetik çekirdek yoksa ('#N/A 300'
    → salt-sayı; 'I.I.Q' → tek-harf) eşleşmez → NEW_MASTER. Hata sınıfı B (çöp sızma) kapanır.
    """
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE
    analyzer = _get_analyzer(country)
    # NOT (#4): token_count EŞİTLİĞİ burada DENENDİ ve GERİ ALINDI — clean_analyzer
    # synonym_graph genişlemesi sorgu-zamanı sayısını indeks-zamanı sayısıyla tutarsız
    # kılıyor → live_probe recall 8/10→4/10 düştü (WITTE/VIBRACOUSTIC gibi gerçek varyantlar
    # bloklandı). ALCATEL ⊂ ALCATEL LUCENT subset over-merge'i bunun yerine config.STAGES
    # min_score kalibrasyonu (rematch sonrası) + ileride çekirdek-coverage ile ele alınmalı.
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
    """
    Kelime sırası toleranslı phrase eşleşmesi (slop=1).
    Aynı kelimeler ama farklı sırada veya araya kelime girmiş durumları yakalar.

    GATE (#3): hata hacmi en yüksek stage. Ayırt edici alfabetik çekirdek yoksa eşleşmez →
    NEW_MASTER (çöp/akronim seed engeli). Farklı-marka birleşmeleri (C sınıfı) için ayrıca
    config.STAGES min_score yükseltilmeli (rematch ile kalibre).
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
    """
    Trigram index-time fuzzy eslesmesi — suffix'ler cikarilmis form uzerinden.
    minimum_should_match: "75%" eklenerek hatalı kısa eşleşmeler önlenir.
    Ülkeye özel analyzer arama zamanında ngram field'ı işlemek için kullanılır.

    Guard (Faz 3, PHONETIC ile tutarlı): ayırt edici çekirdek BOŞ ise (yalnızca
    yasal ek / ülke adı / çöp) trigram'lar paylaşılan suffix parçaları üzerinden
    farklı firmaları birleştirir → sentinel ile bloklanır. Asıl precision'ı
    stage-bağımsız coverage post-verify (main_processor) sağlar; bu guard yalnızca
    çöp/magnet sızıntısını keser. min_score (config.STAGES) rematch ile kalibre edilir.
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
    """
    Sestese dayalı (phonetic) eşleşme — sadece ana isim üzerinden.
    Double Metaphone algoritması ile suffix gürültüsü olmadan eşleşir.

    Coverage (over-merge) güvencesi TAMAMEN ES TARAFINDADIR (Python doğrulaması YOK):
    nested query'ye bir token_count filtresi eklenir — kazanan dokümanın stripped
    token sayısı sorgununkiyle EŞİT olmalı. Böylece subset over-merge'i (ALCATEL ⊂
    ALCATEL-LUCENT: 5 ≠ 6 token) ES eler; tipo varyantları (MANAGMENT ↔ MANAGEMENT,
    aynı token sayısı) korunur. Bu, CANONICAL_EXACT/STRIPPED_EXACT'in token_count
    deseninin aynısıdır.
    """
    # Guard yalnızca AYIRT EDİCİ çekirdek token sayısı eşiğin ALTINDA ise bloklar.
    # drop_geo=True: yasal ekler + ülke-adı/coğrafi token'lar ('mexico') çekirdek
    # dışıdır → yalnızca-suffix / yalnızca-ülke-adı / çöp isimler (0 token) bloklanır.
    # Gerçek tek-marka firmalar (IGSA, AUDI MEXICO, VIBRACOUSTIC) ELENMEZ: fonetik
    # alandan yasal-ek parçaları temizlendiğinden (es_manager legal_fragment_stop)
    # farklı markalar operator:and altında zaten eşleşmez. Canlı doğrulama:
    # analysis/live_probe.py.
    core = normalize_core(name, country, drop_geo=True)
    if len(core) < PHONETIC_MIN_CORE_TOKENS:
        return MATCH_NONE
    expected_count = _get_token_count(es, name, _get_stripped_analyzer(country))
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
