# Firma Adı Eşleştirme — Literatür ve Endüstri Bulguları

**Tarih:** 2026-06-15  
**Kapsam:** Entity resolution / record linkage alanında akademi + endüstri; bizim ES+PG mimarimize uyarlanabilir teknikler.  
**Araştırma Yöntemi:** Exa web araması + akademik PDF erişimi (Papadakis et al. VLDB/ACM, Bailey et al. AEA, Splink, GraLMatch, UBlocker, vb.)

---

## 1. Blocking / Indexing Stratejileri (Aday Üretimi)

### Nedir?
Blocking, tam N×M karşılaştırması yerine "muhtemelen eşleşebilir" aday çiftleri üreten ön-filtreleme adımıdır. Doğru blocking olmadan recall mükemmel olsa da maliyet patlar; yanlış blocking olursa gerçek eşleşmeler hiç karşılaştırılmaz.

### Başlıca Yöntemler (Papadakis et al., VLDB 2016 + ACM CSUR 2020)

| Yöntem | Mantık | Avantaj | Dezavantaj |
|--------|--------|---------|------------|
| **Standard Blocking (StBl)** | Her token → ayrı blok, aynı token'a sahip kayıtlar aynı blokta | Hızlı, basit | Yazım hatası toleransı sıfır |
| **Sorted Neighborhood (SoNe/ESoNe)** | Anahtar sırala, sabit pencere kaydır | Hata toleranslı, küçük deviasyonları yakalar | Pencere boyutu (w) kritik; büyük w → çok karşılaştırma |
| **Q-Gram Blocking (QGBl / EQGBl)** | Token → karakter-düzeyinde n-gram, gram'a göre blokla | Yazım hatasına dayanıklı | Büyük veri kümelerinde çok büyük blok sayısı |
| **Canopy Clustering (CaCl/ECaCl)** | Jaccard/TF-IDF ile hızlı yakın-komşu, iki eşik (w1 giriş, w2 çıkış) | Örtüşen bloklar → yüksek recall | Eşik ayarı hassas |
| **Suffix Arrays (SuAr/ESuAr)** | Suffix-tabanlı paylaşım | Çok iyi recall | Yavaş, büyük indeks |
| **MFIBlocks** | Q-gram üzerinden MaxFrequent Itemset mining | Çok düşük gereksiz çift sayısı | Kısıtlayıcı anahtar → recall düşer |
| **UBlocker (2024, arXiv)** | Transformer tabanlı evrensel dense blocker; 1M tabloda contrastif öğrenme | Herhangi bir domain'de çalışır | Büyük ölçekte CPU/bellek maliyeti |
| **BlockingPy (2025)** | FAISS/HNSW/ANN grafik tabanlı blocking; GPU destekli | Milyonlarca kayıtta saniyeler içinde | Embedding altyapısı gerektirir |

### Bizim Sistemimize Uyarlama
- **ES zaten kendi Token Blocking'ini yapıyor.** Her match query ES'in terslenmiş indeksini kullanır — bu Standard Blocking'in production-grade halidir.  
- **ESoNe karşılığı:** ES'te `span_near` veya `prefix` query + `sort` ile pencereleme yapılabilir; ancak mevcut msearch mimarisi yeterince uygundur.  
- **Q-Gram Blocking:** ES'teki `ngram` tokenizer zaten karakter n-gram üretir; `es_manager.py`'deki ngram analizer açıldığında bu strateji devreye girer.  
- **Canopy/UBlocker:** Dense vector (embedding) yaklaşımı gerektirir — Bölüm 6'da ele alınıyor.  
- **Öneri:** Mevcut stage'lere "Geo-token blocker" eklenebilir: `country_code` zaten hard filter, ek olarak "city name first 3 token" bloğu gereksiz karşılaştırmaları daha da azaltır.

**Kaynak:** Papadakis, G. et al. "Blocking and Filtering Techniques for Entity Resolution: A Survey." ACM CSUR 2020. / BlockingPy (arXiv 2504.04266, 2025). / UBlocker (arXiv 2404.14831, 2024).

