# tests/test_synonym_loader.py
from core.synonym_loader import (
    get_all_company_type_tokens,
    get_all_legal_suffix_fragments,
    get_article_stopwords,
    get_company_type_tokens,
    get_country_name_tokens,
    get_legal_suffix_fragments,
)


def test_legal_suffix_fragments_derived_from_json_not_hardcoded():
    """MX yasal-ek parçaları legal_suffixes ifadelerinden türetilmeli (hardcode değil)."""
    mx = get_legal_suffix_fragments("MX")
    # 'S.A. DE C.V.' / 'S. DE R.L.' parçaları:
    assert {"s", "a", "c", "v", "sa", "cv", "rl", "sc", "del"} <= mx
    # Tam iş kelimeleri (len>4) parça olarak SIZMAMALI — aksi halde meşru isimler silinir.
    assert "general" not in mx
    assert "civil" not in mx
    assert "company" not in mx


def test_legal_suffix_fragments_country_specific():
    # Türetme ülkeye özgüdür: MX dosyası olmayan ülke yalnızca common parçalarını alır.
    mx = get_legal_suffix_fragments("MX")
    de = get_legal_suffix_fragments("DE")
    # MX'e özgü 'sapi' DE'de olmamalı (DE dosyasında yoksa).
    assert "sapi" in mx
    assert "sapi" not in de


def test_all_legal_suffix_fragments_is_union():
    frags = get_all_legal_suffix_fragments()
    assert {"sa", "cv", "de", "s", "a", "c", "v"} <= frags
    assert "general" not in frags


def test_country_name_tokens_derived_from_countries_json():
    mx = get_country_name_tokens("MX")
    assert "mexico" in mx
    # Çok-kelimeli uzun ad (United Mexican States) ayrıştırılmaz → jenerik sızıntı yok.
    assert "united" not in mx
    assert "states" not in mx
    # Başka ülke için 'mexico' dönmemeli.
    assert "mexico" not in get_country_name_tokens("TR")


def test_get_company_type_tokens_includes_common_tokens():
    """common.json legal_suffixes tokenları her ülke için dahil edilmeli.

    Sprint 2 note: get_company_type_tokens is now a shim over
    get_legal_suffix_tokens. Sector/role words (e.g. "holding") live in
    business_sectors now and should NOT appear here.
    """
    tokens = get_company_type_tokens("TR")
    assert "corp" in tokens
    assert "inc" in tokens
    assert "limited" in tokens
    # "holding" is a business sector in Sprint 2 and must not leak in
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
    """Sprint 2: ulke dosyasi yeni sema (legal_suffixes) ile migrate edildiginde
    ulkeye ozgu tokenlar da dahil edilmeli. Shu an sadece in.json yeni
    semaya gectigi icin IN uzerinden kontrol ediyoruz.

    NOT: tr.json / de.json / us.json hala eski 'company_types' semasini
    kullaniyor — bu dosyalar sonraki tasklarda migrate edildiginde tests
    genisletilebilir (TR: 'aş', 'komandit', DE: 'gmbh' vb.).
    """
    in_tokens = get_company_type_tokens("IN")
    # IN-specific legal suffixes from in.json
    assert "opc" in in_tokens
    assert "huf" in in_tokens
    assert "nidhi" in in_tokens
    # Common legal suffixes must still flow through
    assert "ltd" in in_tokens
    assert "pvt" in in_tokens


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


def test_get_company_type_tokens_equals_legal_suffixes():
    """Sprint 2: get_company_type_tokens is a shim over get_legal_suffix_tokens."""
    from core.synonym_loader import get_company_type_tokens, get_legal_suffix_tokens
    assert get_company_type_tokens("IN") == get_legal_suffix_tokens("IN")


def test_get_legal_suffix_tokens_returns_frozenset():
    """Sprint 2: get_legal_suffix_tokens reads the 'legal_suffixes' category
    from common.json plus the per-country file."""
    from core.synonym_loader import get_legal_suffix_tokens

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
    from core.synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    for sector in ("pharma", "chemicals", "industries", "enterprises",
                   "trading", "international", "technologies"):
        assert sector not in tokens, f"{sector!r} leaked into legal_suffixes"


