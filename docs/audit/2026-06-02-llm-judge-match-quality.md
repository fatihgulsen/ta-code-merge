# Eşleştirme Kalite Denetimi — LLM-as-Judge (2026-06-02)

**Yöntem:** `p7_firms_v2` salt-okunur (SELECT) örneklendi; aday çiftleri/grupları
173 batch hâlinde **Haiku alt-ajanlarına** dağıtıldı; her grup için "aynı ticari
firma mı?" kararı **modele** verdirildi (Python'da fuzzy/Levenshtein kullanılmadı).
Token-örtüşme yalnızca *aday havuzu ön-elemesi* için kullanıldı — nihai yargı LLM'e ait.

> **Önemli bağlam:** Tüm veri tek ülke (**MX**, 530.876 satır). Bu nedenle
> `COUNTRY_LEAK` yapısal olarak imkânsız ve gözlemlenmedi. `country_code` hard-filter
> her stage sorgusunda mevcut (aşağıda doğrulandı). Ayrıca **462.276 satır hiç
> işlenmemiş** (`master_code` ve `match_type` NULL); denetim evreni işlenmiş **68.600**
> satırdır.

---

## 1. Özet Metrikler

| Havuz | Aday | LLM kararı | Yorum |
|---|---:|---|---|
| **Over-merge** (token-örtüşme <0.5) | 1.130 | **866 OVER_MERGE** / 264 CORRECT | Şüpheli adayların **%76,6'sı gerçek yanlış-birleşme** |
| **Split / under-merge** | 480 | **346 SHOULD_MERGE** / 127 ayrı / 7 diğer | Adayların **%72'si gerçek under-merge**; **~1.228 kayıt** birleşmeli |
| **Kontrol** (yüksek-örtüşme, "doğru" varsayılan) | 120 | 98 CORRECT / **22 OVER_MERGE** | Yüksek-örtüşmeli gruplarda bile **%18 over-merge** → sorun yaygın |

- **Over-merge havuzunda yanlış birleştirilen toplam kayıt: ~1.047** (`bad_ids`).
- Onaylı over-merge'lerin **%81'i** PHONETIC veya NGRAM kaynaklı.
- Over-merge'lerin **%12'si** çöp/geçersiz bir "seed" (NEW_MASTER) etrafında toplanmış
  (uzun gümrük beyanı dizesi, `#N/A`, yalnızca-suffix kısaltması).

---

## 2. Hata Tablosu — match_type × Over-merge Oranı

Üye-bazlı: over-merge-şüpheli master'lardaki üyelerden (NEW_MASTER hariç) kaçının
LLM tarafından "ait değil" (`bad_ids`) işaretlendiği. *Bu oran şüpheli örneklem
içindir — stage'in küresel hata oranı değil, **hangi stage'in yanlış-birleşmeyi
ürettiğinin** göstergesidir.*

| match_type | Yanlış üye | Toplam üye | Over-merge oranı | Değerlendirme |
|---|---:|---:|---:|---|
| **NGRAM_MATCH** | 115 | 121 | **95,0%** | 🔴 KRİTİK — neredeyse tamamı hatalı |
| **PHONETIC_MATCH** | 749 | 936 | **80,0%** | 🔴 KRİTİK — en yüksek hacim |
| **EXACT_FUZZY** | 64 | 104 | **61,5%** | 🟠 yüksek (çoğu çöp/`#N/A` veri) |
| **TOKEN_COVERAGE** | 37 | 82 | **45,1%** | 🟠 yüksek (subset/partial isim) |
| **SUFFIX_FUZZY** | 67 | 299 | **22,4%** | 🟡 orta |
| **FUZZY_PHRASE** | 16 | 139 | **11,5%** | 🟢 düşük |
| **CANONICAL_EXACT** | 3 | 35 | **8,6%** | 🟢 düşük (truncation/çöp) |
| **STRIPPED_EXACT** | 1 | 36 | **2,8%** | 🟢 çok düşük |

**Sonuç:** Hatalı birleşmeler ezici çoğunlukla **PHONETIC_MATCH** ve **NGRAM_MATCH**
stage'lerinden geliyor. Bu iki stage, paylaşılan **yasal-ek / ülke token'ları**
(`S.A. DE C.V.`, `MEXICO`, `USA INC`, `LLC`, `PTE LTD`) üzerinden ayırt edici çekirdek
isim olmadan eşleşiyor.

---

## 3. Örnek Vakalar

### 3.1 Over-merge (yanlış birleşme)

