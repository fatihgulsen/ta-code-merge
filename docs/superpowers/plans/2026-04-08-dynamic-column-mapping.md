# Dynamic Column Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `generate_config.py` scripti olustur — PostgreSQL'den `p7_firms_v2` tablosunun sutunlarini okuyup `config.py`'deki `COLUMN_MAPPING` dictionary'sini otomatik olusturur.

**Architecture:** Tek dosyalik generator script. `config.py`'den `DB_CONFIG` ve `RAW_TABLE_NAME` import eder, `information_schema.columns` ile sutunlari ceker, `config.py` dosyasini metin olarak parse edip sadece `COLUMN_MAPPING` blogunu degistirir.

**Tech Stack:** Python 3, psycopg2, re (regex)

---

## File Structure

| Dosya | Durum | Sorumluluk |
|-------|-------|-----------|
| `generate_config.py` | Yeni | DB'den sutun okuma, config.py parse/guncelleme |
| `tests/test_generate_config.py` | Yeni | Generator icin unit testler |
| `config.py` | Degisiklik yok | Generator tarafindan COLUMN_MAPPING blogu guncellenecek |

---

## Task 1: config.py Parse — COLUMN_MAPPING Blogunu Bul ve Degistir

**Files:**
- Create: `generate_config.py`
- Test: `tests/test_generate_config.py`

Bu task sadece dosya parse/replace mantigi ile ilgilenir. DB baglantisi yok.

- [ ] **Step 1: Write failing test — find_column_mapping_block**

`tests/test_generate_config.py` dosyasini olustur:

```python
"""Tests for generate_config.py — config.py parser and updater."""


def test_find_column_mapping_block_simple():
    """COLUMN_MAPPING blogunu basit bir config icinde bulur."""
    from generate_config import find_column_mapping_block

    content = '''DB_CONFIG = {"host": "localhost"}

COLUMN_MAPPING = {
    "id": "id",
    "company_name": "name",
}

BATCH_SIZE = 5000
'''
    start, end = find_column_mapping_block(content)
    block = content[start:end]
    assert "COLUMN_MAPPING = {" in block
    assert '"id": "id"' in block
    assert "}" in block
    # Blogun disindakiler dahil olmamali
    assert "DB_CONFIG" not in block
    assert "BATCH_SIZE" not in block


def test_find_column_mapping_block_with_comments():
    """Yorum satirli COLUMN_MAPPING blogunu dogru bulur."""
    from generate_config import find_column_mapping_block

    content = '''# --- Tablo ve Sutun Ayarlari ---
RAW_TABLE_NAME = "p7_firms_v2"

# Dahili degisken isimleri -> Veritabani sutun isimleri
COLUMN_MAPPING = {
    # Okunacak Sutunlar (Read)
    "id": "id",
    "company_name": "name",
    # Guncellenecek Sutunlar (Write)
    "master_code": "master_code",
}

MANDATORY_READ_COLUMNS = ["id", "company_name"]
'''
    start, end = find_column_mapping_block(content)
    block = content[start:end]
    assert "COLUMN_MAPPING = {" in block
    assert '"master_code": "master_code"' in block
    assert "MANDATORY_READ_COLUMNS" not in block


def test_find_column_mapping_block_not_found():
    """COLUMN_MAPPING blogu yoksa ValueError firlatir."""
    from generate_config import find_column_mapping_block
    import pytest

    content = '''DB_CONFIG = {"host": "localhost"}
BATCH_SIZE = 5000
'''
    with pytest.raises(ValueError, match="COLUMN_MAPPING blogu bulunamadi"):
        find_column_mapping_block(content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generate_config'`

- [ ] **Step 3: Implement find_column_mapping_block**

`generate_config.py` dosyasini olustur:

