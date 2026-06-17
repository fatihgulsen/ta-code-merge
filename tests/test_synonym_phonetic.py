"""Fonetik typo-rescue altın-küme testleri.

NOT: Bu testler bu branch'te KOŞULMAZ (kullanıcı talebi). Reindex/rematch ÖNCESİ
test izni olan ortamda MUTLAKA koşulmalı — marka over-rescue'yi yakalamanın tek yolu.
"""
from core.synonym_phonetic import canonicalize_phonetic, build_synonym_phonetic_map


def test_truncation_typo_legal_rescued():
    # limtd -> 'ltd.' (LMT prefix-of LMTT)
    out = canonicalize_phonetic("acme limtd", "TR")
    assert "acme" in out and "ltd" in out and "limtd" not in out


def test_substitution_typo_sector_rescued():
    # internacaonal -> 'international' (aynı uzunluk, 1 sub)
    out = canonicalize_phonetic("apex internacaonal", "TR")
    assert "apex" in out and "international" in out


def test_vowel_noise_typo_rescued():
    # tradng -> 'trading' (kod eşit), avenu -> 'ave.' (kod eşit)
    assert "trading" in canonicalize_phonetic("xyz tradng", "TR")
    assert "ave" in canonicalize_phonetic("xyz avenu", "TR")


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


def test_digits_token_not_rescued():
    out = canonicalize_phonetic("3m mexico", "MX")
    assert "3m" in out


def test_build_map_is_first_char_bucketed():
    m = build_synonym_phonetic_map("TR")
    assert isinstance(m, dict)
    for k, v in m.items():
        assert len(k) == 1 and isinstance(v, tuple)
        for code, canon in v:
            assert isinstance(code, str) and isinstance(canon, str)
