# tests/test_es_ingest.py
from unittest.mock import MagicMock


def test_pipeline_name_format():
    """Pipeline ismi country_code lowercase ile formatlanmalı."""
    from es_ingest import pipeline_name
    assert pipeline_name("TR") == "company_name_tr"
    assert pipeline_name("DE") == "company_name_de"
    assert pipeline_name("IN") == "company_name_in"
    assert pipeline_name("tr") == "company_name_tr"


def test_build_pipeline_body_has_two_processors():
    """Pipeline body 2 script processor içermeli."""
    from es_ingest import build_pipeline_body
    body = build_pipeline_body("TR")
    assert "processors" in body
    assert len(body["processors"]) == 2


def test_build_pipeline_body_differs_per_country():
    """Farklı ülkelerin pipeline body'si farklı olmalı (TR vs AE)."""
    from es_ingest import build_pipeline_body
    body_tr = build_pipeline_body("TR")
    body_ae = build_pipeline_body("AE")
    # Script source'ları farklı olmalı (ülkeye özgü tokenlar farklı)
    clean_tr = body_tr["processors"][0]["script"]["source"]
    clean_ae = body_ae["processors"][0]["script"]["source"]
    assert clean_tr != clean_ae


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
