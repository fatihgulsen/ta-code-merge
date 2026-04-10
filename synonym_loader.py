# ============================================================================
# synonym_loader.py - Ülke Bazlı Synonym Yükleme
# ============================================================================
# ES index ayarlarına ülke başına synonym listesi üretir.
#
# Kural:
#   - Tüm ülkeler: common.json + countries.json + other.json
#   - Ülke dosyası varsa (örn. tr.json): üstteki + tr.json
#
# ES formatı (Solr): "kaynak1,kaynak2 => hedef"
# ============================================================================

import json
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path

from config import BUSINESS_DESCRIPTORS

logger = logging.getLogger(__name__)

# synonyms_data/ klasörünün yolu (bu dosyayla aynı dizinde)
SYNONYMS_DIR = Path(__file__).parent / "synonyms_data"

# Her zaman yüklenecek ortak dosyalar
COMMON_FILES = ["common.json", "countries.json", "other.json"]


def normalize_text(text: str) -> str:
    """Metni NFKC formatında normalize eder."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


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

    Her zaman:  common.json + countries.json + other.json
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


@lru_cache(maxsize=128)
def get_generic_tokens_for_country(country_code: str) -> frozenset:
    """
    Ülkeye özgü 'generic' kelimeleri döner (frozenset — cache-safe).
    Bunlar:
      1. common.json + countries.json + other.json içindeki 'generic' kategorisi
      2. Ülke dosyasındaki 'generic' kategorisi (varsa)
      3. Tüm 'company_types' kurallarındaki HEDEF (=> sağ tarafı) kelimeler.
    """
    country_code = country_code.upper()
    generics: set[str] = set()

    files_to_read = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        files_to_read.append(country_file)

    for path in files_to_read:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 'generic' kategorisi — SOL taraftaki her token'ı generic say
        # Kural formatı: "token1,token2,token3=>hedef"
        for rule in data.get("generic", []):
            rule_norm = normalize_text(rule)
            sources_part = rule_norm.split("=>")[0] if "=>" in rule_norm else rule_norm
            for token in sources_part.split(","):
                t = token.strip().lower()
                if t:
                    generics.add(t)

        # 'company_types' — HEDEF (sağ taraf) kelimeleri de generic say
        for rule in data.get("company_types", []):
            rule_norm = normalize_text(rule)
            if "=>" in rule_norm:
                target = rule_norm.split("=>")[1].strip().lower().rstrip(".")
                if target:
                    generics.add(target)

    # Business descriptor'ları çıkar — bunlar firma isminin anlamlı parçaları
    generics -= BUSINESS_DESCRIPTORS

    return frozenset(generics)


def _parse_company_type_tokens(paths: list) -> frozenset:
    """
    Verilen Path listesindeki dosyaların 'company_types' kurallarından
    tüm tokenları çıkarır. Her iki taraftaki (=> solundaki ve sağındaki)
    tokenlar dahil edilir. Noktalar tamamen silinir, her şey küçük harfe çevrilir.
    """
    tokens: set[str] = set()

    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        for rule in data.get("company_types", []):
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
def get_company_type_tokens(country_code: str) -> frozenset:
    """
    Verilen ülke kodu için tüm company_type tokenlarını döner.
    Ortak dosyalar (common.json, countries.json, other.json) + ülke dosyası
    birleştirilerek hesaplanır.

    Dönüş: frozenset (lru_cache için hashable, immutable)
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    return _parse_company_type_tokens(paths)


@lru_cache(maxsize=None)
def get_all_company_type_tokens() -> frozenset:
    """
    Tüm ülke dosyaları + ortak dosyalar dahil olmak üzere
    tüm company_type tokenlarının birleşimini döner.

    Dönüş: frozenset (lru_cache için hashable, immutable)
    """
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    for f in SYNONYMS_DIR.glob("*.json"):
        if f.stem.lower() not in {"common", "countries", "other"}:
            paths.append(f)

    return _parse_company_type_tokens(paths)


@lru_cache(maxsize=None)
def get_article_stopwords(country_code: str) -> frozenset:
    """
    Ülkeye özgü article/stopword listesi döner.
    common.json articles + ülke dosyası articles birleştirilerek hesaplanır.

    Dönüş: frozenset (lru_cache için hashable, immutable)
    """
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
    Ortak dosyalar (common, countries, other) hariç tutulur.
    """
    excluded = {"common", "countries", "other"}
    codes = []
    for f in SYNONYMS_DIR.glob("*.json"):
        stem = f.stem.upper()
        if f.stem.lower() not in excluded:
            codes.append(stem)
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

    for cc in ["TR", "US", "DE"]:
        gt = get_generic_tokens_for_country(cc)
        print(f"\n--- {cc} için generic tokenlar ({len(gt)}) ---")
        print(f"  Örnekler: {list(gt)[:10]}")
