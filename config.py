"""Firma eşleştirme sistemi yapılandırması.

Eşik değerleri, DB/ES bağlantıları, MatchType etiketleri ve aktif STAGES listesi.
Eşiklerin ardındaki ayrıntılı gerekçe/karar geçmişi için `docs/audit/` raporlarına
bakılır; buradaki yorumlar yalnızca ayarın ne işe yaradığını ve kısa nedenini verir.
"""


class MatchType:
    """Eşleştirme sonucu tip etiketleri (PG `match_type` sütununa yazılır)."""

    CANONICAL_EXACT = "CANONICAL_EXACT"
    STRIPPED_EXACT = "STRIPPED_EXACT"
    SUFFIX_FUZZY = "SUFFIX_FUZZY"
    FUZZY_PHRASE = "FUZZY_PHRASE"
    TOKEN_COVERAGE = "TOKEN_COVERAGE"
    PHONETIC_MATCH = "PHONETIC_MATCH"
    NGRAM_MATCH = "NGRAM_MATCH"
    NEW_MASTER = "NEW_MASTER"
    # Fingerprint auto-merge ile bir primary'e birleştirilen ikincil NEW_MASTER
    # anchor'ı bu tipe demote edilir → aynı master_code'da >1 NEW_MASTER kalmaz
    # (watch-query kör noktası). Bkz. docs/audit/2026-06-15-*.
    AUTO_DEDUP = "AUTO_DEDUP"
    # Firma-olmayan girdi (placeholder, salt-kod, n/a): eşleştirmeye sokulmadan
    # izole edilir, ES'e indekslenmez (magnet olamaz). Bkz. input_filter.py.
    EXCLUDED = "EXCLUDED"


# --- PostgreSQL bağlantısı ---
DB_CONFIG = {
    "dbname": "market_calculus",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
}

# --- Tablo ve sütun ayarları ---
RAW_TABLE_NAME = "p7_firms_v2_ar_pe"

# Yalnızca tek ülke işlenecekse kodu (örn. "mx"); None = tüm ülkeler.
COUNTRY_CODE_FILTER = None

# Dahili değişken adı → veritabanı sütun adı eşlemesi.
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

# Eksik update sütunları otomatik oluşturulsun mu (ALTER TABLE).
AUTO_CREATE_UPDATE_COLUMNS = True

# --- Elasticsearch bağlantısı ---
ES_HOST = "http://localhost:9200"
ES_INDEX = "living_companies_v1"

# --- Eşleştirme akışı ---
# PG'den tek seferde okunan kayıt sayısı.
BATCH_SIZE = 5000

# NEW_MASTER alt-grup boyutu: her N kayıt ES'e indekslenip refresh edilir
# (within-batch duplicate penceresini daraltır).
NEW_MASTER_SUBBATCH_SIZE = 200

# Her N kayıtta bir ES refresh (tüm stage'ler).
ES_REFRESH_INTERVAL = 50

# msearch chunk boyutu: kayıtlar bu boyutta gruplanıp tek index anlık-görüntüsüne
# karşı toplu sorgulanır, chunk sonunda refresh edilir. chunk = refresh penceresi
# olduğundan görünürlük tekil-akışla aynıdır → sonuç değişmez, round-trip azalır.
# 1 = eski kayıt-başına davranış. Büyütmek refresh'i seyrekleştirir (fuzzy varyant
# recall'ını etkileyebilir → ölçerek artır).
MATCH_BATCH_SIZE = 50

# --- ES skor / log ---
ES_MIN_SCORE = 3.0       # ES min_score filtresi (bu altı hiç dönmez)
LOG_ALL_STAGES = False   # Her stage sonucunu (başarısız dahil) logla

# --- Eşik değerleri ---
LENGTH_RATIO_THRESHOLD = 0.4
TOKEN_COVERAGE_THRESHOLD = 0.95  # Token'ların en az %95'i örtüşmeli

