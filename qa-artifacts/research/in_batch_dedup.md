# Batch-içi Duplicate NEW_MASTER Sorunu — ES-Tarafı Araştırma

**Tarih:** 2026-06-15  
**Kapsam:** `main_processor.py` batch akışı, `dedup_auto_merge.py`, `config.py`, `es_transform.py`  
**Soru:** Aynı batch içinde birbirinin eşi olması gereken kayıtlar neden farklı NEW_MASTER alıyor ve bunu ES-tarafında, hardcode/Python-fuzzy olmadan nasıl düzeltiriz?

---

## 1. Mevcut Mekanizma ve Boşlukların Analizi

### 1.1 Batch Akışı (Kod Referansları)

`main_processor.py:process_all_data()` şu döngüyü çalıştırır:

```
BATCH_SIZE (5000) kayıt çek
  └─ MATCH_BATCH_SIZE (50) kayıtlık CHUNK'lara böl
       └─ Her chunk:
            1. match_records_batch() → tüm kayıtları AYNI index snapshot'ına karşı msearch
            2. apply-pass: kazanan → mevcut master'a bağla; kaybeden → _index_new_master()
               (refresh=False, pipeline ile ES'e yazar — satır 873-889)
            3. Chunk sonu → es.indices.refresh(index=ES_INDEX)  (satır 1214)
            4. pg_updates flush
  └─ Batch sonu → AUTO_DEDUP_PER_BATCH: auto_merge_duplicates(restrict_master_ids=batch_new_master_ids)
```

### 1.2 Read-After-Write Penceresi (Kök Neden)

**Sorun:** `match_records_batch()` (satır 820-853), chunk içindeki TÜM kayıtları eş-zamanlı msearch ile AYNI index snapshot'ına karşı sorgular. Bu snapshot, chunk işlenmeye başlamadan ÖNCE çekilmiş görünümdür (Lucene near-real-time semantiği: `refresh=False` yazımlar bir sonraki `refresh` çağrısına kadar görünmez).

**Somut senaryo:**
- Chunk-k içinde kayıt X ve kayıt Y, gerçekte aynı firmayı temsil ediyor (örn. "SAMSUNG ELECTRONICS" ve "SAMSUNG ELECTRONICS CO" — STRIPPED_EXACT veya FUZZY_PHRASE ile eşleşmesi gerekirdi).
- Kayıt X: msearch → hiçbir master bulunamadı → `_index_new_master()` çağrısı (satır 1173) → `refresh=False` ile ES'e yazıldı; master_id_X oluştu.
- Kayıt Y (aynı chunk): msearch sorgusu AYNI anlık-görüntüde → master_id_X henüz görünmez → Y de "eşleşme yok" → `_index_new_master()` → master_id_Y oluştu.
- Sonuç: aynı batch içinde iki farklı NEW_MASTER, aynı firmayı temsil ediyor.

**Pencere boyutu = MATCH_BATCH_SIZE kayıt (50).** Chunk içindeki kayıtlar birbirini göremez. Cross-chunk aynı-firma kayıtları ise chunk sonundaki `es.indices.refresh` (satır 1214) sayesinde genellikle birleşir.

### 1.3 Mevcut Savunma Mekanizmaları ve Boşlukları

#### Savunma 1: `create_new_masters()` içi exact dedup (satır 549-579)
`create_new_masters()` fonksiyonu (satır 528) `process_all_data()` içinden çağrılmıyor — bu fonksiyon yalnızca batch-processing modunun ESKİ (stage-bazlı `run_stage`) koduna aitti. Aktif `process_all_data()` döngüsü doğrudan `_index_new_master()` (satır 856) çağırır; bu fonksiyon herhangi bir pre-dedup yapmaz.

