"""Synonym-içi fonetik typo-rescue.

Çekirdeğe sızan bozuk-yazımlı synonym token'larını (suffix/sector/address) double-metaphone
ile tespitleyip kanonik forma çevirir. Eşleşme: metaphone kodu TAM eşit, PREFIX (truncation
typo, uzunluk farkı <=2), ya da AYNI-UZUNLUKTA <=1 karakter fark (substitution). Markaya
dokunma riski guard'larla sınırlanır: token len>=5, synonym kaynağı len>=4, kod len>=3, ve
AMBIGUITY guard (token >1 FARKLI kanonike uyarsa rescue YOK). first-char bucket ile perf.
Geo + article KAPSAM DIŞI (geo ISO-kanonik / article çok kısa).
"""
from functools import lru_cache

from metaphone import doublemetaphone

from core.synonym_loader import get_synonym_canonical_map

_RESCUE_CATEGORIES = ("legal_suffixes", "business_sectors", "address_abbreviations")

MIN_TOKEN_LEN = 5          # sorgu token'ı (kısa marka/akronim korunur)
MIN_SYNONYM_SRC_LEN = 4    # synonym kaynak token'ı
MIN_CODE_LEN = 3           # fuzzy için min metaphone kod uzunluğu
_MAX_PREFIX_DIFF = 2       # prefix eşleşmede izinli uzunluk farkı


def _primary_code(token: str) -> str:
    code, _ = doublemetaphone(token)
    return code or ""


def _code_matches(tc: str, sc: str) -> bool:
    """Token kodu tc, synonym kodu sc ile fonetik eşleşiyor mu? (eşit/prefix/sub-1)."""
    if tc == sc:
        return True
    if len(tc) < MIN_CODE_LEN or len(sc) < MIN_CODE_LEN:
        return False
    shorter, longer = (tc, sc) if len(tc) <= len(sc) else (sc, tc)
    if longer.startswith(shorter) and (len(longer) - len(shorter)) <= _MAX_PREFIX_DIFF:
        return True
    if len(tc) == len(sc) and sum(a != b for a, b in zip(tc, sc)) <= 1:
        return True
    return False


@lru_cache(maxsize=None)
def _exact_synonym_sources(country_code: str) -> frozenset:
    """Rescue kategorilerindeki TÜM tam synonym kaynak token'ları (dokunulmayacaklar)."""
    cc = country_code.upper()
    return frozenset(get_synonym_canonical_map(cc, _RESCUE_CATEGORIES).keys())


@lru_cache(maxsize=None)
def build_synonym_phonetic_map(country_code: str) -> dict:
    """{ilk_char: ((metaphone_code, kanonik), ...)} — kod ilk-harfine göre bucket.

    len>=MIN_SYNONYM_SRC_LEN alfabetik kaynaklar; (code, canon) tekilleştirilir.
    Ambiguity match-zamanında çözülür (canonicalize_phonetic).
    """
    cc = country_code.upper()
    canon_map = get_synonym_canonical_map(cc, _RESCUE_CATEGORIES)
    buckets: dict[str, list] = {}
    seen = set()
    for src, canon in canon_map.items():
        if len(src) < MIN_SYNONYM_SRC_LEN or not src.isalpha():
            continue
        code = _primary_code(src)
        if not code:
            continue
        key = (code, canon)
        if key in seen:
            continue
        seen.add(key)
        buckets.setdefault(code[0], []).append(key)
    return {k: tuple(v) for k, v in buckets.items()}


@lru_cache(maxsize=100_000)
def canonicalize_phonetic(name: str, country_code: str) -> str:
    """İsimdeki bozuk-yazımlı synonym token'larını kanonik forma çevirir (marka-korumalı).

    Token zaten tam-synonym ise / kısa ise / alfabetik değilse → dokunma. Aksi halde
    metaphone'u synonym kodlarıyla _code_matches eden TEK kanonik varsa → çevir; 0 veya
    >1 (ambiguous) ise → koru.
    """
    if not name:
        return name
    cc = country_code.upper()
    exact_sources = _exact_synonym_sources(cc)
    buckets = build_synonym_phonetic_map(cc)
    out_tokens = []
    for tok in name.split():
        bare = tok.lower().replace(".", "")
        if bare in exact_sources or len(bare) < MIN_TOKEN_LEN or not bare.isalpha():
            out_tokens.append(tok)
            continue
        tc = _primary_code(bare)
        if not tc:
            out_tokens.append(tok)
            continue
        cands = {canon for (code, canon) in buckets.get(tc[0], ()) if _code_matches(tc, code)}
        out_tokens.append(cands.pop() if len(cands) == 1 else tok)
    return " ".join(out_tokens)
