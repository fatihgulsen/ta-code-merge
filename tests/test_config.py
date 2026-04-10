"""Tests for config.py STAGES configuration."""

import config


def test_stages_has_required_keys():
    """Verify each stage in STAGES has all required keys."""
    required = {"name", "order", "query_fn", "min_score", "enabled"}
    for stage in config.STAGES:
        missing = required - stage.keys()
        assert not missing, f"Stage '{stage.get('name')}' için eksik anahtarlar: {missing}"


def test_stages_ordered_correctly():
    """Verify enabled stages are sorted by order value."""
    enabled = [s for s in config.STAGES if s["enabled"]]
    orders = [s["order"] for s in enabled]
    assert orders == sorted(orders), "Aktif stage'ler 'order' değerine göre sıralı değil"


def test_stage_query_fns_exist_in_es_queries():
    """Verify that query_fn values match functions in es_queries module."""
    try:
        import es_queries
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


def test_suffix_fuzzy_constants_exist():
    assert hasattr(config, "SUFFIX_FUZZY_MIN_SCORE")
    assert hasattr(config, "SUFFIX_FUZZY_SCORE")
    assert config.SUFFIX_FUZZY_SCORE == 85
    assert config.SUFFIX_FUZZY_MIN_SCORE == 1.5


def test_suffix_fuzzy_stage_in_stages():
    names = [s["name"] for s in config.STAGES]
    assert "SUFFIX_FUZZY" in names


def test_stage_order():
    """STRIPPED_EXACT en sonda olmalı; SUFFIX_FUZZY CANONICAL_EXACT'tan sonra TOKEN_COVERAGE'dan önce gelmeli."""
    stages_by_name = {s["name"]: s["order"] for s in config.STAGES}
    assert stages_by_name["CANONICAL_EXACT"] < stages_by_name["SUFFIX_FUZZY"]
    assert stages_by_name["SUFFIX_FUZZY"] < stages_by_name["TOKEN_COVERAGE"]
    assert stages_by_name["STRIPPED_EXACT"] > stages_by_name["NGRAM_MATCH"]


def test_business_descriptors_includes_sector_words():
    """Sprint 1: BUSINESS_DESCRIPTORS must include sector differentiators
    so that synonym_loader does not strip them from canonical/stripped forms."""
    from config import BUSINESS_DESCRIPTORS

    required = {
        # tekil/çoğul
        "enterprise", "enterprises", "industry", "industries",
        "holding", "holdings",
        "service", "services", "solution", "solutions",
        "technology", "technologies",
        # ticari roller
        "trader", "traders", "exports", "imports", "export", "import",
        "dealers", "distributors", "suppliers", "agency", "agencies",
        "consultants", "consulting", "associates", "ventures", "systems",
        "overseas",
        # sektör
        "pharma", "pharmaceuticals", "chemicals", "chemical",
        "textiles", "textile", "steel", "metals", "metal",
        "plastics", "packaging", "foods", "food", "agro",
        "auto", "automobile", "automotive",
        "electronics", "electric", "electrical",
        "software", "hardware", "media", "communications",
        "healthcare", "education", "finance", "capital",
        "investments", "securities", "insurance", "commodities",
        "power", "energy", "petroleum",
        "hotel", "hospitality", "resort",
        "aviation", "shipping", "marine",
        "logistics", "transport", "engineering", "construction",
        "infra", "realty", "developers", "retail", "global",
    }
    missing = required - BUSINESS_DESCRIPTORS
    assert not missing, f"Missing descriptor tokens: {sorted(missing)}"
