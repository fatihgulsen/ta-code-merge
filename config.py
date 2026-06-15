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
    # A3 (2026-06-15): fingerprint auto-merge (dedup_auto_merge) ile bir primary'e
    # birleştirilen İKİNCİL NEW_MASTER anchor'ları bu tipe demote edilir. Böylece aynı
    # master_code'da >1 NEW_MASTER kalmaz → over-merge watch query (match_type!=NEW_MASTER
    # join) kör noktası kapanır. Variant'lar (zaten bir stage ile eşleşmiş) tipini korur.
    AUTO_DEDUP = "AUTO_DEDUP"
    # Boundary girdi-geçerliliği filtresi (P0-B / Faz 4): firma-olmayan girdiler
    # (placeholder, salt-kod/sayı, baş-harf, aşırı uzun gümrük dizesi) eşleştirmeye
    # SOKULMADAN izole edilir → ES'e indekslenmez (magnet olamaz). Bkz. input_filter.py.
    EXCLUDED = "EXCLUDED"


# --- PostgreSQL Bağlantı ---
DB_CONFIG = {
    "dbname": "market_calculus",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
}

# --- Tablo ve Sütun Ayarları ---
RAW_TABLE_NAME = "p7_firms_v2_ar_pe"

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

# Eşleştirme chunk boyutu (Q1 — toplu msearch): kayıtlar bu boyutta gruplanıp TEK index
# anlık-görüntüsüne karşı toplu msearch ile eşleştirilir; chunk sonunda refresh yapılır.
# chunk = refresh penceresi olduğundan görünürlük tekil-akışla AYNI (refresh=False yazımlar
# pencere içinde zaten görünmez) → eşleşme sonucu DEĞİŞMEZ, yalnız round-trip azalır.
# 1 yaparsan eski kayıt-başına davranışa döner. Büyütürsen refresh seyrekleşir (Q3: kanonik
# dup'ları batch-içi dedup toplar, ama fuzzy varyant recall'ı düşebilir → ölçerek artır).
MATCH_BATCH_SIZE = 50

# --- ES Skor Eşikleri ---
ES_MIN_SCORE = 3.0  # ES'te min_score filtresi (bu altı hiç dönmez)
LOG_ALL_STAGES = False  # Her bir stage sonucunu (failed dahil) logla


# --- Eşik Değerleri ve Sabitler ---
LENGTH_RATIO_THRESHOLD = 0.4
TOKEN_COVERAGE_THRESHOLD = 0.95  # Token'ların en az %95'i örtüşmeli

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

# --- Girdi Filtresi (P0-B / Faz 4) — YALNIZCA tamamen anlamsız girdileri ele ---
# docs/audit/2026-06-03-llm-judge-rematch-comparison.md §4: 'Sin Razon Social' (1.181
# üyeli magnet) gibi 'isim yok' placeholder'ları + '#N/A'/null işaretçileri NEW_MASTER
# seed'i olup mıknatıs görevi görüyor.
#
# FELSEFE: Bir firmanın "doğru" olup olmadığına karar VEREMEYİZ — salt kod/sayı/baş-harf
# veya çok uzun bir isim gerçek bir (yeni) firma OLABİLİR ve NEW_MASTER olmalı. Bu yüzden
# yalnızca içerik-taşımayan / 'isim yok' girdiler elenir (boş, salt-noktalama, n/a/null,
# placeholder). Bu bir KİMLİK kararı DEĞİL; boundary geçerlilik kontrolü.
ENABLE_INPUT_FILTER = True

# --- Batch-içi otomatik dedup (P0-C, sistem-içi) ---
# Her batch sonunda, o batch'te oluşturulan NEW_MASTER'lar arasında AYNI kanonik
# fingerprint'e sahip olanları ES-tarafı birleştirir (dedup_auto_merge). Ayrı script
# çalıştırma zorunluluğunu kaldırır; iş yükü batch'e ölçeklenir (tüm index taranmaz).
# Refresh-lag penceresinde oluşan within-batch duplikasyonu sistemin kendi içinde kapanır.
AUTO_DEDUP_PER_BATCH = True

