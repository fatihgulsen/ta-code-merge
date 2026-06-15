# Firma Eşleştirme — Master İyileştirme Yol Haritası

**Tarih:** 2026-06-15
**Sentez kaynağı:** 3 paralel araştırma agent'ı + Round-5/6/7 denetimleri + geo-mıknatıs kök-neden analizi.
**Alt-raporlar:**
- [literatür & endüstri bulguları](../../qa-artifacts/research/literature_findings.md)
- [kod-temelli problem brainstorm](../../qa-artifacts/research/codebase_brainstorm.md)
- [%100-yakınsama & clustering stratejisi](../../qa-artifacts/research/convergence_strategy.md)

**Soru:** "Birleştirmede acil ~%100'e yakınsamamız lazım. Tam olarak hangi iyileştirmeleri, nasıl, hangi sırayla yapmalıyız? Literatürde insanlar ne yapıyor?"

---

## 1. Önce Net Gerçek: "%100 Otomatik" Yanlış Hedef (Literatür Konsensüsü)

Serbest-metin firma adı eşleştirmesinde **hiçbir yöntem tutarlı %100 precision+recall vermiyor:**
- Bailey et al. (AEJ 2021): en iyi otomatik algoritmalar **%15-37 hata** üretiyor; el-ile linkleme bile temsilî değil.
- Correlation clustering **NP-hard** (AAAI-20); homonim (aynı ülkede aynı isimli farklı firma), kısaltma, adres-karışımı, slash-multi-entity → **kesin cevabı olmayan** vaka sınıfı her zaman var.
- ONS / PMC: **Dual-threshold + insan-denetimi (HITL)** ile belirsiz "gri bölge" **%1-5'e** indirgenebilir — pratik maksimum budur.

**Bizim için doğru "~%100" tanımı:**

| Katman | Hedef | Araç |
|--------|-------|------|
| Otomatik **auto-zone** | precision **>%99** | mıknatıs-önleme (Bölüm 3) |
| **Gri bölge** | **<%5**, %100 insan kapsaması | güven bandı → `dedup_reviewer` |
| Kaçan gerçek hata | **<%2** | her reindex'te golden-set regresyon |

→ "Acil %100" = **agresif over-merge önleme + her belirsiz vakayı insana yönlendiren güvenlik ağı.** İkisi birlikte. Bu, sektör standardı iki-katmanlı mimari (Splink/Zingg/Senzing/Dataiku hepsi böyle).

---

## 2. Sorunun Literatürdeki Adı: "Magnet / Snowball Cluster"

Bizim "argentina mıknatısı" tam olarak literatürdeki **transitive-closure magnet** problemi:

> Greedy-incremental birleştirme A~B, B~C eşleşmelerini görüp **A≁C olsa bile** A-B-C'yi tek master'a toplar. Zayıf bir "hub" token (geo "argentina", tek harf, çok-yaygın kelime) yüzlerce alakasız firmayı tek mastera çeker.

- **GraLMatch (arXiv 2024):** *"Az sayıda yanlış-pozitif çift tahmini, çok sayıda kaydın grup atamasını bozar."* → **precision, recall'dan daha belirleyici.**
- **Microclustering property (arXiv 2025):** en büyük kümenin boyutu veri ile **sub-lineer** büyümeli; lineer büyüme = gürültü işareti.
- **Çözüm felsefesi:** "yalnızca **güçlü, ayırt-edici-token-destekli** kenarda birleştir" + küme boyutunu sınırla + belirsizi insana ver.

Bizim sistemdeki kanıtlı tetikleyiciler: stripped analyzer'da geo-stop yokluğu (geo token hub oluyor), token-tekrarı, SUFFIX_FUZZY'de core-coverage yokluğu (kapatıldı), izleme kör noktası (830 dup NEW_MASTER).

---

## 3. İyileştirmeler — 3 Aşamalı Plan

