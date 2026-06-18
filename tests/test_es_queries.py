# tests/test_es_queries.py
import es.queries as es_queries


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
    assert any("term" in f and "variations.name.token_count" in f["term"] for f in inner_filters)


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



def test_fuzzy_phrase_has_slop():
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    must = q["query"]["bool"]["must"]
    nested = next(c["nested"] for c in must if "nested" in c)
    phrase = nested["query"]["match_phrase"]["variations.name"]
    assert phrase.get("slop", 0) >= 1



def test_all_queries_include_country_filter():
    name = "test company"
    country = "FR"
    # TOKEN_COVERAGE requires es (no es → MATCH_NONE by design); test only es-independent stages.
    fns = [
        lambda: es_queries.CANONICAL_EXACT(name, country),
        lambda: es_queries.FUZZY_PHRASE(name, country),
    ]
    for fn in fns:
        assert _get_country_filter(fn()) == country, f"{fn} country filter eksik"


# ── Ayırt-edici çekirdek GATE (Round-3 #3) ─────────────────────────────────

def _es_returning(tokens):
    """stripped analyzer çıktısını taklit eden MagicMock es."""
    from unittest.mock import MagicMock
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": t} for t in tokens]}
    return es


def test_core_gate_blocks_single_char_residue():
    """Tek-harfe çöken çekirdek ('M S.A.'→'m') CANONICAL_EXACT ve FUZZY_PHRASE'de MATCH_NONE.
    TOKEN_COVERAGE kendi fingerprint gate'ini kullanır (ayrı test); buradan çıkarıldı."""
    es = _es_returning(["m"])
    for fn in (es_queries.CANONICAL_EXACT, es_queries.FUZZY_PHRASE):
        es_queries.clear_token_count_cache()
        assert fn("M S.A. DE C.V.", "MX", es=es) == es_queries.MATCH_NONE, fn.__name__


def test_core_gate_allows_distinctive_brand():
    """Gerçek marka (>=2-char alfabetik çekirdek) tüm stage'lerde geçer."""
    es = _es_returning(["siemens"])
    for fn in (es_queries.CANONICAL_EXACT, es_queries.TOKEN_COVERAGE, es_queries.FUZZY_PHRASE):
        es_queries.clear_token_count_cache()
        assert fn("SIEMENS S.A. DE C.V.", "MX", es=es) != es_queries.MATCH_NONE, fn.__name__


def test_core_gate_two_char_brand_preserved():
    """2-harfli gerçek marka (VF/3M) korunur (MATCH_CORE_MIN_TOKEN_LEN=2)."""
    es_queries.clear_token_count_cache()
    assert es_queries.TOKEN_COVERAGE("VF OUTDOOR", "MX", es=_es_returning(["vf", "outdoor"])) != es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.FUZZY_PHRASE("3M", "MX", es=_es_returning(["3m"])) != es_queries.MATCH_NONE


def test_core_gate_numeric_only_blocked_in_fuzzy_stages():
    """Salt-sayı çekirdek ('#N/A 300'→['300']): loose stage'lerde (require_alpha) bloklanır
    (B-sınıfı çöp sızma)."""
    es = _es_returning(["300"])
    es_queries.clear_token_count_cache()
    assert es_queries.TOKEN_COVERAGE("#N/A 300", "MX", es=es) == es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.FUZZY_PHRASE("#N/A 300", "MX", es=es) == es_queries.MATCH_NONE


def test_generic_core_gate_blocks_solo_generic_word():
    """Jenerik-kelime magnet fix: stripped çekirdek YALNIZCA jenerik iş-kelimesi ('trading',
    'importaciones', 'inversiones', 'group') ise CANONICAL_EXACT ve FUZZY_PHRASE'de MATCH_NONE.
    TOKEN_COVERAGE kendi fingerprint gate'ini kullanır (generic-word blocking bu stage'de
    _has_distinctive_core yerine fingerprint+canonical_full üzerinden gelir)."""
    for word in ("trading", "importaciones", "inversiones", "group"):
        es = _es_returning([word])
        for fn in (es_queries.CANONICAL_EXACT, es_queries.FUZZY_PHRASE):
            es_queries.clear_token_count_cache()
            assert fn(f"L M {word.upper()} S.A.", "PE", es=es) == es_queries.MATCH_NONE, \
                f"{fn.__name__} salt-jenerik '{word}' çekirdeğini bloklamalı"


def test_generic_core_gate_allows_brand_plus_generic():
    """Çok-token çekirdekte ≥1 jenerik-OLMAYAN token varsa ayırt edicidir → geçer.
    'KIMBERLY CLARK' (marka) ve 'APEX TRADING' (apex ayırt edici) korunur."""
    es_queries.clear_token_count_cache()
    assert es_queries.CANONICAL_EXACT("KIMBERLY CLARK S.A.", "PE",
                                      es=_es_returning(["kimberly", "clark"])) != es_queries.MATCH_NONE
    es_queries.clear_token_count_cache()
    assert es_queries.TOKEN_COVERAGE("APEX TRADING", "PE",
                                     es=_es_returning(["apex", "trading"])) != es_queries.MATCH_NONE


