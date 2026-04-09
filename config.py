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

    SUFFIX_FUZZY = "SUFFIX_FUZZY"
    # Suffix kısmı fuzzy eşleşme, name kısmı exact

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

# Dahili degisken isimleri -> Veritabani sutun isimleri
COLUMN_MAPPING = {
    # Okunacak Sutunlar (Read)
    "id": "ta_code",
    "company_name": "company_name",
    "country_code": "city_state",       # Gercek ulke kodu ta_code prefix'inden turetilir
    "tax_number": "company_tax_id",
    "phone_number": "tel",
    # Guncellenecek Sutunlar (Write) — AUTO_CREATE ile olusturulur
    "master_code": "master_code",
    "match_score": "match_score",
    "match_type": "match_type",
    # Opsiyonel
    "city": "city_state",
    "address": "company_address",
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

SUFFIX_FUZZY_MIN_SCORE = 1.5  # ES score eşiği — prod testleriyle kalibre edilmeli
SUFFIX_FUZZY_SCORE = 85  # match sonucu skoru

# --- ES Rescore Score Tier Sabitleri ---
# interpret_match_result() _score değerinden match_type belirler
# Bu değerler es_scripts.py'deki Painless script ile uyumlu olmalı
RESCORE_WINDOW_SIZE = 20  # Rescore sadece top N adaya uygulanır

# --- msearch Ayarları ---
MSEARCH_CHUNK_SIZE = 500  # Tek msearch çağrısında max sorgu sayısı

# --- Business Descriptors (Generic Token'dan Hariç Tutulacaklar) ---
# Bu kelimeler company_types hedeflerinde yer alsa da firma isminin
# ANLAMLI parçalarıdır. stripped_form'da kaldırılmamalı.
# Örnek: "Apple Trading" vs "Apple Manufacturing" = farklı firmalar
BUSINESS_DESCRIPTORS = frozenset({
    "enterprises",
    "group",
    "holding",
    "industrial",
    "industries",
    "internacional",
    "international",
    "manufacturing",
    "prod",
    "sanayi",
    "services",
    "solutions",
    "technologies",
    "ticaret",
    "trading",
    "comercial",
    "koncern",
})

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

# --- Stage Konfigürasyonu ---
# Stage eklemek:   Listeye yeni dict ekle + es_queries.py'e aynı isimde fonksiyon yaz
# Stage çıkarmak:  "enabled": False yap veya listeden sil
# Sıralamak:       "order" değerini veya listenin sırasını değiştir

STAGES = [
    {
        "name": "TAX_EXACT",
        "order": 1,
        "query_fn": "TAX_EXACT",
        "min_score": 1.0,
        "enabled": True,
    },
    {
        "name": "CANONICAL_EXACT",
        "order": 2,
        "query_fn": "CANONICAL_EXACT",
        "min_score": 3.0,
        "enabled": True,
    },
    {
        "name": "STRIPPED_EXACT",
        "order": 3,
        "query_fn": "STRIPPED_EXACT",
        "min_score": 3.0,
        "enabled": True,
    },
    {
        "name": "SUFFIX_FUZZY",
        "order": 4,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": SUFFIX_FUZZY_MIN_SCORE,
        "enabled": True,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 5,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 6,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
    },
    {
        "name": "NGRAM_MATCH",
        "order": 7,
        "query_fn": "NGRAM_MATCH",
        "min_score": 3.0,
        "enabled": True,
    },
]
