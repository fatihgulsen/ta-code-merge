# ============================================================================
# config.py - Firma Eşleştirme Sistemi Ayarları
# ============================================================================


# --- Match Type Sabitleri ---
class MatchType:
    """Eşleştirme sonucu tip etiketleri."""

    CANONICAL_EXACT = "CANONICAL_EXACT"
    STRIPPED_EXACT = "STRIPPED_EXACT"
    SUFFIX_FUZZY = "SUFFIX_FUZZY"
    FUZZY_PHRASE = "FUZZY_PHRASE"
    TOKEN_COVERAGE = "TOKEN_COVERAGE"
    PHONETIC_MATCH = "PHONETIC_MATCH"
    NGRAM_MATCH = "NGRAM_MATCH"
    NEW_MASTER = "NEW_MASTER"


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

# COUNTRY_CODE_FILTER = "mx"
COUNTRY_CODE_FILTER = None

# Dahili degisken isimleri -> Veritabani sutun isimleri
COLUMN_MAPPING = {
    "id": "id",
    "company_name": "name",
    "country_code": "country_code",
    "phone_number": "tel",
    "master_code": "master_code",
    "match_score": "match_score",
    "match_type": "match_type",
    "match_details": "match_details",
    "city": "city_state",
    "address": "address",
}


MANDATORY_READ_COLUMNS = ["id", "company_name", "country_code"]
MANDATORY_UPDATE_COLUMNS = ["master_code", "match_score", "match_type", "match_details"]

AUTO_CREATE_UPDATE_COLUMNS = True

# --- Elasticsearch Bağlantı ---
ES_HOST = "http://localhost:9200"
ES_INDEX = "living_companies_v1"

# --- Eşleştirme Ayarları ---

BATCH_SIZE = 5000

# NEW_MASTER sub-batch boyutu — within-batch duplicate minimizasyonu icin
# Her N kayitlik alt grup ES'e index'lenir, ardindan refresh yapilir.
NEW_MASTER_SUBBATCH_SIZE = 200

# ES refresh araligi — her N kayitta bir refresh yapilir (tum stage'ler)
ES_REFRESH_INTERVAL = 50

# --- ES Skor Eşikleri ---
ES_MIN_SCORE = 3.0  # ES'te min_score filtresi (bu altı hiç dönmez)
LOG_ALL_STAGES = False  # Her bir stage sonucunu (failed dahil) logla


# --- Eşik Değerleri ve Sabitler ---
LENGTH_RATIO_THRESHOLD = 0.4
TOKEN_COVERAGE_THRESHOLD = 0.95  # Token'ların en az %95'i örtüşmeli

# --- Çekirdek-token coverage post-verify (Faz 2) ---
# Kazanan eşleşme kabul edilmeden ÖNCE, sorgu ile kazananın çekirdek (core_name)
# token kümeleri arasındaki simetrik örtüşme bu eşiğin ALTINDAYSA eşleşme reddedilir.
# Stage-bağımsız bir güvenlik kapısıdır; subset over-merge'leri (ALCATEL ⊂
# ALCATEL-LUCENT) ve ayırt edici-çekirdek uyuşmazlıklarını yakalar. 0 → devre dışı.
# Canlı kalibrasyon: analysis/live_probe.py.
CORE_COVERAGE_THRESHOLD = 0.6

SUFFIX_FUZZY_MIN_SCORE = 1.5  # ES score eşiği — prod testleriyle kalibre edilmeli
SUFFIX_FUZZY_SCORE = 85  # match sonucu skoru (normalised tier score)
SUFFIX_FUZZY_COVERAGE_THRESHOLD = 0.85  # name token coverage eşiği (_post_verify)

# --- ES Rescore Score Tier Sabitleri ---
# interpret_match_result() _score değerinden match_type belirler
# Bu değerler es_scripts.py'deki Painless script ile uyumlu olmalı
RESCORE_WINDOW_SIZE = 20  # Rescore sadece top N adaya uygulanır

# PHONETIC_MATCH guard — yalnızca AYIRT EDİCİ çekirdek token sayısı bu eşiğin
# ALTINDA ise fonetik eşleşme bloklanır. drop_geo ile ülke-adı/coğrafi token'lar
# çekirdek dışıdır; böylece yalnızca-suffix / yalnızca-ülke-adı / çöp isimler
# (0 ayırt edici token) bloklanır. Gerçek tek-marka firmalar (IGSA, VIBRACOUSTIC,
# AUDI MEXICO) ELENMEZ — fonetik alandan yasal-ek parçaları temizlendiği için
# (es_manager legal_fragment_stop) farklı markalar zaten birbirine eşleşmez.
# Bkz. docs/audit/2026-06-02 + analysis/live_probe.py (canlı doğrulama).
PHONETIC_MIN_CORE_TOKENS = 1

# NGRAM_MATCH guard — PHONETIC ile aynı mantık: yalnızca AYIRT EDİCİ çekirdek
# token sayısı bu eşiğin ALTINDAysa (boş çekirdek: yalnızca suffix/ülke-adı/çöp)
# trigram eşleşmesi paylaşılan suffix parçalarından farklı firmaları birleştirir
# → bloklanır. Asıl precision coverage post-verify'dadır; bu guard çöp sızıntısı içindir.
NGRAM_MIN_CORE_TOKENS = 1

# --- msearch Ayarları ---
MSEARCH_CHUNK_SIZE = 500  # Tek msearch çağrısında max sorgu sayısı


# --- Stage Konfigürasyonu ---
# Stage eklemek:   Listeye yeni dict ekle + es_queries.py'e aynı isimde fonksiyon yaz
# Stage çıkarmak:  "enabled": False yap veya listeden sil
# Sıralamak:       "order" değerini veya listenin sırasını değiştir

STAGES = [
    {
        "name": "CANONICAL_EXACT",
        "order": 1,
        "query_fn": "CANONICAL_EXACT",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": True,
    },
    {
        "name": "STRIPPED_EXACT",
        "order": 2,
        "query_fn": "STRIPPED_EXACT",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": True,
    },
    {
        "name": "SUFFIX_FUZZY",
        "order": 3,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": SUFFIX_FUZZY_MIN_SCORE,
        "enabled": True,
        "index_variation": False,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 4,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 5,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        "name": "PHONETIC_MATCH",
        "order": 6,
        "query_fn": "PHONETIC_MATCH",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        "name": "NGRAM_MATCH",
        "order": 7,
        "query_fn": "NGRAM_MATCH",
        "min_score": 10.0,
        "enabled": True,
        "index_variation": False,
    },
]
