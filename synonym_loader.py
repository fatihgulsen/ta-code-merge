# ============================================================================
# synonym_loader.py - Ülke Bazlı Synonym Yükleme
# ============================================================================
# ES index ayarlarına ülke başına synonym listesi üretir.
#
# Kural:
#   - Tüm ülkeler: common.json + countries.json
#   - Ülke dosyası varsa (örn. tr.json): üstteki + tr.json
#
# ES formatı (Solr): "kaynak1,kaynak2 => hedef"
# ============================================================================

import json
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# synonyms_data/ klasörünün yolu (bu dosyayla aynı dizinde)
SYNONYMS_DIR = Path(__file__).parent / "synonyms_data"

# Her zaman yüklenecek ortak dosyalar
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
            # NFKC normalizasyonu uygula
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

    # 1. Ortak dosyalar — her ülke için geçerli
    for filename in COMMON_FILES:
        path = SYNONYMS_DIR / filename
        rules.extend(_extract_rules_from_file(path))

    # 2. Ülkeye özgü dosya — varsa ekle, yoksa ortak kurallarla devam et
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

    # Boş ve tekrarlı kuralları temizle
    seen = set()
    clean_rules = []
    for rule in rules:
        rule = rule.strip()
        if rule and rule not in seen:
            seen.add(rule)
            clean_rules.append(rule)

    return tuple(clean_rules)


def _parse_category_tokens(paths: list, category: str) -> frozenset:
    """Verilen JSON dosyalarindan belirli bir kategoriden tum token'lari cikarir.

    Solr synonym format: 'src1,src2,src3=>target'
    Her iki taraftaki (sol ve sag) her token ayri ayri donulur.
    Noktalar silinir, kucuk harfe cevrilir.
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
    """Ulkeye ozgu legal_suffixes token'larini doner.

    Hem common.json hem de ulke dosyasindan 'legal_suffixes' kategorisini okur.
    Bunlar stripping pipeline'inda silinir (tuzel kisi ekleri).
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "legal_suffixes")


@lru_cache(maxsize=None)
def get_business_sector_tokens(country_code: str) -> frozenset:
    """Ulkeye ozgu business_sector token'larini doner.

    Bunlar stripping'e GIRMEZ — firma ismini AYIRT eden sektor/is kolu kelimeleridir.
    "Apex Pharma" ve "Apex Steel" farkli firmalardir.

    Data integrity: legal_suffixes ve business_sectors kategorilerinin
    disjoint olmasi JSON seviyesinde garanti edilir (bkz. common.json ve
    per-country files). Runtime subtraction yok.
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "business_sectors")


@lru_cache(maxsize=None)
def get_business_sector_canonical_map(country_code: str) -> dict:
    """Ulkeye ozgu business_sectors kurallarindan {source: target} map'i doner.

    Her kural 'src1,src2,src3=>target' formatinda. Soldaki her token ve
    target'in kendisi target'a map edilir. Hem cogul normalizasyonu
    (industry -> industries) hem de kisaltma normalizasyonu (intl ->
    international) tek bir yerden yonetilir.

    Donus: dict (NOT frozenset — bu bir map)
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
            # Target also maps to itself (idempotent canonicalisation)
            mapping[target] = target
    return mapping


@lru_cache(maxsize=None)
def get_company_type_tokens(country_code: str) -> frozenset:
    """DEPRECATED shim — use get_legal_suffix_tokens directly.

    Sprint 2: Bu fonksiyon artik yalnizca legal_suffixes kategorisini doner.
    business_sectors ayri bir kategori haline geldi ve stripping'e girmez.
    Eski cagrilar icin backward-compat saglamak uzere korunuyor.
    """
    return get_legal_suffix_tokens(country_code)


@lru_cache(maxsize=None)
def get_all_company_type_tokens() -> frozenset:
    """
    Tüm ülke dosyaları + ortak dosyalar dahil olmak üzere
    tüm legal_suffixes tokenlarının birleşimini döner.
    Underscore ile baslayan dosyalar (_template.json) ve
    ortak dosyalar (common, countries) hariç tutulur.

    Sprint 2: company_types -> legal_suffixes (business sectors ayri).

    Dönüş: frozenset (lru_cache için hashable, immutable)
    """
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.startswith("_"):
            continue  # _template.json, _internal, etc.
        if f.stem.lower() in {"common", "countries"}:
            continue
        paths.append(f)

    return _parse_category_tokens(paths, "legal_suffixes")


@lru_cache(maxsize=None)
def get_article_stopwords(country_code: str) -> frozenset:
    """
    Ülkeye özgü article/stopword listesi döner.
    common.json articles + ülke dosyası articles birleştirilerek hesaplanır.

    Dönüş: frozenset (lru_cache için hashable, immutable)
    """
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


def get_all_country_codes() -> list[str]:
    """
    synonyms_data/ klasöründeki tüm ülke dosyalarının kodlarını döner.
    Ortak dosyalar (common, countries) hariç tutulur.
    Underscore ile baslayan dosyalar (_template.json, _archive/) de hariç.
    """
    excluded = {"common", "countries"}
    codes = []
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.startswith("_"):
            continue  # _template.json, _internal, etc.
        if f.stem.lower() in excluded:
            continue
        codes.append(f.stem.upper())
    return sorted(codes)


def get_common_synonyms() -> tuple[str, ...]:
    """
    Sadece ortak synonym kurallarını döner.
    Ülke dosyası olmayan firmalar için kullanılır.
    """
    return load_synonyms_for_country("__common__")


if __name__ == "__main__":
    # Hızlı test
    codes = get_all_country_codes()
    print(f"Ülke dosyası bulunan ülkeler ({len(codes)}): {codes[:10]}...")

    for cc in ["TR", "US", "DE", "IN"]:
        ls = get_legal_suffix_tokens(cc)
        bs = get_business_sector_tokens(cc)
        print(f"\n--- {cc} legal_suffixes ({len(ls)}) / business_sectors ({len(bs)}) ---")
        print(f"  legal sample:  {sorted(list(ls))[:10]}")
        print(f"  sector sample: {sorted(list(bs))[:10]}")
