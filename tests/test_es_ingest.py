# tests/test_es_ingest.py
from unittest.mock import MagicMock
import es.ingest as es_ingest


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
    from es.ingest import pipeline_name
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
    from es.ingest import build_pipeline_body
    body_tr = build_pipeline_body("MX")
    body_ae = build_pipeline_body("US")
    # Sprint 2: clean script is now global, stripped script differs by country (legal_suffixes)
    stripped_tr = body_tr["processors"][1]["script"]["source"]
    stripped_ae = body_ae["processors"][1]["script"]["source"]
    assert stripped_tr != stripped_ae


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


def test_stripped_script_strips_geo_tokens():
    """A1 (geo-mıknatıs fix, index tarafı): _build_stripped_script saklanan
    variations_stripped string'inden geo token'larını da çıkarmalı — yoksa
    match_phrase bitişikliği query tarafıyla tutarsız kalır (recall kaybı:
    'AUDI ARGENTINA MOTORS' index'te 3 token, query'de 2). Geo token listesi
    countries.json'dan türetilir (get_country_name_tokens) — hardcode yok."""
    from es.ingest import _build_stripped_script
    from core.synonym_loader import get_country_name_tokens
    script = _build_stripped_script("AR")
    geo_tokens = [t for t in get_country_name_tokens("AR") if " " not in t]
    assert geo_tokens, "AR için countries.json'dan geo token bekleniyordu"
    # En ayırt edici geo token (argentina) generic-strip listesinde olmalı
    assert "argentina" in script.lower(), \
        "_build_stripped_script çıktısı 'argentina' geo token'ını strip listesinde içermeli"
