"""Synonym-ici fonetik typo-rescue.

Cekirdege sizان bozuk-yazimli synonym token'larini (suffix/sector/address) double-metaphone
ile tespitleyip kanonik forma cevirir. MARKAYA/CEKIRDEGE ASLA dokunmaz: yalniz synonym
sozluguyle TAM metaphone eslesen, yeterince uzun, ambiguity-icermeyen token'lar cevrilir.

Geo + article siniflari KAPSAM DISI (geo ISO-kanoniك mekanigi / article cok kisa).
"""
from functools import lru_cache

from metaphone import doublemetaphone

from core.synonym_loader import get_synonym_canonical_map

# Rescue YALNIZ bu siniflarda (kanoniği normal token olanlar):
_RESCUE_CATEGORIES = ("legal_suffixes", "business_sectors", "address_abbreviations")

# Brand-guvenlik guard'lari:
MIN_TOKEN_LEN = 5          # sorgu token'i bu uzunlukta olmali (kisa marka/akronim korunur)
MIN_SYNONYM_SRC_LEN = 4    # synonym kaynak token'i bu uzunlukta olmali (kisa kodlar collision yapar)


def _primary_code(token: str) -> str:
    """Token'in birincil double-metaphone kodu (bossa '')."""
    code, _ = doublemetaphone(token)
    return code or ""


@lru_cache(maxsize=None)
def _exact_synonym_sources(country_code: str) -> frozenset:
    """Rescue kategorilerindeki TUM tam synonym kaynak token'lari (dokunulmayacaklar)."""
    cc = country_code.upper()
    m = get_synonym_canonical_map(cc, _RESCUE_CATEGORIES)
    return frozenset(m.keys())


@lru_cache(maxsize=None)
def build_synonym_phonetic_map(country_code: str) -> dict:
    """{metaphone_code: kanonik_form} — ambiguous kodlar ve kisa kaynaklar haric.

    Ayni metaphone koduna FARKLI kanonikler duserse o kod ATILIR (yanlis-cevir onlenir).
    """
    cc = country_code.upper()
    canon_map = get_synonym_canonical_map(cc, _RESCUE_CATEGORIES)
    code_to_canon: dict[str, str] = {}
    ambiguous: set[str] = set()
    for src, canon in canon_map.items():
        if len(src) < MIN_SYNONYM_SRC_LEN or not src.isalpha():
            continue
        code = _primary_code(src)
        if not code:
            continue
        existing = code_to_canon.get(code)
        if existing is not None and existing != canon:
            ambiguous.add(code)
        else:
            code_to_canon[code] = canon
    for code in ambiguous:
        code_to_canon.pop(code, None)
    return code_to_canon


@lru_cache(maxsize=100_000)
def canonicalize_phonetic(name: str, country_code: str) -> str:
    """Isimdeki bozuk-yazimli synonym token'larini kanonik forma cevirir.

    Her token icin: zaten tam-synonym ise / kisa ise / alfabetik degilse -> dokunma.
    Aksi halde metaphone'u haritada TAM eslesmisse -> kanonik forma cevir; yoksa -> koru.
    MARKAYA dokunmaz (markalarin metaphone'u synonym sozlugunde TAM eslesmez).
    """
    if not name:
        return name
    cc = country_code.upper()
    exact_sources = _exact_synonym_sources(cc)
    phon_map = build_synonym_phonetic_map(cc)
    out_tokens = []
    for tok in name.split():
        low = tok.lower()
        bare = low.replace(".", "")
        if (
            bare in exact_sources
            or len(bare) < MIN_TOKEN_LEN
            or not bare.isalpha()
        ):
            out_tokens.append(tok)
            continue
        canon = phon_map.get(_primary_code(bare))
        out_tokens.append(canon if canon is not None else tok)
    return " ".join(out_tokens)
