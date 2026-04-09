"""Tests for generate_config.py — config.py parser and updater."""

import os
import tempfile


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


def test_find_column_mapping_block_unclosed_brace():
    """COLUMN_MAPPING acilip kapanmazsa ValueError firlatir."""
    from generate_config import find_column_mapping_block
    import pytest

    content = 'COLUMN_MAPPING = {\n    "id": "id"\n'
    with pytest.raises(ValueError, match="kapanan.*eksik"):
        find_column_mapping_block(content)


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


def test_fetch_table_columns_query():
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


def test_fetch_table_columns_empty():
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