### AŞAMA A — Kod (reindex ÖNCESİ hazırlık)

| # | İyileştirme | Dosya:Satır | Literatür dayanağı | Recall |
|---|-------------|-------------|--------------------|--------|
| **A1** | **Geo-stop'u stripped analyzer'a ekle.** `geo_stopwords_global`'ı `stripped_search_analyzer_{cc}` (:173) + global (:186) zincirine; tanımı :189→~:157'ye taşı. | `es_manager.py` | Canonicalization: geo ayırt edici değil; IDF ile aynı amaç ama küçük corpus'ta explicit stopword daha güvenli | **nötr** |
| **A2** | **Token-tekrar dedup.** Painless clean script'e ardışık-yinelenen-token atma. | `es_ingest.py:_build_clean_script()` | `RICARD RICARD`→`RICARD` token-şişirme önlenir | nötr |
| **A3** | **AUTO_DEDUP demote.** `MatchType.AUTO_DEDUP` sabiti + dedup sonrası `match_type` UPDATE. | `config.py:7`, `main_processor.py` | İzleme kör noktası (830 dup NEW_MASTER) kapanır | — |
| **A4** | **Max-cluster-size guard.** `MAX_VARIATIONS_PER_MASTER` (örn. 100); master variation_count aşınca yeni eşleşme bloklanır → gri kuyruk. | `config.py`, `main_processor.py` winner-seçimi | Microclustering: büyük küme = hata sinyali (GraLMatch) | nötr (hard gate) |

> **A1 = bu oturumda raporlanan `SAL ARGENTINA` mıknatısının doğrudan kök-neden fix'i.** `SAL ARGENTINA`→`[]`→NEW_MASTER; `AUDI ARGENTINA`→`['audi']`→korunur. GM kararına da uyar: `GM BRASIL`=`GM DE ARGENTINA`→`['gm']`→birleşir.

### AŞAMA B — Tek Reindex Penceresi (A1+A2 + PE'yi birlikte canlıya alır)

```bash
python es_ingest.py            # A2 pipeline + temiz strip
python es_manager.py --force   # A1 geo-stop + PE analyzer (B1) + stale-AR tazele
python main_processor.py       # tam rematch: AR %35 / PE %40 → %100
```
- **B1 — PE blocker:** kod değişikliği YOK; `--force` PE analyzer'larını otomatik kurar (kök neden: index `pe.json` öncesi kurulmuş; canlı kanıt `_analyze pe`→400). PE eşleştirme sıfırdan açılır.
- **Kritik:** A1, A2, B1 **aynı tek reindex'te** devreye girer — ayrı ayrı reindex YAPMA.

### AŞAMA C — Reindex Sonrası: Ölç + Güvenlik Ağı + İnce Ayar

| # | İyileştirme | Açıklama | Öncelik |
|---|-------------|----------|---------|
| **C1** | **Round-8 QA** (haiku census + zorunlu adversarial verify) | A1-A4'ün gerçek precision/recall etkisini ölç; before/after | P0 |
| **C2** | **Dual-threshold güven bandı** | `score>T_HIGH`→auto-commit; `T_LOW<score<T_HIGH`→`match_confidence=REVIEW` PG'ye; altı→NEW_MASTER. Eşikler golden-set'te F1/MCC ile kalibre. | P1 |
| **C3** | **`dedup_reviewer.py` güçlendirme** | öncelik-sıralı kuyruk (güven×küme-riski×bekleme) + kategori etiketi + `split` komutu + PG geri-yazım. Gri bölge + max-cluster karantinası buraya akar. | P1 |
| **C4** | **Eşit-token-farklı-marka** (`ALL OVER`vs`ALL IN`) | A1 sonrası **hacmi yeniden ölç**; hâlâ yüksekse IDF-ağırlıklı `script_score` rescore (nadir token = yüksek ağırlık). Düşükse ertele. | P2 (ölçüme bağlı) |
| **C5** | **`COMPL-xxxx` gümrük-kodu strip** (AR under-merge) | `input_filter`/Painless ile `COMPL-\d+` deseni temizle (synonyms_data sabit). | P2 |
| **C6** | **Golden-set regresyon otomasyonu** | her reindex'te golden çalıştır; herhangi stage precision %3+ düşerse alarm. `audit_batch.ps1` altyapısı. | P1 |

