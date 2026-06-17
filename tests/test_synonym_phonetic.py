"""Fonetik typo-rescue altin-kume testleri.

NOT: Bu testler bu branch'te KOSULMAZ (kullanici talebi). Reindex/rematch ONCESI
test izni olan ortamda MUTLAKA kosulmali — marka over-rescue'yi yakalamanin tek yolu.
"""
from core.synonym_phonetic import canonicalize_phonetic, build_synonym_phonetic_map


def test_typod_legal_suffix_rescued_to_canonical():
    out = canonicalize_phonetic("acme limmtd", "TR")
    assert "acme" in out
    assert "ltd" in out
    assert "limmtd" not in out


def test_typod_sector_rescued():
    out = canonicalize_phonetic("apex internacaonal", "TR")
    assert "apex" in out
    assert "international" in out


def test_real_brand_not_rescued():
    for brand in ["santander", "halliburton", "siemens", "flextronics", "vibracoustic"]:
        out = canonicalize_phonetic(brand, "TR")
        assert out == brand, f"marka degismemeli: {brand} -> {out}"


def test_exact_synonym_token_untouched_passthrough():
    out = canonicalize_phonetic("acme ltd", "TR")
    assert "acme" in out and "ltd" in out


def test_short_tokens_not_rescued():
    out = canonicalize_phonetic("vf sa", "TR")
    assert "vf" in out


def test_ambiguous_metaphone_excluded_from_map():
    m = build_synonym_phonetic_map("TR")
    assert all(isinstance(v, str) for v in m.values())


def test_digits_token_not_rescued():
    out = canonicalize_phonetic("3m mexico", "MX")
    assert "3m" in out
