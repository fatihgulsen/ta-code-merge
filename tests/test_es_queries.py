# tests/test_es_queries.py
import pytest
import es_queries


def _get_country_filter(query_dict: dict) -> str | None:
    """Query içindeki country_code filter değerini döner."""
    bool_q = query_dict.get("query", {}).get("bool", {})
    for f in bool_q.get("filter", []):
        if "term" in f and "country_code" in f["term"]:
            return f["term"]["country_code"]
    return None


def test_tax_exact_structure():
    q = es_queries.TAX_EXACT("acme inc", "TR", tax_number="1234567890")
    filters = q["query"]["bool"]["filter"]
    tax_filter = next(f["term"]["tax_number"] for f in filters if "term" in f and "tax_number" in f["term"])
    assert tax_filter == "1234567890"
    assert _get_country_filter(q) == "TR"
    assert q.get("size") == 1


def test_tax_exact_normalizes_tax():
    q = es_queries.TAX_EXACT("acme inc", "TR", tax_number="123-456.789/0")
    filters = q["query"]["bool"]["filter"]
    tax_val = next(f["term"]["tax_number"] for f in filters if "term" in f and "tax_number" in f["term"])
    assert tax_val == "1234567890"


def test_canonical_exact_structure():
    q = es_queries.CANONICAL_EXACT("apple trading", "TR")
    assert _get_country_filter(q) == "TR"
    bool_q = q["query"]["bool"]
    must_phrases = [
        c["match_phrase"]["variations"]["query"]
        for c in bool_q.get("must", [])
        if "match_phrase" in c and "variations" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases


def test_canonical_exact_uses_country_analyzer():
    q = es_queries.CANONICAL_EXACT("apple trading", "DE")
    must = q["query"]["bool"]["must"]
    analyzer = must[0]["match_phrase"]["variations"]["analyzer"]
    assert analyzer == "clean_analyzer_DE"


def test_canonical_exact_fallback_analyzer_for_unknown_country():
    q = es_queries.CANONICAL_EXACT("apple trading", "XX")
    must = q["query"]["bool"]["must"]
    analyzer = must[0]["match_phrase"]["variations"]["analyzer"]
    assert analyzer == "clean_analyzer_common"


def test_stripped_exact_structure():
    q = es_queries.STRIPPED_EXACT("apple trading", "US")
    assert _get_country_filter(q) == "US"
    bool_q = q["query"]["bool"]
    must_phrases = [
        c["match_phrase"]["variations_stripped"]["query"]
        for c in bool_q.get("must", [])
        if "match_phrase" in c and "variations_stripped" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases


def test_token_coverage_uses_and_operator():
    q = es_queries.TOKEN_COVERAGE("apple trading limited", "US")
    must = q["query"]["bool"]["must"]
    match_clause = next(
        c["match"]["variations"]
        for c in must
        if "match" in c and "variations" in c["match"]
    )
    assert match_clause["operator"] == "and"


def test_fuzzy_phrase_has_slop():
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    must = q["query"]["bool"]["must"]
    phrase = next(
        c["match_phrase"]["variations"]
        for c in must
        if "match_phrase" in c and "variations" in c["match_phrase"]
    )
    assert phrase.get("slop", 0) >= 1


def test_ngram_match_queries_ngram_field():
    q = es_queries.NGRAM_MATCH("apple", "US")
    must = q["query"]["bool"]["must"]
    assert any(
        "match" in c and "variations_stripped.ngram" in c["match"]
        for c in must
    )


def test_all_queries_include_country_filter():
    name = "test company"
    country = "FR"
    fns = [
        lambda: es_queries.CANONICAL_EXACT(name, country),
        lambda: es_queries.STRIPPED_EXACT(name, country),
        lambda: es_queries.TOKEN_COVERAGE(name, country),
        lambda: es_queries.FUZZY_PHRASE(name, country),
        lambda: es_queries.NGRAM_MATCH(name, country),
    ]
    for fn in fns:
        assert _get_country_filter(fn()) == country, f"{fn} country filter eksik"


def test_stripped_exact_uses_country_analyzer():
    """STRIPPED_EXACT bilinen ülke için stripped_search_analyzer_{cc} kullanmalı."""
    query = es_queries.STRIPPED_EXACT("Acme Limited", "TR")
    match_phrase = query["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped"]["analyzer"]
    assert analyzer == "stripped_search_analyzer_tr"


def test_stripped_exact_uses_global_analyzer_for_unknown_country():
    """STRIPPED_EXACT bilinmeyen ülke için global fallback analyzer kullanmalı."""
    query = es_queries.STRIPPED_EXACT("Acme Limited", "XX")
    match_phrase = query["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped"]["analyzer"]
    assert analyzer == "stripped_search_analyzer"
