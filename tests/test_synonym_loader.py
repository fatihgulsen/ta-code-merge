# tests/test_synonym_loader.py
from synonym_loader import get_company_type_tokens, get_all_company_type_tokens, get_article_stopwords


def test_get_company_type_tokens_includes_common_tokens():
    """common.json company_types tokenları her ülke için dahil edilmeli.

    Sprint 1 note: BUSINESS_DESCRIPTORS (e.g. "holding") are now subtracted
    from the returned set — legal suffixes stay, sector/role words leave.
    """
    tokens = get_company_type_tokens("TR")
    assert "corp" in tokens
    assert "inc" in tokens
    assert "limited" in tokens
    # "holding" is a business descriptor and must be stripped out
    assert "holding" not in tokens


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


def test_get_company_type_tokens_excludes_business_descriptors():
    """Sprint 1: get_company_type_tokens must subtract BUSINESS_DESCRIPTORS so
    that stripping pipelines do not remove sector/role words."""
    from synonym_loader import get_company_type_tokens
    from config import BUSINESS_DESCRIPTORS

    tokens = get_company_type_tokens("IN")

    # Legal suffixes must still be present
    for legal in ("ltd", "pvt", "inc", "llp", "opc", "huf"):
        assert legal in tokens, f"Expected legal suffix {legal!r} in IN tokens"

    # Sector/role words must NOT be present
    for sector in ("pharma", "chemicals", "auto", "electronics", "steel",
                   "industries", "traders", "enterprises", "international",
                   "agencies", "overseas", "global"):
        assert sector not in tokens, (
            f"Sector token {sector!r} leaked into company_type tokens for IN"
        )

    # Guard must not produce intersection with BUSINESS_DESCRIPTORS
    assert tokens.isdisjoint(BUSINESS_DESCRIPTORS)


def test_get_legal_suffix_tokens_returns_frozenset():
    """Sprint 2: get_legal_suffix_tokens reads the 'legal_suffixes' category
    from common.json plus the per-country file."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    assert isinstance(tokens, frozenset)
    # Universal English legal forms from common.json
    for expected in ("ltd", "inc", "corp", "llc", "llp", "pvt"):
        assert expected in tokens, f"{expected!r} missing from IN legal suffixes"
    # IN-specific legal forms from in.json
    for expected in ("opc", "huf", "nidhi"):
        assert expected in tokens, f"{expected!r} (IN-specific) missing"


def test_get_legal_suffix_tokens_excludes_sectors():
    """Legal suffixes must NOT contain business sector words."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    for sector in ("pharma", "chemicals", "industries", "enterprises",
                   "trading", "international", "technologies"):
        assert sector not in tokens, f"{sector!r} leaked into legal_suffixes"


def test_get_legal_suffix_tokens_excludes_foreign_suffixes():
    """Sprint 2 fix: 'ab' (Swedish) and 'as' (Norwegian/Latvian) must NOT
    appear in IN legal suffixes. other.json is archived."""
    from synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    # These caused the BABA WOOD PRODUCTS false positive before Sprint 2.
    assert "ab" not in tokens, "Swedish 'ab' leaking into IN suffixes"
    assert "as" not in tokens, "Norwegian 'as' leaking into IN suffixes"


def test_get_business_sector_tokens_returns_frozenset():
    """Sprint 2: business sector tokens are preserved, not stripped."""
    from synonym_loader import get_business_sector_tokens

    tokens = get_business_sector_tokens("IN")
    assert isinstance(tokens, frozenset)
    # Universal sectors from common.json
    for expected in ("industries", "enterprises", "trading", "international",
                     "technologies", "services", "solutions"):
        assert expected in tokens
    # IN-specific sectors
    for expected in ("pharma", "chemicals", "auto", "electronics", "steel"):
        assert expected in tokens


def test_get_business_sector_tokens_excludes_legal_suffixes():
    """Business sectors and legal suffixes are disjoint."""
    from synonym_loader import (
        get_business_sector_tokens,
        get_legal_suffix_tokens,
    )

    sectors = get_business_sector_tokens("IN")
    legal = get_legal_suffix_tokens("IN")
    overlap = sectors & legal
    assert not overlap, f"Categories must be disjoint, overlap={sorted(overlap)}"


def test_get_business_sector_canonical_map_maps_to_rule_target():
    """Each source token on the left of => maps to the rule's canonical target."""
    from synonym_loader import get_business_sector_canonical_map

    mapping = get_business_sector_canonical_map("IN")
    # Regular plurals
    assert mapping.get("enterprise") == "enterprises"
    assert mapping.get("enterprises") == "enterprises"
    # Irregular plurals handled via explicit rule target
    assert mapping.get("industry") == "industries"
    assert mapping.get("industries") == "industries"
    assert mapping.get("technology") == "technologies"
    assert mapping.get("technologies") == "technologies"
    # Abbreviations canonicalise to full form
    assert mapping.get("tech") == "technologies"
    assert mapping.get("intl") == "international"
    # Sector words from IN-specific file
    assert mapping.get("pharmaceutical") == "pharma"
    assert mapping.get("pharmaceuticals") == "pharma"
