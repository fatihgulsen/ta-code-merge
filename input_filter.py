# ============================================================================
# input_filter.py — Sınır (boundary) girdi-geçerliliği filtresi (P0-B / Faz 4)
# ============================================================================
# "Bu bir firma adı mı?" sorusunu yanıtlar. Firma-OLMAYAN girdileri (placeholder,
# salt-kod/sayı, baş-harf, aşırı uzun gümrük dizesi) tespit eder; bunlar eşleştirmeye
# sokulmadan EXCLUDED olarak izole edilir (ES'e indekslenmez → magnet olamaz).
#
# Bu KİMLİK/eşleşme kararı DEĞİLDİR (iki firmayı karşılaştırmaz) — yalnızca girdinin
# geçerli bir firma adı olup olmadığını denetler (CLAUDE.md: validate at boundaries).
# Fuzzy/Levenshtein YOK. Ülke-özel placeholder'lar config'ten gelir (synonyms_data sabit).
# Kanıt/ölçek: docs/audit/2026-06-03-llm-judge-rematch-comparison.md §4.
# ============================================================================

import re
import unicodedata

from config import (
    GARBAGE_CODE_DIGIT_RATIO,
    GARBAGE_CODE_MIN_LEN,
    GARBAGE_MAX_NAME_LEN,
    GARBAGE_MIN_INITIALS,
    NON_FIRM_PLACEHOLDERS,
)

_NONALNUM = re.compile(r"[^a-z0-9]+")
_NA_MARKERS = {"n a", "n/a", "s n", "nd"}  # '#N/A','N/A','S/N' → normalize sonrası


def _norm(text: str) -> str:
    """lower + aksan-fold (NFKD) + alfanümerik-olmayanları boşluğa indir + tek boşluk."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    return _NONALNUM.sub(" ", no_accent).strip()


def _placeholder_set(country: str) -> set:
    cc = (country or "").upper()
    return set(NON_FIRM_PLACEHOLDERS.get(cc, ())) | set(NON_FIRM_PLACEHOLDERS.get("__common__", ()))


def classify_input(raw_name: str, country: str) -> str | None:
    """Girdi firma-olmayan ise sebep stringi, geçerli firma adı ise None döner.

    Sebepler: empty | too_long | no_alnum | placeholder | na_marker | numeric |
              code | initials
    """
    if not raw_name or not raw_name.strip():
        return "empty"
    name = raw_name.strip()
    if len(name) > GARBAGE_MAX_NAME_LEN:
        return "too_long"

    norm = _norm(name)
    if not norm:
        return "no_alnum"

    # Ülke-özel/ortak placeholder (tam eşleşme)
    if norm in _placeholder_set(country):
        return "placeholder"

    # #N/A, N/A, S/N gibi işaretçiler
    if norm in _NA_MARKERS:
        return "na_marker"

    tokens = norm.split()
    core = norm.replace(" ", "")
    digit_count = sum(c.isdigit() for c in core)

    # Hiç harf yok → salt sayı/işaret
    if not any(c.isalpha() for c in core):
        return "numeric"

    # Alnum referans kodu: yeterli uzunluk + yüksek rakam oranı (3M gibi kısa markaları korur)
    if (
        len(core) >= GARBAGE_CODE_MIN_LEN
        and digit_count >= 3
        and digit_count / len(core) >= GARBAGE_CODE_DIGIT_RATIO
    ):
        return "code"

    # Baş-harf çöpü: >=N token, hepsi tek-harf (A.S/H M gibi 2'liler korunur)
    if len(tokens) >= GARBAGE_MIN_INITIALS and all(len(t) == 1 and t.isalpha() for t in tokens):
        return "initials"

    return None


# ─────────────────────────────────────────────────────────────────────
# DRY-RUN RAPOR — PG'yi salt-okunur tarar, neyin dışlanacağını sebep+örnek+sayı ile gösterir
# ─────────────────────────────────────────────────────────────────────

def report(conn, sample_per_reason: int = 8, only_unprocessed: bool = True) -> dict:
    """p7_firms_v2'yi tarar; her dışlama sebebi için sayı + örnek toplar (DEĞİŞİKLİK YOK)."""
    from collections import Counter, defaultdict
    import psycopg2.sql
    from psycopg2.extras import DictCursor
    from config import RAW_TABLE_NAME, COLUMN_MAPPING

    col_name = COLUMN_MAPPING["company_name"]
    col_country = COLUMN_MAPPING["country_code"]
    col_master = COLUMN_MAPPING["master_code"]

    where = psycopg2.sql.SQL("{m} IS NULL").format(m=psycopg2.sql.Identifier(col_master)) \
        if only_unprocessed else psycopg2.sql.SQL("TRUE")
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        psycopg2.sql.SQL("SELECT {n}, {c} FROM {t} WHERE {w}").format(
            n=psycopg2.sql.Identifier(col_name),
            c=psycopg2.sql.Identifier(col_country),
            t=psycopg2.sql.Identifier(RAW_TABLE_NAME),
            w=where,
        )
    )
    counts = Counter()
    samples = defaultdict(list)
    total = 0
    for r in cur:
        total += 1
        reason = classify_input((r[col_name] or ""), (r[col_country] or ""))
        if reason:
            counts[reason] += 1
            if len(samples[reason]) < sample_per_reason:
                samples[reason].append((r[col_name] or "")[:60])
    cur.close()
    return {"scanned": total, "excluded": sum(counts.values()), "by_reason": dict(counts),
            "samples": {k: v for k, v in samples.items()}}


if __name__ == "__main__":
    import psycopg2
    from config import DB_CONFIG

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rep = report(conn)
        print(f"Taranan: {rep['scanned']:,}  Dışlanacak: {rep['excluded']:,}")
        for reason, n in sorted(rep["by_reason"].items(), key=lambda kv: -kv[1]):
            print(f"\n  [{reason}] {n:,}")
            for s in rep["samples"][reason]:
                print(f"      {s}")
    finally:
        conn.close()
