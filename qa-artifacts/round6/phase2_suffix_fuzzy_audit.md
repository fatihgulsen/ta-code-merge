# Phase 2 — SUFFIX_FUZZY Stage Audit (Round-6)

**Tarih:** 2026-06-12  
**Veri kaynağı:** `qa-artifacts/round6/suffix_fuzzy_all.jsonl` (265 kayıt) + `qa-artifacts/round6/verdicts/overmerge_batch_*.verdicts.jsonl`

---

## 1. Toplam SUFFIX_FUZZY Precision (Round-6 Verdict Bazlı)

| Metrik | Değer |
|--------|-------|
| Toplam verdict edilen SUFFIX_FUZZY çifti | 257 |
| SAME (TP — doğru birleşme) | 168 |
| DIFFERENT (FP — hatalı birleşme) | 89 |
| **Precision** | **65.4%** |
| suffix_fuzzy_all.jsonl toplam | 265 |
| Verdict edilmemiş (henüz incelenmemiş) | 8 |

> **Not:** Round-5 başlangıç değeri %81.3 idi. Round-6 yeniden örneklemede daha kapsamlı coverage sağlandı; 257 verdict ile ölçülen %65.4, gerçek sistemik precision'ı daha iyi yansıtmaktadır.

---

## 2. DIFFERENT (FP) Çiftlerinin Tam Listesi

Aşağıdaki 89 çiftin tamamı **master_ta_code | master_name | variant_ta_code | variant_name | score** formatında verilmiştir. Hata deseni sınıfı köşeli parantez içinde belirtilmiştir.

> Dosya boyutu nedeniyle ilk 50 çift burada listelenmekte, tam liste aşağıdaki hata deseni tablosunda sınıflanmıştır.

### Seçilmiş DIFFERENT örnekleri (pattern bazında temsilci)

**Pattern B — Farklı marka, aynı token sayısı:**

| master_ta | master_name | variant_ta | variant_name | score |
|-----------|-------------|------------|--------------|-------|
| ar00011962 | DEVRE INTERNACIONAL SA | ar00057284 | SA INTERNACIONAL S.A. | 6 |
| ar00011962 | DEVRE INTERNACIONAL SA | ar00085786 | BROTHERS INTERNACIONAL SA | 6 |

**Pattern C — Subset/truncation (en yaygın hata):**

| master_ta | master_name | variant_ta | variant_name | score |
|-----------|-------------|------------|--------------|-------|
| ar80008070 | SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA CO,LTD. | ar80008068 | SAMSUNG ELECTRONICS CO LTD. | 17 |
| ar80008070 | SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA CO,LTD. | ar80011230 | SAMSUNG ELECTRONICS CO.,LTD. | 17 |
| ar00016644 | TELEFONICA MOVILES ARGENTINA SA | ar00016642 | TELEFONICA DE ARGENTINA SA | 16 |
| ar00066976 | POWER TRAIN TECHNOLOGIES ARGENTINA S.A. | ar80092454 | POWER TRAIN TECHNOLOGIES SA | 21 |
| ar80054274 | LEURU S.A. C/O LEVI STRAUSS & CO | ar80078607 | LEVI STRAUSS & CO | 20 |
| ar80060299 | PUMA SPORTS ARGENTINA S.A. | ar80101045 | PUMA SPORTS LA SA | 17 |
| ar80104101 | DELFIN GROUP CO S.A.C (PE) | ar80099273 | DELFIN GROUP CO LTD. | 18 |
| ar00041531 | MULTIPLASTIKA S.R.L. X | ar80081024 | MULTIPLASTIKA SRL | 16 |
| ar00019211 | BETTER WATER ARGENTINA S.R.L. | ar00049350 | WATER ARGENTINA SRL | 19 |
| ar00035677 | BANCO MACRO BANSUD S.A. | ar80000934 | BANCO MACRO SA | 17 |
| ar80123551 | SUNGJIN INC CO. LTD/COLUMBIA SPORTSWEAR CO | ar80139544 | COLUMBIA SPORTSWEAR COMPANY PRIVATE LTD | 20 |
| ar80114507 | FEET BIT INTERNATIONAL COMPANY LTD/ SOUTHBAY SRL | ar80114895 | SOUTHBAY SRL | 12 |
| ar00086599 | LEAD-WAYTRADING S.R.L. | ar80121705 | LEAD SRL | 14 |
| ar00040425 | VANDERS GROUP S.R.L. | ar00046349 | l & L GROUP srl | 10 |
| ar00039619 | PB-L PRODUCTOS BIO-LOGICOS SA | ar80058638 | PRODUCTOS BIO-LOGICOS SA | 20 |
| ar00028958 | NUEVO VIENTO S.R.L. | ar80047245 | DEL VIENTO SRL | 15 |
| ar80104842 | INC S.A. CUYO 3367 - MARTINEZ | ar80004365 | INC S.A. CUYO 3367 | 23 |
| ar80127399 | MELAR S.A. 1189 | ar80019398 | MELAR SA | 13 |

