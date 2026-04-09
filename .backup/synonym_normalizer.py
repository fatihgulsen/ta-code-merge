# ============================================================================
# synonym_normalizer.py - Python-Taraflı Canonical Form Normalizasyonu
# ============================================================================
# ES'e sorgu göndermeden önce incoming name'i canonical forma çevirir.
# Solr synonym kurallarını ("corp,corporation => corp.") Python'da uygular.
#
# Amaç: ES BM25 scoring'ini daha tutarlı hale getirmek.
#   "Apple Corporation Ltd."  → "apple corp. ltd."
#   "Apple Corp. Limited"     → "apple corp. ltd."
#   Her ikisi de aynı canonical form → ES'e aynı sorgu → tutarlı skor
# ============================================================================
import re
from functools import lru_cache

from synonym_loader import (
    load_synonyms_for_country,
    normalize_text,
    get_generic_tokens_for_country,
)
from config import SUFFIX_TYPO_MAP


def parse_synonym_rules(rules: tuple[str, ...]) -> list[tuple[list[str], str]]:
    """
    Solr formatındaki synonym kurallarını parse eder.

    Format: "kaynak1,kaynak2,kaynak3 => hedef"
    Çıktı: [(["kaynak1","kaynak2","kaynak3"], "hedef"), ...]

    - Yalnızca directed (=>) kurallar işlenir.
    - Equivalence kuralları (=> içermeyen) atlanır.
    - Çoklu token source'lar (bigram/trigram) desteklenir.
    - Longest-match önce uygulanacak şekilde sıralanır.
    """
    parsed: list[tuple[list[str], str]] = []

    for rule in rules:
        rule = rule.strip()
        if "=>" not in rule:
            continue

        parts = rule.split("=>", 1)
        if len(parts) != 2:
            continue

        sources_raw = parts[0].strip()
        target = parts[1].strip().lower()

        if not sources_raw or not target:
            continue

        sources = [s.strip().lower() for s in sources_raw.split(",") if s.strip()]
        if sources:
            parsed.append((sources, target))

    # Longest-match önceliği: kaynak token sayısı çoktan aza sırala
    # Böylece "private limited" → "ltd." kuralı, "limited" → "ltd." kuralından önce denenir
    parsed.sort(key=lambda item: max(len(s.split()) for s in item[0]), reverse=True)

    return parsed


@lru_cache(maxsize=128)
def _get_parsed_rules(country_code: str) -> list[tuple[list[str], str]]:
    """
    Ülke kodu için parse edilmiş synonym kural listesi.
    lru_cache ile önbelleklenir — her ülke için yalnızca bir kez parse edilir.
    """
    raw_rules = load_synonyms_for_country(country_code.upper())
    return parse_synonym_rules(raw_rules)


@lru_cache(maxsize=128)
def build_known_suffixes(country_code: str) -> set[str]:
    """
    Synonym dosyalarından bilinen suffix/uzantı setini dinamik olarak oluşturur.

    Hem source hem target tokenları dahil edilir.
    Noktalar temizlenir → "ltd." ve "ltd" aynı sette bulunur.

    Kullanım alanları:
    - Birleşik suffix ayırma (PVTLTD → PVT LTD)
    - Boşluklu harf normalizasyonu (L T D → LTD)
    - Çift-harf typo düzeltme (INCC → INC)
    """
    parsed_rules = _get_parsed_rules(country_code.upper())
    suffixes: set[str] = set()

    for sources, target in parsed_rules:
        for source in sources:
            # Tekli token source'ları ekle (çoklu olanlar birleştirme için uygun değil)
            source_clean = source.rstrip(".").replace(".", "")
            if " " not in source and len(source_clean) >= 2:
                suffixes.add(source_clean)
        target_clean = target.rstrip(".").replace(".", "")
        if " " not in target and len(target_clean) >= 2:
            suffixes.add(target_clean)

    return suffixes


def apply_synonyms(text: str, parsed_rules: list[tuple[list[str], str]]) -> str:
    """
    Parse edilmiş synonym kurallarını token bazlı uygular.

    Önce çok-kelimeli (bigram/trigram) eşleşmeler denenir (longest-match).
    Sonra tekli token eşleşmeleri uygulanır.

    Giriş: lowercase, normalize edilmiş text
    Çıktı: canonical form (kurallar uygulanmış)
    """
    if not text or not parsed_rules:
        return text

    tokens = text.split()
    result_tokens: list[str] = []
    i = 0

    while i < len(tokens):
        matched = False

        for sources, target in parsed_rules:
            # Çok-token source'ları dene (bigram, trigram, vs.)
            for source in sources:
                source_tokens = source.split()
                source_len = len(source_tokens)

                if source_len > 1:
                    # Bigram/trigram: yeterli token var mı?
                    if i + source_len <= len(tokens):
                        window = tokens[i : i + source_len]
                        if window == source_tokens:
                            result_tokens.append(target)
                            i += source_len
                            matched = True
                            break
                else:
                    # Tekli token: nokta dahil esnek karşılaştırma
                    # "corp." ile "corp" aynı sayılır
                    current = tokens[i].rstrip(".")
                    src = source.rstrip(".")
                    if current == src:
                        result_tokens.append(target)
                        i += 1
                        matched = True
                        break

            if matched:
                break

        if not matched:
            result_tokens.append(tokens[i])
            i += 1

    # Boşlukları normalize et
    return re.sub(r"\s+", " ", " ".join(result_tokens)).strip()