# Dedup fingerprint dejenere-guard eşiği (P-R2-1). Bir fingerprint'in dedup ANAHTARI
# olabilmesi için EN AZ BİR token'ı bu uzunlukta (karakter) olmalı; aksi halde dejenere
# sayılıp birleştirilmez (magnet önlenir).
#   1 = guard pratikte KAPALI — yalnız boş fingerprint engellenir (mevcut davranış).
#   2 = akronim-çökmesi magnet'lerini (C.M.S.A.D.C / U M S.A. DE C.V. → 'm') engeller,
#       gerçek 2-harfli markaları (VF/3M/HM/GM → vf/3m/hm/gm) korur.
# NOT (docs/audit/2026-06-03-round2-preliminary-2.9pct.md §P-R2-1, ampirik eşik testi):
# ≥2 bile YETERLİ DEĞİL — kısa-residue false-merge'ler ('av' = HUF+P.AV.I, 'adm') geçer;
# asıl kök neden analyzer aşırı-strip'i (tek-harf token atma + HUF yutma) → gerçek çözüm
# analyzer-side + reindex (rematch sonrası).
# KARAR (docs/audit/2026-06-05-round3-unicode-config-dedup.md §ADIM 4, %31 rematch + kanıt):
# 2'ye çekildi. Simülasyon: 21 tek-harf dejenere dedup grubu (fp 'm'/'t'/'g'…) kapanır,
# 0 GERÇEK MARKA kaybı (3m/gm/dr/mt len≥2 korunur). Bedava/baskın hijyen. UYARI: magnetlerin
# %91'i STRIPPED_EXACT eşleşme-zamanından geliyor → bu eşik onları materyal küçültmez;
# asıl çözüm analyzer-side akronim-glue (Öneri-1) + reindex.
DEDUP_MIN_FINGERPRINT_TOKEN_LEN = 2

# NOT (A4 kararı, 2026-06-15): Sabit "max-cluster-size" tavanı (örn. 100 variation)
# DENENDİ ve GERİ ALINDI. Gerekçe (kullanıcı): boyut tek başına hata değildir — 2M kayıt
# gerçekten aynı firmaysa hepsi birleşmeli; sabit tavan meşru dev kümeleri (büyük
# ithalatçı, milyonlarca gümrük kaydı) zorla böler → ciddi UNDER-MERGE. Asıl sorun
# boyut değil ZAYIF KENAR (geo/jenerik token üzerinden birleşme) → A1 (geo-stop) + A2
# (token-dedup) + _core_coverage_filter bunu kök seviyede çözer. Büyük küme bir
# İZLEME sinyalidir (engellenmez): C6 monitör SQL'i + dedup_reviewer (C3) ile insan
# denetimine işaretlenir, eşleştirme yolunda hard-gate YOKTUR.

# Firma-OLMAYAN placeholder'lar ("ticari unvan yok" / "alıcı=gönderici") artık DATA-DRIVEN:
# synonyms_data/{common,<cc>}.json içindeki "non_firm_placeholders" kategorisinde tanımlıdır.
#   - __common__ karşılığı  → common.json (gümrük "same as ..." işaretçileri, tüm ülkelere)
#   - ülkeye-özgü (MX vb.)  → <cc>.json   (örn. "sin razon social")
# synonym_loader.get_non_firm_placeholders(cc) okur; input_filter EXCLUDED yapar (ES'e
# indekslenmez). TAM eşleşme; gerçek firma adı bu biçimde normalize olmaz.
# CLAUDE.md §1.4 İSTİSNASI: synonyms_data SABİT kuralı bu kategori için gevşetilmiştir
# (kullanıcı kararı) — placeholder'ları hardcode etmemek için JSON'a eklenebilir.
# (n/a, null, none, nan, s/n gibi yapısal işaretçiler input_filter._NA_MARKERS'ta.)


