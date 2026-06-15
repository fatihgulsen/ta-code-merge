# Round-6 — Paralel Haiku QA Taraması (`p7_firms_v2_ar_pe`)

**Tarih:** 2026-06-12
**Yöntem:** Orchestrator + 34 paralel `haiku` denetçi (28 over-merge batch, 6 under-merge batch) + 2 `sonnet` stage denetçisi (SUFFIX_FUZZY, FUZZY_PHRASE)
**Kapsam:** Tablodaki TÜM master-variant eşleşmeleri (2.925 variant / 2.367 grup) + 3.000 örnekli under-merge adayı
**Çalışma modu:** READ-ONLY. Kod/DB değişikliği YAPILMADI. pg_trgm + ES `_analyze` kullanıldı; Python fuzzy YOK.
**Artefaktlar:** `qa-artifacts/round6/` (groups.jsonl, verdicts/, diagnostics.json, phase2_*_audit.md, *_synthesis.json)

---

## 0. Yönetici Özeti

| Konu | Bulgu | Önem |
|------|-------|------|
| **AR over-merge precision** | **%89.5** (2.570 SAME / 2.871 karar) — Round-5 %95.9'dan düşük görünüyor ama bu kez TÜM eşleşmeler tarandı (tam sayım, örnekleme değil) | — |
| **SUFFIX_FUZZY precision** | **%65.4** (en zayıf stage; 89 FP) — kök neden: A-gate (`_core_coverage_filter`) bu stage'de EKSİK | 🔴 HIGH |
| **FUZZY_PHRASE precision** | **%89.7** — mevcut eşleşmeler core-coverage filtresi commit'inden (2206407) ÖNCE üretildi; rematch ile ~%92.6'ya çıkar | 🟠 MEDIUM |
| **STRIPPED_EXACT precision** | **%92.5** — çoğu hata noktalama/suffix DEĞİL, gerçek subset (`APERAM STAINLESS SERVICES` ⊂ `...AND`) | 🟠 MEDIUM |
| **TOKEN_COVERAGE precision** | **%86.8** — token tekrarı (`RICARD RICARD`, `ADIDAS ADIDAS`) ve kelime sırası | 🟠 MEDIUM |
| **COUNTRY_LEAK** | **0** — hard filter sağlam ✓ | ✅ |
| **PE eşleştirme** | **HİÇ çalışmamış** — PE'de 0 variant eşleşmesi; sim=1.0 tam dup'lar (`3M PERU S.A.` × 2) bile birleşmemiş | 🔴 P0 BLOCKER |
| **Veri kalitesi** | YPFB/TLP fatura-satırı kayıtları (`...FAC-1387 REF-80`) firma adı alanında → 589 sahte AR NEW_MASTER, 172.817 sahte under-merge adayı | 🔴 HIGH |
| **Duplike NEW_MASTER** | 727 grup aynı UUID'de >1 anchor taşıyor → over-merge denetiminin kör noktası | 🟠 MEDIUM |

**Tek cümlelik aksiyon:** `SUFFIX_FUZZY` query'sine `_core_coverage_filter` ekle + tam rematch çalıştır + PE indeksleme/eşleştirme blocker'ını çöz.

---

## 1. Genel Metrikler

### 1.1 Tablo dağılımı (Faz 0)

| country | NEW_MASTER | STRIPPED_EXACT | FUZZY_PHRASE | SUFFIX_FUZZY | TOKEN_COVERAGE | EXCLUDED |
|---------|-----------:|---------------:|-------------:|-------------:|---------------:|---------:|
| **AR** | 41.368 | 2.140 | 298 | 243 | 136 | 2 |
| **PE** | 69.861 | **0** | **0** | **0** | **0** | 1 |

> **PE'de tek bir variant eşleşmesi yok.** Tüm eşleştirme stage'leri yalnızca AR üzerinde sonuç üretmiş. Bu, "PE index stale" şüphesini doğrular ve ötesine geçer: PE için eşleştirme süreci ya hiç koşmamış ya da boş ES anlık-görüntüsüne karşı koşmuş (bkz. §4).

