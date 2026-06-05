# ============================================================================
# tests/test_es_manager.py - es_manager per-country analyzer testleri
# ============================================================================

from synonym_loader import get_all_country_codes


def test_no_hardcoded_generic_tokens():
    """es_manager.py'da hardcoded common_generic_tokens olmamalı."""
    import es_manager
    # Module-level sabit olmamalı
    assert not hasattr(es_manager, "common_generic_tokens")


def test_es_manager_imports_cleanly():
    """es_manager.py import hatası vermemeli."""
    import es_manager  # ImportError olmamalı
    assert True


def test_phonetic_analyzer_wires_fragment_stop_before_metaphone():
    """phonetic_analyzer mevcutsa: legal_fragment_stop, phonetic_filter'dan ÖNCE gelmeli.

    phonetic_analyzer yalnızca analysis-phonetic plugin'i kuruluysa üretilir; es=None
    ile (test ortamı) üretilmez. Plugin yoksa bu davranış doğrulanamaz → skip."""
    import pytest
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    analyzers = settings["settings"]["analysis"]["analyzer"]
    if "phonetic_analyzer" not in analyzers:
        pytest.skip("analysis-phonetic plugin yok; phonetic_analyzer üretilmedi")
    filters = settings["settings"]["analysis"]["filter"]
    assert "legal_fragment_stop" in filters
    chain = analyzers["phonetic_analyzer"]["filter"]
    assert "legal_fragment_stop" in chain and "phonetic_filter" in chain
    assert chain.index("legal_fragment_stop") < chain.index("phonetic_filter")


def test_stripped_search_analyzer_global_fallback_exists():
    """build_index_settings fonksiyonu global stripped_search_analyzer üretmeli."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]
    assert "stripped_search_analyzer" in analyzers
    assert "generic_stopwords_global" in filters


def test_per_country_stripped_analyzers_exist():
    """Her ülke için ayrı stripped_search_analyzer_{cc} oluşturulmalı."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]
    codes = get_all_country_codes()
    for cc in codes[:3]:  # İlk 3 ülke yeterli
        assert f"stripped_search_analyzer_{cc.lower()}" in analyzers, \
            f"stripped_search_analyzer_{cc.lower()} analyzer'ı bulunamadı"
        assert f"generic_stopwords_{cc.lower()}" in filters, \
            f"generic_stopwords_{cc.lower()} filter'ı bulunamadı"


def test_build_index_settings_includes_articles_in_stop_filter():
    """Per-country stop filter article token'larını içermeli."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
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
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    filters = settings["settings"]["analysis"]["filter"]
    global_filter = filters.get("generic_stopwords_global")
    assert global_filter is not None
    assert "and" in global_filter["stopwords"]
    assert "von" in global_filter["stopwords"]


def test_fingerprint_analyzer_normalizes_suffix_and_geo():
    """P0-C/Option-2: variations.fingerprint için özel fingerprint_analyzer —
    yasal-ek + jenerik + geo token'ları düşürür, sonra fingerprint (sort+dedup) uygular.
    Böylece 'ACME DE MEXICO S.A. DE C.V.' ile 'ACME' aynı fingerprint'e iner."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]

    assert "fingerprint_analyzer" in analyzers, "özel fingerprint_analyzer bulunamadı"
    chain = analyzers["fingerprint_analyzer"]["filter"]
    assert "legal_fragment_stop" in chain
    assert "generic_stopwords_global" in chain
    assert "geo_stopwords_global" in chain
    # fingerprint (sort+dedup) filtresi zincirin SONUNDA olmalı
    fp_filters = [f for f in chain if filters.get(f, {}).get("type") == "fingerprint"]
    assert fp_filters, "fingerprint tipli filtre zincirde yok"
    assert chain.index(fp_filters[0]) == len(chain) - 1, "fingerprint filtresi en sonda olmalı"
    # geo stop filtresi gerçek bir stop filtresi olmalı
    assert filters["geo_stopwords_global"]["type"] == "stop"


def test_acronym_glue_char_filter_precedes_punctuation_remover():
    """Round-3 (P-R3-1): akronim-glue char-filter tanımlı ve fingerprint/stripped
    analyzer zincirinde punctuation_remover'dan ÖNCE çalışmalı. 'C.M.S.A.D.C' → 'CMSADC'
    olur, tek harfe ('m') çökmez → STRIPPED_EXACT/dedup akronim magneti önlenir.
    docs/audit/2026-06-05-round3-unicode-config-dedup.md §ADIM 5."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
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
    from es_manager import acronym_glue_active

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
    """variations.name.fingerprint subfield'ı built-in yerine fingerprint_analyzer kullanmalı."""
    from es_manager import build_index_settings
    settings = build_index_settings(es=None)
    fp = settings["mappings"]["properties"]["variations"]["properties"]["name"]["fields"]["fingerprint"]
    assert fp["analyzer"] == "fingerprint_analyzer", f"beklenen fingerprint_analyzer, görülen {fp.get('analyzer')}"
    # text alanda dedup aggregation için fielddata zorunlu
    assert fp.get("fielddata") is True, "fingerprint alanı aggregation için fielddata=True olmalı"