```python
"""
generate_config.py — p7_firms_v2 tablosunun sutunlarini DB'den okuyup
config.py'deki COLUMN_MAPPING dictionary'sini otomatik olusturur.

Kullanim:
    python generate_config.py
"""

import re
import sys

import psycopg2


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
    # Oncesinde yorum satirlari olabilir, onlari dahil etmiyoruz
    match = re.search(r'^COLUMN_MAPPING\s*=\s*\{', content, re.MULTILINE)
    if not match:
        raise ValueError("COLUMN_MAPPING blogu bulunamadi — config.py'de 'COLUMN_MAPPING = {' satiri yok")

    start = match.start()
    # Suslu parantez sayaci ile blogun sonunu bul
    brace_count = 0
    i = match.start()
    while i < len(content):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                return start, end
        i += 1

    raise ValueError("COLUMN_MAPPING blogu bulunamadi — kapanan '}' eksik")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/All-project/ta-code-merge
git add generate_config.py tests/test_generate_config.py
git commit -m "feat: add config.py COLUMN_MAPPING block parser"
```

---

## Task 2: COLUMN_MAPPING Blok Olusturma ve Dosya Guncelleme

**Files:**
- Modify: `generate_config.py`
- Modify: `tests/test_generate_config.py`

- [ ] **Step 1: Write failing tests — build_column_mapping_block + replace_column_mapping**

`tests/test_generate_config.py` dosyasina ekle:

```python
def test_build_column_mapping_block():
    """DB sutunlarindan COLUMN_MAPPING blogu olusturur."""
    from generate_config import build_column_mapping_block

    columns = [
        ("id", "integer"),
        ("name", "character varying"),
        ("country_code", "character varying"),
        ("tax_id", "character varying"),
    ]
    result = build_column_mapping_block(columns)
    assert "COLUMN_MAPPING = {" in result
    assert '"id": "id",' in result
    assert '"name": "name",' in result
    assert "# integer" in result
    assert "# character varying" in result
    # Zorunlu internal isimler yorum olarak belirtilmeli
    assert "id, company_name, country_code" in result
    assert "master_code, match_score, match_type" in result


def test_build_column_mapping_block_empty():
    """Bos sutun listesi icin bos COLUMN_MAPPING olusturur."""
    from generate_config import build_column_mapping_block

    result = build_column_mapping_block([])
    assert "COLUMN_MAPPING = {" in result
    assert "}" in result


def test_replace_column_mapping():
    """config.py iceriginde COLUMN_MAPPING blogunu degistirir."""
    from generate_config import replace_column_mapping

    original = '''DB_CONFIG = {"host": "localhost"}

COLUMN_MAPPING = {
    "id": "id",
    "company_name": "name",
}

BATCH_SIZE = 5000
'''
    columns = [
        ("id", "integer"),
        ("firma_adi", "character varying"),
        ("ulke_kodu", "character varying"),
    ]
    result = replace_column_mapping(original, columns)
    # Yeni sutunlar olmali
    assert '"firma_adi": "firma_adi"' in result
    assert '"ulke_kodu": "ulke_kodu"' in result
    # Eski sutunlar olmamali
    assert '"company_name": "name"' not in result
    # Diger config degismemeli
    assert 'DB_CONFIG = {"host": "localhost"}' in result
    assert "BATCH_SIZE = 5000" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: 3 new tests FAIL — `ImportError: cannot import name 'build_column_mapping_block'`

- [ ] **Step 3: Implement build_column_mapping_block and replace_column_mapping**

`generate_config.py` dosyasina ekle (mevcut kodun altina):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/All-project/ta-code-merge
git add generate_config.py tests/test_generate_config.py
git commit -m "feat: add COLUMN_MAPPING block builder and replacer"
```

---

## Task 3: DB'den Sutun Okuma

**Files:**
- Modify: `generate_config.py`
- Modify: `tests/test_generate_config.py`

- [ ] **Step 1: Write failing test — fetch_table_columns**

`tests/test_generate_config.py` dosyasina ekle:

