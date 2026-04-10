# tests/test_synonym_loader.py
from synonym_loader import get_company_type_tokens, get_all_company_type_tokens, get_article_stopwords


def test_get_company_type_tokens_includes_common_tokens():
    """common.json company_types tokenları her ülke için dahil edilmeli."""
    tokens = get_company_type_tokens("TR")
    assert "corp" in tokens
    assert "inc" in tokens
    assert "limited" in tokens
    assert "holding" in tokens


def test_get_company_type_tokens_strips_dots():
    """Nokta karakterleri tamamen çıkarılmalı."""
    tokens = get_company_type_tokens("US")
    assert "corp" in tokens
    assert "corp." not in tokens
    assert "inc" in tokens
    assert "inc." not in tokens


def test_get_company_type_tokens_lowercase():
    """Tüm tokenlar lowercase olmalı."""
    tokens = get_company_type_tokens("TR")
    for t in tokens:
        assert t == t.lower(), f"Token '{t}' lowercase değil"


def test_get_company_type_tokens_includes_both_sides_of_arrow():
    """=> solundaki ve sağındaki tokenlar dahil edilmeli."""
    tokens = get_company_type_tokens("TR")
    assert "corporation" in tokens
    assert "corp" in tokens
    assert "company" in tokens


def test_get_company_type_tokens_country_specific():
    """Ülkeye özgü tokenlar da dahil edilmeli."""
    tr_tokens = get_company_type_tokens("TR")
    de_tokens = get_company_type_tokens("DE")
    # tr.json has "anonim şirket,...,a.ş. => a.ş." → dots removed → "aş"
    assert "aş" in tr_tokens
    # de.json has gmbh (also present in other.json which is a common file loaded for all)
    assert "gmbh" in de_tokens
    # TR-specific token "komandit" is also in tr_tokens (via tr.json or other.json)
    assert "komandit" in tr_tokens
    # DE-specific form "gesellschaft mit beschränkter haftung" is in de_tokens
    assert "gesellschaft mit beschränkter haftung" in de_tokens


def test_get_company_type_tokens_lru_cache():
    """lru_cache sayesinde aynı nesne döndürülmeli."""
    tokens1 = get_company_type_tokens("TR")
    tokens2 = get_company_type_tokens("TR")
    assert tokens1 is tokens2


def test_get_all_company_type_tokens_is_superset():
    """Global set, her ülke setinin süperkümesi olmalı."""
    tr_tokens = get_company_type_tokens("TR")
    de_tokens = get_company_type_tokens("DE")
    all_tokens = get_all_company_type_tokens()
    assert tr_tokens.issubset(all_tokens)
    assert de_tokens.issubset(all_tokens)


def test_get_all_company_type_tokens_nonempty():
    """Global set boş olmamalı."""
    all_tokens = get_all_company_type_tokens()
    assert len(all_tokens) > 20


def test_get_article_stopwords_returns_frozenset():
    """Dönüş tipi frozenset olmalı."""
    result = get_article_stopwords("TR")
    assert isinstance(result, frozenset)


def test_get_article_stopwords_contains_common_articles():
    """common.json articles her ülke için yüklenmeli."""
    result = get_article_stopwords("TR")
    assert "and" in result
    assert "of" in result
    assert "the" in result
    assert "de" in result
    assert "von" in result


def test_get_article_stopwords_unknown_country_returns_common():
    """Ülke dosyası olmayan ülke için sadece common articles döner."""
    result = get_article_stopwords("XX")
    assert "and" in result
    assert isinstance(result, frozenset)


def test_get_article_stopwords_falls_back_to_common():
    """articles key'i olmayan dosya için boş ek döner (ortak yeterli)."""
    # Herhangi bir ülke için common articles mutlaka gelir
    result = get_article_stopwords("US")
    assert "for" in result and "und" in result


def test_get_article_stopwords_lru_cache():
    """lru_cache sayesinde aynı nesne döndürülmeli."""
    r1 = get_article_stopwords("TR")
    r2 = get_article_stopwords("TR")
    assert r1 is r2
