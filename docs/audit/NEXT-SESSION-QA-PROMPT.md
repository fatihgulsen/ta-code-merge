# Yeni Session Prompt — Rematch Sonrası QA: Önce/Sonra + NEW_MASTER Recall Denetimi

> Bu dosyanın **aşağıdaki "PROMPT" bölümünü** kopyalayıp yeni bir Claude Code
> session'ına yapıştır. Rematch (`python main_processor.py`) BİTTİKTEN sonra çalıştır.

---

## PROMPT (kopyala ↓)

# GÖREV: Rematch Sonrası Eşleştirme Kalite Denetimi (LLM-as-Judge) — Önce/Sonra + NEW_MASTER Recall

Sen bir firma-eşleştirme QA denetçisisin. `feat/phonetic-overmerge-guard` branch'indeki
düzeltmeler (Faz 1-3) uygulandı, ES index'i yeni analyzer'larla **reindex** edildi ve
`main_processor.py` ile **yeniden eşleştirme (rematch)** koşuldu. Görevin: sonuçların
kalitesini ilk denetimle (`docs/audit/2026-06-02-llm-judge-match-quality.md`)
**karşılaştırmalı** ölçmek VE bu sefer **NEW_MASTER kayıtlarını** da denetleyerek
"eşleşmesi gereken eşleşti mi?" (kaçırılan eşleşme / under-merge) sorusunu yanıtlamak.

Bu bir LLM-yargı görevidir: firma çiftlerinin/gruplarının AYNI ticari firma olup
olmadığına SEN (model) karar vereceksin.

## KATI KURALLAR
- **Python'da fuzzy/Levenshtein YASAK.** Benzerliği SEN değerlendireceksin. Token-set
  (normalize_core / Jaccard) işlemleri yalnızca "incelenecek aday havuzu" ön-elemesi
  içindir — KARAR senindir, koda string-mesafesi hesaplatma.
- **Python'da eşleşme DOĞRULAMASI yapma.** Üretim mantığı tamamen ES tarafında; sen
  sadece PG'den OKU ve yargı ver.
- **country_code HARD FILTER.** Farklı country_code'lu kayıtlar ASLA aynı firma sayılamaz.
  Bir grupta karışık ülke görürsen otomatik COUNTRY_LEAK işaretle. (Veri büyük olasılıkla
  tümü MX — o durumda COUNTRY_LEAK yapısal olarak imkânsız, raporda belirt.)
- **Salt-okunur:** Bu session'da `p7_firms_v2`'ye YAZMA (sadece SELECT).
- **Hardcoded ülke token'ı yok:** ülke-özel her şey `synonyms_data/` JSON'larından türetilir.

## VERİ KAYNAĞI
- DB: `market_calculus` (PostgreSQL, localhost:5432) — `config.DB_CONFIG`.
- Tablo: `p7_firms_v2`. Sütunlar: `id, name, country_code, master_code, match_type,
  match_score, match_details`.
- **dbhub MCP genelde DOWN** (npx ENOENT) → `psycopg2` + `config.DB_CONFIG` ile bağlan,
  parametrik sorgu kullan. (Önce dbhub'ı dene; hata verirse psycopg2'ye düş.)
- Repo modüllerini import etmek için `PYTHONPATH=C:/All-project/ta-code-merge` ile çalıştır
  ve Windows'ta `PYTHONUTF8=1` ver.