```python
def test_fetch_table_columns_query(monkeypatch):
    """fetch_table_columns dogru SQL sorgusunu calistirir."""
    from generate_config import fetch_table_columns

    executed_queries = []

    class FakeCursor:
        def execute(self, query, params=None):
            executed_queries.append((query, params))

        def fetchall(self):
            return [("id", "integer", 1), ("name", "character varying", 2)]

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    result = fetch_table_columns(FakeConn(), "p7_firms_v2")
    assert result == [("id", "integer"), ("name", "character varying")]
    assert len(executed_queries) == 1
    assert "information_schema.columns" in executed_queries[0][0]
    assert executed_queries[0][1] == ("p7_firms_v2",)


def test_fetch_table_columns_empty(monkeypatch):
    """Tablo bos veya bulunamazsa bos liste doner."""
    from generate_config import fetch_table_columns

    class FakeCursor:
        def execute(self, query, params=None):
            pass

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    result = fetch_table_columns(FakeConn(), "nonexistent_table")
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py::test_fetch_table_columns_query tests/test_generate_config.py::test_fetch_table_columns_empty -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_table_columns'`

- [ ] **Step 3: Implement fetch_table_columns**

`generate_config.py` dosyasina ekle (`find_column_mapping_block` fonksiyonunun ustune):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/All-project/ta-code-merge
git add generate_config.py tests/test_generate_config.py
git commit -m "feat: add DB column fetcher for table schema discovery"
```

---

## Task 4: main() Fonksiyonu — Hepsini Birlestir

**Files:**
- Modify: `generate_config.py`
- Modify: `tests/test_generate_config.py`

- [ ] **Step 1: Write failing test — main flow**

`tests/test_generate_config.py` dosyasina ekle:

```python
import os
import tempfile


def test_main_updates_config_file(monkeypatch):
    """main() config.py dosyasini DB sutunlariyla gunceller."""
    from generate_config import main

    # Fake config.py icerigi
    fake_config_content = '''DB_CONFIG = {"host": "localhost"}

RAW_TABLE_NAME = "p7_firms_v2"

COLUMN_MAPPING = {
    "id": "id",
    "company_name": "name",
}

BATCH_SIZE = 5000
'''
    # Gecici dosya olustur
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(fake_config_content)
        temp_path = f.name

    try:
        # DB baglantisini mockla
        class FakeCursor:
            def execute(self, query, params=None):
                pass

            def fetchall(self):
                return [
                    ("id", "integer", 1),
                    ("firma_adi", "character varying", 2),
                    ("ulke", "character varying", 3),
                ]

            def close(self):
                pass

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def close(self):
                pass

        monkeypatch.setattr(
            "generate_config.psycopg2",
            type("FakePsycopg2", (), {"connect": staticmethod(lambda **kw: FakeConn())})(),
        )
        monkeypatch.setattr("generate_config.DB_CONFIG", {"host": "localhost"})
        monkeypatch.setattr("generate_config.RAW_TABLE_NAME", "p7_firms_v2")

        main(config_path=temp_path)

        with open(temp_path, 'r', encoding='utf-8') as f:
            result = f.read()

        # Yeni sutunlar olmali
        assert '"firma_adi": "firma_adi"' in result
        assert '"ulke": "ulke"' in result
        # Eski sutunlar olmamali
        assert '"company_name": "name"' not in result
        # Diger config degismemeli
        assert "BATCH_SIZE = 5000" in result
        assert 'RAW_TABLE_NAME = "p7_firms_v2"' in result
    finally:
        os.unlink(temp_path)


def test_main_config_file_not_found(monkeypatch):
    """config.py bulunamazsa SystemExit firlatir."""
    from generate_config import main
    import pytest

    monkeypatch.setattr("generate_config.DB_CONFIG", {"host": "localhost"})
    monkeypatch.setattr("generate_config.RAW_TABLE_NAME", "p7_firms_v2")

    class FakeConn:
        def cursor(self):
            return type("C", (), {
                "execute": lambda s, q, p=None: None,
                "fetchall": lambda s: [("id", "integer", 1)],
                "close": lambda s: None,
            })()

        def close(self):
            pass

    monkeypatch.setattr(
        "generate_config.psycopg2",
        type("FakePsycopg2", (), {"connect": staticmethod(lambda **kw: FakeConn())})(),
    )

    with pytest.raises(SystemExit):
        main(config_path="/nonexistent/path/config.py")


