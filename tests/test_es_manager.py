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