#### Savunma 2: AUTO_DEDUP_PER_BATCH = True (satır 1286-1300)
Batch sonunda `auto_merge_duplicates(restrict_master_ids=batch_new_master_ids)` çağrısı yapılır. Bu:
- **Yalnızca BİREBİR aynı kanonik fingerprint'leri yakalar** (`_FINGERPRINT_FIELD = "variations.name.fingerprint"` üzerinden `composite aggregation`, `dedup_auto_merge.py:116`)
- `fingerprint_analyzer` → `jenerik + yasal-ek + geo stop → sort + dedup`; token dizisi BİREBİR aynı olmak zorunda

**Boşluk A (Yazım/Typo/Suffix varyantlar):** "SAMSUNG ELECTRONICS" ve "SAMSUNG ELECTRONICS CO" farklı fingerprint üretir (`samsung electronics` vs `samsung electronics co`). FUZZY_PHRASE veya STRIPPED_EXACT ile eşleşmeleri gereken ama fingerprint'i farklı olan bu çiftler batch-sonu dedup tarafından YAKALANMAZ.

**Boşluk B (Chunk-içi pencere):** MATCH_BATCH_SIZE=50; aynı chunk'taki iki kayıt birbirini asla göremez. Batch sonu dedup bu durumu fingerprint eşitliği varsa kapatır (Boşluk A yoksa), ama FUZZY_PHRASE/STRIPPED_EXACT farkı varsa kaçar.

**Boşluk C (Dejenere fingerprint guard):** `_is_distinctive_fingerprint` (satır 40-53, `dedup_auto_merge.py`), `DEDUP_MIN_FINGERPRINT_TOKEN_LEN=2` altında kalan fingerprint'leri (akronim çökmesi) birleştirmez. Bu correct behavior ama "farklı fingerprint, aynı firma" sorununu çözmez.

#### Savunma 3: `create_new_masters()` Adım 3 arası ES eşleşmesi (satır 683-713)
Bu savunma aktif kod yolunda (`_index_new_master` çağrısı) ÇALIŞMAZ — yalnızca `create_new_masters()` (eski batch yolu) içindedir.

### 1.4 Özet Boşluk Tablosu

| Senaryo | Mevcut Mekanizma | Yakalanıyor mu? |
|---------|-----------------|-----------------|
| Chunk-içi, AYNI fingerprint | AUTO_DEDUP_PER_BATCH (batch sonu) | EVET (fingerprint eşitse) |
| Chunk-içi, FUZZY_PHRASE farkı (typo/suffix) | Hiçbiri | HAYIR |
| Chunk-içi, STRIPPED_EXACT farkı | Hiçbiri | HAYIR |
| Cross-chunk, AYNI fingerprint | refresh + stage sorguları + AUTO_DEDUP | EVET |
| Cross-chunk, FUZZY_PHRASE farkı | refresh + stage sorguları | EVET (chunk sonu refresh sayesinde) |

**Kritik bulgu:** Sorun yalnızca MATCH_BATCH_SIZE=50 boyutundaki penceredir ve yalnızca fingerprint'i farklı olan çiftleri etkiler (CANONICAL_EXACT ile birleşenler zaten eşleşir). Pratik etki: STRIPPED_EXACT veya FUZZY_PHRASE ile eşleşmesi gereken iki kayıt aynı chunk'ta gelirse ikisi de NEW_MASTER olur.

---

## 2. ES-Tarafı Çözüm Seçenekleri

### Seçenek 1: `refresh=wait_for` veya Chunk Boyutunu 1'e İndirmek

**Nasıl çalışır:** `_index_new_master()` içinde `es.index(..., refresh="wait_for")` ile her NEW_MASTER yazımının hemen görünür olmasını bekle; ya da `MATCH_BATCH_SIZE=1` yaparak chunk'ı tekil kayda indir.

**Artılar:**
- Basit, kod değişikliği minimal
- Her yeni master bir sonraki kayıt tarafından görülür

**Eksiler:**
- `refresh=wait_for`: her yazımda ES segment merge tetikler → ciddi throughput düşüşü (yoğun işlemde 5-10x yavaşlama); Elasticsearch dökümantasyonu "yalnızca test/düşük-hacim için" önerir.
- `MATCH_BATCH_SIZE=1`: msearch avantajını sıfırlar; N kayıt = N×stages msearch round-trip.
- `refresh=false` + toplu chunk, ardından refresh: mevcut davranış budur — değiştirmiyor.