def test_core_gate_inert_without_es():
    """es yoksa FUZZY_PHRASE guard devre dışı — mevcut davranış korunur.
    TOKEN_COVERAGE es olmadan MATCH_NONE döner (canonical_full exact-match gerektiriyor)."""
    assert es_queries.TOKEN_COVERAGE("M S.A.", "MX") == es_queries.MATCH_NONE
    assert es_queries.FUZZY_PHRASE("M S.A.", "MX") != es_queries.MATCH_NONE


# ── Çözüm A: ayırt-edici-çekirdek COVERAGE gate (Round-4, clean_analyzer) ──
# FUZZY_PHRASE / TOKEN_COVERAGE'a ES-side clean_analyzer token_count eşitlik filtresi:
# kısa/kesik isim (SPM ⊂ SPM FLOW CONTROL) farklı core-count → master'a giremez.

def _core_filter_terms(q):
    """Query'deki tüm variations.name.token_count term değerlerini topla."""
    terms = []
    for c in q["query"]["bool"]["must"]:
        nested = c.get("nested")
        if nested and nested.get("path") == "variations":
            for f in nested.get("query", {}).get("bool", {}).get("filter", []):
                t = f.get("term", {})
                if "variations.name.token_count" in t:
                    terms.append(t["variations.name.token_count"])
    return terms


def test_fuzzy_phrase_adds_core_coverage_filter():
    """es verildiğinde FUZZY_PHRASE'e STRIPPED core-count term filtresi eklenir."""
    es_queries.clear_token_count_cache()
    es = _es_returning(["spm"])  # 1 ayırt edici token
    q = es_queries.FUZZY_PHRASE("SPM", "MX", es=es)
    assert q != es_queries.MATCH_NONE
    assert 1 in _core_filter_terms(q)


def test_core_coverage_count_matches_distinctive_token_count():
    """Filtre değeri STRIPPED ayırt-edici token sayısına eşit (çok-token brand)."""
    es_queries.clear_token_count_cache()
    es = _es_returning(["flow", "control", "spm"])  # 3 token
    q = es_queries.FUZZY_PHRASE("SPM FLOW CONTROL", "MX", es=es)
    assert 3 in _core_filter_terms(q)


def test_core_coverage_inert_without_es():
    """es yoksa FUZZY_PHRASE core-coverage filtresi eklenmez (graceful)."""
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    assert _core_filter_terms(q) == []



# ─────────────────────────────────────────────────────────────────────
# _get_token_count memoization (perf — analyze round-trip'lerini azaltır)
# ─────────────────────────────────────────────────────────────────────

def test_get_token_count_memoizes_same_analyzer_text():
    """Aynı (analyzer, text) için es.indices.analyze YALNIZCA bir kez çağrılmalı."""
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"t": 1}, {"t": 2}, {"t": 3}]}

    a = es_queries._get_token_count(es, "ACME S.A. DE C.V.", "stripped_search_analyzer_mx", "MX")
    b = es_queries._get_token_count(es, "ACME S.A. DE C.V.", "stripped_search_analyzer_mx", "MX")
    assert a == b == 3
    assert es.indices.analyze.call_count == 1  # ikinci çağrı cache'ten


def test_get_token_count_distinct_keys_recompute():
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"t": 1}]}
    es_queries._get_token_count(es, "A", "an1", "MX")
    es_queries._get_token_count(es, "B", "an1", "MX")    # farklı text
    es_queries._get_token_count(es, "A", "an2", "MX")    # farklı analyzer
    assert es.indices.analyze.call_count == 3


def test_get_token_count_does_not_cache_errors():
    """Hata (exception) durumunda 0 döner ama CACHE'LENMEZ → sonraki çağrı tekrar dener."""
    from unittest.mock import MagicMock
    es_queries.clear_token_count_cache()
    es = MagicMock()
    es.indices.analyze.side_effect = [RuntimeError("down"), {"tokens": [{"t": 1}, {"t": 2}]}]
    first = es_queries._get_token_count(es, "X", "an", "MX")
    second = es_queries._get_token_count(es, "X", "an", "MX")
    assert first == 0          # hata → 0
    assert second == 2         # cache'lenmediği için yeniden denendi ve başardı
    assert es.indices.analyze.call_count == 2


def test_analyze_index_uses_country_alias():
    from es.queries import _analyze_index
    assert _analyze_index("tr") == "living_companies_tr"


def test_analyze_index_respects_override(monkeypatch):
    import config
    monkeypatch.setattr(config, "ES_ANALYZE_INDEX_OVERRIDE", "probe_idx")
    from es.queries import _analyze_index
    assert _analyze_index("tr") == "probe_idx"


