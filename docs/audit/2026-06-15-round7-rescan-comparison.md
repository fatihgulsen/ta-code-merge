# Round-7 — Yeniden Tarama & R6 Karşılaştırması (`p7_firms_v2_ar_pe`)

**Tarih:** 2026-06-15
**Tetikleyici:** Kullanıcı "araya zaman girdi, eşleştirme ilerledi, iyice karşılaştır ve daha iyi öneri ver".
**Yöntem:** Güncel veriyle tam AR over-merge sayımı (40 haiku batch, 4.826 variant) + **adversarial verify pass** (5 sonnet agent, 551 DIFFERENT çiftin tamamı yeniden yargılandı) + PE kök-neden canlı doğrulama.
**Mod:** READ-ONLY. Kod/DB değişikliği YOK.

---

## 0. En Önemli Sonuç: Hiçbir Şey Düzeltilmemiş, Ama Veri Büyümüş

R6'dan (2026-06-12) bu yana **kod/index düzeyinde hiçbir aksiyon alınmamış.** Git log son commit `2206407` (R6 öncesi). Buna rağmen eşleştirme AR üzerinde ilerlemiş (daha çok kayıt işlenmiş), PE ise hâlâ tamamen kırık.

| Durum | R6 (06-12) | R7 (06-15) | Yorum |
|-------|-----------:|-----------:|-------|
| AR işlenmiş | — | **%35** (60k/171k) | rematch yarıda, durmuş görünüyor |
| PE işlenmiş | — | **%40** (91k/229k) ama **0 eşleşme** | tamamen NEW_MASTER |
| AR variant eşleşmesi | 2.925 | **4.826** | +%65 büyüme |
| PE variant eşleşmesi | 0 | **0** | hâlâ kırık |
| COUNTRY_LEAK | 0 | **0** | ✓ |
| Duplike NEW_MASTER | 727 | **830** | artıyor |

---

## 1. ★ Düzeltilmiş Precision (Adversarial Verify Sonrası)

R6'daki en büyük metodoloji zaafı: haiku denetçileri **tüzel-ek farkını** (S.A. vs S.R.L. vs SAC...) sistematik olarak "farklı firma" sanıyor. R7'de bu kez **551 DIFFERENT çiftinin tamamı** sonnet ile yeniden yargılandı (katı kural: suffix farkı = aynı firma). Sonuç: **551 ham DIFFERENT'in 227'si (≈%41) aslında doğru eşleşmeydi** (yanlış bayrak).

| match_type | Ham precision | **Düzeltilmiş precision** | Onaylanmış gerçek hata | Δ R6 |
|------------|--------------:|--------------------------:|----------------------:|------|
| STRIPPED_EXACT | %90.8 | **%96.2** | 138 | ↑ (R6 raw %92.5) |
| FUZZY_PHRASE | %87.3 | **%92.4** | 38 | ↑ |
| TOKEN_COVERAGE | %91.4 | **%93.6** | 17 | ↑ |
| **SUFFIX_FUZZY** | %65.2 | **%68.0** | **120** | ~aynı (R6 %65.4) |
| **TOPLAM** | %88.5 | **%93.4** | **313** | gerçek değer |

> **Doğru okuma:** Sistemin gerçek AR over-merge precision'ı **%93.4** (R6'nın ham %89.5'i verify yapılmadığı için precision'ı olduğundan düşük gösteriyordu). Ama **SUFFIX_FUZZY %68'de çakılı** — diğer tüm stage'ler %92+. Verify pass bile SUFFIX_FUZZY'yi kurtaramıyor çünkü hataları gerçek (tüzel-ek değil, subset).

---

## 2. ★ İki Kök Neden — Kanıtlanmış, Hâlâ Açık

### 2.1 PE TAMAMEN KIRIK — analyzer index'te yok (P0)

Canlı ES testi (kesin kanıt):
```
POST /living_companies_v1/_analyze {"analyzer":"stripped_search_analyzer_pe", ...}
→ 400 "failed to find analyzer [stripped_search_analyzer_pe]"
```
Index analyzer listesinde `_ar`, `_mx`, `_es`, `_ec`, `_us`... var ama **`_pe` YOK**. `synonyms_data/pe.json` diskte mevcut (10 Haz), `get_all_country_codes()` PE'yi döndürüyor, `es_manager.py:161` her ülke için analyzer üretiyor — **ama index pe.json eklenmeden kurulmuş ve bir daha `--force` ile yeniden kurulmamış.** Sonuç: her PE kaydı 2-5. stage'lerde ES-400 alıp sessizce NEW_MASTER oluyor.

**Kanıt-2 (davranışsal):** PE'de sim=1.0 birebir tam dup'lar bile ayrı master'da (önceki R6 bulgusu sürüyor); R7'de PE'de >0.9 benzerlikli 3.017 birleşmemiş çift var.