def canonical_form(text: str, country_code: str) -> str:
    """
    Ana API: ham metin → canonical form.

    Pipeline:
      1. NFKC Normalizasyonu
      2. Lowercase + boşluk normalizasyonu
      3. Noktalama temizliği (harf/rakam/temel işaretler)
      4. Synonym kuralları uygulama (ülkeye özgü + ortak)
    """
    if not text:
        return ""

    # NFKC Normalizasyonu
    text = normalize_text(text)

    # Lowercase + temel temizlik
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^\w\s\.\-\&]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return ""

    parsed_rules = _get_parsed_rules(country_code.upper())
    return apply_synonyms(cleaned, parsed_rules)


def stripped_form(text: str, country_code: str) -> str:
    """
    Generic kelimeleri (LTD, LLC, INC vb.) TAMAMEN temizler.
    Temizlenecek kelimeler o ülkenin synonym dosyalarındaki HEDEF (target)
    kısımlarından ve dinamik generic token listesinden gelir.
    """
    if not text:
        return ""

    # NFKC Normalizasyonu
    text = normalize_text(text)

    # 1. Temel temizlik (canonical_form ile aynı)
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^\w\s\.\-\&]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return ""

    # 2. Ülke bazlı generic token'ları al
    # Dönen değer cache-safe frozenset olduğu için mutable bir set'e çeviriyoruz
    to_remove = set(get_generic_tokens_for_country(country_code))

    # 3A. SUFFIX_TYPO_MAP key'lerini de temizlik listesine ekle.
    for typo in SUFFIX_TYPO_MAP:
        to_remove.add(typo.rstrip("."))

    # 4. Token bazlı temizlik
    tokens = cleaned.split()
    result_tokens = []
    for t in tokens:
        clean_t = t.rstrip(".")
        if clean_t in to_remove:
            continue
        # 3B. Son-harf-fazlalığı kontrolü: "INCC" → "INC" bilinen ise atla
        if len(clean_t) > 2 and clean_t[:-1] in to_remove:
            continue
        result_tokens.append(t)

    return " ".join(result_tokens).strip()


# ─────────────────────────────────────────────────────────────────────
# Hızlı test / geliştirme yardımcısı
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("Apple Corporation Ltd.", "US"),
        ("Apple Corp. Limited", "US"),
        ("Apple Corp. Ltd.", "US"),
        ("TOYOTA MOTORS INTERNATIONAL", "TR"),
        ("Toyota Otomotiv International", "TR"),
        ("Anonim Şirket Holding", "TR"),
        ("GmbH & Co. KG", "DE"),
    ]

    print("Canonical Form Testleri:")
    print("-" * 60)
    for name, cc in test_cases:
        result = canonical_form(name, cc)
        print(f"  [{cc}] {name!r}")
        print(f"       → {result!r}")
        print()

    print("Stripped Form Testleri:")
    print("-" * 60)
    stripped_tests = [
        ("Apple Inc.", "US"),
        ("Apple INCC", "US"),          # Typo: son-harf-fazlalığı
        ("Apple Limted", "US"),        # Typo: SUFFIX_TYPO_MAP
        ("Siemens GMHB", "DE"),       # Typo: SUFFIX_TYPO_MAP
        ("Konya Ticaret Ltd.", "TR"),
    ]
    for name, cc in stripped_tests:
        result = stripped_form(name, cc)
        print(f"  [{cc}] {name!r}")
        print(f"       → {result!r}")
        print()

    print("Bilinen Suffix Seti (US, ilk 20):")
    print("-" * 60)
    us_suffixes = sorted(build_known_suffixes("US"))[:20]
    print(f"  {us_suffixes}")


# ─────────────────────────────────────────────────────────────────────
# Hızlı test / geliştirme yardımcısı
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("Apple Corporation Ltd.", "US"),
        ("Apple Corp. Limited", "US"),
        ("Apple Corp. Ltd.", "US"),
        ("TOYOTA MOTORS INTERNATIONAL", "TR"),
        ("Toyota Otomotiv International", "TR"),
        ("Anonim Şirket Holding", "TR"),
        ("GmbH & Co. KG", "DE"),
    ]

    print("Canonical Form Testleri:")
    print("-" * 60)
    for name, cc in test_cases:
        result = canonical_form(name, cc)
        print(f"  [{cc}] {name!r}")
        print(f"       → {result!r}")
        print()

    print("Stripped Form Testleri:")
    print("-" * 60)
    stripped_tests = [
        ("Apple Inc.", "US"),
        ("Apple INCC", "US"),          # Typo: son-harf-fazlalığı
        ("Apple Limted", "US"),        # Typo: SUFFIX_TYPO_MAP
        ("Siemens GMHB", "DE"),       # Typo: SUFFIX_TYPO_MAP
        ("Konya Ticaret Ltd.", "TR"),
    ]
    for name, cc in stripped_tests:
        result = stripped_form(name, cc)
        print(f"  [{cc}] {name!r}")
        print(f"       → {result!r}")
        print()

    print("Bilinen Suffix Seti (US, ilk 20):")
    print("-" * 60)
    us_suffixes = sorted(build_known_suffixes("US"))[:20]
    print(f"  {us_suffixes}")
