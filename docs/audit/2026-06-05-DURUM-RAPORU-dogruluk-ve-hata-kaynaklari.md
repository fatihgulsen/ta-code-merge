# 📊 DURUM RAPORU — Eşleştirme Doğruluğu & Hata Kaynakları

**Tarih:** 2026-06-05 · **Branch:** `feat/phonetic-overmerge-guard`
**Veri:** `p7_firms_v2` (tümü MX, 530.876 satır) · **Rematch %31 tamamlandı (166.450 işlendi, snapshot statik)**
**Yöntem:** Kalibre edilmiş ölçüm — **rastgele** 400 eşleşme örneği + 172-batch şüpheli denetim, LLM (Haiku) yargısı. Salt-okuma.

> ⚠️ Sayılar oran-bazlı (rematch %31). Mutlak değerler 530k'da büyür ama **oranlar temsilîdir.** "Doğruluk" rastgele örneklemden; "%67" gibi önceki sayılar kasıtlı kötü-zenginleştirilmiş havuzdandı — bu rapordaki precision rakamı **rastgele = gerçekçi.**

---

## 1. 🎯 GENEL DURUM — Tek Bakışta

| Gösterge | Değer | Yorum |
| :--- | :---: | :--- |
| İşlenen kayıt | 166.450 / 530.876 (%31) | Rematch yarım |
| **Eşleşme YAPILAN** (bir master'a katılan) | **30.582** | Asıl "karar verdiğimiz" kayıtlar |
| Eşleşmeyen (NEW_MASTER) | 134.526 | Çoğu "ilk görülen" + bir kısmı KAÇIRILAN merge |
| Dışlanan (EXCLUDED, çöp) | 1.342 | Salt placeholder ✓ |
| **★ EŞLEŞME DOĞRULUĞU (precision)** | **~%90,3** | 30.582 eşleşmenin ~%90'ı DOĞRU |
| **★ Yanlış eşleşme (over-merge)** | **~%9,7 (~2.955 kayıt)** | Alakasız firma birleşmiş |
| Kaçırılan merge (recall açığı) | **YÜKSEK** | Aynı firma ayrı master'larda kalmış (aşağıda) |

> **Özet cümle:** Bir eşleşme yaptığımızda **10'da 9'u doğru** (precision ~%90). Ama **gerektiği halde eşleştirmediğimiz** çok firma var (recall düşük) — bu, phonetic/ngram'ı kapatmanın bedeli.

---

## 2. 🔴 HATALAR EN ÇOK NEREDEN? — Stage-bazlı (rastgele örnek, kalibre)

| Stage | Eşleşme hacmi | Doğruluk | Yanlış oranı | **Toplam hatadaki payı** |
| :--- | :---: | :---: | :---: | :---: |
| **STRIPPED_EXACT** | 22.049 (%72) | **%97,5** ✅ | %2,5 | %19 (~551) |
| **FUZZY_PHRASE** | 5.784 (%19) | %75,7 ⚠️ | %24,3 | **%48 (~1.405)** 🔴 |
| **TOKEN_COVERAGE** | 2.219 (%7) | **%61,8** 🔴 | %38,2 | %29 (~847) |
| **SUFFIX_FUZZY** | 530 (%2) | %71,4 | %28,6 | %5 (~151) |

### Okunuşu
- **STRIPPED_EXACT** eşleşmelerin **%72'sini** yapıyor ve **%97,5 doğru** — sistemin sağlam çekirdeği. Buradaki %2,5 hata = **akronim magnetler** (`B.A.T`/`C.M.S.A.D.C` → tek harfe çöküp birleşme).
- **FUZZY_PHRASE = hataların %48'i** (en büyük tek kaynak). Hacmi orta ama %24 yanlış → farklı markaları ortak kelimeyle birleştiriyor.
- **TOKEN_COVERAGE = en düşük doğruluk (%61,8)** + hataların %29'u. Gevşek örtüşme eşiği `#N/A` çöpünü ve farklı markaları yutuyor.

---

## 3. 🔬 HATALARIN 3 KÖK SINIFI (somut örnekler)

### A) Akronim çökmesi — STRIPPED_EXACT (hataların ~%19'u)
Noktalı baş-harf isimleri analyzer'da tek "junk" harfe çöküyor → alakasız firmalar aynı master'da:
`B.A.T`→`t`, `C.M.S.A.D.C`→`m`, `D.R.G`→`g`. En büyük magnet 72 üye (`m`).
**→ Bu oturumda ÇÖZÜLDÜ** (acronym-glue + min=2; reindex bekliyor).

### B) `#N/A` / harf-parçası çöp gerçek markaya sızıyor — TOKEN_COVERAGE (hataların büyük kısmı)
`#N/A 300` → **TOYOTA TSUSHO**'ya; `#N/A` → **QHE LOGISTICS**'e; `I.I.Q`/`Q.S.I` → MERIDIAN IQ'ya; `WI SC`/`UAE` → CASA HOMS/SAFRAN'a.
Sebep: `#N/A 300` (sayı içerdiğinden) EXCLUDED olmuyor + TOKEN_COVERAGE gevşek örtüşmeyle yapıştırıyor.
**→ token_count çekirdek-gate ile çözülür** (planlandı).

### C) Farklı markalar jenerik kelimeyle birleşiyor — FUZZY_PHRASE + TOKEN_COVERAGE (EN BÜYÜK kalan)
**CLARIANT ↔ LESCHACO** · **BANCO MEXICO ↔ BANCO SANTANDER** · **IMEX AGRO ↔ D.F.A. INC** · **ALKHORAYEF PETROLEUM ↔ ENERGY CORPORATION** · **COMERCIAL TRADE UP ↔ IE TRADE COMERCIAL**.
Ayrıca parent↔subsidiary (WHIRLPOOL CORP ↔ INDUSTRIAS ACROS WHIRLPOOL) ve kırpma belirsizliği (JABIL MX).
**→ glue/gate ÇÖZMEZ. FUZZY_PHRASE/TOKEN_COVERAGE precision sıkılaştırma gerekir** (öneri D).

---

## 4. 🟡 DİĞER YÜZ: RECALL (Kaçırılan Merge / Under-merge)

Precision (%90) sadece *yaptığımız* eşleşmeler için. Asıl büyük açık **yapmadığımız** eşleşmeler:

| Gösterge | Değer |
| :--- | :---: |
| Özdeş çekirdekli ama AYRI master grupları (multi-master, ≥1 NEW_MASTER) | **7.342 grup** |
| Bunlardan "birleşmeliydi" (LLM) | **~%85 (nme SHOULD_MERGE)** |
| Örnek bölünmeler | SIEMENS 8 master · FLEXTRONICS 78 · CUMMINS 74 · JOHN DEERE 62 |

Sebep: phonetic/ngram kapalı + yasal-ek kırpma varyantları (`SIEMENS S.A. DE C.V.` vs `SIEMENS MEXICO`) farklı fingerprint üretiyor. **Acronym-glue reindex'i bu recall'in bir kısmını da kazandırır** (aynı analyzer tutarlılığı), ama suffix-truncation normalizasyonu ayrı iş.

---

## 5. ✅ NE YAPILDI (bu oturum) / 📋 NE GEREKİYOR

| # | İş | Hangi hatayı çözer | Durum |
| :--- | :--- | :--- | :--- |
| 1 | `DEDUP_MIN_FINGERPRINT_TOKEN_LEN=2` | Akronim dedup magneti (kısmi) | ✅ Uygulandı |
| 2 | `acronym_glue` analyzer | **A sınıfı** (akronim çökmesi) | ✅ Uygulandı, doğrulandı — **reindex bekliyor** |
| 3 | **Ayırt-edici çekirdek GATE** (STRIPPED_EXACT + SUFFIX_FUZZY + TOKEN_COVERAGE + FUZZY_PHRASE) | **B sınıfı** (#N/A/harf-parçası) + A-artığı (`M S.A.`→`m`) | ✅ **Uygulandı, live_probe ile doğrulandı** |
| 4 | FUZZY_PHRASE + TOKEN_COVERAGE precision (min_score) | **C sınıfı** (farklı marka) — en büyük kalan | 📋 **min_score → rematch sonrası kalibre** (aşağıda) |
| 5 | Suffix-truncation canonical normalize | Recall (kaçırılan merge) | 📋 Sonraki faz |
| 6 | parent/subsidiary + kırpma → `dedup_reviewer` insan denetimi | Belirsiz vakalar | 📋 Otomatize edilemez |

### #3 GATE — uygulandı (es_queries.py `_has_distinctive_core`)
ES STRIPPED analyzer çıktısında ayırt edici çekirdek (≥`MATCH_CORE_MIN_TOKEN_LEN`=2 token) yoksa stage `MATCH_NONE` döner → kayıt NEW_MASTER olur. Karar %100 ES analyzer'ından (acronym_glue dahil); Python fuzzy/normalize YOK; guard'dır (PHONETIC/NGRAM deseni). Loose stage'lerde (TOKEN_COVERAGE/FUZZY/SUFFIX) ek **alfabetik** şart → `#N/A 300`→`['300']` bloklanır; STRIPPED_EXACT'te (tam eşleşme güvenli) salt-sayı korunur. config: `ENABLE_CORE_GATE`, `MATCH_CORE_MIN_TOKEN_LEN`, `MATCH_CORE_FUZZY_REQUIRE_ALPHA`. **live_probe: recall 8/10 KORUNDU** (hiçbir gerçek firma bloklanmadı), 2-harf marka (VF/3M) geçer.

### #4 — min_score kalibrasyonu (rematch sonrası, veri-güdümlü)
- **TOKEN_COVERAGE token_count eşitliği DENENDİ → GERİ ALINDI:** clean_analyzer synonym_graph genişlemesi sorgu/indeks token sayısını tutarsız kıldı → live_probe recall **8/10→4/10 düştü** (WITTE/VIBRACOUSTIC gerçek varyantları bloklandı). Bu yol KAPALI.
- Kalan `ALCATEL ⊂ ALCATEL LUCENT` subset over-merge'i (live_probe'da 1 ihlal) + farklı-marka birleşmeleri için **doğru kol `config.STAGES` min_score** (FUZZY_PHRASE 5.0, TOKEN_COVERAGE 3.0). Bunlar **skor-dağılımı görmeden kör ayarlanamaz** → reindex+rematch sonrası gerçek skorlarla kalibre edilmeli (projenin "önce ölç sonra ayarla" deseni). Çekirdek-coverage (token_count) clean-analyzer'da güvenli değil; STRIPPED tabanlı bir coverage gerekirse ayrı tasarlanmalı.

---

## 6. 🎯 %100'E GİDİYOR MUYUZ? — Dürüst Cevap

**Hayır, %100 gerçekçi değil.** Gerçekçi hedef:

| | Şimdi | 1+2+3 sonrası (tahmin) | +4 (FUZZY/TOKEN sıkı) sonrası | Teorik tavan |
| :--- | :---: | :---: | :---: | :---: |
| **Match precision** | ~%90,3 | ~%93-94 | **~%97-98** | ~%99 |
| Kalan hata | akronim+#N/A+marka | farklı-marka birleşmeleri | kırpma/parent belirsizliği | insan-denetim işi |

- **1+2+3** akronim (A) + #N/A sızma (B) sınıflarını büyük ölçüde kapatır → ~%93-94.
- **4** (asıl kalan) farklı-marka birleşmelerini (C, hataların %77'si) hedefler → ~%97-98.
- Son ~%2: `JABIL MX` tek başına JABIL mi? / parent↔subsidiary gibi **doğası gereği belirsiz** kararlar — bunlar `dedup_reviewer` insan-denetimi işidir, otomatik %100 imkânsız.
- **Recall (kaçırılan merge) ayrı eksendir** — precision %98 olsa bile bölünmüş firmalar (SIEMENS 8 master) ancak suffix-normalize + dikkatli fuzzy ile toparlanır.

---

## 7. 📌 EN YÜKSEK ETKİ SIRASI (öneri)

1. **Reindex + tam rematch** → acronym-glue'yu aktive et (A sınıfı kapanır, +recall). *Operasyonel karar: ne zaman?*
2. **token_count çekirdek-gate** (#3) → #N/A/harf-parçası sızması (B) kapanır. Reindex ile birlikte.
3. **FUZZY_PHRASE + TOKEN_COVERAGE precision sıkılaştırma** (#4) → **hataların %77'si** (C sınıfı). En yüksek precision kazancı.
4. **Suffix-truncation normalize** (#5) → recall (kaçırılan merge) — SIEMENS/FLEXTRONICS bölünmeleri.
5. Belirsiz vakalar → `dedup_reviewer` insan onayı.

> Artefaktlar: `C:/tmp/cand4_random.json`, `C:/tmp/qa4_results/*` (398 verdict, rastgele), `C:/tmp/qa2_summary.json` (şüpheli havuz), `docs/audit/2026-06-05-round3-unicode-config-dedup.md` (akronim detay). p7_firms_v2'ye YAZILMADI.
