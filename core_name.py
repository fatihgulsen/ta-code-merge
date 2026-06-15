"""Ham firma ismini ayırt edici "çekirdek" token'lara indirger.

synonym_loader'dan yasal-ek verisini kullanır. es_queries (PHONETIC guard) ve
QA katmanı tarafından paylaşılır. Fuzzy kütüphane yok; yalnızca set/regex.
"""

import re
from functools import lru_cache

from synonym_loader import (
    get_country_name_tokens,
    get_legal_suffix_fragments,
    get_legal_suffix_tokens,
)

# Ülke-bazlılık JSON'dan gelir; bu modülde hardcoded ülke listesi yoktur.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _strip_tokens(country: str) -> frozenset:
    """Ülkeye özgü düşürülecek token kümesini döner (JSON-türetimli).

    Yasal-ek kısaltma parçaları (get_legal_suffix_fragments) ve tek-kelimelik
    yasal ekler (gmbh, limited…) dahildir. Çok-kelimeli ifadelerin tam iş
    kelimeleri (general, civil) korunur; yalnızca kısa parçalar düşürülür.
    """
    country = country.upper()
    out = set(get_legal_suffix_fragments(country))
    for phrase in get_legal_suffix_tokens(country):
        toks = [t for t in _TOKEN_SPLIT.split(phrase.lower()) if t]
        if len(toks) == 1:
            out.add(toks[0])
    return frozenset(out)


def normalize_core(name: str, country: str, drop_geo: bool = False) -> tuple[str, ...]:
    """Ham ismi ayırt edici çekirdek token tuple'ına indirger.

    Adımlar: lower → alfanümerik token'lara böl → sayısal / tek-harf /
    yasal-ek token'larını düş. Sıra korunur.

    drop_geo=True: ülke ad token'ları da düşürülür (yalnızca PHONETIC guard kullanır).
    """
    if not name:
        return ()
    cc = country.upper()
    strip = _strip_tokens(cc)
    geo = get_country_name_tokens(cc) if drop_geo else frozenset()
    tokens = [t for t in _TOKEN_SPLIT.split(name.lower()) if t]
    return tuple(
        t for t in tokens
        if not t.isdigit() and len(t) > 1 and t not in strip and t not in geo
    )
