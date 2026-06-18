# tests/test_es_ingest.py
from unittest.mock import MagicMock
import es.ingest as es_ingest


def test_pipeline_name_format():
    """Pipeline ismi country_code lowercase ile formatlanmalı."""
    from es.ingest import pipeline_name
    assert pipeline_name("TR") == "company_name_tr"
    assert pipeline_name("DE") == "company_name_de"
    assert pipeline_name("IN") == "company_name_in"
    assert pipeline_name("tr") == "company_name_tr"


def test_register_all_pipelines_calls_each_country():
    """register_all_pipelines her ülke için ayrı pipeline kaydeder."""
    from es.ingest import register_all_pipelines
    from core.synonym_loader import get_all_country_codes
    mock_es = MagicMock()
    register_all_pipelines(mock_es)
    all_codes = get_all_country_codes()
    assert mock_es.ingest.put_pipeline.call_count == len(all_codes)


def test_register_pipeline_uses_correct_name():
    """register_pipeline doğru pipeline ismiyle kaydeder."""
    from es.ingest import register_pipeline, pipeline_name
    mock_es = MagicMock()
    register_pipeline(mock_es, "TR")
    mock_es.ingest.put_pipeline.assert_called_once()
    call_kwargs = mock_es.ingest.put_pipeline.call_args[1]
    assert call_kwargs["id"] == pipeline_name("TR")


def test_no_hardcoded_pipeline_name_constant():
    """PIPELINE_NAME sabit değişkeni artık olmamalı."""
    import es.ingest as es_ingest
    assert not hasattr(es_ingest, "PIPELINE_NAME")


def test_clean_script_collapses_consecutive_dup_tokens():
    """A2 (token-tekrar fix): _build_clean_script ardışık yinelenen token'ları tek'e
    indirmeli ('RICARD RICARD ARGENTINA' → 'RICARD ARGENTINA'). Kaynak-veri token
    tekrarı TOKEN_COVERAGE skorunu/coverage'ını şişirip over-merge üretiyor
    (R7 en yüksek skorlu hata: PERNOD RICARD ⇸ RICARD RICARD, score 27).
    Painless ES'te çalıştığından yapısal imza doğrulanır; davranış reindex G3'te."""
    from es.ingest import _build_clean_script
    script = _build_clean_script("AR")
    # Ardışık-tekrar dedup: önceki-token karşılaştırması ('prevTok') içermeli
    assert "prevTok" in script, "ardışık-tekrar token dedup mantığı (prevTok) bulunamadı"


def test_pipeline_only_has_light_clean_processor():
    from es.ingest import build_pipeline_body
    body = build_pipeline_body("TR")
    descs = [list(p.values())[0].get("description", "") for p in body["processors"]]
    assert any("light_clean" in d for d in descs)
    assert not any("stripped" in d for d in descs)
    assert not any("suffix" in d for d in descs)
    assert len(body["processors"]) == 1
