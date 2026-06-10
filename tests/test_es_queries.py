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


def test_ngram_match_uses_country_specific_analyzer():
    q = es_queries.NGRAM_MATCH("apple trading", "DE")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    match_clause = nested["query"]["match"]["variations_stripped.name.ngram"]
    analyzer = match_clause.get("analyzer")
    assert analyzer == "stripped_search_analyzer_de"


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


def test_suffix_fuzzy_should_clause_requires_minimum_should_match():
    """SUFFIX_FUZZY should clause'u minimum_should_match=1 içermeli (suffix match zorunlu)."""
    q = es_queries.SUFFIX_FUZZY("acme ltd", "TR")
    bool_q = q["query"]["bool"]

    # minimum_should_match kontrolü
    assert "minimum_should_match" in bool_q, "minimum_should_match eksik"
    assert bool_q["minimum_should_match"] >= 1, "minimum_should_match en az 1 olmalı"

    # should clause var ve boş değil
    assert "should" in bool_q, "should clause eksik"
    assert len(bool_q["should"]) >= 1, "should clause boş olmamalı"


def test_variations_suffix_mapping_has_explicit_search_analyzer():
    """variations_suffix alanı hem analyzer hem search_analyzer'ı açıkça tanımlamalı."""
    settings = build_index_settings(es=None)
    props = settings["mappings"]["properties"]
    suffix_field = props["variations_suffix"]
    assert suffix_field["analyzer"] == "standard"
    assert suffix_field.get("search_analyzer") == "standard"


def test_phonetic_match_blocks_empty_core():
    # SIFIR ayırt edici token (yalnızca yasal ek / coğrafi ad / çöp) → guard
    # devreye girer: eşleşmeyi imkânsız kılan sentinel query (çöp/magnet master'a
    # sızmayı önler). Fonetik alan temizliği (legal_fragment_stop) gerçek markaların
    # ayrımını zaten yaptığından guard yalnızca BOŞ çekirdeği bloklar.
    assert es_queries.PHONETIC_MATCH("S.A. DE C.V.", "MX") == es_queries.MATCH_NONE  # yalnızca suffix
    assert es_queries.PHONETIC_MATCH("MEXICO", "MX") == es_queries.MATCH_NONE        # yalnızca ülke adı (drop_geo)


def test_phonetic_match_adds_token_count_filter_es_side():
    """ES-tarafı coverage: es verildiğinde nested query'ye token_count term filtresi
    eklenir (subset over-merge'i ES eler; Python doğrulaması YOK)."""
    from unittest.mock import MagicMock
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "alcatel"}]}  # 1 token
    q = es_queries.PHONETIC_MATCH("ALCATEL S.A. DE C.V.", "MX", es=es)
    nested = next(c["nested"] for c in q["query"]["bool"]["must"] if "nested" in c)
    inner_filter = nested["query"]["bool"]["filter"]
    assert {"term": {"variations_stripped.name.token_count": 1}} in inner_filter


def test_phonetic_match_no_token_count_filter_without_es():
    """es yoksa (birim test) token_count hesaplanamaz → filtre eklenmez (graceful)."""
    q = es_queries.PHONETIC_MATCH("IGSA S.A. DE C.V.", "MX")
    nested = next(c["nested"] for c in q["query"]["bool"]["must"] if "nested" in c)
    assert nested["query"]["bool"]["filter"] == []


# ── Ayırt-edici çekirdek GATE (Round-3 #3) ─────────────────────────────────

def _es_returning(tokens):
    """stripped analyzer çıktısını taklit eden MagicMock es."""
    from unittest.mock import MagicMock
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": t} for t in tokens]}
    return es


def test_core_gate_blocks_single_char_residue():
    """Tek-harfe çöken çekirdek ('M S.A.'→'m') tüm matching stage'lerde MATCH_NONE →
    NEW_MASTER. Akronim magnet artığı (A-sınıfı) ve magnet-seed engellenir."""
    es = _es_returning(["m"])
    for fn in (es_queries.CANONICAL_EXACT, es_queries.STRIPPED_EXACT, es_queries.TOKEN_COVERAGE,
               es_queries.FUZZY_PHRASE, es_queries.SUFFIX_FUZZY):
        es_queries.clear_token_count_cache()
        assert fn("M S.A. DE C.V.", "MX", es=es) == es_queries.MATCH_NONE, fn.__name__


