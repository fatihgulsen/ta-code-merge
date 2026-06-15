"""Girdi geçerlilik filtresi.

'Bu girdi firma adı olarak anlamlı mı?' sorusunu yanıtlar. Boş, salt-noktalama,
n/a işaretçileri ve 'unvan yok' placeholder'ları EXCLUDED olarak izole edilir —
eşleştirmeye sokulmazlar. Yalnızca içerik taşımayan girdiler elenir; kimlik kararı
verilmez (salt-kod/baş-harf grupları NEW_MASTER olabilir). Placeholder'lar
synonyms_data JSON'undan okunur, hardcode edilmez (bkz. docs/audit/).
"""

import re
import unicodedata
from functools import lru_cache

from synonym_loader import get_non_firm_placeholders

# Unicode-aware: Latin-dışı alfabeler (Kiril/CJK/Arap) içerik taşır → no_alnum sayılmaz.
# \w py3'te Unicode harf/rakam eşler; '_' ayrıca elenir.
_NONALNUM = re.compile(r"[\W_]+")
# Dil-bağımsız yapısal boş/null işaretçileri (içerik taşımayan):
_NA_MARKERS = {"n a", "na", "s n", "sn", "null", "none", "nan", "nil"}


def _norm(text: str) -> str:
    """lower + NFKD aksan-fold + alfanümerik-olmayanları boşluğa indir + tek boşluk.

    Latin-dışı içerik (Kiril/CJK) korunur; bu sayede 'isim yok' kararı
    yalnızca gerçekten içerik taşımayan girdilere uygulanır."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    return _NONALNUM.sub(" ", no_accent).strip()


@lru_cache(maxsize=None)
def _placeholder_set(country: str) -> frozenset:
    """Ülke için 'firma değil' placeholder'larını _norm edilmiş frozenset olarak döner.

    synonyms_data/{common,<cc>}.json 'non_firm_placeholders' kategorisinden okunur
    (hardcode değil). classify_input ile aynı _norm geçirilir → tam eşleşme tutarlı."""
    cc = (country or "").upper()
    return frozenset(n for p in get_non_firm_placeholders(cc) if (n := _norm(p)))


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


def report(conn, sample_per_reason: int = 8, only_unprocessed: bool = True) -> dict:
    """PG'yi salt-okunur tarar; her dışlama sebebi için sayı ve örnek toplar (değişiklik yapmaz)."""
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