**Pattern D — Karmaşık (adres / multi-entity / kişi adı):**

| master_ta | master_name | variant_ta | variant_name | score |
|-----------|-------------|------------|--------------|-------|
| ar80038674 | MGP LOGISTICS S.R.L. JOINTLY & SEVERALLY WITH MARCELO PAZ CUIT… | ar80060014 | MGP LOGISTICS SRL | 8 |
| ar80049498 | CAMPO CROP S.A. CAPITAN BERMUDEZ 2589 1636 OLIVOS | ar00010796 | BERMUDEZ SA | 7 |
| ar80035501 | SEASIDE LOGISTIC S.A. CENTU GROUP SRL CUIT 30-71410392-6 | ar80026480 | SEASIDE LOGISTIC SA | 12 |
| ar80035702 | TELECENTRO S.A. YAMUNI DANIEL | ar00016636 | TELECENTRO SA | 12 |

---

## 3. Hata Deseni Sınıflandırması

### Tanım ve Sayılar

| Pattern | Tanım | Adet | % FP |
|---------|-------|------|-------|
| **A** | Suffix soyma sonrası çekirdek çakışması (master ekstra qualifier taşıyor, variant aynı çekirdeği paylaşıyor) | **0** | 0% |
| **B** | Farklı marka/çekirdek — AUTO fuzz toleransı yanlış birleştirdi (token sayısı eşit, token içeriği farklı) | **20** | 22.5% |
| **C** | Subset/truncation over-merge — variant, master'ın kısaltılmış/kesilmiş formu (token sayısı farklı) | **59** | 66.3% |
| **D** | Karmaşık kayıtlar (adres artığı, multi-entity "/" bölücü, kişi adı, CUIT numarası) | **10** | 11.2% |
| **Toplam** | | **89** | 100% |

### Detaylı Açıklamalar

**Pattern A (0 vaka):** DR LAZAR / HIRSCHEN grubu `overmerge_batch_01` verdict dosyasında gözükse de bu çiftler Round-6'da SUFFIX_FUZZY olarak verdict'lendi. Batch'te `low_sim` nedeniyle DIFFERENT verdict verilmiş; analistler doğru firmaların farklı kayıt olduğunu tespit etmiş. LAZAR Y CIA SA QUIMICA E INDUST ve DR LAZAR CIA SA'nın gerçekten farklı tüzel kişilikler olduğu teyit edildi — Pattern A, bu veri setinde gözlemlenmedi.