## MEVCUT ARAÇLAR (yeniden kullan)
- `analysis/detectors.py` — `load_matched_rows`, `detect_over_merge`, `detect_splits`
  (salt-okunur, token-set ön-eleme; KARAR LLM'in).
- `analysis/live_probe.py` — golden-set canlı probe (ES query/analyzer regresyonu).
- `core_name.normalize_core(name, country, drop_geo=True)` — çekirdek token üretimi.
- Önceki QA betikleri (referans): `C:/tmp/qa_sample.py`, `C:/tmp/make_batches.py`,
  `C:/tmp/aggregate.py` (silinmişse, mantığını tekrar üret).
- Önceki rapor (karşılaştırma temeli): `docs/audit/2026-06-02-llm-judge-match-quality.md`.
  Oradaki temel sayılar: over-merge şüphelilerinin %76,6'sı (866/1130) gerçek over-merge;
  PHONETIC üye over-merge %80, NGRAM %95, EXACT_FUZZY %62, TOKEN_COVERAGE %45; split
  adaylarının %72'si (346/480) gerçek under-merge (~1228 kayıt). Kontrolün %18'i over-merge.

## YÖNTEM

### ADIM 0 — Rematch doğrulama + temel metrikler (önce/sonra)
1. `p7_firms_v2`'de `match_type` dağılımı, toplam satır, distinct `master_code`,
   master grup-boyutu dağılımı (1, 2, 3-5, 6+, max), ülke dağılımını çıkar.
2. Önceki run ile karşılaştır (önce: 530.876 satır; 68.600 işlenmiş; NEW_MASTER 63.206;
   PHONETIC 1111; NGRAM 146; SUFFIX_FUZZY 1567; TOKEN_COVERAGE 540...). Bu rematch'in
   KAÇ satır işlediğini ve NEW_MASTER oranının nasıl değiştiğini not et.
   - **Beklenti:** over-merge fix'leri sonrası NEW_MASTER oranı ARTMALI (daha az birleşme),
     master grup boyutları KÜÇÜLMELİ, 52-üyeli magnet master'lar KAYBOLMALI.

### ADIM 1 — Aday havuzları (kod tarafı = SADECE veri çekme/ön-eleme)
A) **OVER-MERGE adayları:** üyesi >1 olan master grupları; özellikle kırılgan stage'ler
   (PHONETIC, NGRAM, TOKEN_COVERAGE, SUFFIX_FUZZY, EXACT_FUZZY). `detect_over_merge`
   (düşük token-örtüşme) ile sırala. Her grup: `(master_code, culprit_stage,
   [id,name,country,match_type] üyeleri)`.
B) **SPLIT / UNDER-MERGE adayları:** `detect_splits` — aynı country + aynı/yakın çekirdek
   imza, farklı master. (Bu, matched master'lar arası split.)
C) **★ YENİ — NEW_MASTER RECALL havuzu (asıl yeni odak):**
   `match_type='NEW_MASTER'` (yani hiçbir şeye eşleşmemiş, kendi master'ı olmuş) kayıtları
   al. Bunların "eşleşmesi gerekirken eşleşmedi mi" diye iki ön-eleme ile aday üret:
   - (c1) **Aynı çekirdek imza:** NEW_MASTER kaydının `normalize_core(name,country,drop_geo=True)`
     imzası, BAŞKA bir kaydın (NEW_MASTER ya da matched) imzasıyla aynı → "kaçırılmış olası
     eşleşme". (Bu, A'nın/B'nin yan ürünüdür ama burada NEW_MASTER'a ODAKLAN.)
   - (c2) **Yakın çekirdek (gevşek ön-eleme):** aynı country içinde ilk-1/ilk-2 çekirdek
     token'ı paylaşan ama farklı master'da olan NEW_MASTER'lar (truncation/typo kaçaklarını
     yakalamak için, örn. `VIBRACOUSTIC ... S.A. DE C.V.` vs `... S.A. DE CA`). Bu ön-eleme
     SADECE aday havuzu; benzerlik kararını LLM verecek.
   Her aday: `(country, çekirdek_imza, [id,name,master_code,match_type] üyeleri)`.

> Örnekleme dengesi: her havuzdan en az birkaç yüz aday tara; bütçe elverdikçe artır.
> NEW_MASTER recall havuzunu **bol tut** (asıl yeni soru bu). Truncation/abbreviation
> kalıplarına (S.A. DE CA, eksik kelime, kısaltma) özellikle odaklan.

### ADIM 2 — Yargılama (Haiku alt-ajanlar, 10'ar 10'ar, Workflow ile)
Adayları 10'luk batch'ler hâlinde Haiku subagent'lara dağıt (Workflow + schema ile yapısal
çıktı zorla). Her batch dosyasını bir Haiku oku, yargıla, sonucu JSON yaz (ilk session'daki
gibi: batch dosyaları + result dosyaları + aggregate). Sınıflandırma:
- Over-merge/control grubu için: `CORRECT` / `OVER_MERGE` / `COUNTRY_LEAK`
  (+ `bad_ids`, `culprit_stage`, kısa gerekçe).
