"""ES index ayarlarına ülke başına synonym listesi üretir.

Kural: common.json + countries.json her ülke için; varsa {cc}.json da eklenir.
ES formatı (Solr): "kaynak1,kaynak2 => hedef".
"""

import json
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

SYNONYMS_DIR = Path(__file__).parent / "synonyms_data"
COMMON_FILES = ["common.json", "countries.json"]


def normalize_text(text: str) -> str:
    """Metni NFKC formatında normalize eder."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).casefold()


def _extract_rules_from_file(filepath: Path) -> list[str]:
    """
    Bir JSON dosyasındaki tüm kategorileri düz synonym listesine çevirir.
    JSON formatı: { "kategori": ["A,B => C", ...], ... }
    """
    if not filepath.exists():
        return []

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    rules = []
    for category_rules in data.values():
        if isinstance(category_rules, list):
            rules.extend([normalize_text(r) for r in category_rules])

    return rules


@lru_cache(maxsize=128)
def load_synonyms_for_country(country_code: str) -> tuple[str, ...]:
    """
    Verilen ülke kodu için ES synonym listesi döner.

    Her zaman:  common.json + countries.json
    + Varsa:    {country_code.lower()}.json

    Dönüş: tuple (lru_cache için hashable)
    """
    rules: list[str] = []

    for filename in COMMON_FILES:
        path = SYNONYMS_DIR / filename
        rules.extend(_extract_rules_from_file(path))

    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        rules.extend(_extract_rules_from_file(country_file))
    elif country_code not in ("__COMMON__", "__common__"):
        logger.warning(
            "Ulke '%s' icin synonym dosyasi bulunamadi (%s). "
            "Ortak synonymler (common) kullaniliyor.",
            country_code.upper(),
            country_file.name,
        )

    seen = set()
    clean_rules = []
    for rule in rules:
        rule = rule.strip()
        if rule and rule not in seen:
            seen.add(rule)
            clean_rules.append(rule)

    return tuple(clean_rules)


def _parse_category_tokens(paths: list, category: str) -> frozenset:
    """Verilen JSON dosyalarındaki belirtilen kategorinin tüm token'larını döner.

    Solr formatı: 'src1,src2=>target'. Sol ve sağ taraftaki her token ayrı ayrı
    döner; noktalar silinir, küçük harfe çevrilir.
    """
    tokens: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get(category, [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            rule_norm = normalize_text(rule)
            if "=>" in rule_norm:
                left, right = rule_norm.split("=>", 1)
                all_parts = left.split(",") + [right]
            else:
                all_parts = rule_norm.split(",")
            for part in all_parts:
                t = part.strip().lower().replace(".", "")
                if t:
                    tokens.add(t)
    return frozenset(tokens)


@lru_cache(maxsize=None)
def get_legal_suffix_tokens(country_code: str) -> frozenset:
    """Ülkeye özgü 'legal_suffixes' token'larını döner (common.json + ülke dosyası).

    Stripping pipeline'ında tüzel kişi eklerini (gmbh, ltd, sa vb.) düşürür.
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "legal_suffixes")


# Çok-kelimeli yasal ifadelerdeki KISALTMA parçaları (s, a, de, cv…) bu uzunluğa
# kadar kabul edilir; tam iş kelimeleri (general, civil, len>4) korunur.
_LEGAL_FRAGMENT_MAX_LEN = 4


@lru_cache(maxsize=None)
def get_legal_suffix_fragments(country_code: str) -> frozenset:
    """Ülkeye özgü yasal-ek kısaltma parçalarını döner (JSON'dan türetilir).

    legal_suffixes ifadelerini boşlukta böler; yalnızca kısa (<=_LEGAL_FRAGMENT_MAX_LEN)
    alfabetik parçalar döner — örn. 'S.A. DE C.V.' → {s, a, de, c, v}.
    core_name ve es_manager fonetik stop filtresi kullanır.
    """
    frags: set[str] = set()
    for phrase in get_legal_suffix_tokens(country_code):
        for piece in phrase.split():
            if piece.isalpha() and len(piece) <= _LEGAL_FRAGMENT_MAX_LEN:
                frags.add(piece)
    return frozenset(frags)


@lru_cache(maxsize=None)
def get_all_legal_suffix_fragments() -> frozenset:
    """Tüm ülkelerin yasal-ek kısaltma parçalarının birleşimi.

    es_manager phonetic_analyzer'da metaphone gürültüsü yaratan parçaları
    stop'lamak için kullanır. Tamamen JSON'dan türetilir.
    """
    frags: set[str] = set()
    for phrase in get_all_company_type_tokens():
        for piece in phrase.split():
            if piece.isalpha() and len(piece) <= _LEGAL_FRAGMENT_MAX_LEN:
                frags.add(piece)
    return frozenset(frags)


@lru_cache(maxsize=None)
def get_country_name_tokens(country_code: str) -> frozenset:
    """countries.json'dan ülkenin tek-kelimelik ad token'larını döner (örn. MX → {mexico, mex, mx}).

    Çok-kelimeli adlar (United Mexican States) ayrıştırılmaz; jenerik kelimelerin
    (united, states) sızmasını önler. PHONETIC guard drop_geo=True ile kullanır.
    """
    cc = country_code.upper()
    path = SYNONYMS_DIR / "countries.json"
    if not path.exists():
        return frozenset()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: set[str] = set()
    for rule in data.get("countries", []):
        rule_norm = normalize_text(rule)
        if "=>" not in rule_norm:
            continue
        left, right = rule_norm.split("=>", 1)
        if right.strip().lower().replace(".", "") != cc.lower():
            continue
        for src in left.split(","):
            t = src.strip().lower().replace(".", "")
            if t and " " not in t:
                out.add(t)
    return frozenset(out)


