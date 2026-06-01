# Eşleştirme Kalitesi QA Analizi — Tasarım Dokümanı

**Tarih:** 2026-06-01
**Konu:** PostgreSQL üzerinde manuel/yarı-otomatik analizle eşleştirme sonuçlarının kalite denetimi, yanlış eşleşme (over-merge) ve bölünme (split / under-merge) tespiti, ve sorumlu ES stage/query'leri için optimizasyon önerileri + onaylı TDD düzeltmeleri.

---

## 1. Amaç ve Kapsam

Firma eşleştirme sisteminin ürettiği sonuçları (`p7_firms_v2` + `match_stages_log` + `match_audit`) analiz ederek iki hata sınıfını tespit etmek:

- **Over-merge (false positive):** Birbirinden farklı iki+ firma yanlışlıkla **aynı** `master_code` altında toplanmış.
- **Split (under-merge):** Aynı firma, **farklı** `master_code`'lara dağılmış (birleşmesi gerekirken birleşmemiş).

Her tespit için sorumlu stage/query'yi belirleyip somut optimizasyon önerisi sunmak; kullanıcı onayı sonrası ilgili düzeltmeyi `es_queries.py`/`config.py` üzerinde **TDD ile** uygulamak.

### Kapsam Kararları (kullanıcı onaylı)
- **Veri:** Mevcut DB verisi olduğu gibi analiz edilir (~62.950 işlenmiş kayıt, tek ülke=MX). Yeniden tam koşu yapılmaz.
- **Çıktı:** Markdown rapor **+** onaylanan optimizasyonların TDD ile uygulanması.
- **Tespit yaklaşımı:** Hibrit — SQL ile aday üret, düzeltme yapılacak kritik vakalarda ES'e geri sorgulayarak kök-nedeni birebir doğrula.
- **Uzantı yok:** `pg_trgm`/`fuzzystrmatch` KURULMAZ. Tespit, PostgreSQL yerleşik dizi/token fonksiyonları (`string_to_array`, `unnest`, küme kesişimi) ile yapılır — pipeline'ın "token coverage" mantığıyla hizalı.
- **ES:** Ayakta; TDD doğrulamaları ES'e karşı çalıştırılabilir.

### Kapsam Dışı
- `p7_firms_v2` veri içeriğinin değiştirilmesi (analiz salt-okunur). Yalnızca onaylı kod düzeltmeleri dosyalara dokunur.
- Yeni stage tasarımı; sadece mevcut stage/query optimizasyonu.
- Çoklu ülke senaryosu (veri tek ülke).

---

## 2. Mevcut Durum Gözlemleri (keşif bulguları)

- 530.876 toplam kayıt, **62.950** işlenmiş (`master_code` dolu), 58.099 farklı master → düşük konsolidasyon (erken-koşu etkisi + olası over/under-merge karışımı).
- Grup boyutu dağılımı: 1 master'da **49 üye**, ardından 11/9/8... ; 3.371 adet 2'li, 54.133 tekil.
- `match_type` dağılımında **legacy residue** var: `EXACT_FUZZY`, `ADDRESS_CLEAN_MATCH`, `SUBSET_MATCH` — güncel `config.STAGES`'te yok. Rapor bunları ayrı işaretler.
- **Somut over-merge bulgusu:** 49 üyeli master'ın kökü çöp bir kayıt (tam gümrük beyanname satırı). 48 farklı firma (IGSA, WITTE, AUDI MEXICO, KOHLER DE MEXICO...) `PHONETIC_MATCH` ile bağlanmış. Ortak payda: hepsinde `S.A. DE C.V.` yasal eki → **fonetik kodlama paylaşılan yasal ek üzerinden çakışıyor** hipotezi.

---

## 3. Mimari — 5 Katman

```
p7_firms_v2 ──┐
match_stages_log ──┼─▶ [1] Hazırlık (core-name normalize CTE/VIEW, salt-okunur)
match_audit ──┘        │
                       ├─▶ [2] Over-merge dedektörü (master-içi token-örtüşme düşük)
                       ├─▶ [3] Split dedektörü (master-arası çekirdek-isim ~özdeş)
                       ├─▶ [4] Attribution (match_type + stage trace → sorumlu stage)
                       └─▶ [5] Manuel triyaj + rapor → (onay) → TDD düzeltme
```

### [1] Hazırlık — Çekirdek İsim Normalizasyonu
- Salt-okunur SQL CTE/`VIEW`: ham `name` → lower + yasal ek temizliği (`S.A. DE C.V.`, `S. DE R.L.`, `S.A.S.` vb.) + noktalama sadeleştirme + token dizisine ayırma.
- Yasal ek listesi `config.SUFFIX_TYPO_MAP` ve `synonyms_data/MX*` referans alınarak türetilir (pipeline ile tutarlılık). Synonym JSON dosyaları DEĞİŞTİRİLMEZ.
- Çıktı: `(id, master_code, country_code, raw_name, core_tokens text[], match_type)`.

