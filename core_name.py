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

# Ülke-bazlı küratörlü yasal-ek kısaltma parçaları.
#
# Bunlar çok-kelimeli yasal-kişilik eklerinin tek tek harf/parçalarıdır
# (örn. MX "S.A. DE C.V." → s, a, de, c, v). Synonym verisinde TEK-KELİMELİK
# bir kayıt olarak GEÇMEZLER; bu yüzden `get_legal_suffix_tokens` üzerinden
# türetilemezler ve burada küratörlenir.
#
# > [!IMPORTANT]
# > Bu küme KASITLI OLARAK ÜLKEYE ÖZGÜDÜR. MX'e ait "sc"/"rl"/"del"/"de" gibi
# > parçaları başka ülkelere uygulamak, o ülkelerde meşru isim token'larını
# > yanlışlıkla siler (örn. DE "DEL MONTE", TR "SC JOHNSON") ve hem QA
# > tespitini hem de PHONETIC_MATCH guard'ını bozar. Yeni bir ülke
# > onboard edilirken yasal formları kısaltılıyorsa buraya ayrı bir
# > giriş eklenir; varsayılan olarak diğer ülkeler boş küme alır.
_SUFFIX_FRAGMENTS_BY_COUNTRY: dict[str, frozenset[str]] = {
    "MX": frozenset({"s", "a", "de", "c", "v", "sa", "cv", "sab", "rl", "sc", "sapi", "del"}),
}

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _strip_tokens(country: str) -> frozenset:
    """Ülkeye özgü düşürülecek token kümesi: ülkeye özgü küratörlü kısaltma
    parçaları + yalnızca tek-kelimelik yasal ekler (çok-kelimeli ifadeler
    parçalanmaz — aksi halde 'general partnership' gibi ifadeler 'general' iş
    kelimesini siler).

    Kısaltma parçaları artık ülke-bazlıdır: yalnızca o ülke için küratörlenmiş
    parçalar uygulanır, böylece MX'e özgü parçalar diğer ülkelere sızmaz."""
    country = country.upper()
    out = set(_SUFFIX_FRAGMENTS_BY_COUNTRY.get(country, frozenset()))
    for phrase in get_legal_suffix_tokens(country):
        toks = [t for t in _TOKEN_SPLIT.split(phrase.lower()) if t]
        if len(toks) == 1:
            out.add(toks[0])
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
