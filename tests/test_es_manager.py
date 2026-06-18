# ============================================================================
# tests/test_es_manager.py - es_manager per-country analyzer testleri
# ============================================================================

from core.synonym_loader import get_all_country_codes


def test_no_hardcoded_generic_tokens():
    """es_manager.py'da hardcoded common_generic_tokens olmamalı."""
    import es.manager as es_manager
    # Module-level sabit olmamalı
    assert not hasattr(es_manager, "common_generic_tokens")


def test_es_manager_imports_cleanly():
    """es_manager.py import hatası vermemeli."""
    import es.manager as es_manager  # ImportError olmamalı
    assert True


def test_phonetic_analyzer_wires_fragment_stop_before_metaphone():
    """phonetic_analyzer mevcutsa: legal_fragment_stop, phonetic_filter'dan ÖNCE gelmeli.

    phonetic_analyzer yalnızca analysis-phonetic plugin'i kuruluysa üretilir; es=None
    ile (test ortamı) üretilmez. Plugin yoksa bu davranış doğrulanamaz → skip."""
    import pytest
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    if "phonetic_analyzer" not in analyzers:
        pytest.skip("analysis-phonetic plugin yok; phonetic_analyzer üretilmedi")
    filters = settings["settings"]["analysis"]["filter"]
    assert "legal_fragment_stop" in filters
    chain = analyzers["phonetic_analyzer"]["filter"]
    assert "legal_fragment_stop" in chain and "phonetic_filter" in chain
    assert chain.index("legal_fragment_stop") < chain.index("phonetic_filter")



def test_article_stop_wired_after_synonym_in_clean_analyzers():
    """article_stop, clean analyzer'larda synonym_filter'dan SONRA gelmeli.

    Article'lar synonym kanonikleşmesinden ÖNCE düşürülürse çok-kelimeli yasal/sektör
    synonym'leri ('sociedad DE responsabilidad limitada=>srl') bozulur. flatten_graph,
    synonym_graph ile article_stop arasında index-time graph'ı düzleştirmek için olmalı."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    filters = s["settings"]["analysis"]["filter"]
    analyzers = s["settings"]["analysis"]["analyzer"]
    assert "article_stop" in filters
    assert filters["article_stop"]["type"] == "stop"
    # common 'de' + ülke 'articles' yüklenmeli
    assert "de" in filters["article_stop"]["stopwords"]
    for an_name, syn in (("clean_analyzer_common", "synonym_filter_common"),
                         ("clean_analyzer_MX", "synonym_filter_MX")):
        chain = analyzers[an_name]["filter"]
        assert syn in chain and "flatten_graph" in chain and "article_stop" in chain
        assert chain.index(syn) < chain.index("flatten_graph") < chain.index("article_stop")


def test_article_stop_in_fingerprint_after_fragment_stop():
    """fingerprint_analyzer article_stop içermeli (parmak izi article-bağımsız olsun);
    fingerprint_token_filter'dan ÖNCE gelmeli. Burada synonym_graph yok → flatten gereksiz."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    chain = s["settings"]["analysis"]["analyzer"]["fingerprint_analyzer"]["filter"]
    assert "article_stop" in chain
    assert chain.index("article_stop") < chain.index("fingerprint_token_filter")


def test_only_target_country_analyzer_built():
    """Tek-ülke settings YALNIZCA o ülkenin clean_analyzer'ını içermeli (65x sismez)."""
    from es.manager import build_index_settings
    from core.synonym_loader import get_all_country_codes
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    assert "clean_analyzer_TR" in analyzers
    assert "clean_analyzer_common" in analyzers  # default + token_count
    others = [c for c in get_all_country_codes() if c != "TR"][:3]
    for cc in others:
        assert f"clean_analyzer_{cc}" not in analyzers


