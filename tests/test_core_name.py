from core_name import normalize_core


def test_strips_mx_legal_suffix_single_token():
    assert normalize_core("WITTE, S.A. DE C.V.", "MX") == ("witte",)
    assert normalize_core("IGSA S.A. DE C.V.", "MX") == ("igsa",)


def test_keeps_distinctive_multi_token_core():
    assert normalize_core("AUDI MEXICO S.A. DE C.V.", "MX") == ("audi", "mexico")
    assert normalize_core("KOHLER DE MEXICO S.A. DE C.V.", "MX") == ("kohler", "mexico")


def test_drops_single_char_and_numeric_tokens():
    # "O-TEK" → "o" (tek harf, düşer) + "tek"
    assert normalize_core("O-TEK MEXICO, S.A. DE C.V.", "MX") == ("tek", "mexico")
    assert normalize_core("FORM 123 S.A. DE C.V.", "MX") == ("form",)


def test_empty_and_whitespace():
    assert normalize_core("", "MX") == ()
    assert normalize_core("   ", "MX") == ()


def test_preserves_business_words_from_multiword_suffix_phrases():
    # 'general'/'industrial'/'civil' yalnızca çok-kelimeli ek ifadelerinde geçer,
    # tek başına yasal ek değildir → silinmemeli.
    assert normalize_core("GENERAL ELECTRIC SA", "MX") == ("general", "electric")
    assert normalize_core("CIVIL ENGINEERING CO", "MX") == ("civil", "engineering")


def test_other_country_single_word_suffix():
    # Tek-kelimelik yasal ek (gmbh) farklı ülkede de strip edilir; country.upper() yolu.
    assert normalize_core("ACME GMBH", "de") == ("acme",)
