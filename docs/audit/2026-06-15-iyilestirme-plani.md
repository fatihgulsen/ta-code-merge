# Eşleştirme Kalitesi İyileştirme Planı (`p7_firms_v2_ar_pe`)

**Tarih:** 2026-06-15
**Dayanak:** Round-5/6/7 denetimleri + geo-mıknatıs kök-neden analizi + kullanıcı kararı (SUFFIX_FUZZY kapatıldı).
**Amaç:** "Tam olarak hangi iyileştirmeleri, hangi sırayla, nasıl yapmalıyız?" sorusunu somut, dosya/fonksiyon referanslı, recall-etkisi ölçülmüş ve uygulanabilir bir plana dökmek.

---

## 0. Mevcut Durum (başlangıç noktası)

| Konu | Durum |
|------|-------|
| Aktif stage'ler | CANONICAL_EXACT → STRIPPED_EXACT → FUZZY_PHRASE → TOKEN_COVERAGE |
| Devre dışı | SUFFIX_FUZZY *(bugün kapatıldı)*, PHONETIC_MATCH, NGRAM_MATCH |
| AR over-merge precision (R7, doğrulanmış) | **%93.4** (STRIPPED %96.2 / FUZZY %92.4 / TOKEN %93.6) |
| PE | **Tamamen kırık** — 0 variant eşleşmesi (analyzer index'te yok) |
| Rematch tamamlanma | AR %35, PE %40 (yarıda durmuş) |
| COUNTRY_LEAK | 0 (hard filter sağlam) |
| Index | `pe.json` eklenmeden kurulmuş, `--force` reindex hiç yapılmamış |

**İki yapısal gerçek planı yönetir:**
1. **Bir reindex zaten zorunlu** (PE analyzer + stale-AR + yarım rematch). Analyzer-seviyesi tüm düzeltmeler bu TEK pencerede bedavaya gelir.
2. **Kalan over-merge hatalarının kök neni "ayırt edici olmayan token'ın çekirdek sanılması"** — geo token (argentina), tekrar eden token (RICARD RICARD), ya da başka markanın alt-kümesi. Hepsi ES analyzer / query-DSL seviyesinde, Python'suz çözülür.

---

## 1. İyileştirmeler (önceliklendirilmiş)

### 🔴 İ1 — Geo-token stripped analyzer'a eklensin (EN YÜKSEK ETKİ)

**Problem:** `SAL ARGENTINA S.R.L.` → `R B ARGENTINA`, `ARGENTINA`, `UNLIMITED ARGENTINA`, `AC ARGENTINA SA`… hepsi STRIPPED_EXACT ile birleşmiş (canlı kanıt: hepsi `['argentina']` tek token'a iniyor).

**Kök neden:** `stripped_search_analyzer_*` zincirinde **geo_stopwords yok** (es_manager.py:173 ve :186). Coğrafi "argentina" sıyrılmıyor; ayırt edici kelimeler (SAL/AC/UNLIMITED + tek-harf) sıyrılınca geriye sadece geo token kalıyor → token_count=1 mıknatısı (index'te 34.178 adet count=1 girişi). `_has_distinctive_core` gate yakalayamıyor çünkü "argentina" 9-harfli alfabetik → ayırt edici sanıyor.

**Fix (es_manager.py):**
```python
# (a) geo_tokens_global / geo_stopwords_global tanımını (şu an :189-199)
#     stripped-analyzer döngüsünden ÖNCE'ye taşı (~satır 157).
# (b) Per-country stripped analyzer (:173):
"filter": base_clean_filters + [filter_name, "legal_fragment_stop", "geo_stopwords_global"]
# (c) Global stripped analyzer (:186):
"filter": base_clean_filters + ["generic_stopwords_global", "legal_fragment_stop", "geo_stopwords_global"]
```

**Etki:** `SAL ARGENTINA` → `[]` → boş çekirdek → `_has_distinctive_core`=False → NEW_MASTER. Geo-only mıknatıs ölür. Bu, R7'deki dominant "geo-substitution + geo-only" hata ailesini STRIPPED_EXACT/FUZZY/TOKEN'ın hepsinde aynı anda kapatır.

**Recall etkisi:** NÖTR. `AUDI ARGENTINA` → `['audi']` → gerçek AUDI kayıtlarıyla eşleşmeye devam (geo zaten ayırt edici değil). Sadece *salt-coğrafi* çöp NEW_MASTER olur — ki olması gereken.

**Maliyet:** `--force` reindex (İ6 ile birlikte). Aynı normalizasyon `fingerprint_analyzer` + `clean_analyzer`'da zaten var → tutarlılık artar.

**Risk notu:** Bu, hafızadaki **P0-D** (bilinen ama hiç uygulanmamış) düzeltmesi. Daha önce sadece fingerprint/canonical'a uygulanmıştı.

---

### 🔴 İ2 — PE analyzer'larını kur (PE'yi sıfırdan açar)

**Problem:** PE'de 0 eşleşme; tüm PE kayıtları NEW_MASTER. sim=1.0 birebir dup'lar (`3M PERU S.A.` ×2) bile ayrı.

**Kök neden (canlı kanıt):** `_analyze {analyzer: stripped_search_analyzer_pe}` → **400 "failed to find analyzer"**. Index'te `_ar/_mx/_es` var, `_pe` yok. `pe.json` diskte (10 Haz), `get_all_country_codes()` PE döndürüyor, `es_manager.py:161` her ülke için analyzer üretiyor — ama index pe.json eklenmeden kurulmuş. Her PE kaydı 2-5. stage'lerde ES-400 → sessiz NEW_MASTER.

**Fix:** Kod değişikliği GEREKMEZ — sadece `python es_manager.py --force`. Yeni index PE analyzer'larını otomatik üretir.

**Etki:** PE eşleştirmesi sıfırdan çalışır. PE precision/recall ancak bundan sonra ölçülebilir.

**Maliyet:** Reindex (İ6 ile aynı pencere).

---

### 🟠 İ3 — Tekrar eden token temizliği (TOKEN_COVERAGE/STRIPPED'i iyileştirir)

**Problem:** `PERNOD RICARD ARGENTINA` ⇸ `RICARD RICARD ARGENTINA` (score 27), `ADIDAS ARGENTINA` ⇸ `ADIDAS ADIDAS ARGENTINA`, `COTO CENTRO INTEGRAL` ⇸ `COTO CENTRO CENTRO`.

**Kök neden:** Kaynak veride ardışık yinelenen token coverage'ı/skoru şişiriyor; `RICARD RICARD` ile `PERNOD RICARD` token kümesi yapay olarak yakınlaşıyor.

**Fix:** `es_ingest.py` Painless pipeline'ına **ardışık-yinelenen-token dedup** ekle (analyzer-side; `unique` token filter veya Painless'te ardışık-tekrar atma). `variations`/`variations_stripped` üretiminde uygulanır.

**Etki:** Token-tekrar bug'lı over-merge'ler kapanır; fingerprint kalitesi de artar.

**Recall etkisi:** Nötr (gerçek isimler ardışık aynı token taşımaz). **Maliyet:** Reindex (İ6 penceresi).

---

### 🟠 İ4 — Geo-token kesişim guard'ı (eşit-token over-merge)

**Problem:** `GM BRASIL` ⇸ `GM DE ARGENTINA`, `VOLKSWAGEN OF AMERICA` ⇸ `VOLKSWAGEN ARGENTINA`, `VANGUARD NZ` ⇸ `VANGUARD ARGENTINA`. İ1 bunları çözmez çünkü token sayısı eşit (geo-strip sonrası `['gm']`==`['gm']` → yine eşleşir; aslında bunlar farklı ülke iştirakleri).

**Karar gerekiyor:** Bu çiftler **gerçekten farklı firma mı, yoksa aynı global markanın yerel iştiraki mi?** İş kuralına bağlı:
- "Farklı tüzel kişilik" isteniyorsa → İ4 gerekli.
- "Aynı marka = aynı master" kabul ediliyorsa → İ1 sonrası bunlar zaten doğru (GM = GM), İ4 GEREKSİZ.

**Fix (eğer ayrı isteniyorsa):** `_core_coverage_filter`'ı genişlet — eşit token sayısında, **en az bir non-geo sorgu token'ı master varyantında da bulunmalı** + geo token'lar eşleşme öncesi ayrı tutulmalı. JSON-türevli geo listesi, hardcode yok.

**Öneri:** İ1 + reindex sonrası bu çiftleri yeniden ölç; **gerçek hacim küçükse ertele.** Önce iş kuralını netleştir (parent/subsidiary politikası — P1-B ile aynı soru).

---

### 🟠 İ5 — Adres/CUIT/slash-multi-entity input guard

**Problem:** `AV ALICIA MOREAU DE JUSTO 1720` (saf adres), `INC S.A. CUYO 3367 - MARTINEZ` (adres artığı), `GRI-ALLESET INC/DUPONT SPECIALTY` (slash ile iki ayrı tüzel kişilik) eşleştirmeye giriyor.

**Fix (`input_filter.py`):** (a) uzunluk + sokak-no/CUIT pattern guard; (b) slash (`/`) ile birden çok tüzel kişilik içeren isimleri ya böl ya EXCLUDED. **Şahıs-adı filtresi YOK** (R4'te reddedildi — persona física meşru firma olabilir).

**Etki:** Boundary-geçerliliği; over-merge kaynağı azalır. **Maliyet:** Kod + reindex değil (input aşaması), ama rematch'te etkili. **Recall:** Nötr (bunlar firma adı değil).

---

### 🟡 İ6 — Tek reindex + tam rematch (ÇATI — İ1/İ2/İ3'ü canlıya alır)

**Sıra:**
```bash
python es_ingest.py        # İ3 pipeline güncellemesi
python es_manager.py --force   # İ1 geo-stop + İ2 PE analyzer + temiz index
python main_processor.py   # tam rematch (%35-40 → %100)
```
**Sonra:** QA harness'i tekrar koş (Round-8) — İ1-İ5'in gerçek etkisini ÖLÇ. Precision/recall ancak %100 rematch sonrası geçerli.

---

### 🟡 İ7 — İzleme & hijyen (düşük öncelik)

- **830 duplike NEW_MASTER:** AUTO_DEDUP sonrası birleştirilen anchor'ların `match_type`'ını demote et; watch query'ye `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` ekle (kör nokta kapansın).
- **Watch query UUID join:** Self-join `v.master_code = m.master_code` (UUID) üzerinden; `ta_code==master_code` VARSAYMA.
- **`updated_at` güvenilmez:** "Eşleştirme ne zaman koştu" sinyali olarak kullanma (yeni satırlar eski timestamp taşıyor); davranışsal/`match_details` kanıtı kullan.

---

## 2. Sıralama Özeti

| Aşama | İş | Tip | Reindex? |
|------|-----|-----|----------|
| **A. Kod (reindex öncesi)** | İ1 geo-stop (es_manager), İ3 token-dedup (es_ingest), İ5 input guard (input_filter) | Kod + test (TDD) | — |
| **B. Tek reindex penceresi (İ6)** | `es_ingest` → `es_manager --force` → `main_processor` | Çalıştırma | ✓ (İ1+İ2+İ3 burada canlıya gelir) |
| **C. Reindex sonrası ölçüm** | Round-8 QA (haiku census + adversarial verify), İ4 kararı, İ7 hijyen | Denetim | — |

> **Kritik içgörü:** İ1, İ2, İ3 (ve istenirse İ5) **tek bir reindex'te birlikte** devreye girer. Ayrı ayrı reindex YAPMA — hepsini A'da kodla, B'de tek seferde uygula.

---

## 3. Beklenen Sonuç (tahmin)

| Metrik | Şimdi | İ1+İ2+İ3+İ6 sonrası (tahmin) |
|--------|------:|------------------------------:|
| AR over-merge precision | %93.4 | **~%96-97** (geo-mıknatıs + token-tekrar kapanır) |
| PE | ölü | **çalışır** (precision ilk kez ölçülür) |
| SUFFIX_FUZZY kaynaklı hata | kapatıldı | yok (devre dışı) |
| COUNTRY_LEAK | 0 | 0 (korunur) |

%100 ulaşılamaz (parent/subsidiary + truncation belirsizliği → insan denetimi `dedup_reviewer`). Hedef: kalan hatayı iş-kuralı kararına (İ4) ve insan-denetimine indirgemek.

---

## 4. Doğrulama Planı (her kod değişikliği için TDD)

1. **İ1 golden:** `SAL ARGENTINA SRL`/`R B ARGENTINA`/`UNLIMITED ARGENTINA` → reindex sonrası `_analyze` ile `[]`; `AUDI ARGENTINA` → `['audi']` (recall korunur). `live_probe.py`'ye ekle.
2. **İ3 golden:** `RICARD RICARD` → tek `ricard`; `PERNOD RICARD` ile eşleşmemeli.
3. **İ2:** reindex sonrası `_analyze {stripped_search_analyzer_pe}` 200 dönmeli; PE örnek eşleşmeleri üretilmeli.
4. **Genel:** `pytest` yeşil (şu an 203 passed); Round-8 QA ile before/after precision.

---

## Ek: Bu Oturumda Uygulanan
- **SUFFIX_FUZZY devre dışı** (config.py STAGES `enabled:False`). Gerekçe: R7 doğrulanmış %68 precision (en düşük), kazanımları asıl işi değil subset over-merge. 203 test geçti. Diğer tüm öneriler (İ1-İ7) **uygulanmadı — onay bekliyor.**
