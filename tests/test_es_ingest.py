import es_ingest


def test_build_suffix_script_returns_string():
    """_build_suffix_script bir string (Painless kodu) döner."""
    result = es_ingest._build_suffix_script(["ltd", "limited", "inc"])
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_suffix_script_contains_generic_tokens():
    """Script içinde generic token listesi bulunmalı."""
    result = es_ingest._build_suffix_script(["ltd", "limited"])
    assert "'ltd'" in result
    assert "'limited'" in result


def test_build_suffix_script_sets_variations_suffix():
    """Script ctx.variations_suffix'i set etmeli."""
    result = es_ingest._build_suffix_script(["ltd"])
    assert "ctx.variations_suffix" in result


def test_build_suffix_script_uses_generic_set_contains():
    """Script generic token'ları IÇEREN token'ları toplamalı (excluded değil)."""
    result = es_ingest._build_suffix_script(["ltd"])
    # Stripped script'in tersine: contains yerine NOT contains yok
    # "genericSet.contains(token)" olmalı
    assert "genericSet.contains(token)" in result


def test_build_pipeline_body_has_three_processors():
    """Pipeline body 3 processor içermeli: clean, stripped, suffix."""
    body = es_ingest.build_pipeline_body()
    assert len(body["processors"]) == 3


def test_build_pipeline_body_suffix_processor_last():
    """Suffix processor en son gelmeli."""
    body = es_ingest.build_pipeline_body()
    last_proc = body["processors"][-1]
    assert "script" in last_proc
    assert "variations_suffix" in last_proc["script"]["source"]