---

## 2. Probabilistik Record Linkage — Fellegi-Sunter, Splink, fastLink, Zingg, Dedupe.io, Senzing

### Nedir?
Fellegi-Sunter (1969) modeli, her alan karşılaştırması için m/u olasılıkları hesaplar:  
- **m:** İki kayıt gerçekten eşleşiyorsa bu alanın aynı çıkma olasılığı  
- **u:** İki kayıt eşleşmiyorsa bu alanın şans eseri aynı çıkma olasılığı  
- **Match weight:** log(m/u) — bu ağırlıkların toplamı → final eşleşme skoru

### Endüstri Araçları

| Araç | Yaklaşım | Güçlü Yön | Zayıf Yön |
|------|----------|-----------|-----------|
| **Splink (MoJ, 2019–2026)** | Fellegi-Sunter + EM; DuckDB/Spark backend; term-frequency düzeltmesi | Denetimsiz öğrenme, 1M kayıt ~1 dakika, interaktif görselleştirme | Tek sütun "bag of words" için önerilmiyor; birden fazla korelasyonsuz alan gerektirir |
| **fastLink (R)** | Fellegi-Sunter + EM | İstatistik camiasında referans | Splink'e göre daha yavaş (50x) |
| **Zingg (Spark tabanlı)** | Active learning + Spark; blok modeli + benzerlik modeli | Büyük ölçek (Snowflake, S3, Elastic), dil bağımsız | Spark altyapısı gerektirir |
| **Dedupe.io (Python)** | Active learning + blocking; az label'la iyi doğruluk | Kullanımı kolay, küçük-orta veri | Çok büyük veri kümelerinde yavaşlar |
| **Senzing** | Real-time identity resolution; graph tabanlı; açıklanabilir | Gerçek zamanlı ingest + self-correct | Ticari lisans, deployment karmaşıklığı |
| **OpenRefine** | Manuel cluster + normalize; interaktif | Non-teknik kullanıcılar için | Ölçeklenmiyor (büyük veri) |
| **AWS Entity Resolution** | Yönetilen servis; rule-based + ML | Hızlı kurulum, AWS entegrasyonu | Vendor lock-in, fine-grained kontrol sınırlı |

### Bizim Sistemimize Uyarlama
- **Splink kullanılamaz doğrudan** — tek alan (company_name) + country_code ile çalışıyoruz; Splink "tek kolon bag-of-words" için uygun değil diyor.  
- **Splink'in term-frequency düzeltmesi fikri uyarlanabilir:** Nadir token → yüksek ağırlık. ES'te bu BM25 IDF ile otomatik yapılıyor. Bunu explicit hale getirmek için Painless script rescore kullanılabilir.  
- **Zingg / Dedupe fikrinden öğrenilecek:** Active learning'in seçtiği "belirsiz çift" havuzu bizim için `dedup_reviewer.py` arayüzüdür; bu yaklaşım zaten doğru.  
- **Fellegi-Sunter m/u mantığını ES'e taşımak:** `function_score` query ile `script_score` yazılarak her token'ın IDF'i m/u proxy olarak kullanılabilir.

**Kaynak:** Splink GitHub (moj-analytical-services); Linacre, R. "Deduplicating and linking large datasets using Splink." RWD Science 2023. / Splink feasibility study (FCDS, 2023). / Zingg GitHub 2026. / Tilores "Top 10 Entity Resolution 2026."

---

## 3. Token / Alan Ağırlıklandırma — IDF-Ağırlıklı Token Önemi

### Nedir?
Bazı tokenlar ayırt edici (nadir), bazıları gürültü (sık). "argentina", "SA", "de" gibi tokenlar çok belgede geçer → düşük IDF → düşük match katkısı. "guadalquivir" sadece 2 belgede geçer → yüksek IDF → güçlü identity sinyali.