**Recall/Throughput:** Recall %100 düzelir; throughput kritik düşer.  
**Hardcode-uyumu:** Evet (hardcode yok).  
**Öneri:** **ÜRETİM İÇİN UYGUN DEĞİL** (throughput maliyeti).

---

### Seçenek 2: Batch-içi Canonical-Key Ön-Gruplama (ES `_analyze` + Python string eşitliği)

**Nasıl çalışır:**
1. Her kayıt ES'e yazılmadan ÖNCE, `es.indices.analyze(analyzer="fingerprint_analyzer", text=raw_name)` çağrısıyla her kaydın kanonik fingerprint tokeni üretilir.
2. Python'da `(fingerprint_tokens_str, country_code)` → `master_id` sözlüğü tutulur.
3. Aynı fingerprint'e düşen ikinci kayıt yeni NEW_MASTER açmak yerine birincisinin master_id'sine bağlanır.

**Bu Python fuzzy MU?** HAYIR. `es.indices.analyze` ES analyzer çıktısı (deterministic, sunucu-tarafı); Python'da yapılan işlem yalnızca `str_a == str_b` (tam eşitlik karşılaştırması). Kural: "Python'da fuzzy/Levenshtein yasak"; bu strict equality, izinli.

**Artılar:**
- Mevcut AUTO_DEDUP_PER_BATCH mantığını batch-BAŞINA taşır (proaktif, reaktif değil)
- Fingerprint aynıysa HIÇBIR ikincil NEW_MASTER açılmaz → batch-sonu dedup yükü sıfıra iner
- Hardcode yok; analyzer konfigürasyonu değişince otomatik adaptasyon
- Throughput: `analyze` API'si bulk (tek çağrıda N token) → makul maliyet

**Eksiler:**
- Batch başına N×1 (veya 1 bulk `_analyze` çağrısı) ek ES round-trip
- Yalnızca fingerprint-eşit çiftleri kapatır; FUZZY_PHRASE/STRIPPED_EXACT farkı olan çiftleri (Boşluk A+B) kapatmaz

**Recall/Throughput:** Fingerprint-eşit sorunları %100 çözer; FUZZY varyant sorununu çözmez. Throughput etkisi minimal.  
**Hardcode-uyumu:** Evet.  
**Öneri:** **KISMİ ÇÖZÜM** — mevcut AUTO_DEDUP_PER_BATCH'in pro-aktif versiyonu. Uygulaması kolay, net kazanım.

---

### Seçenek 3: Chunk'ı Geçici Olarak ES'e Tam `refresh=true` ile Yazıp Self-Join Msearch

**Nasıl çalışır:**
1. Bir chunk'taki tüm kayıtları `refresh=true` ile GERÇEK index'e yaz (ya da alias üzerinden)
2. Ardından aynı kayıtları normal stage sorguları ile sorgula
3. Greedy-sıralı işle: ilk kayıt NEW_MASTER → ikinci kayıt ilkini görür

Bu aslında "chunk boyutunu 1'e indirmek + araya refresh sokmak" ile eşdeğerdir ama gruplu.

**Artılar:** Tüm stage'leri (FUZZY_PHRASE dahil) batch-içi eşleştirmeye açar.