SUFFIX_FUZZY_MIN_SCORE = 1.5            # ES skor eşiği (prod testleriyle kalibre)
SUFFIX_FUZZY_SCORE = 85                 # Sonuç skoru (normalize tier)
SUFFIX_FUZZY_COVERAGE_THRESHOLD = 0.85  # İsim token coverage eşiği

RESCORE_WINDOW_SIZE = 20  # Rescore yalnızca top-N adaya uygulanır

# PHONETIC/NGRAM guard'ları: sorgu kaydının ayırt edici çekirdek token sayısı bu
# eşiğin altındaysa (yalnızca suffix/ülke-adı/çöp → 0 token) stage bloklanır.
# Gerçek tek-marka firmalar (IGSA, AUDI MEXICO) elenmez. Bkz. docs/audit/2026-06-02
# + analysis/live_probe.py. (Her iki stage şu an STAGES'te kapalı.)
PHONETIC_MIN_CORE_TOKENS = 1
NGRAM_MIN_CORE_TOKENS = 1

# --- Girdi filtresi ---
# Yalnızca içerik taşımayan / "isim yok" girdileri eler (boş, salt-noktalama,
# n/a/null, placeholder). KİMLİK kararı DEĞİL, boundary geçerlilik kontrolüdür:
# salt-kod/sayı veya uzun bir isim gerçek bir yeni firma olabilir → elenmez.
# Bkz. docs/audit/2026-06-03-llm-judge-rematch-comparison.md §4.
ENABLE_INPUT_FILTER = True

# --- Batch-içi otomatik dedup ---
# Batch'te oluşan NEW_MASTER'lar arasında aynı kanonik fingerprint'e sahip
# olanları ES-tarafı birleştirir (dedup_auto_merge); ayrı script gerektirmez.
AUTO_DEDUP_PER_BATCH = True

# Dedup sıklığı: her N batch'te bir koşar (aradaki NEW_MASTER'lar biriktirilir,
# güvenlik-cap'te erken + sonda flush edilir). Yüksek N → fingerprint aggregation
# (fielddata, donma kaynağı) daha seyrek koşar. 1 = her batch.
# Tam-rematch için en pürüzsüz seçenek: AUTO_DEDUP_PER_BATCH=False + sonradan
# `python -m dedup.auto_merge --apply` (global, terms-sınırı yok).
AUTO_DEDUP_EVERY_N_BATCHES = 10

# Dedup fingerprint dejenere-guard: fingerprint'in dedup anahtarı olabilmesi için
# en az bir token bu uzunlukta olmalı; aksi halde dejenere sayılır (magnet önlenir).
# 2 = akronim-çökmesi magnet'lerini ('C.M.S.A.D.C'→'m') engeller, 2-harfli gerçek
# markaları (VF/3M) korur. Bkz. docs/audit/2026-06-03-round2-preliminary-2.9pct.md.
DEDUP_MIN_FINGERPRINT_TOKEN_LEN = 2

# NOT: Sabit "max-cluster-size" tavanı denendi ve geri alındı — boyut tek başına hata
# değil (aynı firmanın milyonlarca kaydı birleşmeli); tavan meşru dev kümeleri böler
# (under-merge). Büyük küme yalnızca izleme/insan-denetimi sinyalidir, hard-gate yok.

# Firma-olmayan placeholder'lar ("ticari unvan yok", "alıcı=gönderici") data-driven:
# synonyms_data/{common,<cc>}.json "non_firm_placeholders" kategorisinde tutulur;
# synonym_loader.get_non_firm_placeholders(cc) okur, input_filter TAM eşleşmeyle
# EXCLUDED yapar. (CLAUDE.md §1.4 SABİT-JSON istisnası: bu kategoriye ekleme açıktır.)