### [2] Over-merge Dedektörü (false positive)
- `master_code`'a göre grupla (üye sayısı ≥ 2).
- Her grup için üyelerin `core_tokens` kümeleri arasında **token-örtüşme metriği**: grup-içi medyan/min Jaccard benzeri oran (kesişim / birleşim) yerleşik `unnest`+kümeleme ile.
- **Şüpheli** = düşük örtüşme (eşik kalibre edilir, başlangıç ~0.3) VE/VEYA aşırı uzun kök (çöp kayıt sinyali).
- Sıralama anahtarı: `grup_boyutu × (1 − örtüşme) × stage_riski`. Dominant `match_type` raporlanır (fuzzy stage'ler — PHONETIC/NGRAM/SUFFIX_FUZZY — öncelikli şüpheli).

### [3] Split Dedektörü (under-merge)
- Her master için bir **temsilci çekirdek isim** (en sık/en kısa core_tokens imzası).
- Aynı `country_code` içinde, çekirdek-token imzası **özdeş veya tek-token farklı** olan farklı `master_code` çiftlerini bul (self-join + token imza eşitliği; tam fuzzy gerektirmez).
- Sıralama: etkilenen kayıt sayısı.

### [4] Attribution
- Şüpheli her küme `match_type` ile, gerekirse `match_stages_log` trace'i ile sorumlu stage'e bağlanır.
- Çıktı tablosu: `{küme, hata_tipi, sorumlu_stage, örnek isimler, etki}`.

### [5] Manuel Triyaj + Rapor
- Her dedektörün top-N (örn. 30) kümesini elle gözden geçir, `true_positive`/`false_alarm` etiketle (ground-truth yok → manuel onay zorunlu).
- Rapor: `docs/audits/2026-06-01-match-quality-qa-findings.md`
  - Yönetici özeti + metrikler
  - Over-merge bulguları (somut örnekler, sorumlu stage, kök-neden)
  - Split bulguları (somut örnekler, kök-neden)
  - Stage-bazlı optimizasyon önerileri (öncelik sırasıyla)
  - Legacy residue notu

---

## 4. Veri Akışı

`SELECT` (salt-okunur) → normalize CTE → dedektör sorguları → şüpheli küme listesi (konsola/CSV) → manuel triyaj → stage kök-neden → optimizasyon önerisi → **kullanıcı onayı** → TDD düzeltme döngüsü.

Analiz scriptleri `analysis/` (veya `qa/`) altında izole, salt-okunur Python+SQL olarak durur; `main_processor`/`es_*` üretim modüllerine dokunmaz.

---

## 5. Düzeltme & Doğrulama (TDD)

Onaylanan her kök-neden için:
1. **RED:** Başarısız test yaz. Örnekler:
   - Over-merge: "Şu çöp kök + 48 firma örneğinde PHONETIC_MATCH query'si bu çiftleri eşleştirmemeli" (ES'e karşı veya query DSL doğrulaması).
   - Split: "Şu iki özdeş-çekirdek firma ilgili stage'de eşleşmeli."
2. **Doğrula:** Spesifik vakayı ES'e geri sorgulayarak hipotezi kanıtla (hibrit yaklaşımın B ayağı).
3. **GREEN:** Minimal `es_queries.py`/`config.py` değişikliği uygula.
4. **Refactor + izole commit.** Her düzeltme ayrı commit; her biri öncesi/sonrası etki raporlanır.

### PHONETIC_MATCH için aday optimizasyonlar (rapora girecek, onaya tabi)
- (a) Fonetik kodlamadan önce yasal ekleri strip et (ingest/analyzer hizası).
- (b) `operator:and` + `minimum_should_match` sıkılaştırma.
- (c) Tek-token / çok-kısa çekirdek isimde PHONETIC_MATCH'i atla.
- (d) `config.STAGES` PHONETIC_MATCH `min_score` yükselt.

---

## 6. Hata Yönetimi & Riskler

- **Salt-okunur garanti:** Analiz fazı yalnızca `SELECT`; yanlışlıkla yazımı önlemek için ayrı read-only akış.
- **Eşik kalibrasyonu:** Token-örtüşme eşikleri ilk N örnek elle doğrulanarak kalibre edilir (false-alarm/missed dengesi).
- **Legacy karışım riski:** Eski match_type'lar güncel stage önerileriyle karıştırılmaz; raporda ayrı bölüm.
- **ES bağımlılığı:** TDD doğrulaması ES'e bağlı; ES erişilemezse fix "öneri" statüsünde bekletilir (şu an ayakta).
- **Country hard-filter:** Tek ülke (MX) olsa da split dedektörü `country_code` sınırında kalır (CLAUDE.md country hard-filter ilkesi).

---

## 7. Başarı Kriterleri

- En az ilk N (örn. 30) over-merge ve N split adayı tespit edilip elle etiketlenmiş.
- 49-üyeli PHONETIC_MATCH over-merge vakası kök-nedeniyle raporlanmış.
- Her onaylı düzeltme için RED→GREEN test mevcut, mevcut `pytest` paketi kırılmamış.
- Rapor `docs/audits/` altında, optimizasyonlar öncelik sırasıyla listelenmiş.