def test_routing_not_required_in_mapping():
    """Per-country index'te _routing required OLMAMALI."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    assert "_routing" not in settings["mappings"]



def test_acronym_glue_char_filter_precedes_punctuation_remover():
    """Round-3 (P-R3-1): akronim-glue char-filter tanımlı ve fingerprint
    analyzer zincirinde punctuation_remover'dan ÖNCE çalışmalı. 'C.M.S.A.D.C' → 'CMSADC'
    olur, tek harfe ('m') çökmez → dedup akronim magneti önlenir.
    docs/audit/2026-06-05-round3-unicode-config-dedup.md §ADIM 5."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    char_filters = settings["settings"]["analysis"]["char_filter"]
    analyzers = settings["settings"]["analysis"]["analyzer"]

    assert "acronym_glue" in char_filters, "acronym_glue char-filter tanımlı değil"
    glue = char_filters["acronym_glue"]
    assert glue["type"] == "pattern_replace"
    # tek-harf akronim segmentini yakalayıp grup-1'e indirger (lookbehind-siz, JVM-portable)
    assert r"\p{L}" in glue["pattern"], "pattern tek-harf (\\p{L}) kısıtı taşımalı"
    assert glue["replacement"] == "$1"

    # fingerprint_analyzer'da SIRA: acronym_glue < punctuation_remover
    chain = analyzers["fingerprint_analyzer"]["char_filter"]
    assert "acronym_glue" in chain and "punctuation_remover" in chain, "fingerprint_analyzer char_filter eksik"
    assert chain.index("acronym_glue") < chain.index("punctuation_remover"), \
        "fingerprint_analyzer: acronym_glue punctuation_remover'dan ÖNCE olmalı"


def test_acronym_glue_active_probe():
    """Round-3: acronym_glue_active probe canlı analyzer'ı 'K.W.M' ile yoklar.
    glue varsa tek token 'kwm' → True; eski zincir 3 token → False; hata → None."""
    from unittest.mock import MagicMock
    from es.manager import acronym_glue_active

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
    """fingerprint subfield'ı variations.name altında olmalı ve fingerprint_analyzer kullanmalı."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    props = settings["mappings"]["properties"]
    # Fingerprint artık variations.name altında (variations_stripped kaldırıldı)
    fp = props["variations"]["properties"]["name"]["fields"]["fingerprint"]
    assert fp["analyzer"] == "fingerprint_analyzer", f"beklenen fingerprint_analyzer, görülen {fp.get('analyzer')}"
    # text alanda dedup aggregation için fielddata zorunlu
    assert fp.get("fielddata") is True, "fingerprint alanı aggregation için fielddata=True olmalı"


def test_variations_name_has_fingerprint_and_token_count():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    vfields = s["mappings"]["properties"]["variations"]["properties"]["name"]["fields"]
    assert "fingerprint" in vfields
    assert "token_count" in vfields


def test_no_variations_stripped_field():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    props = s["mappings"]["properties"]
    assert "variations_stripped" not in props
    assert "variations_suffix" not in props


def test_no_stripped_search_analyzer():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    analyzers = s["settings"]["analysis"]["analyzer"]
    assert "stripped_search_analyzer" not in analyzers
    assert "stripped_search_analyzer_tr" not in analyzers


def test_canonical_full_analyzer_keeps_legal_and_sorts():
    """canonical_full_analyzer clean-zincirini + fingerprint_token_filter'ı kullanmalı,
    legal_fragment_stop İÇERMEMELİ (legal korunur), fingerprint_token_filter SON olmalı."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    analyzers = s["settings"]["analysis"]["analyzer"]
    assert "canonical_full_analyzer_MX" in analyzers
    assert "canonical_full_analyzer_common" in analyzers
    chain = analyzers["canonical_full_analyzer_MX"]["filter"]
    assert "legal_fragment_stop" not in chain, "legal korunmalı (strip YOK)"
    assert chain[-1] == "fingerprint_token_filter", "sort/dedup en sonda olmalı"
    assert "article_stop" in chain
    # synonym_graph zinciri clean ile aynı kaynaktan: synonym filter + flatten_graph içermeli
    assert any(f.startswith("synonym_filter_") for f in chain)
    assert "flatten_graph" in chain


def test_variations_name_has_canonical_full_subfield():
    """variations.name altında canonical_full multi-field'ı, per-country analyzer ile."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    fields = s["mappings"]["properties"]["variations"]["properties"]["name"]["fields"]
    assert "canonical_full" in fields
    cf = fields["canonical_full"]
    assert cf["type"] == "text"
    assert cf["analyzer"] == "canonical_full_analyzer_MX"
