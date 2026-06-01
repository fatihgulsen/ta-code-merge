# ============================================================================
# core_name.py — Çekirdek-isim normalizasyonu (paylaşılan üretim helper'ı)
# ============================================================================
# Ham firma ismini, pipeline'ın yasal-ek verisini (synonym_loader) kullanarak
# ayırt edici "çekirdek" token'lara indirger. Hem es_queries (PHONETIC guard)
# hem analysis/ QA katmanı kullanır. Fuzzy kütüphane YOK (yalnızca set/regex).
# ============================================================================

import re
from functools import lru_cache

from synonym_loader import get_legal_suffix_tokens

# Yasal ek kısaltma parçaları (çok-kelimeli ek ifadelerinin tokenları + yaygın MX kısaltmaları)
_SUFFIX_FRAGMENTS = {"s", "a", "de", "c", "v", "sa", "cv", "sab", "rl", "sc", "sapi", "del"}

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _strip_tokens(country: str) -> frozenset:
    """Ülkeye özgü düşürülecek token kümesi: yasal-ek parçaları + kısaltmalar."""
    out = set(_SUFFIX_FRAGMENTS)
    for phrase in get_legal_suffix_tokens(country):
        for tok in _TOKEN_SPLIT.split(phrase.lower()):
            if tok:
                out.add(tok)
    return frozenset(out)


def normalize_core(name: str, country: str) -> tuple[str, ...]:
    """Ham ismi ayırt edici çekirdek token tuple'ına indirger.

    Adımlar: lower → alfanümerik token'lara böl → sayısal / tek-harf /
    yasal-ek token'larını düş. Sıra korunur.
    """
    if not name:
        return ()
    strip = _strip_tokens(country.upper())
    tokens = [t for t in _TOKEN_SPLIT.split(name.lower()) if t]
    return tuple(t for t in tokens if not t.isdigit() and len(t) > 1 and t not in strip)