**Fix (kesin):** `python es_manager.py --force` → PE analyzer'ları kurulur → `main_processor.py` PE için yeniden koşar. Bu tek adım PE'yi sıfırdan açar. **Reindex zaten tüm tablo için gerekli (rematch %35-40'ta).**

### 2.2 SUFFIX_FUZZY'de `_core_coverage_filter` HÂLÂ yok

`es_queries.py` satır kontrolü: `_core_coverage_filter` yalnızca satır **351 (TOKEN_COVERAGE)** ve **391 (FUZZY_PHRASE)**'de çağrılıyor. `SUFFIX_FUZZY` (satır 268-315) çağırmıyor. R6'nın #1 önerisi (A2) **uygulanmamış**.

120 onaylanmış SUFFIX_FUZZY hatasının ezici çoğunluğu **subset/truncation** — token sayısı farklı, yani `_core_coverage_filter` bunları yakalardı:

| score | master → variant | hata tipi |
|------:|------------------|-----------|
| 17 | `SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA` ⇸ `SAMSUNG ELECTRONICS CO LTD` | subset |
| 17 | `BANCO MACRO BANSUD` ⇸ `BANCO MACRO` | ayırt edici token (BANSUD) kaybı |
| 19 | `BETTER WATER ARGENTINA` ⇸ `WATER ARGENTINA` | subset |
| 20 | `AGROPECUARIA RIO CHICO` ⇸ `RIO CHICO` | subset |
| 20 | `PB-L PRODUCTOS BIO-LOGICOS` ⇸ `PRODUCTOS BIO-LOGICOS` | prefix kaybı |
| 22 | `GRI-ALLESET INC/DUPONT SPECIALTY` ⇸ `DUPONT SPECIALTY` | slash multi-entity |
| 20 | `LEURU C/O LEVI STRAUSS` ⇸ `LEVI STRAUSS` | C/O acente |
| 17 | `PUMA SPORTS ARGENTINA` ⇸ `PUMA SPORTS LA` | geo-token (A-gate kapsamaz) |
| 17 | `ALL OVER SHIPPING` ⇸ `ALL IN SHIPPING` | eşit token, OVER≠IN (A-gate kapsamaz) |

**Tahmin:** core_coverage_filter SUFFIX_FUZZY'ye eklenirse 120 hatanın ~%80'i (subset/truncation/slash) kapanır → SUFFIX_FUZZY precision %68 → ~%93. Kalan ~%20 (geo-ikame + eşit-token-farklı-marka) için ayrı tedbir gerekir (§4 R3-R4).

---

## 3. Diğer Bulgular

- **COUNTRY_LEAK = 0** (4.826 variant, 0 ülke-sızıntısı) — hard filter sağlam. ✓
- **830 duplike NEW_MASTER** (153 AR + 597 PE; R6'da 727 idi). Aynı UUID'de >1 anchor (örn. `TLP S.A COMPL-XXXX` fatura varyantları). AUTO_DEDUP master_code'u birleştirip match_type'ı NEW_MASTER bırakıyor → over-merge watch query'sinin (join `match_type != NEW_MASTER`) **kör noktası**.
- **En yüksek skorlu gerçek hatalar** (stage geneli): token-tekrarı bug'ı sürüyor (`PERNOD RICARD` ⇸ `RICARD RICARD`, score 27), geo-ikame (`GM BRASIL` ⇸ `GM ARGENTINA`; `VANGUARD NZ` ⇸ `VANGUARD ARGENTINA`), subset (`APERAM STAINLESS SERVICES` ⇸ `...AND`).

---

## 4. ★ Daha İyi (Önceliklendirilmiş, Kök-Neden) Çözüm Önerileri

R6'da liste vardı; R7'de **sıralama + kanıt + tek-komut netliği** ile keskinleştirildi. İlk üçü tüm tabloyu düzeltir:

### 🔴 R1 — `es_manager.py --force` + tam rematch (TEK HAMLE, en yüksek etki)
Bu **üç** sorunu aynı anda çözer:
1. PE analyzer'larını kurar → PE eşleştirme sıfırdan açılır (şu an %0 → gerçek eşleşmeler).
2. Stale AR analyzer'ları tazeler (R5'teki `anonima sociedad`/`peru` artıkları).
3. Rematch'i %35-40'tan %100'e tamamlar (precision/recall ancak o zaman gerçek ölçülebilir).
- **Sıra:** `python es_ingest.py` → `python es_manager.py --force` → `python main_processor.py`. Süre uzun (~saatler); bittikten sonra QA tekrarlanmalı.
- **Risk:** Mevcut yarım sonuçlar silinip yeniden üretilir (zaten yarım, kayıp yok).

### 🔴 R2 — SUFFIX_FUZZY'ye `_core_coverage_filter` ekle (rematch ÖNCESİ kod fix)
`es_queries.py` `SUFFIX_FUZZY()` "must" listesine FUZZY_PHRASE/TOKEN_COVERAGE ile **simetrik** olarak:
```python
"must": [
    nested_match_phrase_on_variations_stripped,
    *_core_coverage_filter(es, name, country),   # ← EKLE
],
```
- **Etki:** 120 SUFFIX_FUZZY hatasının ~%80'i (subset/truncation/slash multi-entity) kapanır. SUFFIX_FUZZY %68 → ~%93.
- **Maliyet:** `variations_stripped.name.token_count` alanı mapping'de mevcut → ekstra reindex GEREKMEZ; R1 reindex'iyle birlikte canlı olur. Recall-nötr (FUZZY/TOKEN'da R4'te kanıtlandı).
- **TDD:** SAMSUNG/BANCO MACRO/BETTER WATER subset case'lerini test golden'a ekle.

### 🟠 R3 — Token-tekrarı temizliği (ingest Painless)
`PERNOD RICARD`⇸`RICARD RICARD`, `ADIDAS ADIDAS`, `COTO CENTRO CENTRO` — kaynak veride ardışık yinelenen token coverage'ı şişiriyor. `es_ingest.py` Painless'ine **ardışık-yinelenen-token dedup** ekle (analyzer-side, reindex'le birlikte). Hem over-merge hem fingerprint kalitesini düzeltir.

### 🟠 R4 — Geo-token kesişim guard'ı (eşit-token over-merge)
`PUMA ARGENTINA`⇸`PUMA LA`, `GM BRASIL`⇸`GM ARGENTINA`, `VANGUARD NZ`⇸`VANGUARD ARGENTINA` — token sayısı eşit olduğu için core_coverage yakalamaz. `_core_coverage_filter`'ı genişlet: **en az 1 non-geo sorgu token'ı master'da da bulunmalı** (terms filtresi; geo token listesi `geo_stopwords_global`'dan, JSON-türevli). Hardcode yok.

### 🟠 R5 — Adres/CUIT/slash-multi-entity input guard
`AV ALICIA MOREAU...`, `INC S.A. CUYO 3367`, `GRI-ALLESET INC/DUPONT...` (slash ile iki ayrı tüzel kişilik). `input_filter.py`'ye uzunluk + sokak-no/CUIT pattern + slash-multi-entity bölme. (Şahıs-adı filtresi YOK — R4'te reddedildi.)

