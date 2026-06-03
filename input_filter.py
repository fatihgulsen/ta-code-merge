# ============================================================================
# input_filter.py — Sınır (boundary) girdi-geçerliliği filtresi (P0-B / Faz 4)
# ============================================================================
# "Bu girdi TAMAMEN ANLAMSIZ mı?" sorusunu yanıtlar — firma adı olarak GEÇERSİZ
# olanları (boş, salt-noktalama, n/a/null işaretçileri, 'unvan yok' placeholder'ları)
# tespit eder; bunlar eşleştirmeye sokulmadan EXCLUDED olarak izole edilir (ES'e
# indekslenmez → magnet olamaz).
#
# ÖNEMLİ FELSEFE: Bir firmanın "doğru" olup olmadığına KARAR VEREMEYİZ. Yalnızca
# kodlardan/sayılardan/baş-harflerden oluşan ya da çok uzun bir isim PEKÂLÂ gerçek
# (yeni) bir firma olabilir → bunlar DIŞLANMAZ, NEW_MASTER olur. Yalnızca hiçbir
# içerik taşımayan / 'isim yok' anlamına gelen girdiler elenir. Bu KİMLİK kararı
# DEĞİLDİR. Fuzzy/Levenshtein YOK. Placeholder'lar config'ten (synonyms_data sabit).
# Kanıt/ölçek: docs/audit/2026-06-03-llm-judge-rematch-comparison.md §4.
# ============================================================================

import re
import unicodedata

from config import NON_FIRM_PLACEHOLDERS

_NONALNUM = re.compile(r"[^a-z0-9]+")
# Salt yapısal "boş/null" işaretçileri (dil-bağımsız, içerik taşımayan):
_NA_MARKERS = {"n a", "na", "s n", "sn", "null", "none", "nan", "nil"}


def _norm(text: str) -> str:
    """lower + aksan-fold (NFKD) + alfanümerik-olmayanları boşluğa indir + tek boşluk."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    return _NONALNUM.sub(" ", no_accent).strip()


def _placeholder_set(country: str) -> set:
    cc = (country or "").upper()
    return set(NON_FIRM_PLACEHOLDERS.get(cc, ())) | set(NON_FIRM_PLACEHOLDERS.get("__common__", ()))


def classify_input(raw_name: str, country: str) -> str | None:
    """Girdi TAMAMEN ANLAMSIZ ise sebep stringi, aksi halde None döner.

    Sebepler (yalnızca içerik-taşımayan / 'isim yok'): empty | no_alnum | na_marker |
    placeholder.

    Kasıtlı olarak DIŞLANMAYANLAR (gerçek yeni firma olabilir): salt-kod, salt-sayı,
    baş-harf grupları, aşırı uzun isimler.
    """
    if not raw_name or not raw_name.strip():
        return "empty"

    norm = _norm(raw_name)
    if not norm:
        return "no_alnum"  # yalnızca noktalama → içerik yok

    # 'isim yok' anlamına gelen ülke-özel/ortak placeholder (tam eşleşme)
    if norm in _placeholder_set(country):
        return "placeholder"

    # n/a, null, none, nan, s/n gibi yapısal boş işaretçiler (tam eşleşme)
    if norm in _NA_MARKERS:
        return "na_marker"

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
