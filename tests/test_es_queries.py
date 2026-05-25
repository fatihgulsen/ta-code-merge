# tests/test_es_queries.py
import es_queries
from es_manager import build_index_settings


def _get_country_filter(query_dict: dict) -> str | None:
    """Query içindeki country_code filter değerini döner."""
    bool_q = query_dict.get("query", {}).get("bool", {})
    for f in bool_q.get("filter", []):
        if "term" in f and "country_code" in f["term"]:
            return f["term"]["country_code"]
    return None


def test_canonical_exact_structure():
    q = es_queries.CANONICAL_EXACT("apple trading", "TR")
    assert _get_country_filter(q) == "TR"
    bool_q = q["query"]["bool"]
    
    # Nested clause kontrolü
    nested = next(c["nested"] for c in bool_q["must"] if "nested" in c)
    assert nested["path"] == "variations"
    
    inner_must = nested["query"]["bool"]["must"]
    must_phrases = [
        c["match_phrase"]["variations.name"]["query"]
        for c in inner_must
        if "match_phrase" in c and "variations.name" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases
    
    # token_count filtresi kontrolü
    inner_filters = nested["query"]["bool"]["filter"]
    assert any("term" in f and "variations.token_count" in f["term"] for f in inner_filters)


def test_canonical_exact_uses_country_analyzer():
    q = es_queries.CANONICAL_EXACT("apple trading", "DE")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    inner_must = nested["query"]["bool"]["must"]
    analyzer = inner_must[0]["match_phrase"]["variations.name"]["analyzer"]
    assert analyzer == "clean_analyzer_DE"


def test_canonical_exact_fallback_analyzer_for_unknown_country():
    q = es_queries.CANONICAL_EXACT("apple trading", "XX")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    inner_must = nested["query"]["bool"]["must"]
    analyzer = inner_must[0]["match_phrase"]["variations.name"]["analyzer"]
    assert analyzer == "clean_analyzer_common"


def test_stripped_exact_structure():
    q = es_queries.STRIPPED_EXACT("apple trading", "US")
    assert _get_country_filter(q) == "US"
    bool_q = q["query"]["bool"]
    
    nested = next(c["nested"] for c in bool_q["must"] if "nested" in c)
    assert nested["path"] == "variations_stripped"
    
    inner_must = nested["query"]["bool"]["must"]
    must_phrases = [
        c["match_phrase"]["variations_stripped.name"]["query"]
        for c in inner_must
        if "match_phrase" in c and "variations_stripped.name" in c["match_phrase"]
    ]
    assert "apple trading" in must_phrases


def test_stripped_exact_uses_country_analyzer():
    """STRIPPED_EXACT bilinen ülke için stripped_search_analyzer_{cc} kullanmalı."""
    query = es_queries.STRIPPED_EXACT("Acme Limited", "TR")
    must = query["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    match_phrase = nested["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped.name"]["analyzer"]
    assert analyzer == "stripped_search_analyzer_tr"


def test_stripped_exact_uses_global_analyzer_for_unknown_country():
    """STRIPPED_EXACT bilinmeyen ülke için global fallback analyzer kullanmalı."""
    query = es_queries.STRIPPED_EXACT("Acme Limited", "XX")
    must = query["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    match_phrase = nested["query"]["bool"]["must"][0]["match_phrase"]
    analyzer = match_phrase["variations_stripped.name"]["analyzer"]
    assert analyzer == "stripped_search_analyzer"


def test_token_coverage_uses_and_operator():
    q = es_queries.TOKEN_COVERAGE("apple trading limited", "US")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    match_clause = nested["query"]["match"]["variations.name"]
    assert match_clause["operator"] == "and"


def test_fuzzy_phrase_has_slop():
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    phrase = nested["query"]["match_phrase"]["variations.name"]
    assert phrase.get("slop", 0) >= 1


def test_ngram_match_queries_ngram_field():
    q = es_queries.NGRAM_MATCH("apple", "US")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    assert "variations_stripped.name.ngram" in nested["query"]["match"]


def test_all_queries_include_country_filter():
    name = "test company"
    country = "FR"
    fns = [
        lambda: es_queries.CANONICAL_EXACT(name, country),
        lambda: es_queries.STRIPPED_EXACT(name, country),
        lambda: es_queries.TOKEN_COVERAGE(name, country),
        lambda: es_queries.FUZZY_PHRASE(name, country),
        lambda: es_queries.NGRAM_MATCH(name, country),
        lambda: es_queries.SUFFIX_FUZZY(name, country),
    ]
    for fn in fns:
        assert _get_country_filter(fn()) == country, f"{fn} country filter eksik"


def test_suffix_fuzzy_structure():
    """SUFFIX_FUZZY query'si must + should içermeli."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    bool_q = q["query"]["bool"]
    assert "must" in bool_q, "must clause eksik"
    assert "should" in bool_q, "should clause eksik"
    assert _get_country_filter(q) == "TR"
    assert q.get("size") == 1


def test_suffix_fuzzy_must_queries_variations_stripped():
    """must clause variations_stripped alanını sorgulamalı."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    clause = nested["query"]["match_phrase"]["variations_stripped.name"]
    assert clause["query"] == "komerci limted"
    assert clause["analyzer"] == "stripped_search_analyzer_tr"


def test_suffix_fuzzy_should_queries_variations_suffix_with_fuzziness():
    """should clause variations_suffix alanını fuzzy sorgulamalı."""
    q = es_queries.SUFFIX_FUZZY("komerci limted", "TR")
    should = q["query"]["bool"]["should"]
    suffix_clauses = [
        c["match"]["variations_suffix"]
        for c in should
        if "match" in c and "variations_suffix" in c["match"]
    ]
    assert suffix_clauses, "variations_suffix fuzzy clause yok"
    clause = suffix_clauses[0]
    assert clause["fuzziness"] == "AUTO:4,7"
    assert clause["operator"] == "or"


def test_suffix_fuzzy_includes_country_filter():
    """SUFFIX_FUZZY country filter içermeli."""
    q = es_queries.SUFFIX_FUZZY("acme limted", "DE")
    assert _get_country_filter(q) == "DE"


def test_variations_suffix_mapping_has_explicit_search_analyzer():
    """variations_suffix alanı hem analyzer hem search_analyzer'ı açıkça tanımlamalı."""
    settings = build_index_settings(es=None)
    props = settings["mappings"]["properties"]
    suffix_field = props["variations_suffix"]
    assert suffix_field["analyzer"] == "standard"
    assert suffix_field.get("search_analyzer") == "standard"
