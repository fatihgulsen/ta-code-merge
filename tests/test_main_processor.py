# tests/test_main_processor.py
from unittest.mock import MagicMock


def _make_es_hit(master_id: str, score: float = 80.0, variations: list[str] | None = None) -> dict:
    return {
        "_source": {
            "master_id": master_id,
            "variations": variations if variations is not None else [],
        },
        "_score": score,
    }


def _make_msearch_response(hits_per_query: list[list[dict]]) -> dict:
    """Her sorgu için hit listesi içeren msearch yanıtı üretir."""
    return {
        "responses": [
            {"hits": {"hits": hits, "total": {"value": len(hits)}}}
            for hits in hits_per_query
        ]
    }


def test_run_stage_returns_matched_and_unmatched():
    """Eşleşen kayıtlar matched, eşleşmeyenler unmatched listesine girer."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Ltd", "country": "TR", "tax": "", "phone": ""},
        {"row_id": 2, "raw_name": "Beta Corp", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "CANONICAL_EXACT", "order": 2, "query_fn": "CANONICAL_EXACT",
             "min_score": 50.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=80.0, variations=["Acme Ltd"])],  # record 1 eşleşti
        [],                                                                   # record 2 eşleşmedi
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 1
    assert matched[0]["row_id"] == 1
    assert matched[0]["master_id"] == "master-001"
    assert matched[0]["stage_name"] == "CANONICAL_EXACT"

    assert len(unmatched) == 1
    assert unmatched[0]["row_id"] == 2


def test_run_stage_respects_min_score():
    """min_score altındaki hit'ler eşleşme sayılmaz."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Ltd", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "NGRAM_MATCH", "order": 6, "query_fn": "NGRAM_MATCH",
             "min_score": 3.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=1.5)],  # min_score altında
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 0
    assert len(unmatched) == 1