def test_core_gate_allows_distinctive_brand():
    """Gerçek marka (>=2-char alfabetik çekirdek) tüm stage'lerde geçer."""
    es = _es_returning(["siemens"])
    for fn in (es_queries.CANONICAL_EXACT, es_queries.STRIPPED_EXACT,
               es_queries.TOKEN_COVERAGE, es_queries.FUZZY_PHRASE):
        es_queries.clear_token_count_cache()
        assert fn("SIEMENS S.A. DE C.V.", "MX", es=es) != es_queries.MATCH_NONE, fn.__name__


def test_core_gate_two_char_brand_preserved():
    """2-harfli gerçek marka (VF/3M) korunur (MATCH_CORE_MIN_TOKEN_LEN=2)."""
    es_queries.clear_token_count_cache()
    assert es_queries.TOKEN_COVERAGE("VF OUTDOOR", "MX", es=_es_returning(["vf", "outdoor"])) != es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.FUZZY_PHRASE("3M", "MX", es=_es_returning(["3m"])) != es_queries.MATCH_NONE


def test_core_gate_numeric_only_blocked_in_fuzzy_allowed_in_stripped():
    """Salt-sayı çekirdek ('#N/A 300'→['300']): loose stage'lerde (require_alpha) bloklanır
    (B-sınıfı çöp sızma), STRIPPED_EXACT'te (tam eşleşme güvenli) izin verilir."""
    es = _es_returning(["300"])
    es_queries.clear_token_count_cache()
    assert es_queries.TOKEN_COVERAGE("#N/A 300", "MX", es=es) == es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.FUZZY_PHRASE("#N/A 300", "MX", es=es) == es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.STRIPPED_EXACT("300 S.A. DE C.V.", "MX", es=es) != es_queries.MATCH_NONE


def test_core_gate_inert_without_es():
    """es yoksa (birim test / eski çağrı yolu) guard devre dışı — mevcut davranış korunur."""
    assert es_queries.TOKEN_COVERAGE("M S.A.", "MX") != es_queries.MATCH_NONE
    assert es_queries.FUZZY_PHRASE("M S.A.", "MX") != es_queries.MATCH_NONE


# ── Çözüm A: ayırt-edici-çekirdek COVERAGE gate (Round-4) ──────────────────
# FUZZY_PHRASE / TOKEN_COVERAGE'a ES-side STRIPPED token_count eşitlik filtresi:
# kısa/kesik isim (SPM ⊂ SPM FLOW CONTROL) farklı core-count → master'a giremez.
# clean_analyzer DEĞİL (Round-3'te synonym genişlemesi recall'ı kırmıştı) — STRIPPED.

def _core_filter_terms(q):
    """Query'deki tüm variations_stripped.name.token_count term değerlerini topla."""
    terms = []
    for c in q["query"]["bool"]["must"]:
        nested = c.get("nested")
        if nested and nested.get("path") == "variations_stripped":
            for f in nested["query"]["bool"].get("filter", []):
                t = f.get("term", {})
                if "variations_stripped.name.token_count" in t:
                    terms.append(t["variations_stripped.name.token_count"])
    return terms


def test_fuzzy_phrase_adds_core_coverage_filter():
    """es verildiğinde FUZZY_PHRASE'e STRIPPED core-count term filtresi eklenir."""
    es_queries.clear_token_count_cache()
    es = _es_returning(["spm"])  # 1 ayırt edici token
    q = es_queries.FUZZY_PHRASE("SPM", "MX", es=es)
    assert q != es_queries.MATCH_NONE
    assert 1 in _core_filter_terms(q)


def test_token_coverage_adds_core_coverage_filter():
    """es verildiğinde TOKEN_COVERAGE'e STRIPPED core-count term filtresi eklenir."""
    es_queries.clear_token_count_cache()
    es = _es_returning(["amcor"])
    q = es_queries.TOKEN_COVERAGE("AMCOR", "MX", es=es)
    assert q != es_queries.MATCH_NONE
    assert 1 in _core_filter_terms(q)


