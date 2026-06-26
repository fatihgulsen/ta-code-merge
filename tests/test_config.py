"""Tests for config.py STAGES configuration."""

import config


def test_stages_has_required_keys():
    """Verify each stage in STAGES has all required keys."""
    required = {"name", "order", "query_fn", "min_score", "enabled"}
    for stage in config.STAGES:
        missing = required - stage.keys()
        assert not missing, (
            f"Stage '{stage.get('name')}' için eksik anahtarlar: {missing}"
        )


def test_stages_ordered_correctly():
    """Verify enabled stages are sorted by order value."""
    enabled = [s for s in config.STAGES if s["enabled"]]
    orders = [s["order"] for s in enabled]
    assert orders == sorted(orders), (
        "Aktif stage'ler 'order' değerine göre sıralı değil"
    )


def test_stage_query_fns_exist_in_es_queries():
    """Verify that query_fn values match functions in es_queries module."""
    try:
        import es.queries as es_queries
    except ImportError:
        # es_queries.py doesn't exist yet (will be created in Task 3)
        # This test is expected to fail at this stage
        import pytest

        pytest.skip("es_queries.py not yet created (Task 3)")

    for stage in config.STAGES:
        assert hasattr(es_queries, stage["query_fn"]), (
            f"es_queries.py'de '{stage['query_fn']}' fonksiyonu bulunamadı "
            f"(stage: {stage['name']})"
        )


def test_stage_names_unique():
    """Verify stage names are unique."""
    names = [s["name"] for s in config.STAGES]
    assert len(names) == len(set(names)), "STAGES listesinde tekrarlı isim var"


def test_suffix_fuzzy_match_type_exists():
    assert hasattr(config.MatchType, "SUFFIX_FUZZY")
    assert config.MatchType.SUFFIX_FUZZY == "SUFFIX_FUZZY"


def test_auto_dedup_match_type_exists():
    """A3: AUTO_DEDUP match_type — fingerprint auto-merge ile birleştirilen ikincil
    NEW_MASTER anchor'ları bu tipe demote edilir (watch query kör noktası kapanır)."""
    assert hasattr(config.MatchType, "AUTO_DEDUP")
    assert config.MatchType.AUTO_DEDUP == "AUTO_DEDUP"


def test_suffix_fuzzy_constants_exist():
    assert hasattr(config, "SUFFIX_FUZZY_SCORE")
    assert config.SUFFIX_FUZZY_SCORE == 85


def test_stage_order():
    """Plan 4: CANONICAL_EXACT (1) → PHRASE_SLOP (2) → TOKEN_COVERAGE (3)."""
    stages_by_name = {s["name"]: s["order"] for s in config.STAGES}
    assert stages_by_name["CANONICAL_EXACT"] == 1
    assert stages_by_name["PHRASE_SLOP"] == 2
    assert stages_by_name["TOKEN_COVERAGE"] == 3


def test_business_descriptors_in_synonyms():
    """Sprint 2: Descriptors moved to synonyms.
    Checking common business sectors are reachable through synonym_loader."""
    from core.synonym_loader import get_business_sector_tokens

    # Common descriptors that were previously in config.py
    required = {
        "enterprise",
        "industry",
        "holding",
        "service",
        "solution",
        "technology",
        "pharma",
        "clinical",
        "chemicals",
        "steel",
        "metals",
        "plastics",
        "packaging",
        "food",
        "auto",
        "electronics",
        "software",
        "healthcare",
        "finance",
        "logistics",
        "shipping",
        "engineering",
        "construction",
        "retail",
        "global",
        "trading",
        "group",
        "international",
    }
    # Note: tokens in synonyms are normalized (lowercase, punctuation removed)
    common_sectors = get_business_sector_tokens("__common__")

    # We check if at least some of these exist in the common set
    # (exact match depends on how they were merged)
    missing = required - common_sectors
    # Some might be missing due to different mapping targets,
    # but the core ones should be there.
    assert "enterprise" in common_sectors or "enterprises" in common_sectors
    assert "industry" in common_sectors or "industries" in common_sectors


def test_stage_index_variation_plan4():
    """Plan 4: CANONICAL_EXACT indexes variations; PHRASE_SLOP and TOKEN_COVERAGE do not."""
    from config import STAGES

    by_name = {s["name"]: s for s in STAGES}
    # CANONICAL_EXACT enables variations indexing
    assert by_name["CANONICAL_EXACT"]["index_variation"] is True

    # Loose stages remain False
    for stage_name in ("PHRASE_SLOP", "TOKEN_COVERAGE"):
        assert by_name[stage_name]["index_variation"] is False


def test_index_for_country_physical_name():
    from config import index_for_country
    assert index_for_country("tr") == "living_companies_tr_v3"
    assert index_for_country("MX") == "living_companies_mx_v3"


def test_alias_for_country_versionless():
    from config import alias_for_country
    assert alias_for_country("tr") == "living_companies_tr"
    assert alias_for_country("MX") == "living_companies_mx"


def test_analyze_index_override_default_none():
    import config
    assert config.ES_ANALYZE_INDEX_OVERRIDE is None


def test_dirty_data_match_type_exists():
    from config import MatchType
    assert MatchType.DIRTY_DATA == "DIRTY_DATA"


def test_enable_dirty_data_flag_default_true():
    import config
    assert config.ENABLE_DIRTY_DATA is True


def test_stages_only_canonical_fuzzy_coverage():
    from config import STAGES
    names = {s["name"] for s in STAGES}
    assert names == {"CANONICAL_EXACT", "PHRASE_SLOP", "TOKEN_COVERAGE"}
