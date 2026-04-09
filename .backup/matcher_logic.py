# ============================================================================
# matcher_logic.py - Çekirdek Eşleştirme Mantığı
# ============================================================================
# Mimari:
#   Python → veri temizliği + canonical normalizasyon
#   ES     → tüm matching, fuzzy, ranking (function_score + fuzziness)
#   Python → ES _score'u okuyup match_type tag'i ata
#
# Country Code HARD FILTER olarak kullanılır: ülke uyumsuzluğunda
# eşleşme ASLA yapılmaz.
# ============================================================================

import re
import uuid

from elasticsearch import Elasticsearch

from config import (
    ES_INDEX,
    ES_MIN_SCORE,
    ES_TAX_WEIGHT,
    ES_PHONE_WEIGHT,
    SUFFIX_TYPO_MAP,
    LENGTH_RATIO_THRESHOLD,
    TOKEN_COVERAGE_THRESHOLD,
    MatchType,
)
from synonym_loader import (
    normalize_text,
    get_generic_tokens_for_country,
    load_synonyms_for_country,
    get_all_country_codes,
)
from synonym_normalizer import (
    canonical_form,
    stripped_form,
    build_known_suffixes,
)


# ─────────────────────────────────────────────────────────────────────
# 1. VERİ TEMİZLİĞİ
# ─────────────────────────────────────────────────────────────────────


def light_clean(text: str, country_code: str = "") -> str:
    """
    Gelişmiş veri temizliği: Labels ayıklama, suffix typo düzeltme,
    birleşik suffix ayırma, nokta pattern normalizasyonu.

    Pipeline sırası:
        1. NFKC Normalizasyonu
        2. Zero-width / görünmez karakter temizliği
        3. Parantez ve köşeli parantez içeriği kaldırma
        4. Label temizliği (email:, c/o, attn)
        5. C/O ve ATTN sonrası tamamen kesme
        6. Ampersand normalizasyonu (& → and)
        7. Özel karakter temizliği
        8. Nokta-harf pattern normalizasyonu (L.T.D. → LTD)
        9. Boşluklu harf normalizasyonu (L T D → LTD)
        10. Birleşik suffix ayırma (PVTLTD → PVT LTD)
        11. Çift-harf typo düzeltme (INCC → INC)
        12. Bilinen suffix typo düzeltme (LIMTED → LIMITED)
    """
    if not text:
        return ""

    # 1. NFKC Normalizasyonu
    text = normalize_text(text)

    text = text.strip()

    # 2. Zero-width ve görünmez karakter temizliği
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)

    text = text.lower().strip()

    # 3. Parantez içeriği kaldır: "ECIR INC. (UBEL CORP.)" → "ECIR INC."
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)

    # "email:", "tel:" gibi etiketleri temizle (sonrasını kesmeden)
    text = re.sub(r"^(email|attn|tel|phone|web|site)\s*:", "", text)

    # 4. C/O, ATTN ve TO THE ORDER OF temizliği (sonrasını kesmeden sadece kendilerini sil)
    text = re.sub(r"\bc/o\b", "", text)
    text = re.sub(r"\battn\b", "", text)
    text = re.sub(r"\bcare of\b", "", text)
    text = re.sub(r"\bto the order of\b", "", text)

    # 5. Ampersand normalizasyonu: & → and
    text = re.sub(r"\s*&\s*", " and ", text)

    # Özel karakterler temizliği (sadece harf, rakam ve temel işaretler kalsın)
    text = re.sub(r"[^\w\s\&\.\-]", " ", text)

    # 6. Nokta-harf pattern normalizasyonu: L.T.D. → LTD, G.M.B.H. → GMBH
    text = re.sub(
        r"\b((?:[a-zA-ZçğıöşüÇĞİÖŞÜ]\.){2,})",
        lambda m: m.group(0).replace(".", ""),
        text,
    )

    # Çift boşlukları tek indir
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return ""

    # ── Suffix-aware normalizasyonlar (country_code gerektirir) ──
    cc = (country_code or "").strip().upper()
    if cc:
        known_suffixes = build_known_suffixes(cc)
        tokens = text.split()
        tokens = _normalize_spaced_letters(tokens, known_suffixes)
        tokens = _split_fused_suffixes(tokens, known_suffixes)
        tokens = _fix_double_letter_typos(tokens, known_suffixes)
        tokens = _fix_known_suffix_typos(tokens)
        text = " ".join(tokens)

    # Son boşluk normalizasyonu
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_spaced_letters(tokens: list[str], known_suffixes: set[str]) -> list[str]:
    """1C. Boşluklu harf normalizasyonu: ['l', 't', 'd'] → ['ltd']"""
    result: list[str] = []
    i = 0
    while i < len(tokens):
        if len(tokens[i]) == 1 and tokens[i].isalpha():
            j = i + 1
            while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
                j += 1
            run_len = j - i
            if run_len >= 2:
                joined = "".join(tokens[i:j])
                if joined in known_suffixes:
                    result.append(joined)
                    i = j
                    continue
            result.append(tokens[i])
            i += 1
        else:
            result.append(tokens[i])
            i += 1
    return result


