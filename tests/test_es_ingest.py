# tests/test_es_ingest.py
from unittest.mock import MagicMock
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
    assert "genericSet.contains(token)" in result


def test_pipeline_name_format():
    """Pipeline ismi country_code lowercase ile formatlanmalı."""
    from es_ingest import pipeline_name
    assert pipeline_name("TR") == "company_name_tr"
    assert pipeline_name("DE") == "company_name_de"
    assert pipeline_name("IN") == "company_name_in"
    assert pipeline_name("tr") == "company_name_tr"


def test_build_pipeline_body_has_three_processors():
    """Pipeline body 3 processor içermeli: clean, stripped, suffix."""
    body = es_ingest.build_pipeline_body("TR")
    assert len(body["processors"]) == 3


def test_build_pipeline_body_suffix_processor_last():
    """Suffix processor en son gelmeli."""
    body = es_ingest.build_pipeline_body("TR")
    last_proc = body["processors"][-1]
    assert "script" in last_proc
    assert "variations_suffix" in last_proc["script"]["source"]


def test_build_pipeline_body_differs_per_country():
    """Farklı ülkelerin pipeline body'si farklı olmalı (TR vs AE)."""
    from es_ingest import build_pipeline_body
    body_tr = build_pipeline_body("MX")
    body_ae = build_pipeline_body("US")
    # Sprint 2: clean script is now global, stripped script differs by country (legal_suffixes)
    stripped_tr = body_tr["processors"][1]["script"]["source"]
    stripped_ae = body_ae["processors"][1]["script"]["source"]
    assert stripped_tr != stripped_ae


def test_register_all_pipelines_calls_each_country():
    """register_all_pipelines her ülke için ayrı pipeline kaydeder."""
    from es_ingest import register_all_pipelines
    from synonym_loader import get_all_country_codes
    mock_es = MagicMock()
    register_all_pipelines(mock_es)
    all_codes = get_all_country_codes()
    assert mock_es.ingest.put_pipeline.call_count == len(all_codes)


def test_register_pipeline_uses_correct_name():
    """register_pipeline doğru pipeline ismiyle kaydeder."""
    from es_ingest import register_pipeline, pipeline_name
    mock_es = MagicMock()
    register_pipeline(mock_es, "TR")
    mock_es.ingest.put_pipeline.assert_called_once()
    call_kwargs = mock_es.ingest.put_pipeline.call_args[1]
    assert call_kwargs["id"] == pipeline_name("TR")


def test_no_hardcoded_pipeline_name_constant():
    """PIPELINE_NAME sabit değişkeni artık olmamalı."""
    import es_ingest
    assert not hasattr(es_ingest, "PIPELINE_NAME")