| master üye | culprit | örnek (farklı firmalar) | gerekçe |
|---|---|---|---|
| 52 | PHONETIC | QHE LOGISTICS + AUDI, KOHLER, VIBRACOUSTIC, IGSA, DIGA, WITTE… | Çöp gümrük-dizesi seed; 51 farklı firma yalnızca `S.A. DE C.V.` paylaşıyor |
| 11 | NGRAM | K LINE + ALPI, CORDIALSA, HASCOR, KOWI, WOORI… | `USA, INC.` suffix trigramı üzerinden 10 farklı firma |
| 8 | NGRAM | TEMPUR + NACOBRE, PLYCEM, SURREY, BELVEDERE… | `USA LLC` suffix'i üzerinden 7 farklı marka |
| 7 | EXACT_FUZZY | `#N/A 508`, `#N/A 600`, `#N/A 509`… | Tamamı bozuk/geçersiz veri (`#N/A`) |
| 7 | PHONETIC | YUEWEI, KIWI, SSIAA, CAU, WEWOW (`A S. D C. V` seed) | Yalnızca-suffix çöp seed; 5 farklı marka |
| 6 | PHONETIC | INTERCERAS, INTERCO, INTERTEAM, INTERLOGISTICA… | `INTER` ön-eki üzerinden 5 farklı firma |

### 3.2 Split / under-merge (SHOULD_MERGE — aynı firma, farklı master)

| imza | birleşmeli kayıt | gerekçe |
|---|---:|---|
| ceva freight management mexico | 17 | Suffix/adres/idari metin varyasyonları; tek firma |
| ford motor | 15 | COMPANY/CO/CORP eksiltmeleri; tek firma |
| avon cosmetics manufacturing | 11 | Suffix-truncation varyantları |
| hennes mauritz servicios (H&M) | 11 | Noktalama/boşluk varyasyonu |
| cummins grupo industrial | 11 | `GROPO`→`GRUPO` tipo dâhil |
| schryver transportes y logistica | 10 | Suffix/word-order varyantları, 4 master'a bölünmüş |
| stretchline de mexico | 9 | Suffix-truncation (`S.DE.R.L DE C`) |
| vf outdoor mexico | 9 | `S.R.L.` vs `S.A. DE C.V.` (yalnız hukuki form) |

### 3.3 Kontrol havuzunda yakalanan over-merge (yaygınlık kanıtı)

- ENERGY CORPORATION ≠ ALKHORAYEF PETROLEUM (TOKEN_COVERAGE)
- WORLWIDE CARGO & LOGISTICS ≠ AGUNSA LOGISTICS (PHONETIC)
- SUPER STAR LOGISTICS ≠ ZEBRA LOGISTICS (PHONETIC)
- ALCATEL ≠ ALCATEL-LUCENT (partial brand)
- CEVA FREIGHT ≠ CEVA FREIGHT MANAGEMENT (partial brand)

---

## 4. Veri Kalitesi Bulguları

1. **Çöp seed mıknatısları:** Uzun gümrük-beyanı dizeleri (örn. QHE 52-üyeli master)
   ham hâlde NEW_MASTER seed oluyor ve sonraki eşleşmeler için "mıknatıs" görevi görüyor.
2. **`#N/A` kayıtları** EXACT_FUZZY ile birbirine birleşiyor (geçersiz veri eşleşmesi).
3. **`RQMT-xxxxx/yyyy` referans numaraları** firma ismi değil; eşleştirmeye hiç
   girmemeli (18-üyeli sahte grup).

---

## 5. Önceliklendirilmiş ES-İyileştirme Önerileri

> Aşağıdaki öneriler kanıta dayalıdır; **kod henüz değiştirilmedi** — onay bekliyor.

### 🔴 P0-1 — Çekirdek-isme coğrafi/jenerik stopword ekle (PHONETIC'in temel düzeltmesi)
- **Kanıt:** Over-merge üyelerinin ezici çoğunluğu `<MARKA> MEXICO S.A. DE C.V.`
  biçiminde; çekirdek `(marka, mexico)` = 2 token olduğundan `PHONETIC_MIN_CORE_TOKENS=2`
  guard'ını **geçiyor**. `MEXICO`/`MEXICANA` ayırt edici değil.
- **Değişiklik:** `core_name.py` → `normalize_core` için ülke-bazlı **coğrafi/jenerik
  stopword** kümesi ekle (MX: `mexico`, `mexicana`, ve opsiyonel `logistics`,
  `internacional`). Böylece `(audi, mexico) → (audi)` = 1 token → PHONETIC guard bloklar.