def _split_fused_suffixes(tokens: list[str], known_suffixes: set[str]) -> list[str]:
    """1B. Birleşik suffix ayırma: 'pvtltd' → ['pvt', 'ltd']"""
    sorted_suffixes = sorted(known_suffixes, key=len, reverse=True)
    result: list[str] = []
    for token in tokens:
        if len(token) < 4:
            result.append(token)
            continue
        split_done = False
        for suffix in sorted_suffixes:
            if len(suffix) >= len(token):
                continue
            if token.endswith(suffix):
                prefix = token[: -len(suffix)]
                if prefix in known_suffixes:
                    result.append(prefix)
                    result.append(suffix)
                    split_done = True
                    break
        if not split_done:
            result.append(token)
    return result


def _fix_double_letter_typos(tokens: list[str], known_suffixes: set[str]) -> list[str]:
    """1D. Çift-harf typo düzeltme: 'incc' → 'inc'"""
    result: list[str] = []
    for token in tokens:
        if len(token) >= 3 and token[-1] == token[-2]:
            candidate = token[:-1]
            if candidate in known_suffixes and token not in known_suffixes:
                result.append(candidate)
                continue
        result.append(token)
    return result


def _fix_known_suffix_typos(tokens: list[str]) -> list[str]:
    """1E. Bilinen suffix typo düzeltme: 'limted' → 'limited'"""
    result: list[str] = []
    for token in tokens:
        clean_t = token.rstrip(".")
        if clean_t in SUFFIX_TYPO_MAP:
            result.append(SUFFIX_TYPO_MAP[clean_t])
        else:
            result.append(token)
    return result


def latinize(text: str) -> str:
    """Latinize dönüşümü (unidecode yetmiyorsa NFKC sonrası unidecode)."""
    from text_unidecode import unidecode
    return unidecode(text) if text else ""


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    return re.sub(r"[^\d]", "", phone)


def normalize_tax(tax: str | None) -> str:
    if not tax:
        return ""
    return re.sub(r"[^\w]", "", tax).upper()


# ─────────────────────────────────────────────────────────────────────
# 2. TOKEN KALİTE KONTROL YARDIMCILARI
# ─────────────────────────────────────────────────────────────────────


def _meaningful_tokens(canonical_name: str, country_code: str) -> set[str]:
    """Canonical isimden generic token'ları dinamik olarak çıkarır."""
    tokens = set(canonical_name.lower().split())
    generic_tokens = get_generic_tokens_for_country(country_code)
    return tokens - generic_tokens


# ─────────────────────────────────────────────────────────────────────
# 3. ELASTICSEARCH SORGUSU
# ─────────────────────────────────────────────────────────────────────


def _get_analyzer_for_country(country: str) -> str:
    cc = country.upper()
    if cc in get_all_country_codes():
        return f"clean_analyzer_{cc}"
    return "clean_analyzer_common"


