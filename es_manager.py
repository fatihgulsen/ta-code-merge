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
from synonym_loader import (
    get_all_company_type_tokens,
    get_all_country_codes,
    get_all_legal_suffix_fragments,
    get_article_stopwords,
    get_company_type_tokens,
    get_country_name_tokens,
    load_synonyms_for_country,
)

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

    filters["arabic_norm"] = {"type": "arabic_normalization"}

    char_filters = {
        # ── Akronim-glue (Round-3, docs/audit/2026-06-05-round3-unicode-config-dedup.md) ──
        # Noktayı YALNIZCA iki tek-harf arasında siler (acronym): 'C.M.S.A.D.C' → 'CMSADC',
        # 'B.A.T' → 'BAT'. punctuation_remover'dan ÖNCE çalışır. Aksi halde nokta→boşluk
        # akronimi tek harflere bölüyor, legal_fragment_stop tek-harf yasal-ek parçalarını
        # (a b c d e f h i l p r s u v y) atınca geriye tek "junk" harf kalıp ('m'/'g'/'t')
        # alakasız firmaları aynı fingerprint'te topluyordu (STRIPPED_EXACT magnet).
        # REGRESYON YOK: akronim-biçimli yasal ekler (S.A.P.I.→sapi) zaten fragment set'inde
        # (≤4 harf) → strip'lenmeye devam eder. Boşlukla ayrılmış tek-harf markalar
        # ('M S.A.') glue'dan ETKİLENMEZ; onlar DEDUP_MIN=2 + token_count çekirdek-gate ile
        # eşleşme-zamanında engellenir. REINDEX (es_manager.py --force) GEREKTİRİR.
        # Lookbehind-SIZ (Java/JVM-portable): tek-harf + nokta + (sonrası harf) → harf.
        # `\b(\p{L})\.` yalnız KELİME-BAŞI tek harfi yakalar → 'WORD.WORD'/'ACME.INC' GLUE'lanmaz
        # ('MARCA REGISTRADA' ayrı kalır); yalnız akronim segmentleri ('C.M.', 'U.S.') birleşir.
        "acronym_glue": {
            "type": "pattern_replace",
            "pattern": r"\b(\p{L})\.(?=\p{L})",
            "replacement": "$1",
        },
        "punctuation_remover": {
            "type": "pattern_replace",
            "pattern": "[.,]+",
            "replacement": " ",
        },
    }

    base_clean_filters = []
    if has_icu:
        base_clean_filters.extend(
            ["icu_normalizer", "icu_folding", "lowercase", "arabic_norm"]
        )
    else:
        base_clean_filters.extend(["lowercase", "arabic_norm"])

    # ── Yasal-ek parça stop filtresi (tüm ülke legal_suffixes JSON'larından türetilir) ──
    # 'S.A. DE C.V.' gibi dotlu yasal ekler punctuation_remover ile s/a/c/v tek
    # harflerine bölünür. Bu parçaları HEM stripped HEM phonetic analyzer'da düşürmek:
    #   1) fonetik gürültüyü (yaygın metaphone S,A,T,K,F) keser (over-merge),
    #   2) arama-zamanı tokenizasyonunu ingest stripped TEXT'iyle TUTARLI kılar —
    #      böylece token_count filtreleri (STRIPPED_EXACT + PHONETIC coverage) dotlu
    #      suffix'lerde doğru çalışır (analyzer↔ingest uyumsuzluğu giderilir).
    filters["legal_fragment_stop"] = {
        "type": "stop",
        "stopwords": sorted(get_all_legal_suffix_fragments()),
    }

    # ── Ortak (common) filter ve analyzer ──
    common_synonyms = list(load_synonyms_for_country("__common__"))
    filters["synonym_filter_common"] = {
        "type": "synonym_graph",
        "synonyms": common_synonyms,
        "lenient": True,
    }
    analyzers["clean_analyzer_common"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters + ["synonym_filter_common"],
    }

    # ── Per-country Stripped Search Analyzer ──
    # Her ülke için common + ülke company_types tokenlarından stopword filter.
    # variations_stripped alanının search_analyzer'ı olarak kullanılır.
    for cc in get_all_country_codes():
        cc_tokens = list(get_company_type_tokens(cc))
        article_tokens = list(get_article_stopwords(cc))
        filter_name = f"generic_stopwords_{cc.lower()}"
        analyzer_name = f"stripped_search_analyzer_{cc.lower()}"
        filters[filter_name] = {
            "type": "stop",
            "stopwords": cc_tokens + article_tokens,
        }
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            "filter": base_clean_filters + [filter_name, "legal_fragment_stop"],
        }

    # Global fallback stripped analyzer (tüm ülkeler birleşimi)
    global_tokens = list(get_all_company_type_tokens())
    global_articles = list(get_article_stopwords("common"))
    filters["generic_stopwords_global"] = {
        "type": "stop",
        "stopwords": global_tokens + global_articles,
    }
    analyzers["stripped_search_analyzer"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters + ["generic_stopwords_global", "legal_fragment_stop"],
    }

    # ── Geo/ülke-adı stop filtresi (tüm ülke countries.json'larından TÜRETİLİR) ──
    # MX: 'mexico', 'mexicana' vb. Coğrafi token'lar ayırt edici DEĞİL; fingerprint
    # dedup'unda 'BRAND DE MEXICO' ile 'BRAND'in aynı parmak izine inmesini sağlar
    # (docs/audit/2026-06-03 §3.3, recall kaybının %27'si geo token farkından).
    geo_tokens_global = sorted(
        set().union(*(set(get_country_name_tokens(cc)) for cc in get_all_country_codes()))
    ) if get_all_country_codes() else []
    filters["geo_stopwords_global"] = {
        "type": "stop",
        "stopwords": geo_tokens_global,
    }

    # ── Fingerprint (sort + dedup) filtresi + güçlendirilmiş fingerprint_analyzer ──
    # Built-in 'fingerprint' analyzer yasal-ek/geo normalize ETMEZ; bu özel analyzer
    # stripped_search_analyzer ile aynı normalizasyonu (jenerik + yasal-ek + geo stop)
    # uygular, ardından token'ları sıralayıp tekilleştirir → kanonik parmak izi.
    # ES Transform (es_transform.py) bununla aynı-firma master'larını gruplar (Option-2).
    filters["fingerprint_token_filter"] = {
        "type": "fingerprint",
    }
    analyzers["fingerprint_analyzer"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters
        + [
            "generic_stopwords_global",
            "legal_fragment_stop",
            "geo_stopwords_global",
            "fingerprint_token_filter",
        ],
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
            "char_filter": ["acronym_glue", "punctuation_remover"],
            "filter": base_clean_filters + [filter_name],
        }

    # ── ICU Analyzer (plugin varsa) ──
    if has_icu:
        analyzers["icu_analyzer"] = {
            "tokenizer": "icu_tokenizer",
            "char_filter": ["acronym_glue", "punctuation_remover"],
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
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters,
    }
    analyzers["ngram_search_analyzer"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters,
    }

    # ── Phonetic Analyzer (plugin varsa) ──
    if has_phonetic:
        filters["phonetic_filter"] = {
            "type": "phonetic",
            "encoder": "double_metaphone",
            "replace": False,
        }
        # phonetic_analyzer da legal_fragment_stop kullanır (yukarıda koşulsuz tanımlı):
        # yasal-ek parçaları metaphone'a girmeden elenir → over-merge gürültüsü kesilir.
        analyzers["phonetic_analyzer"] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            # legal_fragment_stop, phonetic_filter'dan ÖNCE: yasal-ek parçaları
            # metaphone'a girmeden eler (index + arama tarafında tutarlı).
            "filter": ["lowercase", "legal_fragment_stop", "phonetic_filter"],
        }

    # ── Mapping: variations subfield'ları ──
    variations_fields = {
        # Tam eşleşme kontrolü (synonym uygulanmaz)
        "keyword": {"type": "keyword", "ignore_above": 512},
        # Token Count: Birebir (1-1) eşleşme kontrolü için kelime sayısı.
        # enable_position_increments=False: stop filtresiyle ELENEN token'ların
        # bıraktığı pozisyon boşlukları sayıma DAHİL EDİLMEZ → indeks sayımı,
        # _analyze API'sinin (gerçek token sayısı) sonucuyla TUTARLI olur.
        "token_count": {
            "type": "token_count",
            "analyzer": "clean_analyzer_common",
            "enable_position_increments": False,
        },
        # Fingerprint: token sort + dedup (sırasız eşleşme).
        # Özel fingerprint_analyzer: jenerik + yasal-ek + geo stop → sort/dedup.
        # Built-in 'fingerprint' yerine; aynı-firma varyantları (suffix/geo/word-order)
        # tek kanonik parmak izine iner → ES Transform / dedup_auto_merge (Option-2).
        # fielddata=True: dedup terms/composite aggregation için zorunlu. Analyzer TEK
        # token (birleşik fingerprint) ürettiğinden alan başına kardinalite düşük →
        # fielddata maliyeti sınırlı. (Daha ucuz alternatif: ingest'te keyword fingerprint.)
        "fingerprint": {
            "type": "text",
            "analyzer": "fingerprint_analyzer",
            "fielddata": True,
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

    # Stripped fields:
    stripped_fields = {
        "keyword": {"type": "keyword", "ignore_above": 512},
        # Token Count: Suffix'ler atıldıktan sonraki kelime sayısı.
        # enable_position_increments=False: legal_fragment_stop ile elenen parçaların
        # pozisyon boşlukları sayılmaz → _analyze ile tutarlı (dotlu S.A. DE C.V. dahil).
        "token_count": {
            "type": "token_count",
            "analyzer": "stripped_search_analyzer",
            "enable_position_increments": False,
        },
        "ngram": {
            "type": "text",
            "analyzer": "ngram_analyzer",
            "search_analyzer": "ngram_search_analyzer",
        },
    }
    if has_phonetic:
        stripped_fields["phonetic"] = {
            "type": "text",
            "analyzer": "phonetic_analyzer",
        }

    settings = {
        "settings": {
            "number_of_shards": 5,
            "number_of_replicas": 0,
            "index.max_ngram_diff": 1,
            "analysis": {
                "char_filter": char_filters,
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
                "phone_number": {"type": "keyword"},
                "address": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                    },
                },
                "variations": {
                    "type": "nested",
                    "properties": {
                        "name": {
                            "type": "text",
                            "analyzer": "clean_analyzer_common",
                            "fields": variations_fields,
                        }
                    }
                },
                "variations_stripped": {
                    "type": "nested",
                    "properties": {
                        "name": {
                            "type": "text",
                            "analyzer": "standard",
                            "search_analyzer": "stripped_search_analyzer",
                            "fields": stripped_fields,
                        }
                    }
                },
                "variations_suffix": {
                    "type": "text",
                    "analyzer": "standard",
                    "search_analyzer": "standard",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 512},
                    },
                },
            },
        },
    }

    return settings