### BM25 ve IDF — ES'teki Durum
- ES default BM25: `score = IDF(t) * (tf * (k1+1)) / (tf + k1*(1-b+b*docLen/avgDocLen))`  
- IDF doğal olarak nadir token'a yüksek ağırlık verir — **eğitilmiş kural listesi gerekmez, corpus istatistikleri bu işi yapar.**  
- Kritik bulgular (VLDB 2023, Paulsen et al.): "SM-no-idf greatly underperforms SM" — IDF çıkarıldığında performans ciddi düşüyor.  
- BM25 k1 ayarı: k1=0 → sadece IDF; k1 yüksek → TF doyumu yavaş. Kısa firma adları için k1 düşürülmesi (0.5–0.8) daha stabil.  
- ES `similarity` modülünde scripted TF-IDF ile özel ağırlık tanımlanabilir.

### ES Weighted Tokens Query
ES 8.x'te `weighted_tokens` query: token-ağırlık çifti dışarıdan verilebilir. ELSER (Elastic Learned Sparse Encoder) veya özel sparse model çıktısını doğrudan query eder. `pruning_config` ile düşük ağırlıklı tokenlar atılabilir.

### Bizim Sistemimize Uyarlama (Doğrudan)
- **Geo token damping:** "argentina", "brasil", "de", "del" → ES index'te `stopwords` listesine eklenebilir veya `min_df` ile ayıklanabilir. Bunlar her zaten yüksek docFreq'li olduğundan BM25 onları zaten düşük ağırlıklar — ama explicit stopword daha güvenli.  
- **Token-count guard:** Çok-token firmalar için `token_count` field → kısa/uzun ad orantısız benzerlik puanı sorununu giderir.  
- **IDF-based "argentina mıknatısı" çözümü:** "argentina" tokeni tüm corpus'ta çok yaygınsa IDF'i düşer ve match'e katkısı azalır. Sorun: eğer coğrafi token rare bir dizide geçiyorsa (örn. "argentina gold mining") false positive riski. Çözüm: Geo token listesini synonyms_data'dan çekip ES `stopwords_path` ile kapalı tutmak.

**Kaynak:** Paulsen, D. et al. "Sparkly." VLDB 2023. / "Why Top Engineers Still Use BM25." minimalistinnovation.com 2026. / Elastic BM25 docs + weighted_tokens query docs.

---

## 4. Clustering / Transitive Closure Tuzağı — "Mıknatıs" Problemi

### Nedir?
Greedy pairwise merge + transitive closure kombinasyonu "dev yanlış küme" (magnet cluster) üretir: A≈B, B≈C → A,B,C aynı küme. Eğer B zayıf bir "hub" ise (örn. country geo token paylaşımı), alakasız onlarca firma bir master'a bağlanır.

### Literatür Bulguları

**GraLMatch (arXiv 2406.15015, 2024) — doğrudan bu sorunu inceleyen çalışma:**  
> "A limited amount of false positive pairwise match predictions can throw off the group assignment of large quantities of records."  
GraLMatch: False positive pairwise prediction'ları **graph özellikleriyle** tespit eder ve kaldırır. DistilBERT fine-tune + graph cleanup adımı: precision → recall'dan daha belirleyici.

**Correlation Clustering:**  
- Hedef: Pozitif kenarlı düğümleri aynı, negatif kenarlı düğümleri farklı kümelere ata; hata = yanlış yerdeki kenar sayısı.  
- PIVOT algoritması (3-approximation), Pruned PIVOT (3+ε, lineer), Min-Max correlation clustering (4-approx, 2024).  
- Uygulamada "yalnızca güçlü kenarda birleştir" heuristic'i: kenar ağırlığı eşiğinin üzerindeyse merge et, yoksa bırak.

**Greedy Agglomerative Clustering (Bhattacharya & Getoor, 2007):**  
- Her adımda en yakın küme çiftini birleştir.  
- Transitive closure etkisi veri setine göre değişir — bazı setlerde performansı iyileştirir, bazılarında düşürür.

**Leiden Algoritması (2025 inkremental ER çalışması):**  
- "Stop Relearning" makalesi: Multi-source ER'de inkremental veri için Leiden algoritması ile bağlantı problemi kümeleme → tek dev component'i önler.