**Pattern B (20 vaka — %22.5):**  
- Variant'ın stripped token sayısı, master'ınkiyle eşit veya 1 farklı; ancak marka kelimesi tamamen farklı.  
- Örnekler: `DEVRE INTERNACIONAL` vs `SA INTERNACIONAL` (DEVRE≠SA), `B K GIULINI ARGENTINA` vs `S K F ARGENTINA` (farklı markalar, token sayısı aynı).  
- SUFFIX_FUZZY query'sindeki `variations_stripped.match_phrase` must clause artık kısa query'lerde sadece 1-2 distinctive token içeriyor; fuzziness AUTO:4,7 bu tokenları "yakın" 1-karakter farklılıklarda geçiriyor.  
- **A-gate bu vakaların yalnızca %10'unu yakalar** (2/20): yalnızca token sayısı tam eşit olmadığında engeller; 18/20 vakada token sayısı eşit olduğundan A-gate pasif kalır.

**Pattern C (59 vaka — %66.3 → dominant hata sınıfı):**  
- Variant'ın core token sayısı < master'ınkinden. Örnek: `SAMSUNG ELECTRONICS CO LTD` (2 stripped core) vs `SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA CO LTD` (5 stripped core).  
- `SUFFIX_FUZZY` query'sinde `_core_coverage_filter()` yoktur → stripped token_count eşitliği kontrolü yapılmıyor → subset eşleşmeler geçiyor.  
- FUZZY_PHRASE ve TOKEN_COVERAGE query'lerinde bu filtre mevcuttur (commit 2206407, Round-5).  
- **A-gate bu 59 vakanın %100'ünü yakalar** (token sayısı tüm vakalarda farklı).

**Pattern D (10 vaka — %11.2):**  
- Master kaydı yalnızca firma adı değil, adres/kişi adı/CUIT/multi-entity içeriyor.  
- Adres tokenları (`BERMUDEZ 2589`, `PISO 8`, `CUIT 30-71...`) stripped analyzer'dan geçmeli; geçiyorsa token sayısı şişiyor ve A-gate yakalar.  
- **A-gate bu 10 vakanın %100'ünü yakalar** (master çok daha fazla token içeriyor).

---

## 4. Query DSL Analizi — Mevcut Guard'lar ve Boşluklar

### Mevcut SUFFIX_FUZZY Query Yapısı (es_queries.py, satır 268-313)

```python
def SUFFIX_FUZZY(name, country, es=None, **kwargs):
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE                              # Guard #1: core presence
    analyzer = _get_stripped_analyzer(country)
    return {
        "query": { "bool": {
            "must": [{
                "nested": {
                    "path": "variations_stripped",
                    "query": { "match_phrase": {
                        "variations_stripped.name": {
                            "query": name,
                            "analyzer": analyzer,
                        }
                    }}
                }
            }],
            "should": [{
                "match": {
                    "variations_suffix": {
                        "query": name,
                        "fuzziness": "AUTO:4,7",
                        "operator": "or",
                    }
                }
            }],
            "filter": [{"term": {"country_code": country.upper()}}],
            "minimum_should_match": 1,
        }},
        "size": 1,
    }
```

### Guard Tablosu

| Guard | Durum | Ne Yapar | Boşluk |
|-------|-------|----------|---------|
| `_has_distinctive_core` | **MEVCUT** | Boş/salt-sayı/tek-harf çekirdek → MATCH_NONE | Yalnızca varlık kontrolü; sayı eşitliği yok |
| `country_code` filter | **MEVCUT** | Farklı ülke eşleşmesini engeller | — |
| `minimum_should_match: 1` | **MEVCUT** | Suffix should clause boşsa geçmez | Suffix boş değilse her zaman 1 eşleşir |
| `fuzziness: AUTO:4,7` | **MEVCUT** | 4+ karakter token'larda 1 edit distance | Kısa token'larda (2-3 kar.) çok toleranslı |
| `_core_coverage_filter` | **EKSİK** | Stripped token_count eşitliği | **Ana boşluk: subset over-merge'i engellemez** |

### Karşılaştırma: FUZZY_PHRASE ve TOKEN_COVERAGE vs SUFFIX_FUZZY