def test_tax_exact_skips_records_without_tax():
    """TAX_EXACT stage, tax numarası olmayan kayıtları unmatched'a ekler."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme", "country": "TR", "tax": "", "phone": ""},
        {"row_id": 2, "raw_name": "Beta", "country": "TR", "tax": "123", "phone": ""},
    ]
    stage = {"name": "TAX_EXACT", "order": 1, "query_fn": "TAX_EXACT",
             "min_score": 1.0, "enabled": True}

    mock_es = MagicMock()
    # Only 1 query sent (for record 2 which has tax)
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-002", score=1.0)],
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 1
    assert matched[0]["row_id"] == 2

    assert len(unmatched) == 1
    assert unmatched[0]["row_id"] == 1


def test_post_verify_suffix_fuzzy_passes_when_name_matches():
    """SUFFIX_FUZZY: name token'ları doc stripped'da >= 85% örtüşünce True döner."""
    import main_processor as mp

    doc_source = {
        "variations": ["komerci limited"],
        "variations_stripped": ["komerci"],
    }
    result = mp._post_verify("Komerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is True


def test_post_verify_suffix_fuzzy_fails_when_name_differs():
    """SUFFIX_FUZZY: name token'ları < 85% örtüşünce False döner."""
    import main_processor as mp

    doc_source = {
        "variations": ["komerci limited"],
        "variations_stripped": ["komerci"],
    }
    result = mp._post_verify("Kommerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is False


def test_post_verify_suffix_fuzzy_passes_with_multiple_name_tokens():
    """SUFFIX_FUZZY: çok tokenlı isimde yüksek coverage True döner."""
    import main_processor as mp

    doc_source = {
        "variations": ["komerci trading limited"],
        "variations_stripped": ["komerci trading"],
    }
    result = mp._post_verify("Komerci Trading Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is True


def test_post_verify_suffix_fuzzy_fails_when_doc_stripped_empty():
    """SUFFIX_FUZZY: doc variations_stripped boşsa False döner."""
    import main_processor as mp

    doc_source = {
        "variations": ["limited"],
        "variations_stripped": [],
    }
    result = mp._post_verify("Komerci Limted", doc_source, "SUFFIX_FUZZY", "TR")
    assert result is False


def test_article_stopwords_exists():
    """get_article_stopwords 'and', 'of' gibi tokenlari icermeli; _STOPWORDS olmamali."""
    import main_processor as mp
    from synonym_loader import get_article_stopwords
    assert not hasattr(mp, "_STOPWORDS")
    assert "and" in get_article_stopwords("")
    assert "of" in get_article_stopwords("")


def test_post_verify_word_count_excludes_company_suffixes():
    """Word count 'ltd', 'inc' gibi company suffix tokenlarini saymamali."""
    from main_processor import _clean_labels
    from synonym_loader import get_company_type_tokens, get_article_stopwords
    cc = "TR"
    stopwords = get_article_stopwords(cc) | get_company_type_tokens(cc)
    # "ACME LTD" → 1 meaningful word (ltd filtered)
    word_count = len([
        t for t in _clean_labels("ACME LTD").lower().split()
        if t.rstrip(".,") not in stopwords
        and t.rstrip(".,")
        and t.rstrip(".,").isalnum()
    ])
    assert word_count == 1, f"Expected 1, got {word_count}"


from main_processor import _tokenize


def test_tokenize_excludes_suffix_tokens():
    """Suffix token'ları (ltd, corp, inc) sonuç setine girmemeli."""
    result = _tokenize("Komerci Limited", "TR")
    assert "komerci" in result
    assert "limited" not in result
    assert "ltd" not in result


def test_tokenize_excludes_article_tokens():
    """Article token'ları (of, the, and) sonuç setine girmemeli."""
    result = _tokenize("Acme of the World Corp", "US")
    assert "acme" in result
    assert "world" in result
    assert "of" not in result
    assert "the" not in result
    assert "corp" not in result


def test_tokenize_keeps_initials():
    """Tek harfli alfanumerik token'lar (inisyal/rakam) korunmalı."""
    result = _tokenize("A B Impex Ltd", "IN")
    assert "a" in result
    assert "b" in result
    assert "impex" in result


def test_tokenize_drops_single_non_alnum():
    """Tek harfli non-alnum token'lar (& - .) atlanmalı."""
    result = _tokenize("A & B Corp", "US")
    assert "&" not in result
    assert "a" in result
    assert "b" in result


def test_tokenize_returns_set():
    result = _tokenize("Komerci Ltd", "TR")
    assert isinstance(result, set)


from main_processor import _edit_distance, _is_fuzzy_suffix


def test_edit_distance_identical():
    assert _edit_distance("limited", "limited") == 0


def test_edit_distance_one_edit():
    assert _edit_distance("limted", "limited") == 1


def test_edit_distance_two_edits():
    assert _edit_distance("limtedd", "limited") == 2


def test_edit_distance_three_edits():
    assert _edit_distance("limtddd", "limited") == 3


def test_edit_distance_empty():
    assert _edit_distance("", "ltd") == 3
    assert _edit_distance("ltd", "") == 3


def test_is_fuzzy_suffix_exact_match():
    suffix_tokens = frozenset(["ltd", "limited", "inc", "corp"])
    assert _is_fuzzy_suffix("ltd", suffix_tokens) is True


def test_is_fuzzy_suffix_one_edit_len6():
    """'limted' (6 chars) → max 1 edit → 'limited' (distance=1) → True."""
    suffix_tokens = frozenset(["limited", "ltd", "corp"])
    assert _is_fuzzy_suffix("limted", suffix_tokens) is True


def test_is_fuzzy_suffix_two_edit_len7():
    """'limtedd' (7 chars) → max 2 edits → 'limited' (distance=2) → True."""
    suffix_tokens = frozenset(["limited", "ltd"])
    assert _is_fuzzy_suffix("limtedd", suffix_tokens) is True


def test_is_fuzzy_suffix_too_many_edits():
    """'limtddd' (7 chars) → max 2 edits → 'limited' (distance=3) → False."""
    suffix_tokens = frozenset(["limited", "ltd"])
    assert _is_fuzzy_suffix("limtddd", suffix_tokens) is False


def test_is_fuzzy_suffix_name_token_not_matched():
    """'komerci' hiçbir suffix'e benzemez → False."""
    suffix_tokens = frozenset(["limited", "ltd", "corp", "inc"])
    assert _is_fuzzy_suffix("komerci", suffix_tokens) is False


def test_is_fuzzy_suffix_short_token_exact_only():
    """3 char → max 0 edit → exact only."""
    suffix_tokens = frozenset(["ltd", "inc"])
    assert _is_fuzzy_suffix("ltd", suffix_tokens) is True
    assert _is_fuzzy_suffix("lte", suffix_tokens) is False
