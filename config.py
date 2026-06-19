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
    # Firma-OLMAYAN kirli isim: address synonym'i baskın + ayırt edici çekirdek yok.
    # ES'e indekslenir (sonraki kayıtlar eşleşebilsin) ama PG'de kirli işaretli; zayıf
    # çekirdek nedeniyle distinctive-core gate onu magnet olmaktan korur. Bkz. Plan 3.
    DIRTY_DATA = "DIRTY_DATA"
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
RAW_TABLE_NAME = "p7_firms_v2"

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

# --- Elasticsearch index isimlendirme (per-country) ---
INDEX_PREFIX = "living_companies"
INDEX_VERSION = "v3"


def index_for_country(country_code: str) -> str:
    """Ülkenin FİZİKSEL ES index adı (oluşturma/silme için)."""
    return f"{INDEX_PREFIX}_{country_code.lower()}_{INDEX_VERSION}"


def alias_for_country(country_code: str) -> str:
    """Ülkenin alias adı (sorgu/yazım bunu kullanır; alias-swap ile reindex)."""
    return f"{INDEX_PREFIX}_{country_code.lower()}"


# _analyze hedef override'ı — yalnızca analysis/live_probe.py diagnostiği içindir.
# None ise normal alias_for_country(country) kullanılır.
ES_ANALYZE_INDEX_OVERRIDE = None

# --- Eşleştirme akışı ---
# PG'den tek seferde okunan kayıt sayısı.
BATCH_SIZE = 5000

# NEW_MASTER alt-grup boyutu: her N kayıt ES'e indekslenip refresh edilir
# (within-batch duplicate penceresini daraltır).
NEW_MASTER_SUBBATCH_SIZE = 200

# msearch chunk boyutu: kayıtlar bu boyutta gruplanıp tek index anlık-görüntüsüne
# karşı toplu sorgulanır, chunk sonunda refresh edilir. chunk = refresh penceresi
# olduğundan görünürlük tekil-akışla aynıdır → sonuç değişmez, round-trip azalır.
# 1 = eski kayıt-başına davranış. Büyütmek refresh'i seyrekleştirir (fuzzy varyant
# recall'ını etkileyebilir → ölçerek artır).
MATCH_BATCH_SIZE = 50

# --- ES skor / log ---
LOG_ALL_STAGES = False  # Her stage sonucunu (başarısız dahil) logla

# --- Eşik değerleri ---
SUFFIX_FUZZY_SCORE = 85  # Sonuç skoru (normalize tier)

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

# --- Kirli veri (DIRTY_DATA) işaretleme ---
# Eşleşmeyen kayıt, isminde address synonym'i içeriyor VE address çıkarılınca ayırt edici
# çekirdek kalmıyorsa NEW_MASTER yerine DIRTY_DATA işaretlenir (indekslenir ama PG'de işaretli).
# Karar ES _analyze tokenizasyonu + Python set-membership ile (fuzzy değil). Bkz. es/queries.is_address_dirty.
ENABLE_DIRTY_DATA = True

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
MATCH_CORE_MIN_TOKEN_LEN = 2  # ayırt edici min token uzunluğu (VF/3M korunur)

# --- Jenerik-çekirdek gate (generic-word magnet fix) ---
# Stripped çekirdek YALNIZCA jenerik iş/sektör kelimelerinden ibaretse ('trading',
# 'importaciones', 'inversiones', 'group'...) ayırt edici DEĞİLDİR → tüm merge stage'leri
# bloklanır → NEW_MASTER. Jenerik küme business_sectors JSON'undan türetilir (hardcode yok,
# ülke-bilinçli). Kök neden: tek-harf baş harfler + ekler sıyrılınca alakasız firmalar
# ('L M TRADING', 'B&B TRADING') aynı tek jenerik token'a ('trading') çöküp STRIPPED_EXACT'te
# birleşiyordu. Çok-token çekirdeklerde ≥1 jenerik-OLMAYAN token varsa korunur ('Apex Pharma').
ENABLE_GENERIC_CORE_GATE = True
MATCH_CORE_FUZZY_REQUIRE_ALPHA = True  # loose stage'lerde çekirdek alfabetik olmalı
# (salt-sayı loose eşleşmede güvenilmez; STRIPPED_EXACT hariç)

# --- Ayırt-edici-çekirdek COVERAGE gate ---
# FUZZY_PHRASE / TOKEN_COVERAGE'da eşleşen master'ın STRIPPED çekirdek token sayısı,
# sorgunun çekirdek sayısına EŞİT olmalı (ES-side term filtresi). Böylece kısa/kesik
# isim (SPM ⊂ SPM FLOW CONTROL) farklı sayı taşıdığından master'a giremez →
# subset/truncation over-merge ES tarafında elenir. Yan-etki: gerçekten-kesik-ama-aynı
# firma NEW_MASTER olabilir (recall maliyeti). Bkz. docs/audit/2026-06-10-round4-*.
ENABLE_CORE_COVERAGE_GATE = True

# --- Synonym-içi fonetik typo-rescue (core/synonym_phonetic) ---
# Write-time'da ham synonym typo'larını (socidad→sl gibi) kanoniğe çevirir; markaya
# DOKUNMAZ (tam metaphone-kod eşitliği + uzunluk guard'ları). 2026-06-18 empirik denetim:
# gevşek eşleşme markayı bozuyordu (rafael→retail), tam-kod'a sıkılaştırıldı (%15→%1, 0 marka
# sızıntısı). False yapılırsa canonicalize_phonetic kimliği döner (rescue kapalı).
ENABLE_SYNONYM_PHONETIC = True

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
        # min_score 9.0 denendi/geri alındı (recall 8/10→4/10); over-merge çekirdek-
        # coverage gate (ENABLE_CORE_COVERAGE_GATE) ile çözüldüğünden 5.0'da bırakıldı.
        "name": "FUZZY_PHRASE",
        "order": 2,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        # min_score 11.0 denendi/geri alındı (aynı recall kaybı); subset over-merge
        # çekirdek-coverage gate ile recall-nötr çözüldü → 3.0'da bırakıldı.
        "name": "TOKEN_COVERAGE",
        "order": 3,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,
    },
]