def acronym_glue_active(es: Elasticsearch) -> bool | None:
    """Canlı ES index'inin analyzer zincirinde acronym_glue ETKİN mi? (reindex doğrulaması)

    'K.W.M' = hepsi yasal-OLMAYAN tek harf. acronym_glue varsa tek token 'kwm' üretir;
    eski (glue'suz) zincir nokta→boşluk bölüp 3 token ([k,w,m]) üretir. Distinctive-core
    GATE canlı analyzer'a güvendiğinden, rematch ESKİ index'e karşı koşarsa gate akronim
    isimleri yanlışlıkla bloklar (under-merge).

    Dönüş: True = glue etkin ('kwm'); False = KESİN eski şema (>1 token); None = belirsiz
    (boş/hata/tek-farklı token) → çağıran yalnız KESİN False'ta abort etmeli."""
    try:
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": "fingerprint_analyzer", "text": "K.W.M"})
        tokens = [t["token"] for t in res.get("tokens", [])]
    except Exception:
        return None
    if tokens == ["kwm"]:
        return True
    if len(tokens) > 1:
        return False  # nokta→boşluk bölmüş → glue YOK (kesin eski)
    return None  # boş / tek-farklı → belirsiz (bozma)


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

    # Analyzer tanımı değişti (örn. acronym_glue) → es_queries token_count + çekirdek-gate
    # cache'leri ESKİ analyzer sonuçlarını taşıyor olabilir (anahtar analyzer ADI, tanımı
    # değil). Reindex sonrası bayat sonuçları (özellikle gate'in yanlış MATCH_NONE'u) temizle.
    try:
        from es_queries import clear_token_count_cache
        clear_token_count_cache()
    except Exception:
        logger.warning("es_queries cache temizlenemedi (import?) — reindex sonrası süreç yeniden başlatılmalı")

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
