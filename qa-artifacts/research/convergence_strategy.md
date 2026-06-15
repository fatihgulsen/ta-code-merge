# Firma Eşleştirme Sistemi — %100'e Yakınsama Stratejisi

**Tarih:** 2026-06-15  
**Bağlam:** Round-7 audit (AR precision %93.4 düzeltilmiş, PE tamamen ölü, SUFFIX_FUZZY %68, 830 duplike NEW_MASTER)  
**Odak:** Transitive-closure mıknatıs tuzağı · greedy-incremental riskleri · eşik kalibrasyonu · insan-denetim kuyruğu · gerçekçilik sınırı

---

## 1. Transitive-Closure Mıknatısı: Neden Oluşur, Neden Tehlikelidir

### 1.1 Mekanizma

Greedy-incremental birleştirme, her gelen kaydı *o an mevcut master'lara* karşı sorgular ve ilk yüksek-skorlu eşleşmeye bağlar. Bu yaklaşım, transitif kapanım (connected-component) üretir: A~B ve B~C yeterince yüksek skor getirirse A⇸C olsa bile A-B-C tek master'da toplanır.

Sistem içindeki kanıtlanmış örnekler (R7):
- `BANCO MACRO BANSUD` → `BANCO MACRO` (ayırt edici token BANSUD'un kaybı; SUFFIX_FUZZY)
- `PUMA SPORTS ARGENTINA` → `PUMA SPORTS LA` (geo-token ikamesi; eşit token sayısı)
- `GM BRASIL` → `GM ARGENTINA` (ülke-token farkına rağmen eşleşme)
- `SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA` → `SAMSUNG ELECTRONICS CO LTD` (subset; 6 token → 3 token)

Bu hatalar doğrudan mıknatıs mekanizmasından kaynaklanmaz; birleşmiş master'ın *giderek büyüyen variation listesi* arama zamanında daha fazla gürültülü eşleşme çekmesine yol açar ve küme büyür. Literatürde "magnet cluster" veya "snowball" olarak adlandırılır [(End-to-End ER Survey, 2019)](https://arxiv.org/pdf/1905.06397); microclustering property'ye göre en büyük kümenin boyutu veri seti boyutuyla sub-lineer büyümeli, lineer değil.

### 1.2 Mevcut Mimarideki Tetikleyiciler

| Tetikleyici | Kodu | Risk |
|---|---|---|
| SUFFIX_FUZZY'de `_core_coverage_filter` yok | `es_queries.py:268-315` | Subset-match → küme büyümesi |
| Token-tekrarlı variation | ingest Painless | Sahte yüksek skor → yanlış birleştirme |
| Geo-token ikamesi | core-coverage aşılıyor | `GM BRASIL` ↔ `GM ARGENTINA` |
| 830 duplike NEW_MASTER izleme kör noktası | watch query | Gizli kümeler |

---

## 2. Greedy-Incremental'in Yapısal Riskleri

### 2.1 Sıra Bağımlılığı

Kayıt X, kayıt Y'den *önce* gelirse X yeni master açar ve Y ona bağlanır; tersi sırada Y açar ve X bağlanır. Master'ın canonical adı sıraya göre değişir. Bu kararlılık sorunudur — aynı veri kümesi farklı toplu batch sırasıyla farklı kümeler üretir.

**Azaltma:** Her batch refresh-then-check yapıyor (mevcut: `es.indices.refresh` chunk sonunda). Bu doğru yaklaşım; ancak MATCH_BATCH_SIZE büyükse aynı chunk içindeki kardeş kayıtlar birbirini göremez. Yeterince küçük chunk boyutu (varsayılan 1 veya düşük) sıra bağımlılığını azaltır.

### 2.2 Read-After-Write Penceresi

`_index_new_master` ES'e yazar → refresh → sonraki kayıt okur. Refresh pahalı; batch boyutunu artırınca pencere genişler ve within-chunk duplikalar NEW_MASTER üretir. Mevcut `AUTO_DEDUP_PER_BATCH` bunu batch-sonunda yakalıyor; iyidir, ama gecikmeli (variation zaten yanlış yazılmış olabilir).

### 2.3 Fingerprint Canonical-Key'in Sınırları

`es_transform.py` → aynı fingerprint + country altındaki master_id'leri toplar. Bu *aynı karakter dizisinin farklı UUID'lerle iki kez index'lenmesini* yakalar. Yakalamadığı:
- Variation gürültüsü nedeniyle biri yanlış master'a eklenmiş eş-firmalar (fingerprint farklılaşır).
- Geo-token ikamesi ile oluşan mıknatıs kümeleri.

**Sonuç:** ES Transform gerekli ama yeterli değil; sadece tek-katman güvenliği.

---

## 3. Mıknatısı Yapısal Olarak Önleyen 4 Mekanizma

### M1 — Core-Coverage Zorunluluğu (Her Stage) [Öncelik: P0]

SUFFIX_FUZZY'ye `_core_coverage_filter` eklenmesi (R7-R2 önerisi). Bu, subset-match'i kırıp "master büyük / sorgulayan küçük" durumunu bloklar. Token-coverage skoru asimetrik olarak hesaplanmalı: `min(hit_tokens/query_tokens, hit_tokens/master_tokens)` yerine her iki yönde de eşik.

**Etki:** 120 onaylanmış SUFFIX_FUZZY hatasının ~%80'i (R7 kök neden analizi). Hiç reindex gerektirmez — mapping halihazırda `token_count` alanını içeriyor.

### M2 — Max-Cluster-Size Guard (Çalışma-Zamanı Karantina) [Öncelik: P1]

Master'ın `variations` listesi eşik N'i (örn. 50-100 variation) aştığında **otomatik karantina**: yeni eşleşme bu master'a bağlanmaz, UNCERTAIN kuyruğuna düşer. Karantina limiti ülke + stage bazında konfigüre edilebilir (`config.py`'ye `MAX_VARIATIONS_PER_MASTER` sabiti).

