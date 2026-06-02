from core_name import best_core_coverage, core_token_coverage, normalize_core


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


# ---------------------------------------------------------------------------
# Çok-ülke (multi-country) doğruluk: MX'e özgü kısaltma parçaları (sc, rl, del,
# sa, de, cv...) BAŞKA ülkelere uygulanmamalı. Aksi halde DE/TR gibi ülkelerde
# meşru isim token'ları yanlışlıkla silinir (latent correctness trap).
# ---------------------------------------------------------------------------


def test_mx_fragments_not_stripped_for_other_countries():
    # 'del', 'sc', 'rl' MX yasal-ek kısaltma parçalarıdır; DE/TR'de meşru token.
    assert normalize_core("DEL MONTE", "DE") == ("del", "monte")
    assert normalize_core("SC JOHNSON", "TR") == ("sc", "johnson")
    assert normalize_core("RL POLK", "DE") == ("rl", "polk")


def test_mx_fragments_still_stripped_for_mx():
    # Regresyon koruması: MX'te bu parçalar HÂLÂ silinmeli (davranış korunur).
    assert normalize_core("DEL MONTE", "MX") == ("monte",)
    assert normalize_core("SC JOHNSON", "MX") == ("johnson",)
    assert normalize_core("RL POLK", "MX") == ("polk",)


def test_other_country_still_strips_genuine_legal_suffix():
    # Değişiklik dar kapsamlı: ortak (common) tek-kelimelik yasal ekler her
    # ülkede silinmeye devam eder — yalnızca MX'e özgü parçalar ülke-bazlıdır.
    assert normalize_core("ACME GMBH", "DE") == ("acme",)
    assert normalize_core("ACME LIMITED", "TR") == ("acme",)


# ---------------------------------------------------------------------------
# drop_geo: Coğrafi/jenerik non-distinctive token'lar (MX: 'mexico'/'mexicana')
# PHONETIC guard için ayırt edici sayılmaz. Varsayılan KAPALI (geri uyumluluk).
# ---------------------------------------------------------------------------


def test_drop_geo_collapses_geographic_token():
    # 'mexico' coğrafi gürültü → drop_geo ile düşer, geriye tek ayırt edici core kalır.
    assert normalize_core("AUDI MEXICO S.A. DE C.V.", "MX", drop_geo=True) == ("audi",)
    assert normalize_core("VIBRACOUSTIC DE MEXICO S.A. DE C.V.", "MX", drop_geo=True) == ("vibracoustic",)


def test_drop_geo_default_off_keeps_existing_behaviour():
    # Varsayılan (drop_geo=False) davranış korunur — detektörler etkilenmez.
    assert normalize_core("AUDI MEXICO S.A. DE C.V.", "MX") == ("audi", "mexico")


def test_drop_geo_only_for_country_with_geo_set():
    # MX dışı ülkede 'mexico' coğrafi-stopword DEĞİL → korunur.
    assert normalize_core("ALFA MEXICO", "TR", drop_geo=True) == ("alfa", "mexico")


def test_drop_geo_keeps_two_distinctive_with_mx_suffix():
    # MX yasal ekleri çıkınca iki AYIRT EDİCİ token kalıyorsa guard'a takılmamalı.
    assert normalize_core(
        "VOLKSWAGEN COMERCIALIZADORA S.A. DE C.V.", "MX", drop_geo=True
    ) == ("volkswagen", "comercializadora")


# ---------------------------------------------------------------------------
# core_token_coverage / best_core_coverage — Faz 2 post-verify metriği
# ---------------------------------------------------------------------------


def test_core_token_coverage_jaccard():
    assert core_token_coverage(("a", "b"), ("a", "b")) == 1.0
    assert core_token_coverage(("a",), ("a", "b")) == 0.5      # subset
    assert core_token_coverage(("a",), ("b", "c")) == 0.0      # disjoint
    assert core_token_coverage((), ("a",)) == 0.0


def test_best_core_coverage_same_firm_high():
    # Aynı firma (suffix/coğrafi varyant) → tam örtüşme (geo düşer).
    assert best_core_coverage(
        "VIBRACOUSTIC DE MEXICO S.A. DE C.V.",
        ["VIBRACOUSTIC DE MEXICO, S.A. DE C.V."], "MX"
    ) == 1.0
    assert best_core_coverage(
        "DHL GLOBAL FORWARDING", ["DHL GLOBAL FORWARDING MEXICO"], "MX"
    ) == 1.0


def test_best_core_coverage_subset_overmerge_low():
    # Subset over-merge: ALCATEL ⊂ ALCATEL-LUCENT → düşük örtüşme (gate yakalamalı).
    cov = best_core_coverage("ALCATEL", ["ALCATEL LUCENT"], "MX")
    assert cov == 0.5
    # Tamamen farklı çekirdek → 0.
    assert best_core_coverage("ENERGY CORPORATION", ["ALKHORAYEF PETROLEUM"], "MX") == 0.0


def test_best_core_coverage_empty_query_returns_one():
    # Boş çekirdek (yalnızca suffix) → 1.0 (çift-bloklamayı önler; guard işi).
    assert best_core_coverage("S.A. DE C.V.", ["WHATEVER SA"], "MX") == 1.0