- Split & **NEW_MASTER recall** grubu için: `SHOULD_MERGE` (aslında aynı firma, ayrı
  kalmış/eşleşmemiş) / `CORRECT_SEPARATE` (gerçekten farklı) (+ birleşmesi gereken `ids`,
  gerekçe). NEW_MASTER recall'da `SHOULD_MERGE` = **kaçırılan eşleşme (under-merge)**.

Mexican kuralları hatırlat (Haiku prompt'una koy): yasal ekler (S.A. DE C.V., S. DE R.L.,
S.A.P.I., INC, LLC) ve coğrafi MEXICO/MEXICANA AYIRT EDİCİ DEĞİL — ÇEKİRDEK marka adı
belirleyici. Örn. "AUDI MEXICO" ≠ "KOHLER DE MEXICO"; "VIBRACOUSTIC DE MEXICO S.A. DE C.V."
== "VIBRACOUSTIC DE MEXICO S.A. DE CA" (truncation, aynı firma).

### ADIM 3 — Toplulaştırma + ÖNCE/SONRA
- Tüm Haiku bulgularını birleştir. match_type × hata türü kırılımında oranları çıkar.
- **Karşılaştırma tablosu (2026-06-02 vs bugün):** over-merge oranı (genel + stage bazlı),
  control FP oranı, split SHOULD_MERGE oranı. Hangi stage düzeldi, hangisi hâlâ sorunlu?
- **★ NEW_MASTER recall metriği:** taranan NEW_MASTER adaylarının kaçı `SHOULD_MERGE`
  (= kaçırılmış eşleşme) çıktı? Hangi kalıplar (truncation/typo/abbreviation/word-order)?
  Bu, over-merge fix'lerinin recall'ı ne kadar düşürdüğünü (under-merge'e kaçış) gösterir.

### ADIM 4 — ES-tarafı iyileştirme önerileri (Faz 4/5 için)
Bulgulardan SOMUT, ES-tarafı (Python doğrulaması YOK) öneriler:
- Kalan over-merge üreten stage için query DSL/min_score/token_count ayarı.
- NEW_MASTER recall kayıplarını kapatacak öneriler: truncation/suffix-varyant birleştirme
  (örn. stripped core üzerinde gevşek stage), çöp girdi filtresi (Faz 4: #N/A, salt-sayı,
  >70 karakter gümrük dizesi), token_count band toleransı vb. Her öneri: gerekçe + kanıt
  (örnek vakalar) + hangi dosya/fonksiyon/parametre. KODU DEĞİŞTİRME, önce raporla.

## ÇIKTI
- `docs/audit/` altına tarihli markdown rapor:
  1. Rematch temel metrikleri + 2026-06-02 ile karşılaştırma.
  2. Hata tablosu (match_type × hata türü), önce/sonra.
  3. **NEW_MASTER recall bölümü:** kaçırılan eşleşme sayısı/oranı, örnek vakalar, kalıplar.
  4. Örnek vakalar (over-merge düzeldi mi; hangi split'ler kapandı/açık kaldı).
  5. Önceliklendirilmiş ES-iyileştirme önerileri (Faz 4/5).
- Sonunda 3-5 maddelik "en yüksek etki" özetini sun ve uygulamak için onay iste.

## NOTLAR
- Branch: `feat/phonetic-overmerge-guard` (Faz 1-3 + ES-side coverage commit'li).
- Hafıza dosyaları: `match-quality-fix-roadmap`, `no-hardcoded-country-tokens`,
  `no-python-verification-es-side` (proje memory'sinde).
- Eğer rematch tüm 530k'yı işlediyse sayılar ilk run'dan (68.6k) büyük olacak —
  karşılaştırmayı mümkün olduğunca ORAN bazlı yap, mutlak sayıyı da not et.

## PROMPT (kopyala ↑)