# Kısa ISO kodları (ar, br, us…) marka token'larıyla çakışır (GE, US BANK) → stripping'e girmez.
# Tam ülke adları (argentina, mexico…) mıknatıs sürücüsü olduğundan sıyrılır.
GEO_STOPWORD_MIN_LEN = 4


@lru_cache(maxsize=None)
def get_geo_stopword_tokens(min_len: int = GEO_STOPWORD_MIN_LEN) -> frozenset:
    """Tüm ülkelerin geo token'larının birleşimi; kısa ISO kodları (len < min_len) hariç.

    ES stripped/fingerprint analyzer ve ingest pipeline'ı aynı listeyi kullanır →
    index/search simetrisi. countries.json'dan türetilir, hardcode yok.
    """
    union: set[str] = set()
    for cc in get_all_country_codes():
        union |= {t for t in get_country_name_tokens(cc) if len(t) >= min_len and " " not in t}
    return frozenset(union)


@lru_cache(maxsize=None)
def get_business_sector_tokens(country_code: str) -> frozenset:
    """Ülkeye özgü 'business_sectors' token'larını döner.

    Stripping'e girmez; sektör kelimeleri firma kimliğini ayırt eder
    ("Apex Pharma" ≠ "Apex Steel"). legal_suffixes ile ayrışıklık JSON seviyesinde
    garanti edilir (bkz. common.json).
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "business_sectors")


@lru_cache(maxsize=None)
def get_business_sector_canonical_map(country_code: str) -> dict:
    """Ülkeye özgü business_sectors kurallarından {kaynak: hedef} eşlem döner.

    Çoğul/kısaltma normalizasyonunu (industry→industries, intl→international)
    tek bir yerden yönetir. Dönüş: dict (NOT frozenset).
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    mapping: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("business_sectors", [])
        if not isinstance(rules, list):
            continue
        for rule in rules:
            rule_norm = normalize_text(rule)
            if "=>" not in rule_norm:
                continue
            left, right = rule_norm.split("=>", 1)
            target = right.strip().lower().replace(".", "")
            if not target:
                continue
            for src in left.split(","):
                src_token = src.strip().lower().replace(".", "")
                if src_token:
                    mapping[src_token] = target
            mapping[target] = target  # idempotent: hedef kendisiyle de eşleşir
    return mapping


@lru_cache(maxsize=None)
def get_company_type_tokens(country_code: str) -> frozenset:
    """DEPRECATED — doğrudan get_legal_suffix_tokens kullanın.

    Geriye dönük uyumluluk için korunuyor; yalnızca legal_suffixes döner.
    """
    return get_legal_suffix_tokens(country_code)


@lru_cache(maxsize=None)
def get_all_company_type_tokens() -> frozenset:
    """Tüm ülke + ortak dosyaların legal_suffixes token'larının birleşimini döner.

    Underscore ile başlayan dosyalar (_template.json) ve ortak dosyalar hariç.
    Dönüş: frozenset.
    """
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.startswith("_"):
            continue  # _template.json vb. dahili dosyalar
        if f.stem.lower() in {"common", "countries"}:
            continue
        paths.append(f)

    return _parse_category_tokens(paths, "legal_suffixes")


@lru_cache(maxsize=None)
def get_article_stopwords(country_code: str) -> frozenset:
    """Ülkeye özgü article/stopword listesi döner (common.json + ülke dosyası)."""
    country_code = country_code.upper()
    stopwords: set[str] = set()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for token in data.get("articles", []):
            t = token.strip().lower()
            if t:
                stopwords.add(t)

    return frozenset(stopwords)


@lru_cache(maxsize=None)
def get_non_firm_placeholders(country_code: str) -> frozenset:
    """Firma olmayan placeholder ifadelerini döner (JSON'dan, hardcode değil).

    Düz ifade listesidir ("sin razon social", "same as cnee") — Solr synonym kuralı değil.
    input_filter bunları EXCLUDED yapar; ES'e indekslenmez. HAM string döner;
    normalizasyon input_filter._norm'da yapılır.
    (bkz. CLAUDE.md §1.4 — non_firm_placeholders istisnası)
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    out: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("non_firm_placeholders", []):
            if isinstance(item, str) and item.strip():
                out.add(item.strip())
    return frozenset(out)


def get_all_country_codes() -> list[str]:
    """synonyms_data/ klasöründeki ülke dosya kodlarını döner.

    Ortak dosyalar (common, countries) ve alt çizgiyle başlayanlar hariç.
    """
    excluded = {"common", "countries"}
    codes = []
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.startswith("_"):
            continue  # _template.json vb. dahili dosyalar
        if f.stem.lower() in excluded:
            continue
        codes.append(f.stem.upper())
    return sorted(codes)


def get_common_synonyms() -> tuple[str, ...]:
    """Yalnızca ortak (ülkesiz) synonym kurallarını döner."""
    return load_synonyms_for_country("__common__")


if __name__ == "__main__":
    codes = get_all_country_codes()
    print(f"Ülke dosyası bulunan ülkeler ({len(codes)}): {codes[:10]}...")

    for cc in ["TR", "US", "DE", "IN"]:
        ls = get_legal_suffix_tokens(cc)
        bs = get_business_sector_tokens(cc)
        print(f"\n--- {cc} legal_suffixes ({len(ls)}) / business_sectors ({len(bs)}) ---")
        print(f"  legal sample:  {sorted(list(ls))[:10]}")
        print(f"  sector sample: {sorted(list(bs))[:10]}")