def test_main_empty_table(monkeypatch):
    """Tablo bos ise (sutun yok) SystemExit firlatir."""
    from generate_config import main
    import pytest

    class FakeCursor:
        def execute(self, query, params=None):
            pass

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        "generate_config.psycopg2",
        type("FakePsycopg2", (), {"connect": staticmethod(lambda **kw: FakeConn())})(),
    )
    monkeypatch.setattr("generate_config.DB_CONFIG", {"host": "localhost"})
    monkeypatch.setattr("generate_config.RAW_TABLE_NAME", "test_table")

    with pytest.raises(SystemExit):
        main(config_path="some_path.py")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py::test_main_updates_config_file tests/test_generate_config.py::test_main_config_file_not_found tests/test_generate_config.py::test_main_empty_table -v`
Expected: FAIL — `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement main()**

`generate_config.py` dosyasina ekle (en alta):

```python
from config import DB_CONFIG, RAW_TABLE_NAME


def main(config_path: str = "config.py") -> None:
    """DB'den sutun isimlerini okuyup config.py'deki COLUMN_MAPPING'i gunceller.

    Args:
        config_path: Guncellenecek config dosyasinin yolu.
    """
    # 1. DB'ye baglan ve sutunlari cek
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"HATA: PostgreSQL baglantisi basarisiz — {e}")
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

    print(f"BASARILI: {len(columns)} sutun config.py'ye yazildi.")
    print("Simdi config.py'yi acip COLUMN_MAPPING'in sol tarafindaki isimleri duzenleyin.")
    print(f"Zorunlu internal isimler: id, company_name, country_code")
    print(f"Zorunlu update isimleri: master_code, match_score, match_type")


if __name__ == "__main__":
    main()
```

**Not:** `from config import DB_CONFIG, RAW_TABLE_NAME` satiri dosyanin basindaki importlara tasininmali. Son hali icin dosyadaki import sirasi:

```python
import re
import sys

import psycopg2

from config import DB_CONFIG, RAW_TABLE_NAME
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/test_generate_config.py -v`
Expected: 11 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/All-project/ta-code-merge
git add generate_config.py tests/test_generate_config.py
git commit -m "feat: add main() — complete generate_config.py workflow"
```

---

## Task 5: Son Dogrulama

**Files:**
- Degisiklik yok — sadece test ve dogrulama

- [ ] **Step 1: Tum testleri calistir**

Run: `cd C:/All-project/ta-code-merge && python -m pytest tests/ -v`
Expected: Tum testler PASS (mevcut test_config.py + yeni test_generate_config.py)

- [ ] **Step 2: generate_config.py'yi gercek DB ile test et (opsiyonel)**

Eger PostgreSQL calisiyor ve `p7_firms_v2` tablosu mevcutsa:

Run: `cd C:/All-project/ta-code-merge && python generate_config.py`
Expected:
```
BASARILI: N sutun config.py'ye yazildi.
Simdi config.py'yi acip COLUMN_MAPPING'in sol tarafindaki isimleri duzenleyin.
Zorunlu internal isimler: id, company_name, country_code
Zorunlu update isimleri: master_code, match_score, match_type
```

- [ ] **Step 3: config.py'nin dogru guncellendigini dogrula**

Run: `cd C:/All-project/ta-code-merge && python -c "from config import COLUMN_MAPPING; print(COLUMN_MAPPING)"`
Expected: COLUMN_MAPPING dict'i DB sutunlariyla dolu

- [ ] **Step 4: Final commit**

```bash
cd C:/All-project/ta-code-merge
git add -A
git commit -m "feat: complete dynamic column mapping generator"
```