def test_is_address_dirty_true_when_address_only_no_core():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "street"}, {"token": "no"}]}
    assert q.is_address_dirty(es, "main street no 5", "TR") is True


def test_is_address_dirty_false_when_distinctive_core_present():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "apex"}, {"token": "street"}]}
    assert q.is_address_dirty(es, "apex street", "TR") is False


def test_is_address_dirty_false_when_no_address():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "apex"}, {"token": "pharma"}]}
    assert q.is_address_dirty(es, "apex pharma", "TR") is False


def test_is_address_dirty_false_when_es_none():
    import es.queries as q
    assert q.is_address_dirty(None, "main street", "TR") is False


def _es_by_analyzer(mapping, default=None):
    """body['analyzer'] adına göre farklı token listesi döndüren MagicMock es."""
    from unittest.mock import MagicMock
    es = MagicMock()
    def _analyze(index=None, body=None):
        analyzer = (body or {}).get("analyzer")
        toks = mapping.get(analyzer, default if default is not None else [])
        return {"tokens": [{"token": t} for t in toks]}
    es.indices.analyze.side_effect = _analyze
    return es


def test_get_canonical_full_returns_single_token():
    """_get_canonical_full, canonical_full_analyzer çıktısının ilk (tek) token'ını döner."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"canonical_full_analyzer_MX": ["cv de elektrokontakt rl s"]})
    assert es_queries._get_canonical_full(es, "ELEKTROKONTAKT SRL DE C.V.", "MX") == "cv de elektrokontakt rl s"


def test_get_canonical_full_uses_country_analyzer_name():
    """Bilinmeyen ülke → canonical_full_analyzer_common."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"canonical_full_analyzer_common": ["acme"]})
    assert es_queries._get_canonical_full(es, "ACME", "XX") == "acme"


def test_fingerprint_token_empty_for_legal_only():
    """fingerprint_analyzer boş token üretirse _fingerprint_token '' döner."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"fingerprint_analyzer": []})
    assert es_queries._fingerprint_token(es, "S. S. DE R.L. DE C.V.", "MX") == ""


def test_analyze_single_token_inert_without_es():
    """es None ise '' döner (graceful)."""
    assert es_queries._get_canonical_full(None, "ACME", "MX") == ""
    assert es_queries._fingerprint_token(None, "ACME", "MX") == ""


def _nested_filter_terms(q, field):
    """Nested variations bool.filter içindeki `field` term değerlerini toplar."""
    out = []
    for c in q.get("query", {}).get("bool", {}).get("must", []):
        nested = c.get("nested")
        if nested and nested.get("path") == "variations":
            for f in nested.get("query", {}).get("bool", {}).get("filter", []):
                t = f.get("term", {})
                if field in t:
                    out.append(t[field])
    return out


def test_token_coverage_uses_canonical_full_and_token_count():
    """TOKEN_COVERAGE canonical_full + token_count term-eşitliği kurar (operator:and YOK)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": ["acme gida"],
        "canonical_full_analyzer_MX": ["acme gida sa"],
        "clean_analyzer_MX": ["acme", "gida", "sa"],  # token_count = 3
    })
    q = es_queries.TOKEN_COVERAGE("ACME GIDA SA", "MX", es=es)
    assert q != es_queries.MATCH_NONE
    assert _nested_filter_terms(q, "variations.name.canonical_full") == ["acme gida sa"]
    assert _nested_filter_terms(q, "variations.name.token_count") == [3]
    assert _get_country_filter(q) == "MX"
    import json
    assert '"operator": "and"' not in json.dumps(q)


def test_token_coverage_match_none_when_fingerprint_empty():
    """Ayırt edici çekirdek yok (fingerprint boş) → MATCH_NONE (S. S. DE R.L. DE C.V.)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": [],  # boş çekirdek
        "canonical_full_analyzer_MX": ["cv de rl s"],
        "clean_analyzer_MX": ["s", "s", "de", "rl", "de", "cv"],
    })
    q = es_queries.TOKEN_COVERAGE("S. S. DE R.L. DE C.V.", "MX", es=es)
    assert q == es_queries.MATCH_NONE


def test_token_coverage_match_none_when_fingerprint_non_alpha():
    """fingerprint sadece sayısalsa loose-match yapılmaz (require_alpha semantiği korunur)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": ["12345"],
        "canonical_full_analyzer_MX": ["12345 sa"],
        "clean_analyzer_MX": ["12345", "sa"],
    })
    q = es_queries.TOKEN_COVERAGE("12345 SA", "MX", es=es)
    assert q == es_queries.MATCH_NONE


def test_token_coverage_match_none_without_es():
    """es yoksa exact-match kurulamaz → MATCH_NONE."""
    assert es_queries.TOKEN_COVERAGE("apple trading", "US") == es_queries.MATCH_NONE