# --- Ayırt-edici çekirdek GATE (Round-3 #3, docs/audit/2026-06-05-DURUM-RAPORU...) ---
# Eşleşme stage'leri, sorgu kaydının AYIRT EDİCİ bir çekirdek taşımasını şart koşar.
# "Ayırt edici çekirdek" = stripped analyzer (yasal-ek + geo temizli) çıktısında EN AZ bir
# token >= MATCH_CORE_MIN_TOKEN_LEN. Karar %100 ES analyzer çıktısından (Python fuzzy/normalize
# YOK); bu bir GUARD'dır (stage çalışsın mı), eşleşme DOĞRULAMASI değil — PHONETIC/NGRAM
# guard'larıyla aynı desen. Çekirdeği olmayan girdiler (tek-harf akronim artığı 'M S.A.'→'m',
# '#N/A 300', salt-kod/sayı) loose stage'lerde EŞLEŞMEZ → NEW_MASTER (güvenli; magnet olmaz).
# Hata sınıfları B (#N/A sızma) + A-artığı (boşluk-ayrılmış tek-harf) bununla kapanır.
ENABLE_CORE_GATE = True
MATCH_CORE_MIN_TOKEN_LEN = 2  # ayırt edici sayılmak için min token uzunluğu (2-harf marka VF/3M korunur)
# Loose stage'lerde (TOKEN_COVERAGE / FUZZY_PHRASE / SUFFIX_FUZZY) ek olarak çekirdek token
# ALFABETİK olmalı (salt-sayı '300'/'414' loose eşleşmede güvenilmez → NEW_MASTER). STRIPPED_EXACT
# (tam eşleşme, güvenli) sayıyı ayırt edici sayar → salt-numerik exact-dedup korunur.
MATCH_CORE_FUZZY_REQUIRE_ALPHA = True

