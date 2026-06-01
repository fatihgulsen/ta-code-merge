# Eşleştirme Kalitesi QA Bulgu Raporu

**Tarih:** 2026-06-01
**Veri:** `market_calculus.p7_firms_v2`, ülke = MX (tek ülke), salt-okunur analiz
**Araç:** `analysis/run_qa.py` (over-merge + split dedektörleri), `analysis/es_verify.py` (ES hibrit doğrulama)
**İlgili tasarım:** [spec](../superpowers/specs/2026-06-01-match-quality-qa-analysis-design.md) · [plan](../superpowers/plans/2026-06-01-match-quality-qa-analysis.md)

---

## 1. Yönetici Özeti

- İncelenen eşleşmiş kayıt: **62.950** (toplam tablonun ~%12'si; eşleştirme yarım kalmış).
- **Over-merge (yanlış birleşme) adayı: 741.** En kritik vaka: tek master'da **49 farklı firma**, `PHONETIC_MATCH` ile yasal-ek (`S.A. DE C.V.`) fonetik çakışması üzerinden birleşmiş.
- **Split (yanlış bölünme) adayı: 5187 (ham).** Bunların önemli kısmı GERÇEK under-merge (örn. VALEO 11 master, JABIL CIRCUIT 13, LEVI STRAUSS 12); bir kısmı dedektör false-alarm'ı (tek-jenerik-token imza).
- **Uygulanan düzeltme:** `PHONETIC_MATCH` kısa-çekirdek guard'ı (Faz 3, ayrı commit) — tek ayırt edici token'lı isimlerin çöp/dev master'lara sızmasını engeller.

---

## 2. Metrikler

### 2.1 match_type dağılımı (62.950 kayıt)

| match_type | adet | not |
| :--- | ---: | :--- |
| NEW_MASTER | 58.096 | konsolide edilmemiş tekil |
| SUFFIX_FUZZY | 1.537 | |
| PHONETIC_MATCH | 1.033 | **over-merge ana kaynağı** |
| FUZZY_PHRASE | 811 | |
| TOKEN_COVERAGE | 502 | |
| STRIPPED_EXACT | 360 | |
| CANONICAL_EXACT | 309 | |
| EXACT_FUZZY | 159 | **legacy** (güncel STAGES'te yok) |
| NGRAM_MATCH | 130 | |
| ADDRESS_CLEAN_MATCH | 12 | **legacy** |
| SUBSET_MATCH | 1 | **legacy** |

### 2.2 Master grup-boyutu dağılımı

| üye sayısı | master adedi |
| ---: | ---: |
| 49 | 1 |
| 11 | 1 |
| 9 | 1 |
| 8 | 7 |
| 7 | 5 |
| 6 | 12 |
| 5 | 22 |
| 4 | 95 |
| 3 | 451 |
| 2 | 3.371 |
| 1 | 54.133 |

### 2.3 PHONETIC_MATCH skor dağılımı

min **4**, medyan **13**, max **60**, adet **1.033**.
→ Over-merge kurbanları 8–27 aralığında skorladığından `min_score` yükseltmek (medyan 13) meşru eşleşmeleri de keser. **min_score ayarı uygun çözüm değildir; yapısal guard gerekir.**

---

## 3. Over-merge Bulguları

### 3.1 En kritik vaka — 49 üyeli PHONETIC çöp master (`143c0c54`)

Master'ın kök kaydı bir **gümrük beyanname satırı** (firma ismi değil):
`QHE LOGISTICS MEXICO, S. DE R.L. DE MEXICO Manzanillo EGM 1 HT2/EX/22-23/015 ... 94041000 200TC 100% COTTON FABRIC ...`

Buna bağlanan 48 firma birbirinden tamamen farklı: IGSA, WITTE, DIGA, AUDI MEXICO, KOHLER DE MEXICO, TOKAI DE MEXICO... Ortak payda: hepsinde `S.A. DE C.V.` yasal eki. Grup-içi çekirdek-token örtüşmesi **0.04**.

**ES doğrulama (hibrit, kanıt):**
- `WITTE, S.A. DE C.V.` (1-token çekirdek) → master `6b225073`, temsilci varyasyon `g r ad a y a s a c d v` (tamamen yasal-ek harflerinden oluşan ayrı bir **çöp master**), skor **27.0**. → Saf suffix-fonetik çakışması.
- `AUDI MEXICO S.A. DE C.V.` (2-token çekirdek) → 49-üyeli çöp master `143c0c54`, skor **11.16**. Dev token-çorbası `operator:and`'i tatmin ediyor (`mexico` mevcut + ikinci token fonetik çakışması).

**Kök-neden:** İki faktörün birleşimi:
1. **Çöp/aşırı-uzun master'lar** (gümrük satırları, sadece yasal-ek harfleri) fonetik mıknatıs gibi davranıyor.
2. **Kısa çekirdekli isimler** `PHONETIC_MATCH` + `operator:and` ile bu master'lara kolayca sızıyor.

### 3.2 Diğer PHONETIC over-merge örnekleri

- `08738cfa` (7 üye): YUEWEI / KIWI / SSIAA / CAU / WEWOW S.A. DE C.V. — tek-token yabancı isimler.
- `bf0aa4a0` (6 üye): M-II / J&J DUO / BOYEH / A.B. / I M D E S.A. DE C.V.

### 3.3 Legacy over-merge (güncel pipeline dışı — bilgi amaçlı)

- `EXACT_FUZZY` çöp placeholder birleşmesi: `#N/A 500 / #N/A 508 / ...` (birden çok master); `AB.M / ACM / AEM / ADM` (3-harf kodları).
- `NGRAM_MATCH` (`57b0f612`, 5 üye): farklı Hong Kong firmaları "HONG KONG LTD." üzerinden.

Bu match_type'lar (`EXACT_FUZZY`, `ADDRESS_CLEAN_MATCH`, `SUBSET_MATCH`) güncel `config.STAGES`'te bulunmaz — eski pipeline sürümünden kalma kalıntıdır; güncel-pipeline önerileriyle karıştırılmamalıdır.

---

## 4. Split (under-merge) Bulguları

Ham 5187 adayın iki alt sınıfı var:

### 4.1 GERÇEK under-merge (çok-token ayırt edici imza) — yüksek güven

Aynı firma onlarca master'a bölünmüş; yasal-ek/kısaltma varyantları ve truncation `STRIPPED_EXACT`/`CANONICAL_EXACT`'i bozuyor:

| imza | master sayısı | etkilenen kayıt | örnek |
| :--- | ---: | ---: | :--- |
| valeo sistemas electricos | 11 | 18 | "VALEO SISTEMAS ELECTRICOS S.A. DE Y" / "...,SA DE" / "...S DE RL" |
| jabil circuit mexico | 13 | 16 | "JABIL CIRCUIT DE MEXICO S DE CV" / "...,S.R.L." / "...S DE R.L" |
| levi strauss mexico | 12 | 13 | "LEVI STRAUSS DE MEXICO S.A. DE" / "...S.A. DE C.V." |
| industrias john deere | 12 | 13 | "INDUSTRIAS JOHN DEERE S" / "...S. DE R.L. DE C.V." |
| hennes mauritz servicios | 9 | 10 | "H&M HENNES & MAURITZ SERVICIOS S.A. D" varyantları |
| siemens | 9 | 9 | "SIEMENS S.A. DE C.V." vs "Siemens, S.A. de C.V" (case/noktalama) |
| pepe jeans mexico | 7 | 14 | "Pepe Jeans Mexico" truncation varyantları |
| ford motor | 5 | 12 | "FORD MOTOR CO" / "...COMPANY S.A." / "...CO S.A. DE C.V." |

**Kök-neden:** Suffix/şirket-tipi varyantları (`S.A. DE C.V.`, `S DE RL`, `S.R.L.`, truncated `S DE`, `SA DE`) ve noktalama/case farkları stripping sonrası **aynı çekirdeğe indirgenmiyor**; dolayısıyla exact/stripped stage'ler bu varyantları eşleştiremiyor ve her biri NEW_MASTER oluyor.

**ES doğrulama (hibrit, kanıt — `JABIL CIRCUIT DE MEXICO S DE CV`, MX):**

| stage | sonuç |
| :--- | :--- |
| `STRIPPED_EXACT` | **0 hit** — truncated ek (`S DE CV`) stripping'de tanınmadığından çekirdek eşleşmiyor |
| `CANONICAL_EXACT` | **0 hit** — token_count filtresi farklı-uzunluklu ek varyantlarında tutmuyor |
| `TOKEN_COVERAGE` | 1 hit (skor 20.98) — yalnızca *birebir* aynı token setine sahip varyantı buluyor; `operator:and` farklı ek-token'lı (cv vs rl vs srl) varyantları kaçırıyor |

Yani gerçek under-merge'ün kök-nedeni **suffix stripping'in truncated/varyant Meksika eklerini normalize edememesi**: STRIPPED_EXACT bu varyantları tek çekirdeğe (`jabil circuit mexico`) indirgeyebilseydi 13 master tek master'da birleşirdi.

### 4.2 Dedektör false-alarm (tek-jenerik-token imza) — düşük güven

`mexico`, `logistics`, `international`, `comercializadora`, `logistica`, `rqmt` gibi tek jenerik token'a inen imzalar farklı firmaları yanlışlıkla aynı split grubuna koyuyor (örn. imza=`mexico`: "M S.A. DE MEXICO" vs "P.Q.A. DE MEXICO" — gerçekte farklı firmalar).

**Dedektör iyileştirme önerisi:** split sinyalini imza uzunluğu ≥ 2 ayırt edici token ile sınırla (veya çok-yaygın tek token'ları hariç tut). Bu, `analysis/detectors.py` `detect_splits`'e basit bir guard ile eklenebilir (takip).

---

## 5. Optimizasyon Önerileri (öncelik sırasıyla)

1. **[UYGULANDI — Faz 3] PHONETIC_MATCH kısa-çekirdek guard'ı.** Çekirdek token sayısı `< PHONETIC_MIN_CORE_TOKENS` (=2) ise PHONETIC_MATCH eşleşme döndürmez. Tek-token kurbanları (WITTE, IGSA, KIWI, CAU, YUEWEI...) çöp master'lara sızmaktan kurtulur. Ödün: tek-kelimelik isimlerde fonetik typo recall'ü düşer — ancak exact/stripped stage'ler bunları zaten yakalar; fonetik son-çare fuzzy aşamasıdır.

2. **[TAKİP] Çöp/aşırı-uzun kayıtların master olmasını engelleyen ingest-seviyesi guard.** Gümrük satırları ve sadece yasal-ek harflerinden oluşan kayıtlar master olarak indekslenmemeli (uzunluk/anlamlı-token eşiği). 49-üyeli vakanın 2-token kurbanlarını (AUDI MEXICO, KOHLER MEXICO) tamamen çözer. `es_ingest.py`/`es_manager.py` kapsamı — ayrı plan, ayrı TDD.

3. **[TAKİP] Split için suffix-normalizasyon güçlendirme.** `S DE RL`, `S.R.L.`, truncated `S DE`, `SA DE` varyantlarını stripping'de tek çekirdeğe indir → VALEO/JABIL/LEVI STRAUSS/JOHN DEERE gibi gerçek under-merge'ler birleşir. Her desen ES doğrulamasıyla teyit edilmeli; ayrı RED→GREEN döngüsü.

4. **[TAKİP] Dedektör precision.** `detect_splits`'e imza-uzunluğu ≥ 2 guard'ı ekleyerek tek-jenerik-token false-alarm'larını ele.

---

## 6. Legacy Residue Notu

`EXACT_FUZZY` (159), `ADDRESS_CLEAN_MATCH` (12), `SUBSET_MATCH` (1) kayıtları güncel `config.STAGES` listesinde yer almaz. Bunlar eski pipeline sürümlerinden kalmıştır ve güncel kod davranışını yansıtmaz; güncel-pipeline optimizasyon kararlarına dahil edilmemiştir. Temiz bir ölçüm için tablonun güncel kodla yeniden eşleştirilmesi (taze koşu) ileride önerilir.
