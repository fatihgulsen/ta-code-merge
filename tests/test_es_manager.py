# ============================================================================
# tests/test_es_manager.py - es_manager per-country analyzer testleri
# ============================================================================

from core.synonym_loader import get_all_country_codes


def test_no_hardcoded_generic_tokens():
    """es_manager.py'da hardcoded common_generic_tokens olmamalı."""
    import es.manager as es_manager
    # Module-level sabit olmamalı
    assert not hasattr(es_manager, "common_generic_tokens")


def test_es_manager_imports_cleanly():
    """es_manager.py import hatası vermemeli."""
    import es.manager as es_manager  # ImportError olmamalı
    assert True


def test_phonetic_analyzer_wires_fragment_stop_before_metaphone():
    """phonetic_analyzer mevcutsa: legal_fragment_stop, phonetic_filter'dan ÖNCE gelmeli.

    phonetic_analyzer yalnızca analysis-phonetic plugin'i kuruluysa üretilir; es=None
    ile (test ortamı) üretilmez. Plugin yoksa bu davranış doğrulanamaz → skip."""
    import pytest
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    if "phonetic_analyzer" not in analyzers:
        pytest.skip("analysis-phonetic plugin yok; phonetic_analyzer üretilmedi")
    filters = settings["settings"]["analysis"]["filter"]
    assert "legal_fragment_stop" in filters
    chain = analyzers["phonetic_analyzer"]["filter"]
    assert "legal_fragment_stop" in chain and "phonetic_filter" in chain
    assert chain.index("legal_fragment_stop") < chain.index("phonetic_filter")


def test_stripped_search_analyzer_global_fallback_exists():
    """build_index_settings(es, cc) global stripped_search_analyzer üretmeli."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]
    assert "stripped_search_analyzer" in analyzers
    assert "generic_stopwords_global" in filters


def test_only_target_country_analyzer_built():
    """Tek-ülke settings YALNIZCA o ülkenin clean_analyzer'ını içermeli (65x sismez)."""
    from es.manager import build_index_settings
    from core.synonym_loader import get_all_country_codes
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    assert "clean_analyzer_TR" in analyzers
    assert "clean_analyzer_common" in analyzers  # default + token_count
    others = [c for c in get_all_country_codes() if c != "TR"][:3]
    for cc in others:
        assert f"clean_analyzer_{cc}" not in analyzers


def test_routing_not_required_in_mapping():
    """Per-country index'te _routing required OLMAMALI."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    assert "_routing" not in settings["mappings"]


def test_build_index_settings_includes_articles_in_stop_filter():
    """Per-country stop filter article token'larını içermeli."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    filters = settings["settings"]["analysis"]["filter"]

    # TR için stop filter kontrol et
    tr_filter = filters.get("generic_stopwords_tr")
    assert tr_filter is not None
    stopwords = tr_filter["stopwords"]
    assert "and" in stopwords
    assert "of" in stopwords
    assert "the" in stopwords


def test_build_index_settings_global_filter_includes_articles():
    """Global fallback stop filter da article token'larını içermeli."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    filters = settings["settings"]["analysis"]["filter"]
    global_filter = filters.get("generic_stopwords_global")
    assert global_filter is not None
    assert "and" in global_filter["stopwords"]
    assert "von" in global_filter["stopwords"]


def test_stripped_analyzers_include_geo_stop():
    """A1 (geo-mıknatıs fix): geo-stop hem global hem per-country stripped_search_analyzer
    zincirine eklenmeli. Aksi halde 'SAL ARGENTINA' → ['argentina'] tek-geo-token mıknatısı
    oluşur. Per-country analyzer KENDİ ülke geo filtresini (geo_stopwords_{cc}) kullanır;
    global fallback geo_stopwords_global. Token listesi countries.json'dan türetilir."""
    from es.manager import build_index_settings
    # Global stripped analyzer (fallback) global geo-stop içermeli — TR settings ile test
    settings_tr = build_index_settings(es=None, country_code="TR")
    analyzers_tr = settings_tr["settings"]["analysis"]["analyzer"]
    assert "geo_stopwords_global" in analyzers_tr["stripped_search_analyzer"]["filter"], \
        "global stripped_search_analyzer geo_stopwords_global içermeli"
    # Per-country stripped analyzer KENDİ geo filtresini (geo_stopwords_{cc}) içermeli
    test_codes = [c.upper() for c in [c.lower() for c in get_all_country_codes()][:3]] + ["AR"]
    for cc_upper in test_codes:
        cc = cc_upper.lower()
        cc_settings = build_index_settings(es=None, country_code=cc_upper)
        cc_analyzers = cc_settings["settings"]["analysis"]["analyzer"]
        chain = cc_analyzers[f"stripped_search_analyzer_{cc}"]["filter"]
        assert f"geo_stopwords_{cc}" in chain, \
            f"stripped_search_analyzer_{cc} per-country geo_stopwords_{cc} içermeli"
        # GLOBAL geo filtresini KULLANMAMALI (başka ülke adları korunmalı)
        assert "geo_stopwords_global" not in chain, \
            f"stripped_search_analyzer_{cc} global geo kullanmamalı (per-country izolasyon)"


