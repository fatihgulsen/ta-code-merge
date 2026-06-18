"""ES index/mapping/analyzer yönetimi; custom analyzer (fingerprint, clean) ve mapping'leri kurar."""

import logging

from elasticsearch import Elasticsearch

from config import ES_HOST, alias_for_country, index_for_country
from core.synonym_loader import (
    get_all_country_codes,
    get_all_legal_suffix_fragments,
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
                                → Search-time ve token_count, country_code bilindiğinde

    fingerprint_analyzer    : yasal-ek stop → sort/dedup (variations.name.fingerprint
                                multi-field'ı; dedup aggregation için)
    ───────────────────────────────────────────────────────────────────────────
    """
    filters = {}
    analyzers = {}
    tokenizers = {}

    # ── Plugin kontrolü ──
    has_icu = _check_plugin_installed(es, "analysis-icu") if es else False

    if not has_icu:
        logger.warning(
            "analysis-icu plugin kurulu degil. ICU analyzer devre disi. "
            "Kurmak icin: elasticsearch-plugin install analysis-icu"
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
    # harflerine bölünür. Bu parçalar fingerprint_analyzer'da düşürülür:
    #   → kanonik parmak izinde yasal-ek gürültüsü kesilir (over-merge önlenir).
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

    # ── Fingerprint (sort + dedup) filtresi + güçlendirilmiş fingerprint_analyzer ──
    # Built-in 'fingerprint' analyzer yasal-ek normalize ETMEZ; bu özel analyzer
    # yasal-ek stop uygular, ardından token'ları sıralayıp tekilleştirir → kanonik parmak izi.
    # variations.name.fingerprint multi-field'ı olarak çalışır.
    # ES Transform / dedup_auto_merge bununla aynı-firma master'larını gruplar.
    filters["fingerprint_token_filter"] = {
        "type": "fingerprint",
    }
    analyzers["fingerprint_analyzer"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters + ["legal_fragment_stop", "fingerprint_token_filter"],
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

    # ── Mapping: variations subfield'ları ──
    # token_count analyzer: per-country clean analyzer kullanılır → token_count asimetrisi giderilir.
    tc_analyzer = (
        f"clean_analyzer_{country_code.upper()}"
        if country_code and country_code not in ("__common__", "__COMMON__")
        else "clean_analyzer_common"
    )
    variations_fields = {
        # Tam eşleşme kontrolü (synonym uygulanmaz)
        "keyword": {"type": "keyword", "ignore_above": 512},
        # Token Count: Birebir (1-1) eşleşme kontrolü için kelime sayısı.
        # enable_position_increments=False: stop filtresiyle ELENEN token'ların
        # bıraktığı pozisyon boşlukları sayıma DAHİL EDİLMEZ → indeks sayımı,
        # _analyze API'sinin (gerçek token sayısı) sonucuyla TUTARLI olur.
        # Per-country clean analyzer kullanılır → token_count asimetrisi giderilir.
        "token_count": {
            "type": "token_count",
            "analyzer": tc_analyzer,
            "enable_position_increments": False,
        },
        # Fingerprint: yasal-ek stop → token sort/dedup → kanonik parmak izi.
        # Aynı-firma varyantları (suffix/kelime-sırası farkı) tek ize iner → dedup_auto_merge.
        # fielddata=True: aggregation için; analyzer tek token ürettiğinden kardinalite düşük.
        "fingerprint": {
            "type": "text",
            "analyzer": "fingerprint_analyzer",
            "fielddata": True,
        },
    }

    settings = {
        "settings": {
            "number_of_shards": 5,
            "number_of_replicas": 0,
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
    features = ["synonym", "fingerprint"]
    if _check_plugin_installed(es, "analysis-icu"):
        features.append("ICU")
    print(f"{created} index olusturuldu/yenilendi, ozellikler: {', '.join(features)}")


# ============================================================================
# Doğrudan çalıştırılabilir: python -m es.manager [--force]
# ============================================================================
if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    es = get_es_client()
    create_index(es, force_recreate=force)