**Max-cluster-size guard:**  
- Endüstri pratiği: Bir küme N'den büyük olamaz (örn. N=50 master için). Büyüyen küme otomatik "şüpheli" işaretlenir ve human review kuyruğuna girer.

### Bizim Sistemimize Uyarlama (Kritik)
Bizim "argentina mıknatısı" tam olarak bu fenomendir:
1. **"Argentina" tek başına eşleşmeye yetmemeli.** Token coverage threshold sadece sayısal değil, IDF-ağırlıklı coverage olmalı: nadir token match > sık token match.
2. **Master büyüklük limiti:** Bir master'a bağlanan variation sayısı N'i (örn. 200) geçerse otomatik flag + human review.
3. **"Zayıf hub" tespiti:** Master kaydı neredeyse sadece geo/stop token'lardan oluşuyorsa (token entropy düşükse) o master'ı "low-confidence hub" olarak işaretle — yeni kayıtlar ona bağlanamaz.
4. **GraLMatch yaklaşımı:** Mevcut match grafiğinde bağlı component analizi yapılabilir (PG query veya ES query). Dev component'ler şüpheli sayılır ve `dedup_reviewer.py` kuyruğuna düşer.

**Kaynak:** GraLMatch (arXiv 2406.15015, 2024). / Correlation Clustering (Pruned PIVOT, openreview 2024; Heidrich et al. PMLR 2024). / Bhattacharya & Getoor (2007). / "Stop Relearning" (arXiv 2412.09355, 2024).

---

## 5. Canonicalization / Normalization — Ne Sıyrılmalı, Ne Korunmalı

### Nedir?
Ham firma adını karşılaştırılabilir bir canonical forma dönüştürme. İki tehlike: (1) Yeterince normalize etmemek → "Inc." vs "Incorporated" eşleşmez; (2) Aşırı normalize etmek → "The Limited" → "The" dejenere küme.

### Literatür Bulguları

**Corp-names / TidyName (2025–2026 GitHub):**  
- 1000+ legal suffix, 200+ jurisdiction kapsıyor.  
- "The Limited" gibi brand exception listesi — suffix brand'in parçasıysa kaldırma.  
- Normalization pipeline: unicode → noktalama → tokenize → prefix/suffix strip → nickname resolve → lowercase.

**PUDL / OS-Climate CompanyNameCleaner:**  
- HandleLegalTerms: remove / normalize / keep seçenekleri.  
- `remove_accents`, `remove_unicode` opsiyonel (dil bağımlı).

