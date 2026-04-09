# tests/test_main_processor.py
from unittest.mock import MagicMock, patch
import pytest


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


def test_article_stopwords_exists():
    """_ARTICLE_STOPWORDS olmali, _STOPWORDS olmamali."""
    import main_processor as mp
    assert hasattr(mp, "_ARTICLE_STOPWORDS")
    assert not hasattr(mp, "_STOPWORDS")
    assert "and" in mp._ARTICLE_STOPWORDS
    assert "of" in mp._ARTICLE_STOPWORDS


def test_post_verify_word_count_excludes_company_suffixes():
    """Word count 'ltd', 'inc' gibi company suffix tokenlarini saymamali."""
    from main_processor import _clean_labels, _ARTICLE_STOPWORDS
    from synonym_loader import get_company_type_tokens
    cc = "TR"
    stopwords = _ARTICLE_STOPWORDS | get_company_type_tokens(cc)
    # "ACME LTD" → 1 meaningful word (ltd filtered)
    word_count = len([
        t for t in _clean_labels("ACME LTD").lower().split()
        if t.rstrip(".,") not in stopwords
        and t.rstrip(".,")
        and t.rstrip(".,").isalnum()
    ])
    assert word_count == 1, f"Expected 1, got {word_count}"
