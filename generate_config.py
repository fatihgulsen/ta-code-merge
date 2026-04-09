"""
generate_config.py — p7_firms_v2 tablosunun sutunlarini DB'den okuyup
config.py'deki COLUMN_MAPPING dictionary'sini otomatik olusturur.

Kullanim:
    python generate_config.py
"""

from __future__ import annotations

import re
import sys

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

try:
    from config import DB_CONFIG, RAW_TABLE_NAME
except ImportError:
    DB_CONFIG = None  # type: ignore[assignment]
    RAW_TABLE_NAME = None  # type: ignore[assignment]


def fetch_table_columns(conn, table_name: str) -> list[tuple[str, str]]:
    """PostgreSQL tablosunun sutun isimlerini ve veri tiplerini getirir.

    Args:
        conn: psycopg2 connection nesnesi.
        table_name: Sorgulanacak tablo adi.

    Returns:
        [(sutun_adi, veri_tipi), ...] listesi, ordinal_position sirasinda.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name, data_type, ordinal_position
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [(row[0], row[1]) for row in rows]


def find_column_mapping_block(content: str) -> tuple[int, int]:
    """config.py iceriginde COLUMN_MAPPING = { ... } blogunu bulur.

    Args:
        content: config.py dosyasinin tam icerigi.

    Returns:
        (start, end) — blogun baslangic ve bitis indeksleri (COLUMN_MAPPING
        satirinin basladigindan, kapanan }'nin hemen sonrasina kadar).

    Raises:
        ValueError: COLUMN_MAPPING blogu bulunamazsa.
    """
    # COLUMN_MAPPING = { ile baslayan satiri bul
    match = re.search(r'^COLUMN_MAPPING\s*=\s*\{', content, re.MULTILINE)
    if not match:
        raise ValueError("COLUMN_MAPPING blogu bulunamadi — config.py'de 'COLUMN_MAPPING = {' satiri yok")

    # COLUMN_MAPPING'in hemen oncesindeki ardisik yorum satirlarini da dahil et
    start = match.start()
    lines_before = content[:start].rstrip('\n').split('\n')
    while lines_before and lines_before[-1].strip().startswith('#'):
        lines_before.pop()
    if lines_before:
        start = len('\n'.join(lines_before)) + 1  # +1 for the trailing \n
    else:
        start = 0
    brace_count = 0
    i = match.start()
    in_string = False
    string_char = None

    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == '\\':
                i += 2
                continue
            if ch == string_char:
                in_string = False
        elif ch in ('"', "'"):
            in_string = True
            string_char = ch
        elif ch == '{':
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                return start, end
        i += 1

    raise ValueError("COLUMN_MAPPING blogu bulunamadi — kapanan '}' eksik")


def build_column_mapping_block(columns: list[tuple[str, str]]) -> str:
    """DB sutun listesinden COLUMN_MAPPING blogu olusturur.

    Args:
        columns: [(sutun_adi, veri_tipi), ...] listesi, ordinal_position sirasinda.

    Returns:
        Hazir COLUMN_MAPPING = { ... } blogu (yorum satirlari dahil).
    """
    lines = [
        "# generate_config.py tarafindan otomatik olusturuldu.",
        "# Sol taraftaki isimleri degistirin. Sag taraf DB sutunlaridir.",
        "# Zorunlu internal isimler: id, company_name, country_code",
        "# Zorunlu update isimleri: master_code, match_score, match_type",
        "COLUMN_MAPPING = {",
    ]
    for col_name, col_type in columns:
        # Hizalama icin padding hesapla
        entry = f'    "{col_name}": "{col_name}",'
        padding = max(1, 40 - len(entry))
        lines.append(f'{entry}{" " * padding}# {col_type}')
    lines.append("}")
    return "\n".join(lines)


def replace_column_mapping(content: str, columns: list[tuple[str, str]]) -> str:
    """config.py iceriginde COLUMN_MAPPING blogunu yeni sutunlarla degistirir.

    Args:
        content: config.py dosyasinin tam icerigi.
        columns: [(sutun_adi, veri_tipi), ...] listesi.

    Returns:
        Guncellenmmis config.py icerigi.
    """
    start, end = find_column_mapping_block(content)
    new_block = build_column_mapping_block(columns)
    return content[:start] + new_block + content[end:]


def main(config_path: str = "config.py") -> None:
    """DB'den sutun isimlerini okuyup config.py'deki COLUMN_MAPPING'i gunceller.

    Args:
        config_path: Guncellenecek config dosyasinin yolu.
    """
    # 1. DB'ye baglan ve sutunlari cek
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"HATA: PostgreSQL baglantisi basarisiz - {e}")
        sys.exit(1)

    try:
        columns = fetch_table_columns(conn, RAW_TABLE_NAME)
    finally:
        conn.close()

    if not columns:
        print(f"HATA: '{RAW_TABLE_NAME}' tablosunda sutun bulunamadi veya tablo mevcut degil.")
        sys.exit(1)

    # 2. config.py'yi oku
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"HATA: '{config_path}' dosyasi bulunamadi.")
        sys.exit(1)

    # 3. COLUMN_MAPPING blogunu degistir
    try:
        updated = replace_column_mapping(content, columns)
    except ValueError as e:
        print(f"HATA: {e}")
        sys.exit(1)

    # 4. Dosyayi yaz
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(updated)

    # 5. Sonuc raporu
    col_names = [c[0] for c in columns]
    print(f"\nBASARILI: '{RAW_TABLE_NAME}' tablosundan {len(columns)} sutun okundu.\n")
    print("DB sutunlari:")
    for col_name, col_type in columns:
        print(f"  - {col_name} ({col_type})")

    print(f"\nconfig.py guncellendi: {config_path}")
    print("Sol taraftaki isimleri duzenleyin. Sag taraf DB sutunlaridir.\n")

    # Zorunlu internal isimleri listele ve uyar
    mandatory_read = ["id", "company_name", "country_code"]
    mandatory_update = ["master_code", "match_score", "match_type"]

    print("ZORUNLU internal isimler (sol tarafa bunlari yazin):")
    for m in mandatory_read:
        print(f"  - {m}")
    print()
    print("ZORUNLU update isimleri (sol tarafa bunlari yazin):")
    for m in mandatory_update:
        print(f"  - {m}")

    # Uyari: update sutunlari tabloda yoksa sorun degil (AUTO_CREATE)
    missing_in_db = [m for m in mandatory_update if m not in col_names]
    if missing_in_db:
        print(f"\n  Not: {missing_in_db} tabloda yok - AUTO_CREATE_UPDATE_COLUMNS=True ise otomatik olusturulur.")


if __name__ == "__main__":
    main()