def test_core_coverage_count_matches_distinctive_token_count():
    """Filtre değeri STRIPPED ayırt-edici token sayısına eşit (çok-token brand)."""
    es_queries.clear_token_count_cache()
    es = _es_returning(["flow", "control", "spm"])  # 3 token
    q = es_queries.FUZZY_PHRASE("SPM FLOW CONTROL", "MX", es=es)
    assert 3 in _core_filter_terms(q)


def test_core_coverage_inert_without_es():
    """es yoksa core-coverage filtresi eklenmez (graceful; mevcut yapı korunur)."""
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    assert _core_filter_terms(q) == []
    q2 = es_queries.TOKEN_COVERAGE("apple trading", "US")
    assert _core_filter_terms(q2) == []


def test_ngram_match_blocks_empty_core():
    # Faz 3: yalnızca yasal ek / ülke adı (0 ayırt edici token) → NGRAM bloklanır.
    assert es_queries.NGRAM_MATCH("S.A. DE C.V.", "MX") == es_queries.MATCH_NONE
    assert es_queries.NGRAM_MATCH("MEXICO", "MX") == es_queries.MATCH_NONE


def test_ngram_match_allows_distinctive_core():
    # Ayırt edici çekirdek varsa normal ngram query döner (precision'ı coverage gate sağlar).
    q = es_queries.NGRAM_MATCH("ALPI USA INC", "MX")
    assert q != es_queries.MATCH_NONE
    nested = next(c["nested"] for c in q["query"]["bool"]["must"] if "nested" in c)
    assert nested["query"]["match"]["variations_stripped.name.ngram"]["minimum_should_match"] == "75%"


def test_phonetic_match_allows_single_brand_core():
    # Tek AYIRT EDİCİ marka token'ı (yasal ek + coğrafi çıkınca) → ARTIK eşleşmeye
    # izin verilir; precision'ı fonetik alan temizliği sağlar (canlı: live_probe).
    for name in ("IGSA S.A. DE C.V.", "AUDI MEXICO S.A. DE C.V.", "DHL GLOBAL FORWARDING"):
        q = es_queries.PHONETIC_MATCH(name, "MX")
        assert q != es_queries.MATCH_NONE
        nested = next(c["nested"] for c in q["query"]["bool"]["must"] if "nested" in c)
        assert nested["path"] == "variations_stripped"
        assert _get_country_filter(q) == "MX"


# ─────────────────────────────────────────────────────────────────────
# _get_token_count memoization (perf — analyze round-trip'lerini azaltır)
# ─────────────────────────────────────────────────────────────────────

def test_get_token_count_memoizes_same_analyzer_text():
    """Aynı (analyzer, text) için es.indices.analyze YALNIZCA bir kez çağrılmalı."""
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"t": 1}, {"t": 2}, {"t": 3}]}

    a = es_queries._get_token_count(es, "ACME S.A. DE C.V.", "stripped_search_analyzer_mx")
    b = es_queries._get_token_count(es, "ACME S.A. DE C.V.", "stripped_search_analyzer_mx")
    assert a == b == 3
    assert es.indices.analyze.call_count == 1  # ikinci çağrı cache'ten


def test_get_token_count_distinct_keys_recompute():
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"t": 1}]}
    es_queries._get_token_count(es, "A", "an1")
    es_queries._get_token_count(es, "B", "an1")           # farklı text
    es_queries._get_token_count(es, "A", "an2")           # farklı analyzer
    assert es.indices.analyze.call_count == 3


def test_get_token_count_does_not_cache_errors():
    """Hata (exception) durumunda 0 döner ama CACHE'LENMEZ → sonraki çağrı tekrar dener."""
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.side_effect = [RuntimeError("down"), {"tokens": [{"t": 1}, {"t": 2}]}]
    first = es_queries._get_token_count(es, "X", "an")
    second = es_queries._get_token_count(es, "X", "an")
    assert first == 0          # hata → 0
    assert second == 2         # cache'lenmediği için yeniden denendi ve başardı
    assert es.indices.analyze.call_count == 2