- **Etki:** PHONETIC over-merge'lerinin büyük kısmını kökten keser. Risk düşük
  (gerçek tek-marka firmalar zaten 1-token core ile NEW_MASTER kalır).

### 🔴 P0-2 — NGRAM_MATCH'e çekirdek-token guard + min_score yükselt (veya geçici kapat)
- **Kanıt:** %95 over-merge; tamamı `USA INC`/`LLC`/`PTE LTD` gibi paylaşılan suffix
  trigramları üzerinden. Stage neredeyse hiç doğru eşleşme üretmiyor.
- **Değişiklik:** `es_queries.py > NGRAM_MATCH` başına PHONETIC ile aynı guard'ı ekle
  (`normalize_core(name, country) < PHONETIC_MIN_CORE_TOKENS` ise `MATCH_NONE`); ek
  olarak `config.STAGES` içinde NGRAM `min_score`'u **10.0 → 18-20** aralığına çıkar.
  Guard sağlanana dek stage'i `"enabled": False` yapmak en güvenli adım.

### 🔴 P0-3 — PHONETIC_MATCH'e core-token coverage post-verify
- **Kanıt:** %80 over-merge; guard yalnızca *sorgu* tarafı core-token sayısına bakıyor,
  eşleşen dokümanın aynı *ayırt edici* token'ı paylaştığını doğrulamıyor.
- **Değişiklik:** SUFFIX_FUZZY'deki `SUFFIX_FUZZY_COVERAGE_THRESHOLD` mantığına benzer
  bir **çekirdek-token örtüşme post-verify** ekle (kazanan aday ile sorgunun
  `normalize_core` token kümeleri kesişimi ≥ eşik). `main_processor` doğrulama adımı +
  `config` yeni eşik.

### 🟠 P1-1 — Çöp/geçersiz girdi filtresi (ingest/input)
- **Kanıt:** Over-merge'lerin %12'si çöp seed etrafında; `#N/A` ve `RQMT-…` kayıtları.
- **Değişiklik:** `es_ingest.py` Painless ya da `main_processor` girdi aşamasında:
  `#N/A`, salt-sayı, ve aşırı uzun (örn. >70 karakter gümrük dizesi) kayıtları
  **eşleştirmeden hariç tut** / firma-ismi kısmına kırp.

### 🟠 P1-2 — EXACT_FUZZY + TOKEN_COVERAGE subset/partial guard
- **Kanıt:** ENERGY CORP↔ALKHORAYEF, ALCATEL↔ALCATEL-LUCENT, CEVA FREIGHT↔…MANAGEMENT.
- **Değişiklik:** İki ismden biri diğerinin alt-kümesi olduğunda (ör. token sayısı
  belirgin farklı) eşleşmeyi reddeden core-token coverage post-verify; `TOKEN_COVERAGE`
  zaten `operator:and` — simetrik coverage kontrolü ekle.

### 🟡 P2-1 — Split'leri kapat: truncated-suffix varyantlarını birleştir
- **Kanıt:** 346 SHOULD_MERGE grubu / ~1.228 kayıt; çoğu suffix-truncation
  (`STRETCHLINE … S.DE.R.L DE C`) veya word-order varyantı.
- **Değişiklik:** `STRIPPED_EXACT`/`SUFFIX_FUZZY`'nin neden bu varyantları kaçırdığını
  incele; `variations_stripped` token_count filtresinin truncated suffix'lerde fazla
  katı olduğu hipotezi → stripped form üzerinde core-token coverage tabanlı gevşek bir
  stage ekle.

### ✅ P3 — country_code filtresi doğrulaması (POZİTİF)
`es_queries.py` içindeki **tüm** stage sorgularında (`CANONICAL_EXACT`, `STRIPPED_EXACT`,
`SUFFIX_FUZZY`, `TOKEN_COVERAGE`, `FUZZY_PHRASE`, `NGRAM_MATCH`, `PHONETIC_MATCH`)
`filter: [{term: {country_code: country.upper()}}]` mevcut. Hard-filter sağlam.

---

## 6. Eklenti — Üretim Artefaktları
- Aday havuzları: `C:/tmp/cand_over_merge.json`, `cand_split.json`, `cand_control.json`
- Haiku yargıları: `C:/tmp/qa_results/*.json` (173 batch, 1.730 yargı)
- Makine-okunur özet: `C:/tmp/qa_summary.json`
- Üretici betikler: `analysis/detectors.py` (salt-okunur ön-eleme), `C:/tmp/qa_sample.py`
