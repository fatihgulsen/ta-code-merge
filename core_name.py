# ============================================================================
# core_name.py — Çekirdek-isim normalizasyonu (paylaşılan üretim helper'ı)
# ============================================================================
# Ham firma ismini, pipeline'ın yasal-ek verisini (synonym_loader) kullanarak
# ayırt edici "çekirdek" token'lara indirger. Hem es_queries (PHONETIC guard)
# hem analysis/ QA katmanı kullanır. Fuzzy kütüphane YOK (yalnızca set/regex).
# ============================================================================

import re
from functools import lru_cache

from synonym_loader import (
    get_country_name_tokens,
    get_legal_suffix_fragments,
    get_legal_suffix_tokens,
)

# Tüm ülkeye-özgü token kümeleri synonyms_data/ JSON dosyalarından TÜRETİLİR;
# bu modülde hardcoded ülke listesi YOKTUR. Ülke-bazlılık (MX parçalarının
# DE/TR'ye sızmaması) doğrudan JSON'un ülke-özgü olmasından gelir:
#   - yasal-ek kısaltma parçaları  → synonym_loader.get_legal_suffix_fragments
#   - coğrafi/ülke-adı token'ları   → synonym_loader.get_country_name_tokens

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _strip_tokens(country: str) -> frozenset:
    """Ülkeye özgü düşürülecek token kümesi (tamamen JSON-türetimli):
      - yasal-ek KISALTMA parçaları (örn. MX 'S.A. DE C.V.' → s, a, de, c, v) —
        get_legal_suffix_fragments üzerinden çok-kelimeli ifadelerden türetilir,
      - tek-kelimelik yasal ekler (gmbh, limited, sociedad…) — herhangi uzunlukta.

    Çok-kelimeli ifadelerin yalnızca KISA parçaları alındığından 'general
    partnership' / 'asociacion civil' gibi ifadelerdeki iş kelimeleri (general,
    civil) KORUNUR. Ülke-bazlılık JSON'dan gelir; MX parçaları DE/TR'ye sızmaz."""
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

    drop_geo=True ise ülkenin kendi ad token'ları ('mexico' vb., countries.json'dan
    türetilir) da düşürülür — yalnızca PHONETIC guard gibi "ayırt edicilik"
    kararlarında kullanılır; varsayılan KAPALI olduğundan detektör/QA davranışı değişmez.
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