def build_search_query(
    canon_name: str,
    canon_latin: str,
    country: str,
    tax_number: str = "",
    phone_number: str = "",
) -> dict:
    """
    Elasticsearch sorgusu oluşturur (Order-Aware).
    
    Tier 1: match_phrase (Sıralama önemli) - Boost 100
    Tier 2: match_phrase stripped - Boost 50
    Tier 3: match (operator:and) - Sıralama önemsiz token coverage - Boost 10
    """
    analyzer = _get_analyzer_for_country(country.upper())
    input_stripped = stripped_form(canon_name, country)

    should_clauses = [
        # 1. Canonical Exact Phrase (Sıralama Duyarlı)
        {
            "match_phrase": {
                "variations": {
                    "query": canon_name,
                    "analyzer": analyzer,
                    "boost": 100,
                }
            }
        },
        # 2. Stripped Exact Phrase (Sıralama Duyarlı)
        {
            "match_phrase": {
                "variations_stripped": {
                    "query": input_stripped,
                    "analyzer": "standard",
                    "boost": 50,
                }
            }
        } if input_stripped else None,
        # 3. Token Coverage (Sıralama Önemsiz ama tüm tokenlar olmalı)
        {
            "match": {
                "variations": {
                    "query": canon_name,
                    "analyzer": analyzer,
                    "operator": "and",
                    "boost": 10,
                }
            }
        },
        # 4. Latinize Backstop
        {
            "match_phrase": {
                "variations.unidecode": {
                    "query": canon_latin,
                    "analyzer": "standard",
                    "boost": 5,
                }
            }
        },
        # 5. Fuzzy Backstop (Suffix typo koruması)
        {
            "match": {
                "variations": {
                    "query": canon_name,
                    "analyzer": analyzer,
                    "fuzziness": "AUTO",
                    "prefix_length": 2,
                    "boost": 1,
                }
            }
        },
    ]

    should_clauses = [c for c in should_clauses if c]

    # function_score: Tax ve phone eşleşirse _score'a ekle
    functions = []
    if tax_number:
        functions.append({"filter": {"term": {"tax_number": tax_number}}, "weight": ES_TAX_WEIGHT})
    if phone_number:
        functions.append({"filter": {"term": {"phone_number": phone_number}}, "weight": ES_PHONE_WEIGHT})

    main_query = {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }

    if functions:
        final_query = {
            "function_score": {
                "query": main_query,
                "functions": functions,
                "score_mode": "sum",
                "boost_mode": "sum",
            }
        }
    else:
        final_query = main_query

    return {
        "query": {
            "bool": {
                "must": [final_query],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────
# 4. KARAR MOTORU VE ANA FONKSİYON
# ─────────────────────────────────────────────────────────────────────


def find_best_match(
    es: Elasticsearch,
    raw_name: str,
    country: str,
    tax_number: str = "",
    phone_number: str = "",
) -> dict:
    country = (country or "").strip().upper()
    if not country:
        return _new_master_result(raw_name or "", rejection_reason="MISSING_COUNTRY_CODE")

    name_orig = light_clean(raw_name, country_code=country)
    clean_tax = normalize_tax(tax_number)
    clean_phone = normalize_phone(phone_number)

    if not name_orig:
        return _new_master_result("")

    # ── YOL 0: Tax Number ile Deterministic Eşleme ──
    if clean_tax:
        tax_res = es.search(
            index=ES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"tax_number": clean_tax}},
                            {"term": {"country_code": country}},
                        ]
                    }
                }
            },
            size=1,
        )
        if tax_res["hits"]["total"]["value"] > 0:
            hit = tax_res["hits"]["hits"][0]
            return {
                "master_id": hit["_source"]["master_id"],
                "score": 100,
                "match_type": MatchType.TAX_MATCH,
                "is_new": False,
                "name_orig": name_orig,
            }

    canon_name = canonical_form(name_orig, country)
    canon_latin = latinize(canon_name)

    # Güvenlik: Anlamlı token yoksa blokla
    if not _meaningful_tokens(canon_name, country):
        return _new_master_result(name_orig, canonical_name=canon_name, rejection_reason="ALL_GENERIC_TOKENS")

    # ── ES Sorgusu ──
    query = build_search_query(canon_name, canon_latin, country, clean_tax, clean_phone)
    res = es.search(index=ES_INDEX, body=query, size=10, min_score=ES_MIN_SCORE)
    hits = res["hits"]["hits"]

    if not hits:
        return _new_master_result(name_orig, canonical_name=canon_name)

    input_stripped = stripped_form(name_orig, country)
    
    # Skor bazlı ve Phrase bazlı doğrulama
    for hit in hits:
        src = hit["_source"]
        hit_vars = src.get("variations", [])
        hit_stripped = src.get("variations_stripped", [])

        # 1. CANONICAL_EXACT
        for v in hit_vars:
            if canonical_form(v, country) == canon_name:
                return {
                    "master_id": src["master_id"],
                    "score": 100,
                    "match_type": MatchType.CANONICAL_EXACT,
                    "is_new": False,
                    "name_orig": name_orig,
                    "canonical_name": canon_name,
                }

        # 2. STRIPPED_EXACT
        if input_stripped:
            for vs in hit_stripped:
                if vs == input_stripped:
                    return {
                        "master_id": src["master_id"],
                        "score": 100,
                        "match_type": MatchType.STRIPPED_EXACT,
                        "is_new": False,
                        "name_orig": name_orig,
                        "canonical_name": canon_name,
                    }

    # 3. TOKEN_COVERAGE (Backstop)
    input_meaningful = _meaningful_tokens(canon_name, country)
    if input_meaningful:
        for hit in hits:
            src = hit["_source"]
            for v in src.get("variations", []):
                v_canon = canonical_form(v, country)
                v_meaningful = _meaningful_tokens(v_canon, country)
                if not v_meaningful:
                    continue
                overlap = input_meaningful & v_meaningful
                if not overlap:
                    continue

                cov_input = len(overlap) / len(input_meaningful)
                cov_hit = len(overlap) / len(v_meaningful)

                if cov_input >= TOKEN_COVERAGE_THRESHOLD and cov_hit >= TOKEN_COVERAGE_THRESHOLD:
                    # ── UNIQUE TOKEN GUARD ──────────────────────────────────────
                    # Eğer her iki ismin de overlap dışında en az 1 unique tokeni
                    # varsa, bu iki isim birbirinden ayrışıyordur → match etme.
                    # Örnek:
                    #   M1 = {shenzhenshi, HUTIANYI, keji, youxian, gongsi}
                    #   M2 = {shenzhenshi, SINUOEN,  keji, youxian, gongsi}
                    #   unique_1 = {HUTIANYI}, unique_2 = {SINUOEN}
                    #   → Her ikisi de 1 unique token'a sahip → FALSE POSITIVE → SKIP
                    unique_to_input = input_meaningful - v_meaningful
                    unique_to_hit = v_meaningful - input_meaningful
                    if unique_to_input and unique_to_hit:
                        # Her iki isim birbirinden farklılaşıyor, eşleştirme.
                        continue

                    return {
                        "master_id": src["master_id"],
                        "score": 90,
                        "match_type": MatchType.TOKEN_COVERAGE,
                        "is_new": False,
                        "name_orig": name_orig,
                        "canonical_name": canon_name,
                    }

    return _new_master_result(name_orig, canonical_name=canon_name, rejection_reason="STRICT_IDENTITY_NOT_FOUND")


def _new_master_result(name_orig: str, **kwargs) -> dict:
    res = {
        "master_id": str(uuid.uuid4()),
        "score": 100,
        "match_type": MatchType.NEW_MASTER,
        "is_new": True,
        "name_orig": name_orig,
    }
    res.update(kwargs)
    return res