Literatür desteği: microclustering property — büyük kümeler genelde gürültü içerir [(arxiv:2507.18101)](https://arxiv.org/pdf/2507.18101).

Uygulama:
```python
# es_queries.py run_stage() içinde:
if master_doc["_source"].get("variation_count", 0) > MAX_VARIATIONS_PER_MASTER:
    # Bu master'ı eşleşme adayından çıkar veya UNCERTAIN'a yönlendir
```

### M3 — Ayırt Edici-Token (IDF-Ağırlıklı) Geçit Kontrolü [Öncelik: P1]

Mevcut sistem token sayısı üzerinden çalışıyor (symmetric coverage). Ama `SAMSUNG`+`ELECTRONICS` çok yaygın; `HAINAN`+`FIBER` nadir. Nadir token kaybolduğunda eşleşme **bloklanmalı**.

Uygulama: ES `significant_terms` veya `more_like_this` ile "query'de var ama master'da yok" nadir token tespiti; veya Painless skript ile per-token IDF yükü hesabı. Python'da RapidFuzz yasak olduğundan bu tamamen ES-tarafı Painless/DSL ile yapılabilir.

Pratik ara-yol: `_core_coverage_filter`'ı "en az 1 non-stopword, non-geo core token iki yönde de mevcut" şartıyla genişlet. Bu M1'i güçlendirir.

### M4 — Geo-Token İkamesi Bloğu [Öncelik: P2]

`geo_stopwords_global` veya `synonyms_data/<cc>.json` kaynaklı coğrafya token'ları (ARGENTINA, BRASIL, NZ, LA...) eşleşme kararına sayılmamalı. Eğer query'deki *tek* ayırt edici token bir geo-token ise eşleşme bloklanmalı.

Uygulama: `_core_coverage_filter` içinde geo-token listesini maskeleyerek "core non-geo token coverage" hesapla. Geo listesi hardcode edilmez; `synonym_loader.py`'den ülke tokenlarını alır (CLAUDE.md kural: hardcode yok).

---

## 4. Eşik Kalibrasyonu

### 4.1 Mevcut Sorun

Her stage'in `min_score` değeri (config.py'deki `STAGES` listesi) kör olarak ayarlı; IDF veya küme büyüklüğüne duyarsız. Yüksek-frequency master'lar (çok variation = çok term) düşük IDF skoru alır ama min_score değişmez → over-merge kapısı açık kalır.

### 4.2 IDF-Ağırlıklı Skor Normalizasyonu

ES BM25 zaten IDF uygular. Sorun, `min_score`'un BM25 çıkışına göre statik olmasıdır. Çözüm seçenekleri:

**A) Per-stage normalize min_score:** Her ülke+stage kombinasyonu için golden set üzerinde F1 maksimizasyon grid search (otomatik threshold tuning). Mevcut `match_stages_log` verisi bu için kullanılabilir.

**B) Function Score katmanı:** ES `function_score` + `field_value_factor` ile variation_count'u negatif ağırlıkla penalize et (büyük master daha yüksek min_score gerektirir):
```json
"functions": [{
  "field_value_factor": {
    "field": "variation_count",
    "factor": -0.02,
    "modifier": "log1p"
  }
}]
```

**C) Rescore aşaması:** `query_then_fetch` + `rescore` ile Painless `rare_token_bonus` skript. Sistemin ES-only kısıtına tamamen uygundur.

