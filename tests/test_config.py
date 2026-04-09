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


def test_suffix_fuzzy_stage_order_between_stripped_and_token_coverage():
    """SUFFIX_FUZZY, STRIPPED_EXACT'tan sonra TOKEN_COVERAGE'dan önce gelmeli."""
    stages_by_name = {s["name"]: s["order"] for s in config.STAGES}
    assert stages_by_name["SUFFIX_FUZZY"] > stages_by_name["STRIPPED_EXACT"]
    assert stages_by_name["SUFFIX_FUZZY"] < stages_by_name["TOKEN_COVERAGE"]
