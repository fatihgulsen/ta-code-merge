# ============================================================================
# config.py - Firma Eşleştirme Sistemi Ayarları
# ============================================================================


# --- Match Type Sabitleri ---
class MatchType:
    """Eşleştirme sonucu tip etiketleri."""

    TAX_MATCH = "TAX_MATCH"
    # Vergi no kesin eşleşme (Path 0, deterministic)

    CANONICAL_EXACT = "CANONICAL_EXACT"
    # Canonical form tam eşleşme

    STRIPPED_EXACT = "STRIPPED_EXACT"
    # Synonym ve suffixler temizlendiğinde birebir aynı olanlar

    TOKEN_COVERAGE = "TOKEN_COVERAGE"
    # Anlamlı token'ların simetrik örtüşmesi eşik üstünde

    NEW_MASTER = "NEW_MASTER"
    # Eşleşme yok — yeni master açılır


# --- PostgreSQL Bağlantı ---
DB_CONFIG = {
    "dbname": "market_calculus",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
}

# --- Tablo ve Sütun Ayarları ---
RAW_TABLE_NAME = "p7_firms_v2"

# Dahili değişken isimleri -> Veritabanı sütun isimleri
# Bu mapping sayesinde kod içinde "tax_number" kullanmaya devam edebiliriz,
# veritabanında sütun adı "vergi_no" olsa bile.
COLUMN_MAPPING = {
    # Okunacak Sütunlar (Read)
    "id": "id",
    "company_name": "name",
    "country_code": "country_code",
    "tax_number": "tax_id",
    "phone_number": "tel",
    # Güncellenecek Sütunlar (Write)
    "master_code": "master_code",
    "match_score": "match_score",
    "match_type": "match_type",
    # Opsiyonel: Eğer varsa okunacak diğer sütunlar buraya eklenebilir
    "city": "city_state",
    "address": "address",
}

# Kodun çalışması için ZORUNLU olan sütunlar (Internal Names)
# BURAYA COLUMN_MAPPING SÖZLÜĞÜNÜN **ANAHTARLARINI** (SOL TARAF) YAZMALISINIZ.
# Örnek: COLUMN_MAPPING = {"company_name": "firma_adi"} -> Buraya "company_name" yazılır.
MANDATORY_READ_COLUMNS = ["id", "company_name", "country_code"]
MANDATORY_UPDATE_COLUMNS = ["master_code", "match_score", "match_type"]

# Güncellenecek sütunlar (MANDATORY_UPDATE_COLUMNS) tabloda yoksa otomatik oluşturulsun mu?
AUTO_CREATE_UPDATE_COLUMNS = True

# --- Elasticsearch Bağlantı ---
ES_HOST = "http://localhost:9200"
ES_INDEX = "living_companies_v1"

# --- Eşleştirme Ayarları ---

# Batch büyüklüğü (PostgreSQL cursor)
BATCH_SIZE = 5000

# --- ES Skor Eşikleri ---
ES_MIN_SCORE = 3.0  # ES'te min_score filtresi (bu altı hiç dönmez)
# Not: 4.0'dan 3.0'a düşürüldü — fuzzy match'ler daha düşük skor üretebilir,
# post-ES verification zaten kesin eşleşme kontrolü yapıyor.

# --- ES function_score Ağırlıkları ---
# Path 0 (tax deterministic) için SCORE_WEIGHTS artık kullanılmıyor.
# Aşağıdaki değerler ES function_score'daki weight'lere karşılık gelir.
# _score = name_BM25 + (ES_TAX_WEIGHT if tax_match) + (ES_PHONE_WEIGHT if phone_match)
ES_TAX_WEIGHT = 100  # Tax eşleşirse _score'a eklenir → adayı öne taşır
ES_PHONE_WEIGHT = 20  # Phone eşleşirse _score'a eklenir

# --- Eşik Değerleri ve Sabitler ---
LENGTH_RATIO_THRESHOLD = 0.4
TOKEN_COVERAGE_THRESHOLD = 0.8  # Token'ların en az %80'i örtüşmeli

SUFFIX_TYPO_MAP = {
    "limted": "limited",
    "limted.": "limited",
    "ltdl": "ltd",
    "ltda": "ltd",
    "incp": "inc",
    "incc": "inc",
    "gmhb": "gmbh",
    "corp.": "corp",
}
