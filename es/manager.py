"""ES index/mapping/analyzer yönetimi; custom analyzer (fingerprint, ngram, phonetic, stripped) ve mapping'leri kurar."""

import logging

from elasticsearch import Elasticsearch

from config import ES_HOST, alias_for_country, index_for_country
from core.synonym_loader import (
    get_all_company_type_tokens,
    get_all_country_codes,
    get_all_legal_suffix_fragments,
    get_article_stopwords,
    get_company_type_tokens,
    get_country_geo_stopwords,
    get_geo_stopword_tokens,
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


def build_index_settings(es: Elasticsearch | None = None, country_code: str = "__common__") -> dict:
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
    fingerprint_analyzer    : jenerik + yasal-ek stop → sort/dedup (variations_stripped
                                multi-field'ı; geo per-country İÇERİKTE halledilir)
    stripped_search_analyzer_{cc} : per-country jenerik + yasal-ek + KENDİ geo stop
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
        # Akronim noktalarını siler ('C.M.S.' → 'CMS'), punctuation_remover'dan ÖNCE çalışır.
        # Aksi hâlde nokta→boşluk akronimi parçalıyor; legal_fragment_stop tek harfleri
        # atınca alakasız firmalar aynı fingerprint'e düşüyordu (bkz. docs/audit/2026-06-05-round3-unicode-config-dedup.md).
        # Lookbehind-sız, JVM-portable: `\b(\p{L})\.` yalnız kelime-başı tek harfi yakalar.
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

    # Coğrafi token'lar ('mexico', 'argentina') ayırt edici değil; fingerprint dedup'ta
    # 'BRAND DE MEXICO' ile 'BRAND'ı farklı parmak izine düşürüyordu (bkz. docs/audit/2026-06-03 §3.3).
    # ISO kısa kodları (len<4) marka çakışması riski nedeniyle hariç; kaynak countries.json — hardcode yok.
    # Stripped analyzer döngüsünden ÖNCE tanımlanmalı (forward-ref).
    geo_tokens_global = sorted(get_geo_stopword_tokens())
    filters["geo_stopwords_global"] = {
        "type": "stop",
        "stopwords": geo_tokens_global,
    }

    # ── Verilen ülkenin Stripped Search Analyzer'ı (tek ülke) ──
    # Her ülke için common + ülke company_types tokenlarından stopword filter.
    # variations_stripped alanının search_analyzer'ı olarak kullanılır.
    if country_code and country_code not in ("__common__", "__COMMON__"):
        cc = country_code.upper()
        cc_tokens = list(get_company_type_tokens(cc))
        article_tokens = list(get_article_stopwords(cc))
        filter_name = f"generic_stopwords_{cc.lower()}"
        geo_filter_name = f"geo_stopwords_{cc.lower()}"
        analyzer_name = f"stripped_search_analyzer_{cc.lower()}"
        filters[filter_name] = {"type": "stop", "stopwords": cc_tokens + article_tokens}
        # Per-country geo-stop: YALNIZCA ülkenin KENDİ ad token'ları (brasil/brazil)
        # sıyrılır; başka ülke adları (BR'de 'mexico') o shard'da ayırt edicidir → korunur.
        # country_code HARD FILTER olduğundan kendi ülke adı saf gürültüdür. Index tarafı
        # (ingest stripped_form) aynı per-country listeyi kullanır → simetri korunur.
        filters[geo_filter_name] = {"type": "stop", "stopwords": sorted(get_country_geo_stopwords(cc))}
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            # A1 (per-country): geo_stopwords_{cc} → KENDİ ülke adı çekirdek-dışı (geo-mıknatıs fix)
            "filter": base_clean_filters + [filter_name, "legal_fragment_stop", geo_filter_name],
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
        # A1: geo_stopwords_global → token_count + _has_distinctive_core geo-only'yi boş görür
        "filter": base_clean_filters + ["generic_stopwords_global", "legal_fragment_stop", "geo_stopwords_global"],
    }

    # ── Fingerprint (sort + dedup) filtresi + güçlendirilmiş fingerprint_analyzer ──
    # Built-in 'fingerprint' analyzer yasal-ek normalize ETMEZ; bu özel analyzer jenerik +
    # yasal-ek stop uygular, ardından token'ları sıralayıp tekilleştirir → kanonik parmak izi.
    # variations_stripped.name multi-field'ı olarak çalışır: girdi ZATEN per-country geo
    # (kendi ülke adı) sıyrılmış içeriktir → geo stop burada TEKRAR uygulanmaz; başka ülke
    # adları (BR'de 'mexico') fingerprint'te KORUNUR (per-country dedup izolasyonu).
    # ES Transform / dedup_auto_merge bununla aynı-firma master'larını gruplar (Option-2).
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
            "fingerprint_token_filter",
        ],
    }

    # ── Verilen ülkenin synonym analyzer'ı (tek ülke) ──
    if country_code and country_code not in ("__common__", "__COMMON__"):
        cc = country_code.upper()
        country_synonyms = list(load_synonyms_for_country(cc))
        filter_name = f"synonym_filter_{cc}"
        analyzer_name = f"clean_analyzer_{cc}"
        filters[filter_name] = {"type": "synonym_graph", "synonyms": country_synonyms, "lenient": True}
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
        # Fingerprint: jenerik + yasal-ek stop → token sort/dedup → kanonik parmak izi.
        # variations_stripped üzerinde tanımlı: girdi ZATEN per-country geo (kendi ülke adı)
        # sıyrılmış → fingerprint per-country izole olur (başka ülke adları korunur).
        # Aynı-firma varyantları (suffix/kelime-sırası farkı) tek ize iner → dedup_auto_merge.
        # fielddata=True: aggregation için; analyzer tek token ürettiğinden kardinalite düşük.
        "fingerprint": {
            "type": "text",
            "analyzer": "fingerprint_analyzer",
            "fielddata": True,
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
            # NOT: _routing kaldırıldı — per-country index'te ülke izolasyonu fiziksel.
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


def acronym_glue_active(es: Elasticsearch, country_code: str | None = None) -> bool | None:
    """Canlı index analyzer zincirinde acronym_glue ETKİN mi? (reindex doğrulaması)

    country_code verilmezse ilk bilinen ülke alias'ı kullanılır (şema tüm
    per-country index'lerde aynıdır). Dönüş: True/False/None (bkz. eski docstring).

    'K.W.M' = hepsi yasal-OLMAYAN tek harf. acronym_glue varsa tek token 'kwm' üretir;
    eski (glue'suz) zincir nokta→boşluk bölüp 3 token ([k,w,m]) üretir. Distinctive-core
    GATE canlı analyzer'a güvendiğinden, rematch ESKİ index'e karşı koşarsa gate akronim
    isimleri yanlışlıkla bloklar (under-merge).

    Dönüş: True = glue etkin ('kwm'); False = KESİN eski şema (>1 token); None = belirsiz
    (boş/hata/tek-farklı token) → çağıran yalnız KESİN False'ta abort etmeli."""
    if country_code is None:
        codes = get_all_country_codes()
        if not codes:
            return None
        country_code = codes[0]
    target = alias_for_country(country_code)
    try:
        res = es.indices.analyze(index=target, body={"analyzer": "fingerprint_analyzer", "text": "K.W.M"})
        tokens = [t["token"] for t in res.get("tokens", [])]
    except Exception:
        return None
    if tokens == ["kwm"]:
        return True
    if len(tokens) > 1:
        return False  # nokta→boşluk bölmüş → glue YOK (kesin eski)
    return None  # boş / tek-farklı → belirsiz (bozma)


def _create_country_index(es: Elasticsearch, cc: str, force_recreate: bool) -> None:
    """Tek ülke için fiziksel index + alias oluşturur."""
    physical = index_for_country(cc)
    alias = alias_for_country(cc)
    if es.indices.exists(index=physical):
        if force_recreate:
            es.indices.delete(index=physical, ignore=[404])
            import time
            for _ in range(30):
                if not es.indices.exists(index=physical):
                    break
                time.sleep(1)
        else:
            return
    settings = build_index_settings(es, country_code=cc)
    settings["aliases"] = {alias: {}}
    es.options(request_timeout=120).indices.create(index=physical, body=settings)


def create_index(es: Elasticsearch, force_recreate: bool = False) -> None:
    """Tüm ülkeler için per-country fiziksel index + alias oluşturur."""
    codes = get_all_country_codes()
    print(f"{len(codes)} ulke icin per-country index olusturuluyor...")
    created = 0
    for cc in codes:
        before = es.indices.exists(index=index_for_country(cc))
        _create_country_index(es, cc, force_recreate)
        if force_recreate or not before:
            created += 1
    # Analyzer tanımı değişti (örn. acronym_glue) → es_queries token_count + çekirdek-gate
    # cache'leri ESKİ analyzer sonuçlarını taşıyor olabilir (anahtar analyzer ADI, tanımı
    # değil). Reindex sonrası bayat sonuçları (özellikle gate'in yanlış MATCH_NONE'u) temizle.
    try:
        from es.queries import clear_token_count_cache
        clear_token_count_cache()
    except Exception:
        logger.warning("es_queries cache temizlenemedi — surec yeniden baslatilmali")
    features = ["synonym", "fingerprint", "ngram"]
    if _check_plugin_installed(es, "analysis-icu"):
        features.append("ICU")
    if _check_plugin_installed(es, "analysis-phonetic"):
        features.append("phonetic")
    print(f"{created} index olusturuldu/yenilendi, ozellikler: {', '.join(features)}")


# ============================================================================
# Doğrudan çalıştırılabilir: python -m es.manager [--force]
# ============================================================================
if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    es = get_es_client()
    create_index(es, force_recreate=force)