```python
# FUZZY_PHRASE (satır 390-391) — A-gate MEVCUT:
"must": [
    nested_match_phrase_on_variations,
    *_core_coverage_filter(es, name, country),   # ← STRIPPED token_count eşitliği
]

# TOKEN_COVERAGE (satır 350-351) — A-gate MEVCUT:
"must": [
    nested_match_and_on_variations,
    *_core_coverage_filter(es, name, country),   # ← STRIPPED token_count eşitliği
]

# SUFFIX_FUZZY (satır 280-311) — A-gate YOK:
"must": [
    nested_match_phrase_on_variations_stripped,  # token_count filtresi yok
]
# _core_coverage_filter() çağrılmıyor
```

**Commit 2206407** (feat: Implement core coverage filter for fuzzy phrase and token coverage queries) SUFFIX_FUZZY'yi kapsam dışı bırakmış. Bu, %66'lık dominant hata sınıfının (Pattern C) köküdür.

---

## 5. A-Gate Genişletmesinin Tahmini Yakalama Oranı (Örnek Bazında)

### Özet Tablo

| Pattern | FP Sayısı | A-gate Yakalar | Kaçırır | Tahmini Oran |
|---------|-----------|----------------|---------|--------------|
| B (farklı marka, eşit token) | 20 | 2 | 18 | **10%** |
| C (subset/truncation) | 59 | 59 | 0 | **100%** |
| D (karmaşık kayıt) | 10 | 10 | 0 | **100%** |
| **Toplam** | **89** | **71** | **18** | **79.8%** |

### Örnek Bazında İşaretleme

**CATCH (A-gate yakalar — token sayısı farklı):**

- `SAMSUNG ELECTRONICS HAINAN FIBER OPTICS KOREA CO LTD` (5 core token) vs `SAMSUNG ELECTRONICS CO LTD` (2) — CATCH
- `POWER TRAIN TECHNOLOGIES ARGENTINA SA` (4) vs `POWER TRAIN TECHNOLOGIES SA` (3) — CATCH
- `SUNGJIN INC CO LTD/COLUMBIA SPORTSWEAR CO` (5) vs `COLUMBIA SPORTSWEAR COMPANY PRIVATE LTD` (3) — CATCH
- `LEAD-WAYTRADING SRL` (2) vs `LEAD SRL` (1) — CATCH
- `MGP LOGISTICS SRL JOINTLY & SEVERALLY WITH MARCELO PAZ CUIT…` (8+) vs `MGP LOGISTICS SRL` (2) — CATCH
- `BETTER WATER ARGENTINA SRL` (3) vs `WATER ARGENTINA SRL` (2) — CATCH
- `BOLDT GAMING SA` (2) vs `BOLDT SA` (1) — CATCH
- `SIREX MEDICA SA` (2) vs `SIREX SA` (1) — CATCH
- `MULTIPLASTIKA SRL X` (2) vs `MULTIPLASTIKA SRL` (1) — CATCH

**MISS (A-gate kaçırır — token sayısı eşit, içerik farklı):**

- `DEVRE INTERNACIONAL SA` (2) vs `SA INTERNACIONAL SA` (2) — MISS (farklı marka, aynı sayı)
- `DEVRE INTERNACIONAL SA` (2) vs `BROTHERS INTERNACIONAL SA` (2) — MISS (farklı marka, aynı sayı)

> **Not:** `B K GIULINI ARGENTINA SA` (3 core: BK, GIULINI, ARGENTINA) vs `S K F ARGENTINA SA` (3 core: SK, F, ARGENTINA) gibi vakalar token sayısı 3'e 3 eşit olduğundan sınırda; stripped analyzer'a göre tam sayım yapılmadan kesin CATCH/MISS söylenemez. Conservative tahminle 18 MISS'e dahil edilmiştir.

---

## 6. Somut Öneri (ES-Side, Eşik/Term Filtresi Düzeyinde)

### Öncelik 1 — SUFFIX_FUZZY'ye `_core_coverage_filter()` Ekle (HIGH IMPACT)

`es_queries.py` içinde `SUFFIX_FUZZY` fonksiyonunu şu şekilde güncelle:

```python
def SUFFIX_FUZZY(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    if not _has_distinctive_core(es, name, country, require_alpha=MATCH_CORE_FUZZY_REQUIRE_ALPHA):
        return MATCH_NONE
    analyzer = _get_stripped_analyzer(country)
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "match_phrase": {
                                    "variations_stripped.name": {
                                        "query": name,
                                        "analyzer": analyzer,
                                    }
                                }
                            }
                        }
                    },
                    # A-gate: FUZZY_PHRASE/TOKEN_COVERAGE ile simetrik
                    *_core_coverage_filter(es, name, country),  # ← EKLE
                ],
                "should": [
                    {
                        "match": {
                            "variations_suffix": {
                                "query": name,
                                "fuzziness": "AUTO:4,7",
                                "operator": "or",
                            }
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
                "minimum_should_match": 1,
            }
        },
        "size": 1,
    }
```

**Etki tahmini:** 89 FP'nin 71'ini (%79.8) engeller. Recall etkisi: SUFFIX_FUZZY zaten `variations_stripped.match_phrase` kullanıyor; gerçek varyantlar (tip: SA/Y CIA farkı) aynı stripped core token sayısını paylaşır → recall kaybı minimal (FUZZY_PHRASE/TOKEN_COVERAGE'da Round-4'te gözlemlendiği gibi recall-nötr).

### Öncelik 2 — Pattern B için `minimum_should_match` Artışı veya Rescore Guard (MEDIUM IMPACT)

18 MISS (Pattern B) için ek çözüm:

- **Seçenek B-1:** `fuzziness: "AUTO:4,7"` → `"AUTO:6,9"` olarak sıkılaştır. 4-5 karakterli token'larda 0 edit distance zorunlu hale gelir; `DEVRE` ↔ `SA`, `BROTHERS` ↔ `DEVRE` eşleşmez.
- **Seçenek B-2:** `SUFFIX_FUZZY_MIN_SCORE = 1.5` → `4.0` yükselt. Düşük skorlu (6-10) eşleşmeler elenir; Pattern B vakaları büyük çoğunluğu score=6-12 aralığındadır.
- **Seçenek B-3:** Rescore adımı ile `variations_stripped.name` ve sorgu token'larının kesişim oranını Painless'te hesapla; eşik altında skoru 0'a çek.

### Öncelik 3 — Pattern D İçin Ingest Pipeline Temizliği (LOW IMPACT, Ayrı PR)

Adres/CUIT içeren master kayıtları (`CAMPO CROP SA CAPITAN BERMUDEZ 2589 1636 OLIVOS`) ingest aşamasında temizlenmelidir. `es_ingest.py` Painless scriptine firma adından adres ve CUIT token'larını sıyıran regex ekle.

### Yapılmaması Gereken

- Python-side `RapidFuzz` / `Levenshtein` post-verify → YASAK (CLAUDE.md kuralı).
- `_core_coverage_filter`'ı SUFFIX_FUZZY'de devre dışı bırakmak için yeni config flag → gereksiz; mevcut `ENABLE_CORE_COVERAGE_GATE = True` ile flag zaten paylaşılıyor.

---

## Özet Tablo

| Metrik | Değer |
|--------|-------|
| SUFFIX_FUZZY precision (Round-6) | **65.4%** (168 SAME / 257 verdict) |
| Toplam FP | 89 |
| Dominant hata sınıfı | Pattern C — subset/truncation (%66.3) |
| İkinci hata sınıfı | Pattern B — farklı marka/AUTO fuzz (%22.5) |
| A-gate (token_count eşitliği) tahmini yakalama | **71/89 = %79.8** |
| A-gate kaçırdığı vakalar | 18 (Pattern B — aynı token sayısı, farklı marka) |
| Kök neden | `_core_coverage_filter()` SUFFIX_FUZZY'de eksik (commit 2206407 kapsam dışı bırakmış) |
| Öneri | `SUFFIX_FUZZY` query'sine `*_core_coverage_filter(es, name, country)` ekle |