def test_get_legal_suffix_tokens_excludes_foreign_suffixes():
    """Sprint 2 fix: 'ab' (Swedish) and 'as' (Norwegian/Latvian) must NOT
    appear in IN legal suffixes. other.json is archived."""
    from core.synonym_loader import get_legal_suffix_tokens

    tokens = get_legal_suffix_tokens("IN")
    # These caused the BABA WOOD PRODUCTS false positive before Sprint 2.
    assert "ab" not in tokens, "Swedish 'ab' leaking into IN suffixes"
    assert "as" not in tokens, "Norwegian 'as' leaking into IN suffixes"


def test_get_business_sector_tokens_returns_frozenset():
    """Sprint 2: business sector tokens are preserved, not stripped."""
    from core.synonym_loader import get_business_sector_tokens

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
    from core.synonym_loader import (
        get_business_sector_tokens,
        get_legal_suffix_tokens,
    )

    sectors = get_business_sector_tokens("IN")
    legal = get_legal_suffix_tokens("IN")
    overlap = sectors & legal
    assert not overlap, f"Categories must be disjoint, overlap={sorted(overlap)}"


def test_get_business_sector_canonical_map_maps_to_rule_target():
    """Each source token on the left of => maps to the rule's canonical target."""
    from core.synonym_loader import get_business_sector_canonical_map

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


def test_geo_stopword_tokens_excludes_short_iso_codes():
    """A1/HIGH-2: global geo-stop tam ülke adlarını (argentina, brasil, mexico) içerir
    ama kısa ISO kodlarını (ar, br, us, mx, arg, bra) HARİÇ tutar — kısa kodlar marka
    token'larıyla çakışır (GE HEALTHCARE, US BANK). Kaynak countries.json (hardcode yok)."""
    from core.synonym_loader import get_geo_stopword_tokens
    geo = {t.lower() for t in get_geo_stopword_tokens()}
    # Tam adlar dahil
    assert "argentina" in geo
    assert "brasil" in geo or "brazil" in geo
    # Kısa ISO kodları hariç (len<4)
    for short in ["ar", "br", "us", "mx", "pe", "ge", "es", "arg", "bra", "usa"]:
        assert short not in geo, f"kısa kod {short!r} geo-stop'ta OLMAMALI (marka çakışması)"
    # Hepsi >= 4 karakter
    assert all(len(t) >= 4 for t in geo)


def test_country_geo_stopwords_only_own_country():
    """Per-country geo-stop YALNIZCA ülkenin kendi ad token'larını içerir; başka
    ülkelerin adları (BR'de 'mexico') o shard'da ayırt edici sinyaldir → STRIP EDİLMEZ.
    Kısa ISO kodları (br/bra) marka çakışması riskiyle hariç. Kaynak countries.json."""
    from core.synonym_loader import get_country_geo_stopwords
    br = {t.lower() for t in get_country_geo_stopwords("BR")}
    # Kendi adı dahil
    assert "brasil" in br or "brazil" in br
    # Başka ülke adları HARİÇ (per-country izolasyon)
    assert "mexico" not in br
    assert "argentina" not in br
    # Kısa ISO kodları hariç (len < 4)
    for short in ["br", "bra"]:
        assert short not in br, f"kısa kod {short!r} per-country geo-stop'ta OLMAMALI"
    assert all(len(t) >= 4 for t in br)


def test_get_synonym_canonical_map_maps_source_to_target():
    from core.synonym_loader import get_synonym_canonical_map
    m = get_synonym_canonical_map("TR", ("legal_suffixes",))
    assert m.get("inc") == "corp." or m.get("inc") == "inc."
    ms = get_synonym_canonical_map("TR", ("business_sectors",))
    assert ms.get("traders") == "trading"
    assert ms.get("trading") == "trading"
    ma = get_synonym_canonical_map("TR", ("address_abbreviations",))
    assert ma.get("ave") == "ave."
    assert ma.get("avenue") == "ave."


def test_get_address_tokens_includes_common_address_words():
    from core.synonym_loader import get_address_tokens
    toks = get_address_tokens("TR")
    assert "street" in toks
    assert "avenue" in toks
    assert "st" in toks
    assert "pharma" not in toks
