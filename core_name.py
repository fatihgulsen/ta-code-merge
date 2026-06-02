# ============================================================================
# core_name.py — Çekirdek-isim normalizasyonu (paylaşılan üretim helper'ı)
# ============================================================================
# Ham firma ismini, pipeline'ın yasal-ek verisini (synonym_loader) kullanarak
# ayırt edici "çekirdek" token'lara indirger. Hem es_queries (PHONETIC guard)
# hem analysis/ QA katmanı kullanır. Fuzzy kütüphane YOK (yalnızca set/regex).
# ============================================================================

import re
from functools import lru_cache
from types import MappingProxyType

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
_SUFFIX_FRAGMENTS_BY_COUNTRY: MappingProxyType = MappingProxyType({
    "MX": frozenset({"s", "a", "de", "c", "v", "sa", "cv", "sab", "rl", "sc", "sapi", "del"}),
})

# Ülke-bazlı coğrafi / jenerik "ayırt edici olmayan" token'lar.
#
# Yasal ek DEĞİLLER (synonym verisinde geçmezler) ama tek-ülke (örn. tüm veri MX)
# bağlamında firmaları ayırt etmezler: "AUDI MEXICO" ile "KOHLER DE MEXICO" ortak
# 'mexico' token'ı taşır. PHONETIC guard'ı `drop_geo=True` ile bunları düşürerek
# "marka + MEXICO" kalıbını TEK ayırt edici çekirdek token'a indirger; böylece
# guard zayıf fonetik eşleşmeleri bloklar.
#
# > [!IMPORTANT]
# > Bu küme de KASITLI OLARAK ÜLKEYE ÖZGÜDÜR ve yalnızca `drop_geo=True` çağrılarına
# > uygulanır (varsayılan davranış değişmez). Başka ülkede 'mexico' meşru/ayırt edici
# > olabilir; o yüzden ülke-bazlıdır.
_GEO_STOPWORDS_BY_COUNTRY: MappingProxyType = MappingProxyType({
    "MX": frozenset({"mexico", "mexicana", "mexicano", "mexicanos"}),
})

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def legal_suffix_fragments(country: str) -> frozenset[str]:
    """Ülkeye özgü küratörlü yasal-ek kısaltma parçaları (tek-ülke salt-okunur view)."""
    return _SUFFIX_FRAGMENTS_BY_COUNTRY.get(country.upper(), frozenset())


def curated_fragment_country_count() -> int:
    """Küratörlü yasal-ek parça kümesi tanımlı ülke sayısı.

    es_manager bunu, global (alan-bazlı) fonetik fragment-stop'un tek-ülke
    varsayımının hâlâ geçerli olduğunu doğrulamak için kullanır."""
    return len(_SUFFIX_FRAGMENTS_BY_COUNTRY)


@lru_cache(maxsize=1)
def all_legal_fragments() -> frozenset[str]:
    """Tüm küratörlü ülke yasal-ek parçalarının birleşimi.

    es_manager bunu fonetik alandaki gürültü token'larını (S.A. DE C.V. parçaları)
    stop'lamak için kullanır. NOT: birleşim tek-ülke (MX) varsayımı altında güvenlidir;
    çok-ülke onboarding'inde ülke-bazlı phonetic analyzer'a geçilmelidir
    (bkz. curated_fragment_country_count)."""
    out: set[str] = set()
    for frags in _SUFFIX_FRAGMENTS_BY_COUNTRY.values():
        out |= set(frags)
    return frozenset(out)


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


def normalize_core(name: str, country: str, drop_geo: bool = False) -> tuple[str, ...]:
    """Ham ismi ayırt edici çekirdek token tuple'ına indirger.

    Adımlar: lower → alfanümerik token'lara böl → sayısal / tek-harf /
    yasal-ek token'larını düş. Sıra korunur.

    drop_geo=True ise ülkeye özgü coğrafi/jenerik token'lar ('mexico' vb.) da
    düşürülür — yalnızca PHONETIC guard gibi "ayırt edicilik" kararlarında kullanılır;
    varsayılan KAPALI olduğundan detektör/QA davranışı değişmez.
    """
    if not name:
        return ()
    cc = country.upper()
    strip = _strip_tokens(cc)
    geo = _GEO_STOPWORDS_BY_COUNTRY.get(cc, frozenset()) if drop_geo else frozenset()
    tokens = [t for t in _TOKEN_SPLIT.split(name.lower()) if t]
    return tuple(
        t for t in tokens
        if not t.isdigit() and len(t) > 1 and t not in strip and t not in geo
    )