### 🟡 R6 — 830 duplike NEW_MASTER demote + watch query düzelt
AUTO_DEDUP sonrası birleştirilen anchor'ların match_type'ını güncelle. Watch query'ye `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` bloğu ekle (kör nokta kapansın). Self-join UUID `master_code` üzerinden olmalı (`ta_code==master_code` varsayma).

---

## 5. R6 → R7 Özet Karşılaştırma

| Metrik | R6 | R7 | Not |
|--------|---:|---:|-----|
| AR precision (ham) | %89.5 | %88.5 | apples-to-apples ~sabit |
| AR precision (verify'lı) | ölçülmedi | **%93.4** | gerçek değer |
| SUFFIX_FUZZY | %65.4 | **%68.0** | düzelmemiş — fix uygulanmadı |
| PE durumu | 0 eşleşme | **0 eşleşme** | kök neden artık canlı kanıtlı |
| COUNTRY_LEAK | 0 | 0 | ✓ |
| Uygulanan fix | — | — | hiçbiri |

**Sonuç:** Sistem AR'da gerçekte %93.4 precision ile çalışıyor (sanıldığından iyi), ama (a) PE tamamen ölü, (b) SUFFIX_FUZZY zayıf halka, (c) rematch yarıda. Üçü de **R1 (reindex+rematch) + R2 (SUFFIX core-coverage)** ile çözülür — ikisi tek bir reindex penceresinde birlikte devreye girer.

---

## Ek: Metodoloji
- 40 haiku batch (tam sayım, satır-doğrulaması in==out tüm batch'lerde geçti).
- Adversarial verify: 5 sonnet, 551 DIFFERENT çiftin tamamı (227 düzeltildi → %41 yanlış-bayrak oranı, R5'teki Haiku tüzel-ek önyargısını bir kez daha doğruladı).
- PE/SUFFIX kök nedenleri canlı ES `_analyze` + `es_queries.py` satır kontrolü ile doğrulandı (timestamp'e güvenilmedi — R6'da updated_at'in matching'i yansıtmadığı görüldü).
- Artefaktlar: `qa-artifacts/round7/` (groups.jsonl, verdicts/, verify_out_*.jsonl, overmerge_corrected.json, diagnostics.json).