def test_per_country_geo_stop_filter_isolates_own_country():
    """Per-country geo-stop filtresi YALNIZCA ülkenin kendi ad token'larını içerir;
    başka ülke adları (BR'de 'mexico') o shard'da ayırt edici → filtreye GİRMEZ."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="BR")
    filters = settings["settings"]["analysis"]["filter"]
    br = filters.get("geo_stopwords_br")
    assert br is not None and br["type"] == "stop", "geo_stopwords_br stop filtresi bulunamadı"
    words = {w.lower() for w in br["stopwords"]}
    assert "brasil" in words or "brazil" in words, "kendi ülke adı geo-stop'ta olmalı"
    assert "mexico" not in words, "başka ülke adı per-country geo-stop'a girmemeli"
    assert "argentina" not in words


def test_fingerprint_analyzer_normalizes_suffix_not_global_geo():
    """Option-2 (per-country): fingerprint_analyzer yasal-ek + jenerik token'ları düşürür,
    sonra fingerprint (sort+dedup) uygular. Geo, içerik seviyesinde (variations_stripped,
    per-country) ele alındığından fingerprint_analyzer'da GLOBAL geo stop UYGULANMAZ —
    böylece başka ülke adları (BR'de 'mexico') fingerprint'te korunur, kendi ülke adı
    zaten stripped içerikte yoktur."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]

    assert "fingerprint_analyzer" in analyzers, "özel fingerprint_analyzer bulunamadı"
    chain = analyzers["fingerprint_analyzer"]["filter"]
    assert "legal_fragment_stop" in chain
    assert "generic_stopwords_global" in chain
    # Global geo stop fingerprint_analyzer'da OLMAMALI (per-country geo içerikte halledildi)
    assert "geo_stopwords_global" not in chain, \
        "fingerprint_analyzer global geo kullanmamalı (per-country izolasyon)"
    # fingerprint (sort+dedup) filtresi zincirin SONUNDA olmalı
    fp_filters = [f for f in chain if filters.get(f, {}).get("type") == "fingerprint"]
    assert fp_filters, "fingerprint tipli filtre zincirde yok"
    assert chain.index(fp_filters[0]) == len(chain) - 1, "fingerprint filtresi en sonda olmalı"


def test_acronym_glue_char_filter_precedes_punctuation_remover():
    """Round-3 (P-R3-1): akronim-glue char-filter tanımlı ve fingerprint/stripped
    analyzer zincirinde punctuation_remover'dan ÖNCE çalışmalı. 'C.M.S.A.D.C' → 'CMSADC'
    olur, tek harfe ('m') çökmez → STRIPPED_EXACT/dedup akronim magneti önlenir.
    docs/audit/2026-06-05-round3-unicode-config-dedup.md §ADIM 5."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    char_filters = settings["settings"]["analysis"]["char_filter"]
    analyzers = settings["settings"]["analysis"]["analyzer"]

    assert "acronym_glue" in char_filters, "acronym_glue char-filter tanımlı değil"
    glue = char_filters["acronym_glue"]
    assert glue["type"] == "pattern_replace"
    # tek-harf akronim segmentini yakalayıp grup-1'e indirger (lookbehind-siz, JVM-portable)
    assert r"\p{L}" in glue["pattern"], "pattern tek-harf (\\p{L}) kısıtı taşımalı"
    assert glue["replacement"] == "$1"

    # fingerprint_analyzer + global stripped analyzer'da SIRA: acronym_glue < punctuation_remover
    for name in ("fingerprint_analyzer", "stripped_search_analyzer"):
        chain = analyzers[name]["char_filter"]
        assert "acronym_glue" in chain and "punctuation_remover" in chain, f"{name} char_filter eksik"
        assert chain.index("acronym_glue") < chain.index("punctuation_remover"), \
            f"{name}: acronym_glue punctuation_remover'dan ÖNCE olmalı"


def test_acronym_glue_active_probe():
    """Round-3: acronym_glue_active probe canlı analyzer'ı 'K.W.M' ile yoklar.
    glue varsa tek token 'kwm' → True; eski zincir 3 token → False; hata → None."""
    from unittest.mock import MagicMock
    from es.manager import acronym_glue_active

    es_new = MagicMock()
    es_new.indices.analyze.return_value = {"tokens": [{"token": "kwm"}]}
    assert acronym_glue_active(es_new) is True

    es_old = MagicMock()
    es_old.indices.analyze.return_value = {"tokens": [{"token": "k"}, {"token": "w"}, {"token": "m"}]}
    assert acronym_glue_active(es_old) is False

    es_err = MagicMock()
    es_err.indices.analyze.side_effect = RuntimeError("no index")
    assert acronym_glue_active(es_err) is None


def test_fingerprint_field_uses_custom_analyzer():
    """fingerprint subfield'ı variations_stripped.name altında (per-country geo izolasyonu)
    ve built-in yerine fingerprint_analyzer kullanmalı. variations.name altında OLMAMALI."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    props = settings["mappings"]["properties"]
    # Fingerprint artık variations_stripped.name altında (girdi per-country stripped içerik)
    fp = props["variations_stripped"]["properties"]["name"]["fields"]["fingerprint"]
    assert fp["analyzer"] == "fingerprint_analyzer", f"beklenen fingerprint_analyzer, görülen {fp.get('analyzer')}"
    # text alanda dedup aggregation için fielddata zorunlu
    assert fp.get("fielddata") is True, "fingerprint alanı aggregation için fielddata=True olmalı"
    # variations.name altında ARTIK fingerprint OLMAMALI (taşındı)
    assert "fingerprint" not in props["variations"]["properties"]["name"]["fields"], \
        "fingerprint variations.name'den variations_stripped.name'e taşınmalı"