---

## 4. Literatürden Öğrenilen, Daha İleri (Orta/Uzun Vade)

Acil değil ama "%100'e yakınsama" yolunda sektörün yaptıkları:

1. **IDF-ağırlıklı token coverage** (Enigma Soft-TF-IDF, Splink term-frequency düzeltmesi): flat token sayımı yerine `Σidf(eşleşen)/Σidf(tüm)`. Geo/stop token'ları **doğal olarak** bastırır (A1'in skorlama-seviyesi tamamlayıcısı). ES Painless rescore ile, Python'suz.
2. **Embedding stage (EMBEDDING_KNN)** (Sentence-Transformers + ES `dense_vector` + HNSW): **kısaltma** sorununu (`IAE`≈`International Aero Engines`) çözen TEK yöntem — exact/fuzzy stage'ler yetersiz. Model inference Python'da serbest (yasak olan Levenshtein, inference değil); ES'te sadece kNN + `country_code` filtresi. İnkremental 5. stage olarak eklenebilir.
3. **ES + LLM hybrid validation** (Elastic Labs 2026, EntityMatch): `score≥0.90`→auto; `0.75-0.90`→LLM "same entity?" + açıklama; `<0.65`→ret. Haiku ile ~$0.50/20k doğrulama — gri bölgeyi LLM'le daraltma.
4. **Active learning** (Tahamont 2023): `dedup_reviewer`'da en belirsiz çifti önce sun; 200-500 taktik etiket büyük kazanım → eşik kalibrasyonu için training set.

---

## 5. Bağımlılık & Özet Sıra

```
A1 geo-stop ─┐
A2 token-dedup ┼─► B (tek reindex: es_ingest → es_manager --force → rematch) ─► C1 Round-8 ölçüm
A3 demote ────┤                                                                    │
A4 max-cluster┘                                                                    ▼
                                                          C2 dual-threshold + C3 reviewer kuyruğu (güvenlik ağı)
                                                          C4/C5 (ölçüme bağlı ince ayar) · C6 regresyon
                                                          → orta vade: IDF rescore, EMBEDDING_KNN, LLM-validate
```

**Tek cümle:** Aşama A'da 4 kod değişikliği yap → Aşama B'de **tek reindex** ile A1/A2/PE'yi birlikte canlıya al + tam rematch → Aşama C'de ölç, güven bandı + insan-denetim kuyruğu kur, kalanı ölçüme göre ince ayarla. Mıknatıs yapısal olarak ölür; belirsiz tail insana gider; "%100" = yüksek-güven otomatik + tam-kapsamlı insan denetimi.

---

## 6. Beklenen Sonuç

| Metrik | Şimdi | Aşama B sonrası (tahmin) | + Aşama C |
|--------|------:|-------------------------:|----------:|
| AR auto-zone precision | %93.4 | ~%96-97 | **>%99** (gri bölge ayrılınca) |
| PE | ölü | çalışır (ilk ölçüm) | kalibre |
| Geo-mıknatıs (`SAL ARGENTINA`) | aktif | **ölü** (A1) | — |
| Gri bölge (insan kuyruğu) | yok | — | **<%5**, %100 kapsama |
| COUNTRY_LEAK | 0 | 0 | 0 |

**Not:** Bu oturumda yalnızca SUFFIX_FUZZY deaktivasyonu uygulandı (kod). A1-A4 ve C1-C6 **onay bekliyor** — hiçbiri henüz uygulanmadı.