**Eksiler:**
- Her chunk için `refresh=true` → Seçenek 1 ile aynı throughput maliyeti
- "Yazıp sor" sırası greedy bağımlı → hangi kayıt "ilk" yazılırsa master olur (deterministik değil; kayıt sırası PG'ye bağlı)

**Recall/Throughput:** Tam recall; throughput kritik düşer.  
**Öneri:** **ÜRETİM İÇİN UYGUN DEĞİL**.

---

### Seçenek 4: Deterministik Canonical-ID (Fingerprint'ten UUID v5)

**Nasıl çalışır:**
- `master_id = uuid5(NAMESPACE, f"{country}:{fingerprint_tokens_str}")` — fingerprint'ten deterministik, sıra-bağımsız UUID türet
- `_index_new_master()` yerine `es.index(..., id=canonical_id, op_type="create")` — aynı canonical_id zaten mevcutsa ES `409 Conflict` döner → `create` başarısız olur → master zaten var, varyasyon ekle

**Bu yaklaşım ne yapar:**
- İki kayıt aynı fingerprint'i paylaşıyorsa ikisi de aynı canonical_id'yi hesaplar
- İlki oluşturur, ikincisi "create failed" alır → mevcut master'a variation olarak eklenir
- **Refresh bağımsız**: ES'in hangi anlık-görüntüde olduğu önemli değil; id sabittir

**Artılar:**
- Read-after-write sorununu yapısal olarak çözer (ES'in görünürlük penceresini tamamen bypass eder)
- Sıra-bağımsız, idempotent, yeniden-çalıştırılabilir (`rerun=safe`)
- `refresh=False` yazımlar bile aynı canonical_id'ye yazılacağından çakışma ya da upsert ile doğru davranır
- Yalnızca fingerprint logic'i canonical_id üretimini etkiler; stage sorguları değişmez

**Eksiler:**
- Fingerprint-eşit sorunları çözer; FUZZY/STRIPPED farklı çiftleri (Boşluk A) çözmez
- `uuid.uuid4()` (rastgele) → `uuid5(NAMESPACE, key)` (deterministik) değişikliği gerektirir — `_index_new_master()` ve `build_new_master_doc()` refactor
- `op_type="create"` yerine `upsert` (script ile variation ekle) daha güvenli ama daha karmaşık
- Mevcut PG satırları ESKI rastgele uuid'lere bağlı → reindex ile birlikte uygulanmalı

**Recall/Throughput:** Fingerprint-eşit %100; FUZZY varyant hâlâ batch-sonu dedup'a kalır. Throughput: ek yük neredeyse sıfır (uuid5 hesaplama CPU-trivial).  
**Hardcode-uyumu:** Evet (tüm logic fingerprint_analyzer'dan türetilmiş).  
**Öneri:** **UZUN VADE İÇİN EN SAĞLAM MİMARİ** — ama mevcut PG/ES verisinin uyumluluğu için reindex ile birlikte uygulanmalı.

---

## 3. Önerilen Çözüm: Seçenek 2 + Mevcut AUTO_DEDUP_PER_BATCH Korunur

### Gerekçe

Seçenek 4 (deterministik canonical-id) ideal mimari ama reindex gerektiriyor ve mevcut PG satırlarının master_id'lerine bağımlı (`variations`, `match_stages_log`, `master_code` sütunları). Reindex zaten planlanmış (Aşama B: `es_manager.py --force`); bu dönüşüm o pencereye alınabilir.

**Kısa vadede (şimdi, reindex öncesi):** Seçenek 2 — batch başında ES `_analyze` ile fingerprint tabanlı ön-gruplama.

**Orta vadede (Aşama B reindex ile birlikte):** Seçenek 4 — deterministik canonical-id, `uuid5(NAMESPACE, f"{country_upper}:{fp_tokens}")`.

### Uygulama Eskizi — Seçenek 2 (Kısa Vade)

**Dosya:** `main_processor.py` — `process_all_data()` içindeki chunk apply-pass (satır ~1152-1210 arası)

```python
# Chunk başında: batch-içi fingerprint ön-gruplama
# (ES _analyze → Python str eşitliği — fuzzy DEĞİL)
_within_chunk_fp_cache: dict[tuple[str, str], str] = {}
# key: (fingerprint_tokens_str, country_upper) → master_id

def _get_fingerprint_tokens(es, name: str, country: str) -> str:
    """ES fingerprint_analyzer'dan token string türetir (batch-başı cache için)."""
    resp = es.indices.analyze(
        index=ES_INDEX,
        body={"analyzer": "fingerprint_analyzer", "text": name}
    )
    return " ".join(t["token"] for t in resp.get("tokens", []))
```

Apply-pass içinde `_index_new_master` çağrısından ÖNCE:
```python
fp = _get_fingerprint_tokens(es, raw_name, country)
fp_key = (fp, country.upper())
existing_in_chunk = _within_chunk_fp_cache.get(fp_key)

if fp and existing_in_chunk:
    # Aynı chunk içinde aynı fingerprint → mevcut master'a bağla
    master_id = existing_in_chunk
    stage_name = "NEW_MASTER"  # veya yeni MatchType.CHUNK_DEDUP
    # variation ekle, pg_updates'e yaz
else:
    master_id = _index_new_master(es, rec)
    if fp:
        _within_chunk_fp_cache[fp_key] = master_id
```

**Not:** `_within_chunk_fp_cache`, her chunk başında sıfırlanır (chunk sonu `es.indices.refresh` sonrası cross-chunk görünürlük ES'e devredilir).

**Bulk analyze optimizasyonu:** Tüm chunk kayıtları için `analyze` çağrısını TEK bulk request'e paketlemek mümkündür ancak ES `_analyze` API'si toplu input desteklemez (her istek tek metin); bu yüzden N×1 çağrı kaçınılmaz — ancak MATCH_BATCH_SIZE=50 ile bu 50 adet basit request, kabul edilebilir.

### Uygulama Eskizi — Seçenek 4 (Uzun Vade, Reindex ile)

**Dosya:** `main_processor.py:_index_new_master()` (satır 856-889)

```python
import uuid

_UUID5_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # UUID namespace URL

def _canonical_master_id(fingerprint_tokens: str, country: str) -> str:
    """Fingerprint'ten deterministik UUID v5 üretir (sıra/refresh bağımsız)."""
    key = f"{country.upper()}:{fingerprint_tokens}"
    return str(uuid.uuid5(_UUID5_NAMESPACE, key))

# _index_new_master içinde:
fp = _get_fingerprint_tokens(es, rec["raw_name"], rec["country"])
if fp:
    master_id = _canonical_master_id(fp, rec["country"])
    # op_type="create" — zaten mevcutsa 409, variation ekle
    try:
        es.index(..., id=master_id, op_type="create", ...)
    except ConflictError:
        _add_variation_to_master(es, master_id, rec["raw_name"], rec["country"], rec)
        return master_id
else:
    master_id = str(uuid.uuid4())  # dejenere fp → eski davranış
    es.index(..., id=master_id, ...)
```

---

## 4. Neden Fingerprint-Dedup Tek Başına Yetmiyor

`AUTO_DEDUP_PER_BATCH` (mevcut sistem) **yalnızca BİREBİR aynı kanonik fingerprint'e sahip NEW_MASTER'ları** birleştirir. Aşağıdaki gerçek-dünya senaryoları kaçar:

1. **Yazım varyantı:** "SAMSUNG ELECTRONICS" vs "SAMSUNG ELEKTRONIK" → fingerprint: `electronics samsung` vs `elektronik samsung` → farklı → kaçar. FUZZY_PHRASE ile eşleşmesi gerekir ama aynı chunk'taysa refresh olmadığı için kaçar.

2. **Suffix farkı:** "BANCO MACRO" vs "BANCO MACRO SA" → fingerprint: `banco macro` vs `banco macro` → AYNI (yasal ek strip edilir). Bu vaka fingerprint-dedup tarafından yakalanır. **AMA** `fingerprint_analyzer`'ın stripped davranışı `STRIPPED_EXACT`'tan farklı olabilir; suffix_glue veya analyzer versiyonu değişirse farklılaşabilir.

3. **Tokenizasyon farkı:** Noktalama, emoji, unicode normalizasyon farkları aynı firmayı farklı fingerprint'e düşürebilir. Örn. "C.O.L.E.S.A." (noktalı akronim) — `fingerprint_analyzer` akronim_glue'dan önceyse "c o l e s a" → her token tek harf → `_is_distinctive_fingerprint` false → dedup atlar.

4. **Geo-token artığı:** Aşama A1 (geo-stop) henüz uygulanmadı. "SAL ARGENTINA" → fingerprint `argentina sal`; "SAL" → fingerprint `sal`. Farklı fingerprint → ikisi ayrı NEW_MASTER. Bu aynı zamanda mıknatıs sorunudur: "SAL ARGENTINA"'nın geo token'ı chunk-içi başka firmalarla fingerprint çakışmasına yol açabilir.

5. **Core-count eşitliği sınırı:** `ENABLE_CORE_COVERAGE_GATE=True` (FUZZY_PHRASE / TOKEN_COVERAGE'da core-token sayısı eşitliği şartı) subset over-merge'i engeller ama bu koruma stage-eşleşmesi sırasında çalışır; NEW_MASTER açılmasını engellemez.

**Özet:** Fingerprint-dedup iyi bir ilk savunma katmanıdır ama (a) token üretim farkları, (b) typo/varyant, (c) geo-token artığı nedeniyle %100 coverage sağlayamaz. FUZZY_PHRASE/STRIPPED_EXACT farkı olan chunk-içi çiftler için structured pre-dedup veya deterministik canonical-id gereklidir.

---

## 5. Literatür Notları

**ES read-after-write latansı:** Elasticsearch resmi dökümantasyonu ("Near real-time search") `refresh_interval=1s` (default) veya `refresh=wait_for` API parametresini sunar. `wait_for` üretim yükünde genellikle önerilmez (segment birleştirme baskısı); bunun yerine **uygulama-katmanında canonical-id** veya **toplu pre-grouping** tercih edilir.

**Senzing / Real-time Entity Resolution:** Senzing, her kayıt için deterministik bir "entity key" (canonical hash) kullanır; aynı hash'e düşen kayıtlar otomatik birleştirilir, hash hesaplama refresh-bağımsızdır. Bu, Seçenek 4'ün endüstri referansıdır.

**Splink / Zingg:** Her iki framework da "blocking key" (canonical key) üretimini eşleşme öncesine koyar; batch-içi blocking key çakışmaları greedy merge başlamadan önce çözülür. Bu, Seçenek 2'nin akademik karşılığıdır.

**GraLMatch (arXiv 2024) + Microclustering (arXiv 2025):** Batch-içi görünürlük sorunu "greedy-incremental" ER'nin genel zayıflığıdır; önerilen çözüm "within-batch blocking + merge, then cross-batch incremental" mimarisidir — bu çalışmada Seçenek 2 ve 4'e karşılık gelir.

**ES `_analyze` pre-grouping (community practice):** ES topluluk bloglarında ("Elastic: Duplicate Detection at Scale") `_analyze` API ile blocking-key üretimi, msearch öncesi pre-pass olarak önerilmektedir; Python-fuzzy yasağını ihlal etmez (ES sunucu-tarafı NLP → Python yalnızca string eşitliği).

---

## Ek: Mevcut Durum Özet Tablosu

| Parametre | Değer | Etki |
|-----------|-------|------|
| `MATCH_BATCH_SIZE` | 50 | Read-after-write penceresi: 50 kayıt |
| `NEW_MASTER_SUBBATCH_SIZE` | 200 | `create_new_masters()` (aktif yolda kullanılmıyor) |
| `ES_REFRESH_INTERVAL` | 50 | config'de tanımlı ama `process_all_data()` bunu her chunk sonunda sabit çağırıyor (satır 1214) |
| `AUTO_DEDUP_PER_BATCH` | True | Batch sonunda fingerprint-exact dedup; FUZZY varyantları yakalamaz |
| `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` | 2 | Akronim çökmesi guard; doğru davranış |
| Aktif NEW_MASTER yolu | `_index_new_master()` (satır 856) | `refresh=False`, pre-dedup yok, uuid4 rastgele |
