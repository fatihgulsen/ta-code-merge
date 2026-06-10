# Round-4 — Reindex + Rematch Validation (acronym-glue + distinctive-core gate AKTİF)

**Tarih:** 2026-06-10
**Branch / commit:** `main` @ `b1a7abb` (+ önemsiz uncommitted whitespace in `main_processor.py`)
**Index:** `living_companies_v1` · DB: `p7_firms_v2` (market_calculus, salt-okunur)
**Kapsam:** Reindex sonrası glue+gate doğrulama; kısmi rematch üzerinde oran-bazlı precision ölçümü; A/B/C hata sınıfı kapanma kanıtı; #4 min_score kararı.

> ⚠️ **KISMİ REMATCH UYARISI (kritik):** Rematch **119.500 / 530.876 kayıtta (%22,5) DURMUŞ** durumda — çalışan `main_processor.py` süreci yok, sayaç 25 sn boyunca sabit kaldı. 411.376 kayıt hâlâ `match_type IS NULL`. **Precision metrikleri (ADIM 1/2/4) işlenmiş eşleşmeler üzerinde geçerlidir; recall/under-merge (ADIM 3) %77 işlenmemiş kayıt nedeniyle GÜVENİLİR DEĞİL ve id-sıralı dilim yanlıdır.** Tüm karşılaştırmalar oran-bazlıdır. (Kullanıcı kararı: kısmi snapshot'ta ölç.)

---

## 1. ADIM 0 — Yeni kod CANLI mı? (KAPI: GEÇTİ ✅)

| Kontrol | Beklenti | Sonuç | Durum |
| :-- | :-- | :-- | :--: |
| `es_manager.acronym_glue_active(es)` | True | **True** | ✅ |
| `_analyze C.M.S.A.D.C` | `['cmsadc']` | `['cmsadc']` | ✅ |
| `_analyze B.A.T` | `['bat']` | `['bat']` | ✅ |
| `_analyze S.A.P.I.` | `[]` (yasal-ek strip) | `[]` | ✅ |
| `_analyze VF OUTDOOR MEXICO S.A.` | `outdoor`+`vf` | `['outdoor vf']` | ✅ |
| `_analyze M S.A.` (degenere) | tek-harf `m` | `['m']` | ✅ (gate yakalamalı) |
| `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` | 2 | 2 | ✅ |
| `ENABLE_CORE_GATE` | True | True | ✅ |
| `MATCH_CORE_MIN_TOKEN_LEN` | 2 | 2 | ✅ |
| `MATCH_CORE_FUZZY_REQUIRE_ALPHA` | True | True | ✅ |
| PHONETIC / NGRAM match_type | ≈0 | **0** (hiç yok) | ✅ |

**match_type dağılımı (işlenmiş 119.500):**

| match_type | adet | işlenmişin %'si |
| :-- | --: | --: |
| NEW_MASTER | 96.761 | 81,0% |
| STRIPPED_EXACT | 12.409 | 10,4% |
| FUZZY_PHRASE | 8.036 | 6,7% |
| TOKEN_COVERAGE | 1.951 | 1,6% |
| SUFFIX_FUZZY | 340 | 0,3% |
| EXCLUDED | 3 | <0,01% |
| **(NULL = işlenmemiş)** | **411.376** | — |

### ★ Gate kanıtı (ADIM 0.4) — magnet master'lar KAYBOLDU
- **Max master grup boyutu = 19** (Round-3: max magnet **72**; ayrıca 31/28'lik magnetler).
- Round-3'teki fp `m`/`g`/`t` magnet master'ları (72/31/28 üye) snapshot'ta **yok** — top-12 master boyutu 19,19,17,16,15… ile başlıyor, hiçbiri degenere değil.
- Degenere isimler (`M S.A.`→`m`, tek-harf akronim) gate tarafından **NEW_MASTER**'a yönlendiriliyor (aşağıda doğrulandı).

### ★ EXCLUDED anomalisi (ADIM 0.5) — AÇIKLANDI
Round-3'te 166k'da 1342 EXCLUDED vardı; bu snapshot'ta yalnız **3**:
```
'Sin Razon Social'              → EXCLUDED: placeholder
'Razon Social no determinada'   → EXCLUDED: placeholder
'NULL'                          → EXCLUDED: na_marker
```
**Neden düştü:** EXCLUDED filtresi yalnızca **tam placeholder string**'leri yakalıyor. Round-3'te magnet'e düşen degenere isimler (`M S.A.`, `#N/A 300`, tek-harf akronim) artık **gate tarafından NEW_MASTER**'a yönlendiriliyor (EXCLUDED'a değil). Yani: garbage artık magnet OLUŞTURMUYOR; EXCLUDED sayısının çökmesi gate'in çalıştığının dolaylı kanıtı, bir regresyon değil. `#N/A`/numeric placeholder'lar gerçek master'a sızmıyor (ADIM 2-B).

---

## 2. ADIM 1 — ★ HEADLINE: Kalibre RASTGELE precision

**qa4 deseni** (rastgele 400 gerçek eşleşme, master-grup yargısı, 40 Haiku batch, seed=20260605). Havuz mevcut DB'den yeniden üretildi (22.736 eşleşme: STRIPPED 12.409 · FUZZY 8.036 · TOKEN 1.951 · SUFFIX 340).

| Metrik | Round-3 (%31, eski) | **Round-4 (reindex+gate, kısmi)** | Δ |
| :-- | :--: | :--: | :--: |
| **Record-level precision** | %90,3 | **%90,0** (40/400 yanlış) | ~düz |
| **Stage-weighted precision** | ~%90,3 | **%89,4** | ~düz |
| Master-level temiz | — | %81,5 (322 CORRECT / 64 OVER_MERGE / 9 GARBAGE) | — |

**Stage-bazlı precision (record-level):**

| Stage | Round-3 | **Round-4** | Δ | Not |
| :-- | :--: | :--: | :--: | :-- |
| STRIPPED_EXACT | %97,5 | **%98,6** (218/221) | **+1,1** | akronim çökmesi kapandı |
| FUZZY_PHRASE | %75,7 | **%83,6** (117/140) | **+7,9** | iyileşti |
| TOKEN_COVERAGE | %61,8 | %53,3 (16/30) | −8,5 | n=30 küçük; kişi-adı garbage |
| SUFFIX_FUZZY | %71,4 | %100 (9/9) | +28,6 | n=9 çok küçük |

**Hata-kaynağı payı (yanlış kayıtlar arasında):** FUZZY_PHRASE %55 · TOKEN_COVERAGE %38 · STRIPPED_EXACT **%5** (Round-3'te %19) · NEW_MASTER %2.

### Yorum: precision neden ~%90'da sabit kaldı (beklenti %93-94 değildi)?
- STRIPPED_EXACT zaten %97,5 idi ve en büyük populasyon (12.409). Akronim düzeltmesi onu yalnız %98,6'ya taşıdı → ağırlıklı ortalamayı az hareket ettirdi.
- A-sınıfı (akronim) **kapandı** ama yerini **C-sınıfı + truncation-shell + kişi-adı** aldı; bunlar glue/gate ile çözülmeyen, **skor-tabanlı/yapısal** hatalar (ADIM 4).
- Net: glue+gate hatanın **bileşimini** değiştirdi (A→C kayması), toplam oranı değil. %93-94'e çıkmak min_score/core-coverage gerektirir ve veri bunun **kolay olmadığını** gösteriyor (aşağıda).

---

## 3. ADIM 2 — ★ A / B / C sınıf durumu

### A-sınıfı (akronim magnet) → **KAPANDI** ✅ (kanıtlı)
ES `fingerprint_analyzer` ile size≥5 master'ların üye fp'leri çıkarıldı; ≥%50 üyesi degenere (boş / tek-harf / salt-numeric) fp olan master = magnet.

| Metrik | Round-3 | **Round-4** |
| :-- | :--: | :--: |
| size≥5 master | 207 üye / 13 magnet | **635 master, 0 magnet, 0 magnet-üye** |
| max magnet boyutu | 72 | **yok (max master 19)** |

→ Gate tek-harf/degenere çekirdekleri (`m`, `g`, `t`) NEW_MASTER'a yönlendirerek akronim magnet'leri **yapısal olarak yok etti**. STRIPPED hata payı %19→%5.

### B-sınıfı (`#N/A`/harf-parçası sızma) → **KISMEN kapandı** ⚠️
- **Tam garbage (`#N/A`, salt-numeric, tek-harf) bir master'a SIZMIYOR** — gate `require_alpha` + `MATCH_CORE_MIN_TOKEN_LEN=2` bunları NEW_MASTER/EXCLUDED'a atıyor. ✅
- **AMA 2-3 harfli akronim parçaları hâlâ FUZZY_PHRASE ile düşük skorda sızıyor:** `TSS`, `NYK`, `GR`, `EM`, `SPM`, `M.P`, `A.S`… (skor 6-15). **Bu bir gate AÇIĞI değil, gate'in tasarım sınırı:** `_has_distinctive_core` "≥2 karakterli alfabetik tek token" gördüğünde geçer → `GR`→`gr` (2 char, alpha) **gate'i geçer**. Bunların bir kısmı gerçek (NYK Line, AAK), bir kısmı over-merge garbage (SPM). → Bu artık **skor problemi** (ADIM 4), gate problemi değil.

### C-sınıfı (farklı-marka jenerik-kelime) → **BASKIN KALAN hata** ✅ (teyit)
A kapandığı için C artık dominant. qa4 yanlış örneklerinden:
- **Farklı-marka jenerik:** `WORLDWIDE LOGISTICS`≠`MENLO`, `ENERGIA CHIHUAHUA`≠`ENERGIA ELECTRICA…`, `IND SUPPLY`≠`ATLAS INDUSTRIAL SUPPLY`, `HI TECH`≠`TECHNOLOGY ALIMENTICIA`.
- **Truncation-shell (YENİ alt-sınıf):** `INTER MEX MATERIALES DE`, `TUBERIAS Y VALVULAS DEL`, `GALERIA PRODUCTORA DE` — kesik isimler FUZZY_PHRASE ile yanlış master'a giriyor.
- **Kişi-adı garbage (TOKEN_COVERAGE):** `ABEL SANCHEZ RUVALCABA`, `JOSE CARLOS COSS LUNA`, `FRANCISCO LUIS GRACIA MARQUEZ` — şahıs adları firma sanılıp gruplanıyor.

---

## 4. ADIM 3 — Recall iki yönlü (⚠️ kısmi veri — sınırlı)

> Snapshot %22,5 işlenmiş; NEW_MASTER **%81,0** (96.761/119.500). Bu oran **yapay olarak yüksek**: erken-id kayıtlar master oluyor, gerçek duplikatları (hâlâ `NULL`) henüz katılmadı. **Mutlak master-sayısı / recall karşılaştırması bu dilimde yapılamaz.** Round-3'ün full sayılarıyla (HALLIBURTON/FLEXTRONICS/SIEMENS master sayıları) kıyas elma-armut olur — yapılmadı.

### ★ Glue recall KAZANCI — YAPISAL olarak teyit edildi ✅
Absolut sayı yerine fingerprint-tutarlılığı (glue'nun gerçek kaldıracı) ES `_analyze` ile doğrulandı:

| Varyantlar | Fingerprint | Tutarlı? |
| :-- | :-- | :--: |
| `HALLIBURTON DE MEXICO` / `HALLIBURTON` | `halliburton` / `halliburton` | ✅ |
| `VF OUTDOOR MEXICO S.A.` / `V.F. OUTDOOR` | `outdoor vf` / `outdoor vf` | ✅ (akronim glue) |
| `KUEHNE + NAGEL` / `KUEHNE NAGEL S.A. DE C.V.` | `kuehne nagel` / `kuehne nagel` | ✅ |

→ Reindex, akronim/suffix/geo-token varyantlarını **tutarlı fingerprint'e** indiriyor. Rematch **tamamlandığında** bu varyantlar tek master'da toplanacak (bölünme azalacak). Kısmi veride sayısal teyit mümkün değil — **rematch bittiğinde ölçülmeli.**

### Gate recall MALİYETİ — modest
- Gate degenere isimleri NEW_MASTER yapıyor; **name≤4 karakter olan NEW_MASTER = yalnız 137** kayıt. Yani gate'in under-merge maliyeti mutlak olarak küçük.
- Genel NEW_MASTER %81 — ama bu kısmi-dilim eseri, gate eseri değil; net gate-kaynaklı recall kaybı tam rematch'siz ölçülemez.

---

## 5. ADIM 4 — ★ KARAR: #4 min_score kalibrasyonu

Sampled eşleşmelerin `match_score` dağılımı LLM-onaylı DOĞRU vs YANLIŞ olarak ayrıldı.

**FUZZY_PHRASE (mevcut min=5, n=140 sampled):** yanlışlar skor aralığına **yayılmış**, düşük skora kümelenmemiş (≥30'da bile 1 yanlış var).

| Eşik (drop-below) | Kesilen yanlış | Kaybedilen doğru |
| :--: | :--: | :--: |
| 7 | 1/23 | 0 |
| 9 | 1/23 | 2 |
| 11 | 6/23 | 8 |
| 13 | 11/23 | 17 |

**TOKEN_COVERAGE (mevcut min=3, gözlenen min=4, n=30 sampled):** yanlışların çoğu (6/14) **yüksek skorda** (≥30) — kişi-adı garbage yüksek token-coverage skoru üretiyor.

| Eşik | Kesilen yanlış | Kaybedilen doğru |
| :--: | :--: | :--: |
| 11 | 3/14 | 1 |
| 13 | 4/14 | 2 |
| 15 | 5/14 | 3 |

### Karar / öneri
1. **min_score TEK BAŞINA künt bir kaldıraç.** Baskın residual hatalar (C-sınıfı farklı-marka, truncation-shell, kişi-adı) doğru eşleşmelerle **aynı skor aralığında** → eşik yükseltmek recall'ı orantısız vurur. min_score ile %97-98'e ulaşılamaz.
2. **Düşük-riskli, yapılabilir ayar (öneri):**
   - **TOKEN_COVERAGE min_score 3 → 11**: ~%21 TOKEN hatası keser, ~1 sampled doğru kaybeder (populasyonda ~küçük). Net pozitif.
   - **FUZZY_PHRASE min_score 5 → 9**: neredeyse bedava (1 yanlış kes, 2 doğru kaybet) ama düşük etki; bare-akronim sızıntısını (`ALCATEL`@9, `GR`@10) hafifletir.
3. **Gerçek çözüm yapısaldır — ayrı çekirdek-coverage tasarımı.** Eşleşen master'ın **ayırt edici çekirdeğini** adayın çekirdeğinin KAPSAMASI zorunluluğu (truncation-shell `…DE`/`…DEL` ve generic-word farklı-marka'yı keser). **clean-analyzer token_count GÜVENLİ DEĞİL** (synonym genişlemesi; Round-3'te recall 8/10→4/10 düşürdü, geri alındı). → **STRIPPED-tabanlı core-coverage** tasarlanmalı (Python fuzzy YOK; ES STRIPPED analyzer token kesişimi).

### ★ ALCATEL subset durumu
`ALCATEL` (tek kelime) → FUZZY_PHRASE **skor 9** ile bir master'a katılmış; çevresinde çok sayıda `ALCATEL LUCENT MEXICO …` NEW_MASTER/STRIPPED var. Subset over-merge **mekanizması hâlâ aktif** (kısa/jenerik token, uzun fraza düşük skorla giriyor). min_score 5→9 bunu sınırda keser; kalıcı çözüm core-coverage (ALCATEL ⊄ ALCATEL LUCENT çekirdeği).

---

## 6. ADIM 5 — 5-TUR ÖNCE/SONRA tablosu

| Metrik | 06-02 (phon/ngram açık) | 06-03 (rematch açık) | R3 (%31, eski analyzer, gate KAPALI) | **R4 (reindex+gate, %22,5 kısmi)** |
| :-- | :--: | :--: | :--: | :--: |
| Kalibre RASTGELE precision | — | — | %90,3 | **%90,0** (stage-w %89,4) |
| STRIPPED_EXACT precision | — | — | %97,5 | **%98,6** ↑ |
| FUZZY_PHRASE precision | — | — | %75,7 | **%83,6** ↑ |
| TOKEN_COVERAGE precision | — | — | %61,8 | %53,3 (n=30) |
| SUFFIX_FUZZY precision | — | — | %71,4 | %100 (n=9) |
| max magnet/master boyutu | — | 1.181 | 72 | **19** ↓↓ |
| akronim-magnet sayısı/üye | yüksek | %95,9 master OM | 13 / 207 | **0 / 0** ✅ |
| PHONETIC/NGRAM üye | %80/%95 | %95,9/%98,1 | 0 | **0** ✅ |
| EXCLUDED | — | — | 1342 (@166k) | **3** (gate→NEW_MASTER) |
| NEW_MASTER oranı | — | %81,7 kayıp | %84,6 (nme) | %81,0 (kısmi-yanlı) |
| A-sınıfı (akronim) | — | — | aktif (%19 STRIPPED hata) | **kapandı** (%5) ✅ |
| B-sınıfı (#N/A/parça) | — | — | aktif | tam-garbage kapandı; 2-3 harf akronim **skora kaldı** ⚠️ |
| C-sınıfı (farklı-marka) | — | — | en büyük kalan | **baskın kalan** (≈%55 FUZZY hata) |

---

## ★ EN YÜKSEK ETKİ ÖZETİ (3-5 madde)

1. **Glue+gate CANLI ve yapısal hedefini tuttu:** akronim magnet'ler **tamamen yok** (13→0, max master 72→19), PHONETIC/NGRAM=0, degenere garbage NEW_MASTER'a yönleniyor (EXCLUDED 1342→3 bunun kanıtı). **A-sınıfı kapandı.**
2. **Toplam precision ~düz (%90,0 vs %90,3) — ama hata BİLEŞİMİ değişti:** STRIPPED %97,5→98,6, FUZZY %75,7→83,6 iyileşti; akronim hata payı %19→%5. Yerini **C-sınıfı (farklı-marka) + truncation-shell + kişi-adı** aldı; bunlar glue/gate kapsamı dışında.
3. **min_score künt bir kaldıraç:** residual over-merge'ler doğru eşleşmelerle aynı skor bandında. Tek başına %97-98 vermez. Düşük-riskli ayar: **TOKEN_COVERAGE 3→11** (+ opsiyonel FUZZY 5→9).
4. **Gerçek kazanım için yapısal çekirdek-coverage gate gerek** (STRIPPED-tabanlı, ES-side; clean-analyzer token_count DEĞİL — recall'ı kırar). Bu, truncation-shell + farklı-marka + ALCACEL-subset'i tek hamlede hedefler.
5. **⚠️ Bu ölçüm %22,5 kısmi/yanlı rematch üzerinde:** precision güvenilir, **recall ölçülemedi.** Glue recall kazancı yapısal olarak teyitli ama sayısal teyit için **rematch'in 530k'ya tamamlanması** ve tek-seferde yeniden ölçüm şart.

---

### ONAY İSTEĞİ
Şu adımlardan hangisini/hangilerini uygulayayım?
- **(a)** `config.STAGES` → TOKEN_COVERAGE min_score 3→11 (+ opsiyonel FUZZY_PHRASE 5→9), testlerle.
- **(b)** STRIPPED-tabanlı **core-coverage gate** tasarım+TDD (C-sınıfı + truncation-shell + ALCATEL-subset hedefli).
- **(c)** Önce rematch'i 530k'ya tamamlatıp (senin write-pipeline'ın) tam/önyargısız yeniden ölçüm.
- **(d)** Yalnız raporu sabitle, kod değişikliği yapma.