**BrandNERD (SCITEPRESS 2025):**  
- Canonicalization → similarity clustering döngüsü. Regex kuralları iteratif geliştirilir; downstream pipeline hata geri bildirir.  
- Levenshtein: yazım hatası + suffix için iyi (MRR=0.963), abbreviation için kötü (Recall@1=0.245).  
- Pretrained transformer: abbreviation dahil hepsinde iyi (%99 recall suffix/typo/noise'da).

**Aşırı Sıyırma Riski:**
- "GM BRASIL" → "GM" tek token → binlerce General Motors variasyonuyla eşleşir.  
- "de Argentina" → "" (boş) → EXCLUDED.  
- Kurallar: Sıyrıma sonrası 1 token kalan adlar "degenerate" flag'i almalı; eşleşmeden önce uzunluk kontrolü.

### Bizim Sistemimize Uyarlama
- **ES Ingest Pipeline zaten bu görevi yapıyor** (`es_ingest.py`). Kritik güvenlik: sıyrıma sonrası kayıt 0 anlamlı token bırakıyorsa indeksleme atlanmalı (veya `_excluded` flag'i).  
- **suffix_typo_map (`config.py`):** Mevcut yapı doğru. Ülkeye özgü suffix normalization → `synonyms_data/<cc>.json` içinde tutulması önerilir.  
- **Geo token damping:** "argentina", "brasil" vb. normalization sırasında değil, scoring sırasında bastırılmalı (IDF yoluyla). Normalize ederek çıkarmak recall'u ciddi düşürür ("GM BRASIL" sadece "GM" kalır ve generic olur).  
- **Non-firm placeholder listesi:** Mevcut `non_firm_placeholders` yaklaşımı literatürle örtüşüyor — "sin razon social" gibi ifadeler TAM eşleşmeyle EXCLUDED, bu doğru.

**Kaynak:** corp-o-rate/corp-names (GitHub 2026). / PUDL name_cleaner docs. / BrandNERD (SCITEPRESS 2025). / Zajac thesis (UU 2024).

---

## 6. Embedding / Transformer / LLM Tabanlı Eşleştirme

### Nedir?
Firma adını dense vector'e dönüştür (sentence embedding); kNN ile en yakın vektörü bul. ES `dense_vector` + HNSW algoritması.

### Literatür Bulguları

**Sentence Transformer yaklaşımı (Zajac, UU 2024):**  
- `all-MiniLM-L6-v2` pretrained: JRC-Names'de Recall@1=0.961; GLEIF'de Recall@1=0.446.  
- Fine-tuned: abbreviation dışında hepsi >0.99; Qdrant + vektör DB 65% daha hızlı.  
- Önemli not: GLEIF (resmi hukuki isimler) zor; JRC-Names (ülke/şehir etiketli) kolay.

**Company Name Matcher (easonanalytica, 2024):**  
- Contrastive learning ile fine-tuned multilingual sentence transformer. `$` özel token eklenerek "bu bir firma adı" bağlamı eklendi.  
- O(n log m) complexity vs O(n*m) kaba kuvvet.

**Company Duplicate Search (pacifikus, 2022 → hala referans):**  
- `paraphrase-MiniLM-L6-v2` + ES dense_vector. Precision=0.8'de Recall=0.52.  
- 30.000 vektör, 100 QPS @ laptop.

**ES + LLM hybrid (Elastic Labs, 2026):**  
- ES: BM25 (keyword) + kNN (dense) + alias match → candidate retrieval.  
- LLM: Candidate çiftleri LLM'e ver → "same entity?" kararı + açıklama.  
- XLM-RoBERTa NER modeli ES pipeline'ında çalıştırılabilir.

**ES Hybrid Search (BM25 + kNN + RRF):**  
- Reciprocal Rank Fusion (RRF): BM25 sırası + kNN sırası → birleşik sıralama.  
- Linear retriever: ağırlıklı blend; dataset-spesifik tuning gerektirir.  
- Cypris case: 500M vektör; BBQ (binary quantization) ile 30-60sn → 5-10sn.

**EntityMatch (AntJam-Howell, 2026):**  
- Score ≥0.90 → auto-accept; 0.75–0.90 → LLM validation; <0.65 → reject.  
- Haiku/GPT-4o-mini maliyeti: ~$0.50 / 20.000 validation.

### Bizim Sistemimize Uyarlama
- **Maliyet-Fayda:** Abbrev/abbreviation sorununu çözmek için embedding son derece etkili. "IAE" vs "International Aero Engines" gibi kısaltmalar sadece embedding ile yakalanır.  
- **ES dense_vector hazır:** `es_manager.py`'e `dense_vector` field eklemek ve HNSW indekslemek teknik olarak mümkün.  
- **Öneri (inkremental geliştirme):** Mevcut exact/fuzzy stage'ler geçtikten sonra eşleşmeyen kayıtlar için embedding stage eklenebilir. Bu "EMBEDDING_KNN" adlı 5. stage olur.  
- **Kısıt:** Model inference Python'da yapılır (allowed — yasak sadece Python Levenshtein). Embedding hesaplama offline (ingest zamanında) yapılır; ES'te sadece kNN query çalışır.  
- **country_code filtresi:** kNN query'de `filter: { term: { country_code: "..." } }` ile korunur.

**Kaynak:** Zajac thesis (UU 2024). / easonanalytica/company_name_matcher (GitHub 2024). / Elastic Labs "Entity Resolution with LLM" (2026-02). / pacifikus (2022). / AntJam-Howell/entitymatch (2026).

---

## 7. Threshold Kalibrasyonu + Active Learning + Human-in-the-Loop

### Nedir?
- **Threshold kalibrasyonu:** Match/no-match kararı için eşik değeri belirleme. Sabit eşik genellikle yetersiz; dataset'e göre değişir.  
- **Active learning:** Sisteme "hangi çifti etiketlemeliyim?" sorusu sorduruluyor — en belirsiz (threshold yakını) örnekler seçiliyor.  
- **Human-in-the-loop (HITL):** Belirsiz bölge → insan kuyruğuna; yüksek güven → otomatik karar.

### Literatür Bulguları

**"100% otomasyon mümkün mü?" sorusuna literatür cevabı:**  
- Bailey et al. (AEJ 2021): "No algorithm (including hand-linking) consistently produces representative samples. 15–37% of automated links are classified as errors by trained human reviewers."  
- ONS (2024): "Clerical resolution — a very costly process. Research to maximize automation is key aim." → Tamamen ortadan kaldırılamıyor, minimize edilebilir.  
- Azimaee et al. (IJPDS 2024): Fuzzy matching → clerical review eliminates, "comparable accuracy." Fakat yüksek kalite gerektiren domainlerde (sağlık, finans) %100 otomasyon henüz güvenilir değil.  
- PMC 2014 (EHR dedup): Active learning ile 3.000 etiket → 10.000 random sample ile karşılaştırılabilir sonuç. Dual-threshold (match/review/no-match) ile manual review seti %1.9'a indi.

**Threshold Stratejileri:**  
- Tek eşik → binary (match/no-match): Yüksek recall + precision aynı anda imkânsız (trade-off).  
- **Dual threshold (T1, T2):** T1 üstü → otomatik match; T2 altı → otomatik no-match; arada → human review.  
- ONS dual threshold metodu (2024): Gold standard dataset üzerinde kalibre edilmiş; yüksek-precision ve yüksek-recall iki ayrı threshold.  
- RecordLinkage R paketi: `optimalThreshold()` → PPV/NPV kısıtı altında optimal T hesaplar.

**Active Learning:**  
- Tahamont et al. (PLoS ONE 2023): "Only a relatively small number of tactically-selected ground-truth examples needed to obtain most achievable gains."  
- Ramezani et al. (CEUR 2021): Human-computer hybrid; RF/SVM modelleri yeni settere transfer eder, DNN etmez.  
- Isele dissertation (Mannheim): ActiveGenLink — referans çifti olmadan başlangıç, iteratif etiket.  
- Pool-based active learning (Electronics 2024): Hybrid uncertainty query strategy; 7 dataset, az etiketle DL yöntemlerine eşit.

**Bizim Sistemimize Uyarlama:**  
- **`dedup_reviewer.py` aktif öğrenme temelidir** — bu bileşen literatürle örtüşüyor.  
- **Dual threshold uygulaması:** Mevcut tek-eşik mantığı yerine, yüksek güvenli eşleşmeler (skor > T_high) auto-commit; orta güvenli eşleşmeler (T_low < skor < T_high) review kuyruğuna; altı → no-match. Bu PG'ye 3 durumlu `match_confidence` (HIGH/MEDIUM/REVIEW) yazılabilir.  
- **Threshold kalibrasyonu:** Bilinen doğru çiftlerden (audit verisi) F1/MCC maksimize eden T_high ve T_low hesaplanmalı.  
- **"%100 otomasyon ulaşılabilir mi?"** → Literatür: Yüksek doğruluk gerektiren senaryolarda (finansal, KYC) **hayır**. Belirsiz kuyruk (gray zone) için HITL zorunlu. Hedef: Gray zone küçük, auto-zone büyük.

**Kaynak:** Bailey et al. AEJ 2021. / PMC 2014. / Tahamont et al. PLoS ONE 2023. / Ramezani et al. CEUR 2021. / ONS "Automating thresholds in probabilistic linkage" IJPDS 2024.

---

## 8. Endüstri Araçları Karşılaştırması (2026)

| Araç | Mimari | En İyi Uyum | Bizdeki Karşılık |
|------|--------|-------------|------------------|
| **Splink** | Fellegi-Sunter + EM + DuckDB/Spark | Çok-alan entity resolution | Tek-alan limitasyonu; fikir transferi: IDF-ağırlıklı m/u |
| **Zingg** | Spark + active learning + ML benzerlik | Büyük ölçek master data | Spark yok; blocking fikri: kNN index |
| **Dedupe.io** | Active learning + blocking | Orta ölçek; kolay kurulum | `dedup_reviewer.py` analogu |
| **Senzing** | Real-time graph tabanlı | KYC/AML gerçek zamanlı | Pahalı; mimarimiz benzer hedefler için |
| **OpenRefine** | Manuel cluster | Küçük veri, non-teknik | Bizde yok; interaktif UI için referans |
| **BlockingPy** | ANN (FAISS/HNSW) tabanlı blocking | Python-native, GPU | Embedding stage gerektirir |
| **GraLMatch** | Transformer + graph cleanup | Transitive closure hatası | False positive kenar tespiti fikri |

---

## 9. Özet: Bizdeki En Uygulanabilir Teknikler (Öncelik Sırası)

### 1. IDF-Ağırlıklı Token Coverage (Hemen Uygulanabilir)
**Neden:** Mevcut TOKEN_COVERAGE stage sabit token sayısına bakıyor; IDF-ağırlıklı coverage geo/stop token'ları doğal olarak bastırır.  
**Nasıl:** ES Painless script'te her eşleşen token için `idf(token, field)` değeri çekilebilir; coverage = Σ(idf_eşleşen) / Σ(idf_tümü).  
**Etki:** "Argentina mıknatısı" sönümlenir — "argentina" tokenı düşük IDF'li olduğundan coverage'a katkısı minimal.

### 2. Dual Threshold + Gray Zone → Human Review (Hemen Uygulanabilir)
**Neden:** %100 otomasyon literatürde imkânsız gösterilmiş. Dual eşik; auto-zone büyük, gray zone küçük tutularak clerical effort minimize edilir.  
**Nasıl:** `main_processor.py`'de `best_score > T_HIGH` → auto-commit; `T_LOW < best_score < T_HIGH` → `match_confidence=REVIEW` PG'ye yaz; `dedup_reviewer.py` bu kuyruğu işler.

### 3. Master Büyüklük Limiti + Hub Kalitesi Guard (Orta Vadeli)
**Neden:** GraLMatch + correlation clustering literatürü: Dev cluster = hata sinyali.  
**Nasıl:** PG'de `SELECT master_code, COUNT(*) FROM master_variations GROUP BY master_code HAVING COUNT(*) > 200` → flag. ES Transform veya cron job ile izle.

### 4. Geo Token Explicit Stopword (Hemen Uygulanabilir)
**Neden:** "Argentina", "de", "del", "SA" gibi tokenlar yüksek frequency → düşük IDF → zaten bastırılıyor. Ama IDF küçük corpus'ta yanıltıcı olabilir.  
**Nasıl:** `es_manager.py`'de `stopwords_path: synonyms_data/stopwords/geo_tokens.txt` tanımı. `synonyms_data/` sabit olduğundan bu liste `config.py`'de veya yeni `geo_stopwords.txt`'de tutulur.

### 5. Embedding Stage (Uzun Vadeli)
**Neden:** Kısaltma sorununu (IAE ≈ International Aero Engines) sadece embedding çözer; diğer stage'ler yetersiz.  
**Nasıl:** `es_manager.py`'e `dense_vector` field ekle; ingest sırasında Python'da embedding hesapla (yasak değil — Python Levenshtein yasak, inference değil); ES kNN query ile EMBEDDING_KNN stage'i ekle.  
**Maliyet:** `paraphrase-multilingual-mpnet-base-v2` veya fine-tuned MiniLM. ~384 float × N kayıt ≈ yönetilebilir.

### 6. Active Learning Calibration (`dedup_reviewer.py` Güçlendirme)
**Neden:** Az label (200–500 çift) ile büyük doğruluk kazanımı literatürde kanıtlı.  
**Nasıl:** Gray zone çiftlerini entropy/belirsizlik skoruna göre sıralayıp reviewera sun (en belirsiz önce). Kabul/ret kararları → threshold kalibrasyonu için training set.

---

## 10. "%100 Otomatik Eşleştirme Mümkün Mü?" — Literatür Cevabı

**Kısa cevap:** **Hayır** — yüksek doğruluk kısıtı (precision ~%100) ile tam otomasyon birlikte sağlanamaz.

Uzun cevap:
- Bailey et al. (AEJ 2021): En iyi algoritmalar %15–37 hata üretiyor; **hiçbir algoritma tutarlı olarak %100 doğruluk sağlamıyor.**
- Fellegi-Sunter + EM: Denetimsiz çalışır ama belirsiz bölge her zaman var; clerical review standart parça.
- Fuzzy matching (Azimaee 2024): Clerical review'u elemine edebildi ama healthcare gibi yüksek stake domainlerde değil.
- Machine learning (PMC, ONS 2024): Dual-threshold ile gray zone %1–5'e indirgenebilir. Bu pratik "maksimum otomasyon."
- GraLMatch: "Precision becomes the deciding factor" — yüksek precision için bazı eşleşmeleri kaçırmak (recall düşürme) gerekir.

**Bizim sistemimiz için hedef:**  
- Gray zone < %5 (REVIEW kuyruğu küçük olsun)  
- Auto-zone içinde precision > %99  
- Recall: Mevcut audit bulgularına göre kademeli artırma  
- "%100 otomatik" iddiasından kaçın; HITL'i mimarinin parçası kabul et.

---

## Referans Listesi (Seçilmiş)

1. Papadakis, G. et al. "An Empirical Survey of Data-Driven Entity Resolution Techniques." VLDB 2016.
2. Papadakis, G. et al. "Blocking and Filtering Techniques for Entity Resolution: A Survey." ACM CSUR 2020.
3. Linacre, R. et al. "Splink: Probabilistic record linkage at scale." MoJ, 2019–2026. https://github.com/moj-analytical-services/splink
4. Bailey, M. et al. "How Well Do Automated Linking Methods Perform?" AEJ 2021. https://pmc.ncbi.nlm.nih.gov/articles/PMC8294155/
5. GraLMatch: "Matching Groups of Entities with Graphs and Language Models." arXiv 2406.15015, 2024.
6. UBlocker: "Towards Universal Dense Blocking for Entity Resolution." arXiv 2404.14831, 2024.
7. BlockingPy: "Approximate Nearest Neighbours for Blocking." arXiv 2504.04266, 2025.
8. Paulsen, D. et al. "Sparkly: Entity Blocking with Lucene." VLDB 2023.
9. Heidrich, H. et al. "A 4-Approximation Algorithm for Min Max Correlation Clustering." PMLR 2024.
10. Azimaee, M. et al. "From Probabilistic to Fuzzy Matching Record Linkage." IJPDS 2024.
11. Tahamont, S. et al. "No ground truth? No problem." PLoS ONE 2023.
12. "Stop Relearning: Model Reuse via Feature Distribution Analysis." arXiv 2412.09355, 2024.
13. Elastic Labs. "Entity Resolution with LLM and Elasticsearch." Feb 2026. https://www.elastic.co/search-labs/blog/entity-resolution-llm-elasticsearch
14. Zajac, A. "Organization Name Matching with Sentence Transformers." UU thesis 2024.
15. Bhattacharya, I. & Getoor, L. "Collective Entity Resolution in Relational Data." TKDD 2007.
16. ONS. "Automating thresholds in probabilistic linkage." IJPDS 2024.
17. Tilores. "Top 10 Entity Resolution Tools 2026." https://tilores.io/content/Top-10-Entity-Resolution-Tools-for-Enterprises-in-2026-Ranked-by-Use-Case