# --- Ayırt-edici-çekirdek COVERAGE gate (Round-4 #A, docs/audit/2026-06-10-round4-*) ---
# FUZZY_PHRASE / TOKEN_COVERAGE loose stage'lerinde, eşleşen master'ın STRIPPED ayırt-edici
# çekirdek token SAYISI, sorgu kaydının çekirdek token sayısına EŞİT olmalı (ES-side term
# filtresi; Python doğrulaması YOK). Böylece kısa/kesik isim (SPM ⊂ SPM FLOW CONTROL,
# WORLDWIDE LOGISTICS ⊂ MENLO WORLDWIDE LOGISTICS) farklı core-count taşıdığı için master'a
# GİREMEZ → subset/truncation-shell over-merge (D1/D2/D3) ES tarafında elenir.
# STRIPPED analyzer kullanılır (synonym YOK) — Round-3'te clean_analyzer token_count eşitliği
# synonym_graph genişlemesi yüzünden recall'ı 8/10→4/10 kırıp GERİ ALINMIŞTI; STRIPPED tutarlı.
# Yan-etki: gerçekten-kesik-ama-aynı firma (ör. 'INTER MEX MATERIALES DE') NEW_MASTER olur
# (recall maliyeti, dedup_reviewer'a kalır). Flag ile kapatılabilir; reindex GEREKMEZ
# (variations_stripped.name.token_count alanı zaten STRIPPED_EXACT tarafından kullanılıyor).
ENABLE_CORE_COVERAGE_GATE = True

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
        # DEVRE DIŞI (2026-06-15, docs/audit/2026-06-15-round7-rescan-comparison.md):
        # SUFFIX_FUZZY precision tüm stage'lerin en düşüğü (Round-7 doğrulanmış %68.0;
        # diğer tüm stage'ler %92+). "Kazanımlarının" çoğu asıl amacı olan suffix-typo
        # toleransı DEĞİL, subset/truncation over-merge'ü (SAMSUNG ELECTRONICS CO LTD ⊂
        # SAMSUNG ... HAINAN FIBER OPTICS KOREA, BANCO MACRO ⊂ BANCO MACRO BANSUD,
        # C/O acente + slash multi-entity). Asıl suffix-typo işini yeterince yapamıyor;
        # gerçek suffix-stripped varyantlar zaten STRIPPED_EXACT, fuzzy varyantlar
        # FUZZY_PHRASE tarafından yakalanıyor. PHONETIC/NGRAM ile aynı karar deseni:
        # düşük-precision kaynağı kapatılır, recall kaybı sınırlı. Yeniden açmak için
        # önce es_queries.SUFFIX_FUZZY'ye _core_coverage_filter eklenmeli (subset over-merge'i
        # ES-side eler) + geo-stop reindex sonrası canlı doğrulama (live_probe).
        "name": "SUFFIX_FUZZY",
        "order": 3,
        "query_fn": "SUFFIX_FUZZY",
        "min_score": SUFFIX_FUZZY_MIN_SCORE,
        "enabled": False,
        "index_variation": False,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 4,
        "query_fn": "FUZZY_PHRASE",
        # Round-4 #D DENENDİ ve GERİ ALINDI: 5.0→9.0 raise live_probe recall'ı 8/10→4/10
        # düşürdü (WITTE/VIBRACOUSTIC/CEVA-typo gibi gerçek varyantlar düşük skorlu 5-11 →
        # bloklandı) — token_count'la aynı başarısızlık modu. Çekirdek-coverage gate (#A) zaten
        # over-merge'i 0'a indirdiği için D GEREKSİZ + zararlı. min_score 5.0'da bırakıldı.
        "min_score": 5.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 5,
        "query_fn": "TOKEN_COVERAGE",
        # Round-4 #D DENENDİ ve GERİ ALINDI (3.0→11.0): yukarıdaki FUZZY ile aynı recall kaybı.
        # Subset/truncation over-merge çekirdek-coverage gate (#A, ENABLE_CORE_COVERAGE_GATE)
        # ile ES-side ve recall-nötr şekilde çözülüyor. min_score 3.0'da bırakıldı.
        "min_score": 3.0,
        "enabled": True,
        "index_variation": False,
    },
    {
        # DEVRE DIŞI (2026-06-03, docs/audit/2026-06-03-llm-judge-rematch-comparison.md):
        # PHONETIC_MATCH over-merge'in birincil kaynağı (master-seviyesi %95,9 yanlış).
        # Kök neden: double_metaphone max_code_len=4 → tek-token markaların fonetik
        # ön-ekleri çakışıyor (INTERAGUA/INTERFIG/ENTRETEX → hepsi "ANTR"). guard
        # (core≥1) ve token_count coverage (1==1) tek-token markada no-op kalıyor.
        # Marjinal değer (tipo toleransı) STRIPPED_EXACT/SUFFIX_FUZZY/NGRAM ile kısmen
        # karşılanıyor. Yeniden açılması için önce phonetic_filter'a max_code_len:8-10
        # eklenip reindex + live_probe prefix-collision golden ile doğrulanmalı.
        "name": "PHONETIC_MATCH",
        "order": 6,
        "query_fn": "PHONETIC_MATCH",
        "min_score": 3.0,
        "enabled": False,
        "index_variation": False,
    },
    {
        # DEVRE DIŞI (2026-06-03, docs/audit/2026-06-03-llm-judge-rematch-comparison.md):
        # NGRAM_MATCH PHONETIC ile aynı hastalıkta — master-seviyesi %98,1 over-merge.
        # Paylaşılan trigram'lar (ör. "… PERU S.A.C.", ortak ön-ekler) farklı markaları
        # birleştiriyor; minimum_should_match:"75%" + min_score:10 kısa isimlerde gevşek.
        # Yeniden açmak için: min_score 18-20'ye çıkar + kazanan adaya çekirdek-token
        # coverage (token_count) zorunluluğu ekle, ardından reindex + live_probe ile doğrula.
        "name": "NGRAM_MATCH",
        "order": 7,
        "query_fn": "NGRAM_MATCH",
        "min_score": 10.0,
        "enabled": False,
        "index_variation": False,
    },
]