# --- Ayırt-edici çekirdek GATE ---
# Eşleşme stage'leri, sorgu kaydının ayırt edici bir çekirdek taşımasını şart koşar:
# stripped analyzer (yasal-ek + geo temizli) çıktısında en az bir token uzunluğu
# >= MATCH_CORE_MIN_TOKEN_LEN. Karar %100 ES analyzer çıktısından gelir (Python fuzzy
# yok); stage'in çalışıp çalışmayacağını belirleyen bir GUARD'dır, doğrulama değil.
# Çekirdeksiz girdiler ('M S.A.'→'m', '#N/A 300') loose stage'lerde eşleşmez → NEW_MASTER.
ENABLE_CORE_GATE = True
MATCH_CORE_MIN_TOKEN_LEN = 2          # ayırt edici min token uzunluğu (VF/3M korunur)
MATCH_CORE_FUZZY_REQUIRE_ALPHA = True  # loose stage'lerde çekirdek alfabetik olmalı
                                       # (salt-sayı loose eşleşmede güvenilmez; STRIPPED_EXACT hariç)

# --- Ayırt-edici-çekirdek COVERAGE gate ---
# FUZZY_PHRASE / TOKEN_COVERAGE'da eşleşen master'ın STRIPPED çekirdek token sayısı,
# sorgunun çekirdek sayısına EŞİT olmalı (ES-side term filtresi). Böylece kısa/kesik
# isim (SPM ⊂ SPM FLOW CONTROL) farklı sayı taşıdığından master'a giremez →
# subset/truncation over-merge ES tarafında elenir. Yan-etki: gerçekten-kesik-ama-aynı
# firma NEW_MASTER olabilir (recall maliyeti). Bkz. docs/audit/2026-06-10-round4-*.
ENABLE_CORE_COVERAGE_GATE = True

# --- msearch ---
MSEARCH_CHUNK_SIZE = 500  # tek msearch çağrısındaki max sorgu sayısı

# --- Stage konfigürasyonu ---
# Stage eklemek:  listeye dict ekle + es_queries.py'e aynı isimde fonksiyon yaz.
# Çıkarmak:       "enabled": False yap. Sıralamak: "order" / liste sırasını değiştir.
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
        # KAPALI: en düşük precision (Round-7 %68; diğerleri %92+); kazanımları asıl
        # suffix-typo işi değil subset/truncation over-merge'üydü (STRIPPED_EXACT +
        # FUZZY_PHRASE bunları zaten karşılıyor). Açmadan önce _core_coverage_filter
        # eklenmeli. Bkz. docs/audit/2026-06-15-round7-rescan-comparison.md.
        "name": "SUFFIX_FUZZY",
        "order": 3,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": SUFFIX_FUZZY_MIN_SCORE,
        "enabled": False,
        "index_variation": False,
    },
    {
        # min_score 9.0 denendi/geri alındı (recall 8/10→4/10); over-merge çekirdek-
        # coverage gate (ENABLE_CORE_COVERAGE_GATE) ile çözüldüğünden 5.0'da bırakıldı.
        "name": "FUZZY_PHRASE",
        "order": 4,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        # min_score 11.0 denendi/geri alındı (aynı recall kaybı); subset over-merge
        # çekirdek-coverage gate ile recall-nötr çözüldü → 3.0'da bırakıldı.
        "name": "TOKEN_COVERAGE",
        "order": 5,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        # KAPALI: over-merge'in birincil kaynağıydı (master-seviyesi %95.9 yanlış).
        # Kök neden: double_metaphone max_code_len=4 → tek-token marka ön-ekleri
        # çakışıyor (INTERAGUA/INTERFIG → "ANTR"). Açmak için phonetic_filter'a
        # max_code_len:8-10 + reindex. Bkz. docs/audit/2026-06-03-llm-judge-rematch-*.
        "name": "PHONETIC_MATCH",
        "order": 6,
        "query_fn": "PHONETIC_MATCH",
        "min_score": 3.0,
        "enabled": False,
        "index_variation": False,
    },
    {
        # KAPALI: PHONETIC ile aynı hastalık (master-seviyesi %98.1 over-merge);
        # paylaşılan trigram'lar farklı markaları birleştiriyor. Açmak için min_score
        # 18-20 + çekirdek-token coverage + reindex. Bkz. aynı audit.
        "name": "NGRAM_MATCH",
        "order": 7,
        "query_fn": "NGRAM_MATCH",
        "min_score": 10.0,
        "enabled": False,
        "index_variation": False,
    },
]