### 4.3 SUFFIX_FUZZY için Özel Kalibrasyon

R7: SUFFIX_FUZZY min_score'u muhtemelen ~15-17 civarında; subset hataları da bu bantta. M1 uygulandıktan sonra SUFFIX_FUZZY'nin yeni precision/recall eğrisi golden set üzerinde yeniden ölçülmeli ve min_score yukarı çekilmeli (tahmin: 20-22).

---

## 5. %100 Gerçekçi Mi? Literatür Cevabı

### Kesin Cevap: HAYIR — ve Bu Doğru Hedef Değil

Correlation clustering NP-hard [(AAAI-20, 2020)](https://ojs.aaai.org/index.php/AAAI/article/download/5520/5376). Serbest-metin firma adı eşleştirmesinde özellikle:

1. **Referans belirsizliği indirgenemez:** "SAMSUNG" → hangi Samsung? Ülke filtresi yardımcı olur ama aynı ülkede aynı isimli farklı firmalar gerçekten vardır (homonim).
2. **Kayıt kalitesi gürültüsü:** Kısaltmalar, yazım hataları, adres karışımı (`AV ALICIA MOREAU...`), slash multi-entity — bunların hepsi kesin cevabı olmayan vakalar üretir.
3. **Sıra bağımlılığı + veri evrimi:** Bugün "yanlış" olan eşleşme yarın doğru olabilir (yeni variation eklendi).

### Gerçekçi Hedef Matrisi

| Katman | Hedef | Nasıl |
|---|---|---|
| Otomatik precision | %95+ (düzeltilmiş) | M1+M2+M3+M4 + min_score kalibrasyonu |
| Otomatik recall | %90+ | Reindex (PE) + rematch tamamlama |
| Belirsiz kuyruk | %100 kapsama | UNCERTAIN kuyruğu → insan denetimi |
| Gerçek hata oranı (kaçan) | <%2 | Golden set probe her reindex'te |

"~%100 doğruluğa yakınsama" gerçekçi anlayışla şu demektir: **yüksek-güven otomatik kararlar (%95+ precision) + belirsiz vakaların tamamı insan denetimine yönlendirme + regresyon monitörleme.** Bu sektör pratiğinde [(Dataiku, 2024)](https://www.dataiku.com/stories/blog/accelerating-entity-resolution) standart kabul edilen mimaridir.

---

## 6. İnsan-Denetim Kuyruğu Tasarımı

### 6.1 Hangi Vakalar Kuyruğa Düşer (Routing Mantığı)

```
UNCERTAIN kuyruğu tetikleyicileri (öncelik sırasıyla):
  1. max-cluster-size ihlali (M2 karantinası)
  2. SUFFIX_FUZZY eşleşmesi (stage=SUFFIX_FUZZY; en zayıf halka)
  3. score ∈ [min_score, min_score+5] (düşük güven bandı; stage başına konfigüre)
  4. Slash multi-entity tespiti (input_filter)
  5. ES Transform: fingerprint çakışması, master_count ≥ 2
```

### 6.2 Öncelik Skoru (Reviewer Queue)

```
priority = (güven_eksikliği_skoru × 3)
         + (küme_büyüklüğü_riski × 2)
         + (ülke_kritiklik_katsayısı × 1)
         + (bekleme_süresi_gün × 0.5)
```

Güven eksikliği = `1 - (es_score - min_score) / score_range`  
Küme büyüklüğü riski = `log1p(variation_count) / log1p(MAX_VARIATIONS_PER_MASTER)`

Uygulama: `match_stages_log` + yeni `uncertain_queue` PG tablosu; `dedup_reviewer.py` bu tablodan okuyacak şekilde genişletilir.

### 6.3 Blokaj Kapısı

Max-cluster-size ihlali durumunda (M2) sistem **eşleşme yazmaz** — bekler. Bu "hard gate": reviewer onaylamadan merge gerçekleşmez. Diğer uncertain vakalar "soft gate": otomatik olarak en-yüksek-skor master'a bağlanır ama `needs_review=True` işareti taşır; reviewer sonradan düzeltebilir (reversible).

### 6.4 Kapasite Tahmini

Double-threshold policy [(arxiv:2601.05974)](https://arxiv.org/pdf/2601.05974):
- Otomatik kabo: `score >= high_threshold` → direkt birleştir
- Otomatik ret: `score < low_threshold` → direkt yeni master
- İnsan kuyruğu: `low_threshold ≤ score < high_threshold`

Kapasite = `daily_review_capacity / total_daily_uncertain_volume`. Thresholdlar bu orana göre iteratif kalibre edilir.

### 6.5 dedup_reviewer.py Geliştirme Yol Haritası

Mevcut `dedup_reviewer.py`: ES Transform fingerprint çıktısını interaktif gösterir, y/n/q ile birleştirir. Eksikler:

1. **Öncelik sıralaması:** `priority_score` descending sort
2. **Kategori gösterimi:** Hangi tetikleyiciyle kuyruğa düştü (stage, cluster-size, score-band)
3. **Split işlemi:** `y`=birleştir yanı sıra `s`=böl (mıknatıs tespiti sonrası)
4. **PG geri-yazım:** Kararlar `match_stages_log.reviewed=True` + `reviewer_decision` kolonlarına yansısın
5. **Batch mod:** Tek tek onay yerine "tümünü onayla" / "aynı kategorideki hepsini atla" filtresi

---

## 7. Ölçüm ve Regresyon Stratejisi

### 7.1 Golden Set Genişletme

Mevcut golden set: R5-R7 adversarial verify'dan çıkan ~313 onaylanmış hata + ~500 doğru eşleşme. Her reindex sonrası:
1. Golden set tüm kayıtları yeniden koş.
2. Precision/recall delta hesapla (before/after).
3. Regression: Önceki turda doğru olan vaka şimdi hatalı mı? → Kritik uyarı.

### 7.2 Canlı Probe

`match_stages_log`'dan otomatik örnekleme: Her stage için son 24 saatin rastgele %1'i haiku ile değerlendir (mevcut `audit_batch.ps1` altyapısı). Threshold: eğer herhangi stage'in precision'ı %3'ten fazla düşerse → alarm → reindex/kalibrasyonu tetikle.

### 7.3 Mıknatıs İzleme Query'si

```sql
-- Büyük master'ları izle (M2 öncesi erken uyarı)
SELECT master_code, COUNT(*) as variation_count, country_code
FROM raw_firms
WHERE master_code IS NOT NULL
GROUP BY master_code, country_code
HAVING COUNT(*) > 30
ORDER BY variation_count DESC;
```

+ R7'deki kör nokta düzeltmesi: `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` bloğu da eklenmeli.

---

## 8. Eylem Sırası (Önerilen)

| # | Eylem | Etki | Zaman |
|---|---|---|---|
| **E1** | SUFFIX_FUZZY'ye `_core_coverage_filter` ekle (`es_queries.py`) | SUFFIX_FUZZY %68 → ~%93 | <1 saat |
| **E2** | `python es_ingest.py` → `python es_manager.py --force` → rematch | PE açılır, stale AR tazelenir, %100 coverage | ~saatler |
| **E3** | Max-cluster-size guard (`config.py` + `run_stage`) | Mıknatıs büyümesi durur | <2 saat |
| **E4** | Token-tekrarlı dedup (Painless ingest) | `PERNOD RICARD`/`ADIDAS ADIDAS` gibi skorlar düzelir | <1 saat |
| **E5** | Geo-token mask (`_core_coverage_filter` genişletmesi) | `GM BRASIL`↔`GM ARGENTINA` hatası kapanır | <2 saat |
| **E6** | `dedup_reviewer.py` priority queue + split + PG geri-yazım | İnsan-denetim kuyruğu operasyonel olur | ~1 gün |
| **E7** | Golden set regresyon + canlı probe otomasyon | Sürekli kalite ölçümü | <1 gün |

E1 → E2 bağımlılığı var (E1 kodu E2 reindex'iyle birlikte canlı olur); E3-E5 E2 ile paralel geliştirilebilir.

---

## Referanslar

- [End-to-End Entity Resolution for Big Data: A Survey](https://arxiv.org/pdf/1905.06397)
- [(Almost) All of Entity Resolution — Science Advances](https://www.science.org/doi/10.1126/sciadv.abi8021)
- [Correlation Clustering — AAAI-20](https://ojs.aaai.org/index.php/AAAI/article/download/5520/5376)
- [Large-scale ER via Microclustering](https://arxiv.org/pdf/2507.18101)
- [In-context Clustering ER with LLMs — 2025](https://arxiv.org/pdf/2506.02509)
- [Human-in-the-Loop Framework](https://arxiv.org/pdf/2601.05974)
- [Accelerating ER with Automation and Human Validation — Dataiku](https://www.dataiku.com/stories/blog/accelerating-entity-resolution)
- [Improving ER with Soft TF-IDF — Enigma](https://enigma.com/blog/post/improving-entity-resolution-with-the-soft-tf-idf-algorithm)
- [Incremental ER from Linked Documents](https://arxiv.org/pdf/1402.4417)
- [GNN for Inconsistent Cluster Detection in Incremental ER](https://arxiv.org/pdf/2105.05957)