### 1.2 Over-merge verdict dağılımı (match_type bazlı, AR)

Precision = SAME / (SAME + DIFFERENT). UNSURE ve PLACEHOLDER dışarıda.

| match_type | SAME | DIFFERENT | UNSURE | PLACEHOLDER | **Precision** |
|------------|-----:|----------:|-------:|------------:|--------------:|
| STRIPPED_EXACT | 1.998 | 161 | 30 | 6 | **%92.5** |
| FUZZY_PHRASE | 286 | 33 | 7 | 1 | **%89.7** |
| TOKEN_COVERAGE | 118 | 18 | 1 | 1 | **%86.8** |
| SUFFIX_FUZZY | 168 | 89 | 8 | 0 | **%65.4** |
| **TOPLAM** | **2.570** | **301** | **46** | **8** | **%89.5** |

### 1.3 Round-5 karşılaştırması

| Metrik | Round-5 | Round-6 | Not |
|--------|--------:|--------:|-----|
| AR genel precision | %95.9 (full-cov örnekleme) | %89.5 (TAM sayım) | R6 daha kapsamlı/sert; örnekleme değil tüm eşleşmeler |
| SUFFIX_FUZZY | %81.3 | %65.4 | R6 257 karar; gerçek sistemik değer daha düşük |
| COUNTRY_LEAK | 0 | 0 | ✓ değişmedi |
| Hataların kaynağı | %53 SUFFIX_FUZZY | SUFFIX_FUZZY 89 + STRIPPED_EXACT 161 FP | STRIPPED_EXACT hacmi yüksek (mutlak FP'de #1) |

> **Yorum:** R5↔R6 precision düşüşü gerileme değil, **ölçüm kapsamı** farkı. R5 yüksek-güvenli örneklem üzerindeydi; R6 her eşleşmeyi denetledi. Mutlak hata sayısında STRIPPED_EXACT (161 FP) lider — ama oran olarak SUFFIX_FUZZY (%34.6 hata) en kötü.

---

## 2. Over-Merge Bulguları

### 2.1 En kötü 20 (yüksek skorlu DIFFERENT — sistemin en "emin" olduğu hatalar)

| score | match_type | master → variant |
|------:|------------|------------------|
| 48 | FUZZY_PHRASE | `AV ALICIA MOREAU DE JUSTO 1720 1 A` ⇸ `...1720 1` (adres, firma değil) |
| 35 | TOKEN_COVERAGE | `FAE FABRICACION DE ALEACIONES ESPECIALES` ⇸ `FAE S.A. FABRICACION...` (kelime sırası — aslında SAME sınırda) |
| 29 | TOKEN_COVERAGE | `EVERGREEN LOGISTICS (INDIA)` ⇸ `EVERGREEN LOGISTICS TAIWAN` (farklı ülke iştiraki) |
| 27 | TOKEN_COVERAGE | `PERNOD RICARD ARGENTINA` ⇸ `RICARD RICARD ARGENTINA` (token tekrarı bug) |
| 27 | FUZZY_PHRASE | `ASOCIACION CASA EDITORA SUDAMERICAN` ⇸ `ASOCIACION CASA EDITORA` (subset) |
| 26 | TOKEN_COVERAGE | `COTO CENTRO INTEGRAL DE COMERCIALIZACION` ⇸ `COTO CENTRO CENTRO INTEGRAL` |
| 26 | STRIPPED_EXACT | `APERAM STAINLESS SERVICES` ⇸ `APERAM STAINLESS SERVICES AND` (kesik) |
| 26 | STRIPPED_EXACT | `XYLEM WATER SOLUTIONS ARGENTINA SRL` ⇸ `...S.A.` (farklı tüzel tip — sınırda) |
| 24 | TOKEN_COVERAGE | `PERNOD RICARD ARGENTINA` ⇸ `RICARD RICARD ARGENTINA` |
| 24 | STRIPPED_EXACT | `WDM WATER SYSTEMS SA` ⇸ `WDM WATER SYSTEMS S.A. DE C.V.` (AR↔MX tüzel?) |
| 24 | TOKEN_COVERAGE | `ADIDAS ARGENTINA S.A._678002` ⇸ `ADIDAS ADIDAS ARGENTINA SA` (token tekrarı) |
| 23 | FUZZY_PHRASE | `GM BRASIL` ⇸ `GM DE ARGENTINA S.R.L.` (geo-token ikamesi) |
| 23 | STRIPPED_EXACT | `MFC RESOURCES SRL` ⇸ `MFC RESOURCES, INC.` (farklı tüzel kişilik) |
| 23 | SUFFIX_FUZZY | `INC S.A. CUYO 3367 - MARTINEZ` ⇸ `INC S.A. CUYO 3367` (adres artığı) |
| 21 | SUFFIX_FUZZY | `POWER TRAIN TECHNOLOGIES ARGENTINA` ⇸ `POWER TRAIN TECHNOLOGIES SA` (subset) |
| 21 | TOKEN_COVERAGE | `ALTA CARGAS INTERNACIONAL` ⇸ `ALTA INTERNACIONAL CARGAS` (sıra — sınırda SAME) |
| 20 | STRIPPED_EXACT | `TETRA PAK S.A` ⇸ `TETRA PAK, INC.` (farklı tüzel) |

Tam liste: `qa-artifacts/round6/overmerge_synthesis.json` (`diff_rows`, 301 kayıt).

### 2.2 Hata desenleri (özet)

1. **Subset / truncation** (en yaygın): variant master'ın token-alt kümesi. SUFFIX_FUZZY'de %66, FUZZY_PHRASE'de 9/33. → A-gate çözer.
2. **Geo-token ikamesi**: `GM BRASIL` vs `GM DE ARGENTINA`, `VOLKSWAGEN OF AMERICA` vs `VOLKSWAGEN ARGENTINA`. Token sayısı eşit → A-gate çözmez.
3. **Token tekrarı bug'ı**: `RICARD RICARD`, `ADIDAS ADIDAS`, `COTO CENTRO CENTRO` — kaynak veride yinelenen token, coverage'ı şişiriyor.
4. **Farklı tüzel kişilik / tip**: `MFC RESOURCES SRL` vs `INC`, `TETRA PAK S.A` vs `INC` — gerçek farklı kuruluşlar.
5. **Adres/CUIT firma adı alanında**: `AV ALICIA MOREAU...`, `INC S.A. CUYO 3367 - MARTINEZ` → input_filter sorunu.

---

## 3. Under-Merge Bulguları

### 3.1 Aday havuzu ve örnekleme

- pg_trgm + prefix-blocking ile **502.437 aday** çifti bulundu (sim>0.55). Bunun **172.817'si (≈%34)** YPFB fatura-satırı gürültüsü (aşağıda).
- Tarama için her ülkeden en yüksek benzerlikli **1.500'er çift** (toplam 3.000) örneklendi; AR min sim 0.934, PE min sim 0.919. **Kesilen:** 499.437 düşük-benzerlikli aday (raporlandı, sessizce atlanmadı).

### 3.2 Verdict dağılımı

| ülke × küme | SHOULD_MERGE | CORRECTLY_SEPARATE | UNSURE |
|-------------|-------------:|-------------------:|-------:|
| AR — YPFB fatura kümesi | 500 | 495 | 306 | 
| AR — diğer | 106 | 18 | 75 |
| **PE — diğer** | **1.282** | 97 | 121 |

### 3.3 AR — gerçek kaçırılan birleşmeler (non-YPFB, 106 çift)

Büyük çoğunluğu **noktalama/boşluk varyantı** (A-gate'in recall maliyeti veya stage kapsamı dışında kalanlar):

```
J.L.IMPORTACIONES S.R.L.    <=> J.L. IMPORTACIONES S.R.L.      (sadece boşluk)
DAVICA S.A. I C A I         <=> DAVICA S.A.I.C.A.I.            (suffix noktalama)
RAUL V.BATALLES S.A.        <=> RAUL V BATALLES S.A.           (nokta)
DROGUERIA SAPORITI S.A.C.I.F.A. <=> DROGUERIA SAPORITI S.A. C.I.F.I.A
```

→ Bunlar STRIPPED_EXACT veya CANONICAL_EXACT tarafından yakalanmalıydı; analyzer'ın noktalama/boşluk normalizasyonu eksik kalıyor.

### 3.4 PE — kritik: 1.282 kaçırılmış birleşme, tam dup'lar dahil

PE'de **hiç eşleştirme çalışmadığı için** sim=1.0 tam duplikalar bile ayrı master'da:

```
3M PERU, S.A.            <=> 3M PERU S.A.            (sim 1.0)
APUNTALH S.A.C.          <=> APUNTALH S.A.C.         (sim 1.0 — birebir aynı!)
ACCORD HEALTHCARE S.A.C. <=> ACCORD HEALTHCARE S A C (sim 1.0)
AUTOPARTES, S.A.         <=> AUTOPARTES S.A.         (sim 1.0)
BANCO DE CREDITO DEL PERU<=> BANCO DE CREDITO DEL PERU, (sim 1.0)
```

→ Tek başına bu, PE'nin hiç eşleştirilmediğinin kesin kanıtı. **PE under-merge sayısı anlamsız** — önce eşleştirme koşmalı, sonra ölçülmeli.

---

## 4. COUNTRY_LEAK & PE Blocker

- **COUNTRY_LEAK: 0 grup.** `country_count > 1` olan tek bir master yok. Hard filter sağlam. ✅
- **PE P0 BLOCKER:** PE 69.861 NEW_MASTER + 1 EXCLUDED, **0 variant eşleşmesi**. ES index'inde toplam 207.619 doküman var (640.517 store, 913 silinmiş). PE eşleştirmesi:
  - ya hiç koşmadı,
  - ya da PE dokümanları indekslenmeden / stale snapshot'a karşı koştu.
  - **Aksiyon:** PE'yi `es_manager.py` ile (gerekirse `--force`) reindex et, `main_processor.py`'yi `COUNTRY_CODE_FILTER="pe"` ile koş, sonra PE QA'sını tekrarla. PE sonuçları bu raporda AR'dan ayrı tutulmuştur ve **PE precision ÖLÇÜLEMEDİ** (eşleşme yok).

---

## 5. Sorgu / Pipeline Diyagnostikleri (Faz 0)

| Diyagnostik | Sonuç | Yorum |
|-------------|-------|-------|
| **Yetim gruplar** | 3 | Üçü de EXCLUDED satır (`NULL`, `SAME AS`, `SAME AS`) master_code taşıyor ama NEW_MASTER anchor'ı yok. Zararsız ama temizlenebilir. |
| **Duplike NEW_MASTER** | **727 grup** (153 AR + 597 PE) | Aynı master_code UUID'de >1 NEW_MASTER. Örn. UUID `0a9eb6b9` → 15× `TLP S.A COMPL-2731-X`. AUTO_DEDUP master_code'u birleştirmiş ama match_type'ı NEW_MASTER bırakmış → bu birleşmeler over-merge denetiminde **görünmez** (watch query `match_type != NEW_MASTER` ile join ediyor). |
| **Self-referans "tutarsızlığı"** | 111.329 (YANLIŞ ALARM) | `master_code != ta_code` koşulu yanıltıcı: `master_code` bir UUID, `ta_code` ise `ar80014588` formatında. NEW_MASTER'da master_code=UUID olması **tasarım gereği**. Şema notu: watch sorguları UUID `master_code` üzerinden join etmeli, `ta_code==master_code` VARSAYMAMALI. |
| **NULL match_type + dolu master** | 0 | ✓ temiz |
| **COUNTRY_LEAK** | 0 | ✓ |

---

## 6. SUFFIX_FUZZY ve FUZZY_PHRASE Değerlendirmesi (Faz 2)

### 6.1 SUFFIX_FUZZY — %65.4, en zayıf halka

**Kök neden:** Commit `2206407` (core coverage filter) FUZZY_PHRASE ve TOKEN_COVERAGE'a `_core_coverage_filter()` ekledi ama **SUFFIX_FUZZY'yi kapsam dışı bıraktı**. SUFFIX_FUZZY query'sinde (es_queries.py ~satır 268-313) stripped `token_count` eşitliği kontrolü YOK.

| Pattern | Tanım | Adet | A-gate yakalar |
|---------|-------|-----:|:-------------:|
| C — subset/truncation | `SAMSUNG ELECTRONICS CO LTD` ⊂ `SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA CO LTD` | 59 (%66) | %100 ✓ |
| B — farklı marka, eşit token | `DEVRE INTERNACIONAL` vs `SA INTERNACIONAL` | 20 (%22) | ~%10 ✗ |
| D — adres/CUIT/multi-entity artığı | `MGP LOGISTICS SRL JOINTLY & SEVERALLY WITH...` | 10 (%11) | %100 ✓ |
| A — suffix soyma çakışması | (gözlemlenmedi) | 0 | — |

**A-gate genişletmesi 89 FP'nin 71'ini (%79.8) yakalar.** Kalan 18 (Pattern B) eşit token sayısı taşıdığı için yakalanmaz; bunlar için ek tedbir (fuzziness sıkılaştırma veya min_score artışı) gerekir.

**Öneri (ES-side, recall-nötr):**
```python
# es_queries.py — SUFFIX_FUZZY "must" listesine ekle (FUZZY_PHRASE/TOKEN_COVERAGE ile simetrik):
"must": [
    nested_match_phrase_on_variations_stripped,
    *_core_coverage_filter(es, name, country),   # ← EKLE (A-gate)
],
```
Reindex GEREKMEZ (`variations_stripped.name.token_count` alanı zaten mevcut). `ENABLE_CORE_COVERAGE_GATE` flag'i paylaşılır.

### 6.2 FUZZY_PHRASE — %89.7, ama filtre HİÇ DEVREDE DEĞİLDİ

**Kanıt:** FUZZY_PHRASE satırlarının tamamının `max(updated_at)` = **2026-04-26**; commit 2206407 tarihi = **2026-06-10**. Yani mevcut tüm FUZZY_PHRASE eşleşmeleri core-coverage filtresinden **6+ hafta önce** üretildi. `match_details` yalnızca `[FUZZY_PHRASE] score: X.XX` içeriyor, filtre izi yok.

| Mekanizma | Adet | Filtre çözer mi? |
|-----------|-----:|:----------------:|
| (c) subset/truncation (token sayısı farklı) | 9 | ✓ rematch sonrası |
| (e) eşit token, semantik farklı (`OCEAN EXPORT` vs `IMPORT`) | 13 | ✗ |
| (d) geo-token ikamesi | 5 | ✗ |
| (b) fuzziness/synonym boşluğu (`INTERNACIONAL`/`INTERNATIONAL`) | 3 | ✗ |
| (a) slop=1 kelime ekleme | 2 | ✗ |
| (f) adres verisi | 1 | ✗ |

**Rematch ile beklenen:** 9 FP otomatik kapanır, precision %89.7 → ~%92.6. Kalan 24 için R2-R5 (aşağıda).

---

## 7. İzleme Sorgusu (Watch Query) İyileştirme Önerileri

Kullanıcının gözle-tarama sorgusunu sertleştirmek için:

1. **Verdict join'i:** `qa-artifacts/round6/verdicts/` çıktısını bir geçici tabloya yükleyip (ta_code çiftleri) ana sorguya join et → yalnızca DIFFERENT işaretli satırları göster. Manuel taramayı 2.925 → ~300 satıra indirir.
2. **Severity sıralaması:** `ORDER BY` ile (a) match_type SUFFIX_FUZZY önce, (b) match_score DESC (yüksek skorlu hatalar = sistemin en emin yanılgıları), (c) country_count DESC.
3. **Leak flag'i kolonu:** `count(DISTINCT country_code) OVER (PARTITION BY master_code) AS country_leak_flag` — leak'leri her satırda görünür yap (şu an 0 ama gerileme tespiti için).
4. **Orphan + duplike NEW_MASTER görünürlüğü:** Watch query `match_type != 'NEW_MASTER'` filtresi 727 duplike-NEW_MASTER birleşmesini gizliyor. Ayrı bir `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` bloğu ekle.
5. **YPFB/fatura-satırı maskesi:** `WHERE name !~ 'FAC-[0-9]+|REF-[0-9]+|COMPL[ :-]'` ile fatura-satırı gürültüsünü tarama dışına al (ayrı veri-kalitesi kuyruğuna yönlendir).
6. **UUID join netliği:** Self-join'i `v.master_code = m.master_code` (UUID) üzerinden yap; `ta_code` ile master_code'u asla eşitleme.

---

## 8. Önceliklendirilmiş Aksiyon Listesi

| # | Öncelik | Aksiyon | Dosya / Fonksiyon | Beklenen etki |
|---|---------|---------|-------------------|---------------|
| **A1** | 🔴 P0 | PE reindex + eşleştirme koş | `es_manager.py --force`, `main_processor.py` (`COUNTRY_CODE_FILTER="pe"`) | PE'de 0 → gerçek eşleşmeler; sim=1.0 dup'lar kapanır |
| **A2** | 🔴 HIGH | SUFFIX_FUZZY'ye `_core_coverage_filter` ekle | `es_queries.py` `SUFFIX_FUZZY()` "must" | SUFFIX_FUZZY FP −%79.8 (89→18); precision %65→~%93 |
| **A3** | 🔴 HIGH | Tam rematch (gate zaten aktif) | `main_processor.py` | FUZZY_PHRASE/TOKEN_COVERAGE subset FP'leri kapanır (filtre ilk kez devreye girer) |
| **A4** | 🟠 MED | Token-tekrarı normalizasyonu | `es_ingest.py` Painless (ardışık yinelenen token dedup) | `RICARD RICARD`, `ADIDAS ADIDAS`, `COTO CENTRO CENTRO` FP'leri |
| **A5** | 🟠 MED | Geo-token kesişim kontrolü (FUZZY_PHRASE) | `_core_coverage_filter` genişlet: ≥1 non-geo sorgu token'ı master'da olmalı | `GM BRASIL`/`GM ARGENTINA` tipi 5 FP |
| **A6** | 🟠 MED | Adres/CUIT input_filter guard | `input_filter.py` (uzunluk + sokak-no/CUIT pattern) | `AV ALICIA MOREAU...`, `INC S.A. CUYO 3367` |
| **A7** | 🟠 MED | YPFB/TLP fatura-satırı veri kalitesi | input_filter veya kaynak ETL (`FAC-/REF-/COMPL` pattern) | 589 sahte AR NEW_MASTER + 172k sahte under-merge adayı |
| **A8** | 🟡 LOW | `INTERNACIONAL,INTERNATIONAL` synonym | `synonyms_data/common.json` | 1 FP + cross-dil recall |
| **A9** | 🟡 LOW | Duplike NEW_MASTER demote (727) | AUTO_DEDUP sonrası match_type güncelle | Denetim kör noktası kapanır |
| **A10** | 🟡 LOW | AR noktalama/boşluk normalizasyonu (under-merge) | `es_manager.py` analyzer | 106 AR kaçırılmış birleşme |

> **Tüm öneriler ES-side / pipeline düzeyinde.** Python tarafında RapidFuzz/Levenshtein önerilmedi (CLAUDE.md kuralı).

---

## Ek: Metodoloji Notu — Batch-01 Kontaminasyonu

İlk turda `overmerge_batch_01` denetçisi `low_sim` gibi **mekanik gerekçeler** üretti (127/319 DIFFERENT) — isim-içeriği yerine sayısal benzerlik uydurmuş. Bu batch karantinaya alındı (`.REJECTED-low_sim.jsonl`) ve "Bash/script/similarity KULLANMA, isim anlamına bak" kuralıyla yeniden koşturuldu (sonuç: 23 DIFFERENT). Final agregasyon temiz veriyle yapıldı. Diğer 27 batch + 6 under-merge batch'i ilk turda doğru çalıştı; satır-sayısı doğrulaması (in==out) tüm batch'lerde geçti.
