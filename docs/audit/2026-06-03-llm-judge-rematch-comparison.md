# Rematch Sonrası Eşleştirme Kalite Denetimi — Önce/Sonra + NEW_MASTER Recall (2026-06-03)

**Branch:** `feat/phonetic-overmerge-guard` (Faz 1-3 + ES-side coverage commit'li)
**Yöntem:** `p7_firms_v2` salt-okunur örneklendi; 172 batch (1.724 yargı) **Haiku
alt-ajanlarına** dağıtıldı; "aynı ticari firma mı?" kararı **modele** verdirildi.
Token-örtüşme / çekirdek-imza yalnızca *aday havuzu ön-elemesi* içindir.
Karşılaştırma temeli: [`2026-06-02-llm-judge-match-quality.md`](2026-06-02-llm-judge-match-quality.md).

> **country_code:** Tüm tablo (530.876 satır) tek ülke **MX**. Cross-country
> `COUNTRY_LEAK` yapısal olarak imkânsız (doğrulandı). *İstisna:* kontrol havuzunda
> adı Singapur olan bir kayıt (`WILLIAMS-SONOMA SINGAPORE PTE.LTD`) MX olarak
> etiketli — bu bir **veri-girişi** anomalisi, eşleştirme sızıntısı değil.

---

## 0. Sonuç (TL;DR)

Rematch **daha fazla satır işledi (68.6k → 278.2k)** ama kalite **iki yönden de
kötüleşti**: PHONETIC/NGRAM hâlâ ezici biçimde **over-merge** üretiyor *ve* aynı
firmanın suffix/truncation varyantları **NEW_MASTER olarak ayrı kalıyor (under-merge)**.

> **KÖK NEDEN (kod incelemesi, §2.4):** Faz 1-3 düzeltmeleri (legal_fragment_stop,
> empty-core guard, token_count coverage) **devrede ve tasarlandığı gibi çalışıyor** —
> ama tek-token markalarda mimari olarak kör. `es_manager.phonetic_filter`
> `double_metaphone` için `max_code_len` ayarlamıyor → **ES varsayılanı 4 karakter**.
> Bu yüzden `INTERAGUA / INTERFIG / ENTRETEX / INTROLIGHT` hepsi `ANTR` koduna çöküyor;
> guard (core≥1) ve token_count eşitliği (1==1) tek-token markada no-op olduğundan
> `operator:and` eşleşmeyi geçiriyor. Over-merge'in birincil kaynağı budur.

---

## 1. Temel Metrikler — Önce/Sonra

| Metrik | 2026-06-02 (önce) | 2026-06-03 (sonra) | Δ |
|---|---:|---:|---|
| Toplam satır | 530.876 | 530.876 | — |
| İşlenmiş (master_code dolu) | 68.600 | **278.200** | ×4,1 |
| İşlenmemiş (NULL) | 462.276 | 252.676 | — |
| NEW_MASTER | 63.206 (**%92,1**) | 203.173 (**%73,0**) | daha çok birleşme |
| PHONETIC_MATCH | 1.111 (%1,6) | 34.291 (**%12,3**) | ⬆ büyük artış |
| NGRAM_MATCH | 146 | 7.143 | ⬆ |
| STRIPPED_EXACT | — | 17.978 | |
| FUZZY_PHRASE | — | 8.931 | |
| TOKEN_COVERAGE | 540 | 3.748 | |
| SUFFIX_FUZZY | 1.567 | 2.455 | |
| distinct master_code | — | 203.179 | |
| **max master grup boyutu** | **52** | **1.181** | 🔴 büyüdü |

**Master grup-boyutu dağılımı (sonra):** size=1 → 166.128; size=2 → 23.589;
size 3-5 → 10.774; size ≥6 → 2.688; çok-üyeli master'lardaki satır: 112.072.

> **Yorum:** Beklenti "NEW_MASTER oranı artar, grup boyutları küçülür, 52-üyeli
> magnetler kaybolur" idi. Gerçekleşen **tam tersi**: NEW_MASTER oranı düştü
> (%92→%73), PHONETIC payı 8 katına çıktı, en büyük magnet 52 → **1.181**'e büyüdü.
> Bu, over-merge guard'larının bu index/rematch'te devrede olmadığına işaret ediyor.

---

## 2. Over-merge — Hata Tablosu (Önce/Sonra)

### 2.1 Havuz seviyesinde

| Havuz | Aday | Sonuç | Yorum |
|---|---:|---|---|
| **Over-merge** (en zayıf 600 master) | 600 | **549 OVER_MERGE + 28 GARBAGE** / 23 CORRECT | Şüphelilerin **%96,2'si yanlış** (önce %76,6) |
| **Kontrol** (yüksek-örtüşme, "doğru" varsayımı) | 120 | 87 CORRECT / **30 OVER_MERGE + 2 GARBAGE + 1 "COUNTRY_LEAK"** | "İyi" gruplarda bile **%27,5 hatalı** (önce %18) → kötüleşti |
| **Split / under-merge** | 500 | **347 SHOULD_MERGE + 95 MIXED** / 32 ayrı / 25 garbage | Adayların **%88,4'ü en az kısmen under-merge** |

> Not: bu turdaki over-merge havuzu *en zayıf 600* master (size×düşük-örtüşme) olduğu
> için %96 oranı önceki %76,6 ile birebir kıyaslanmamalı; ama **kontrol havuzunun
> %18 → %27,5'e çıkması** doğrudan kıyaslanabilir ve **over-merge'in yayıldığını** gösterir.

### 2.2 Stage atfı (üye-bazlı, şüpheli örneklem)

| match_type | Yanlış üye | Toplam üye | Oran (sonra) | Oran (önce) |
|---|---:|---:|---:|---:|
| **PHONETIC_MATCH** | 5.020 | 8.049 | **62,4%** | 80,0% |
| **NGRAM_MATCH** | 618 | 1.143 | **54,1%** | 95,0% |
| **TOKEN_COVERAGE** | 19 | 44 | 43,2% | 45,1% |
| **STRIPPED_EXACT** | 125 | 1.030 | 12,1% | 2,8% |
| **FUZZY_PHRASE** | 21 | 151 | 13,9% | 11,5% |
| **SUFFIX_FUZZY** | 2 | 12 | 16,7% | 22,4% |

**Master seviyesi (om havuzu, sampler culprit_stage):** PHONETIC **%95,9** (516/538),
NGRAM **%98,1** (51/52), STRIPPED_EXACT %100 (9/9) over-merge onayı.

> **Kritik:** Üye-bazlı oranlar düşmüş görünse de **mutlak hacim patladı** (PHONETIC
> şüpheli üye 936 → 8.049). Oran düşüşü, daha geniş ve sınırda bir havuzdan kaynaklanıyor;
> **master-seviyesi onay %96-98** ile PHONETIC/NGRAM'in hâlâ kökten bozuk olduğunu
> doğruluyor. STRIPPED_EXACT'in %2,8 → %12,1'e çıkması, garbage/kısaltma seed'lerinin
> exact eşleşmeye sızdığını gösteriyor.

### 2.3 Over-merge kalıbı: fonetik ÖN-EK / kök birleşmesi

PHONETIC over-merge'lerin ezici çoğunluğu **paylaşılan ön-ek/kök** üzerinden farklı
markaları birleştiriyor — guard yalnızca *boş çekirdeği* blokladığı, çekirdek-token
**coverage** doğrulaması bu index'te devrede olmadığı için:

| master sz | culprit | birleşen (farklı firmalar) |
|---:|---|---|
| 202 | PHONETIC | INTERAGUA + INTERFIG + ENTRETEX + WINDARMEX + INTROLIGHT + INTERPELLI (`INTER*`) |
| 65 | PHONETIC | LA IMPERIAL + IMPORTISTO + IMPORIGEN + IMPRECORME (`IMP*`) |
| 63 | NGRAM | TIAMAT + MARA + WELDERS + DIVERSEY (hepsi `… PERU S.A.C.` suffix'i) |
| 59 | PHONETIC | PLASTIFAR + PLASTRAP + POLESTAR + PLASTICUS + PLASTICSER (`PLAST*`) |
| 57 | PHONETIC | TRANSVEL + TRANSTELL + TRINSEO + TORANZU + TRANSMISIONES (`TRANS*`) |
| 46 | PHONETIC | INDUSTRIAS* + INDESP + ANTIESTATIC (`INDUS*`) |
| 43 | PHONETIC | WOCO + FAC + AAG + AAK + YKK + ACCO (paylaşılan `… MEXICO` + kısa kök) |
| 40 | PHONETIC | FLEXAPRINT + FLEXICO + FLUXAL + FLUX (`FL*X`) |

### 2.4 Kök neden — `double_metaphone max_code_len=4` (kod incelemesi)

`es_manager.py:215-219` `phonetic_filter`:
```
{"type": "phonetic", "encoder": "double_metaphone", "replace": False}   # max_code_len YOK → ES varsayılanı = 4
```
Her kelime ilk-4 metaphone karakterine indirgenir; ortak fonetik ön-eke sahip
TÜM tek-token markalar aynı koda çöker:

| kelime grubu | metaphone (len=4) |
|---|---|
| INTERAGUA, INTERFIG, ENTRETEX, INTROLIGHT, INTERELEQ | `ANTR` |
| PLASTIFAR, PLASTRAP, PLASTICUS, PLASTICSER | `PLST` |
| TRANSVEL, TRANSTELL, TRANSINSUMOS, TRANSFORESTA | `TRNS` |
| INDUSTRIAS, INDESP | `ANTS` |

`PHONETIC_MATCH` sorgusu (`es_queries.py:307`) `operator:and` + `token_count` eşitlik
filtresi kullanır. Tek-token marka için: phonetic token = 1 (`ANTR`), `token_count`
= 1. Aday da 1 token + `ANTR` → **eşleşir**. Guard (`core≥1`) ve coverage (`1==1`)
**tek-token markada no-op**; subset over-merge'i (ALCATEL⊂ALCATEL-LUCENT, 5≠6) eler ama
**eş-uzunluk prefix çakışmasını elemez**. Faz 1-3 bu yüzden bu vakaları kaçırıyor —
"devrede değil" değil, "tek-token prefix çakışmasına karşı tasarımca yetersiz".

---

## 3. ★ NEW_MASTER Recall — Kaçırılan Eşleşmeler (asıl yeni bulgu)

NEW_MASTER kayıtlarının "eşleşmesi gerekirken eşleşmedi mi?" denetimi:

| Recall havuzu | Aday | SHOULD_MERGE | MIXED | CORRECT_SEPARATE | GARBAGE | Kaçırma oranı |
|---|---:|---:|---:|---:|---:|---:|
| **nme** (özdeş geo-çekirdek imza) | 300 | **245** | 19 | 27 | 9 | **%81,7** |
| **nml** (ilk-2 çekirdek token paylaşımı) | 200 | 98 | 19 | 72 | 16 | %49,0 |
| **Toplam** | 500 | **343** | 38 | 99 | 25 | — |

- SHOULD_MERGE gruplarında birleşmesi gereken **~3.346 kayıt** (örneklemde).
- Baskın kalıplar (gerekçe-tarama): **suffix 263, truncation 145, punctuation 62,
  spacing 57, word-order 29, typo 26, abbreviation 17**.

### 3.1 Ölçek — recall borcu (tam veri, salt-okunur)

`normalize_core(drop_geo=True)` ile **özdeş geo-çekirdek imzaya** sahip olup yine de
≥2 ayrı master'a düşmüş **24.438 grup** var:

| Grup tipi | Grup | Yorum |
|---|---:|---|
| **Saf NEW_MASTER kopya** (tüm üyeler NEW_MASTER, ≥2 master) | **12.802** (~**27.523 kayıt**) | Aynı firma, hepsi ayrı NEW_MASTER olmuş → **within-batch dedup/refresh kaybı** |
| **Karışık** (NEW_MASTER + matched) | 10.739 | NEW_MASTER mevcut master'a eşleşmeliydi |
| Matched-but-split (NEW_MASTER yok) | 897 | matched master'lar arası bölünme |

> Kaba "birleşmesi mümkün kayıt fazlası": ~15.929 (özdeş geo-çekirdek bazında). Üst
> sınır (saf-kopya kayıtları) ~27.5k. Bu, **over-merge fix'lerinin değil**, asıl olarak
> **suffix-truncation toleransı + within-batch NEW_MASTER dedup** zayıflığının sonucu.

### 3.2 Örnek kaçırılan eşleşmeler (aynı firma, çok master'a bölünmüş)

| çekirdek | bölünme | kalıp |
|---|---|---|
| HALLIBURTON (DE MEXICO) | **9 master** | suffix-truncation (`S DE RL` / `S. DE R.` …) |
| COMPANIA HULERA TORNEL | **11 master** | `COMPANIA`↔`CIA` + suffix |
| FLEXTRONICS MANUFACTURING MEX(ICO) | 7 master | `MEX`/`MEX.`/`MEXICO` + suffix |
| KUEHNE + NAGEL | çok | `+`↔`&`, suffix varyantları |
| SIEMENS S.A. DE C.V. | çok | `MEXICO` geo + noktalama |
| VF OUTDOOR MEXICO | çok | `S.R.L.`↔`S.A. DE C.V.` |
| LEVI STRAUSS DE MEXICO | çok | C.V. truncation, `&`↔`DE` |
| JABIL CIRCUIT (DE MEXICO) | çok | `MEX`/`S.R.L.`/`S DE C` truncation |
| INDUSTRIAS JOHN DEERE | çok | suffix truncation; "Multiple NEW_MASTER" |
| ONATE WILLY Y CIA | 5 master | `Y`↔`&`, `CIA`↔`COMPANIA` |

Birçok gerekçe birebir şunu söylüyor: *"Multiple NEW_MASTER assigned when should match
existing canonical"* → bu **within-batch refresh/dedup zamanlaması** kaybının doğrudan kanıtı.

### 3.3 ★ NEW_MASTER'lar KENDİ ARALARINDA (rematch'siz, salt-okunur)

Soru: *birbiriyle eşleşmesi gereken NEW_MASTER'lar ayrı mı kaldı?* — **Evet, ağır biçimde.**
Yalnızca NEW_MASTER kayıtları (203.173) `normalize_core(drop_geo=True)` ile gruplandı;
hepsi NEW_MASTER olup aynı geo-çekirdeğe sahip ve ≥2 ayrı master'a düşmüş gruplar:

| Havuz | Grup | Yargı (örneklem) | Kaçırma oranı |
|---|---:|---|---:|
| **EXACT** (özdeş geo-çekirdek) | **19.473** (~45.022 kayıt) | 351 SHOULD_MERGE / 25 ayrı / 13 mixed / 8 garbage (n=397) | **%88,4** |
| **LOOSE** (ilk-2 token paylaşımı) | 12.248 | 64 SHOULD_MERGE / 67 ayrı (n=150) | %42,7 |

- **EXACT %88,4 should-merge** → ölçek tahmini: **~17.200 grup** gerçek kaçırılmış birleşme,
  ~40k+ kayıt aslında tek firmanın kopyası.
- Yargıç jenerik-kelime gruplarını DOĞRU ayırıyor (CORRECT_SEPARATE): `comercializadora`,
  `trading`, `fashion`, `grupo`, `internacional`, `industrial` (+ ayırt edici farklı önek)
  + DELPHI tesisleri (plant no. ayırt edici) + EXPO fuarları (farklı yıl). GARBAGE: salt
  kodlar (`RQMT`, `EXP`, `AIL-1264`, `CFR-0289`), adres dizeleri, kişi adları.
- Örnek gerçek kaçırmalar: SIEMENS (13), LEVI STRAUSS (14), JABIL CIRCUIT (14), VF OUTDOOR
  (10), HULERA TORNEL (10), PIRELLI NEUMATICOS (9), KIMBERLY CLARK (11), FLOWSERVE (13).

#### Kök neden ayrımı (SHOULD_MERGE exact gruplar, n=351)

| Neden | Pay | Anlamı |
|---|---:|---|
| **Özdeş STRIPPED kanonik anahtar** | **%73,2** (257) | STRIPPED_EXACT zaten eşleştirmeliydi → **within-batch NEW_MASTER duplikasyonu** (refresh/dedup zamanlaması). Örn. `VGREEN GLOBAL S.A. DE C.V.` vs `VGREEN GLOBAL, S.A. DE C.V.` (yalnız virgül) ayrı master. |
| **Farklı STRIPPED anahtar** | **%26,8** (94) | Analyzer normalize boşluğu — **`mexico` geo token'ı STRIPPED anahtarında kalıyor**: `SENSATA TECHNOLOGIES DE MEXICO` → `mexico sensata technologies` ≠ `SENSATA TECHNOLOGIES` → `sensata technologies`. Geo token strip'lenseydi eşleşirdi. |

> İki ayrı, net ES/orkestrasyon düzeltmesi: (1) within-batch dedup (%73), (2) STRIPPED/
> CANONICAL analyzer'a ülke geo token'larını (mexico/mexicana, JSON-türetimli) stopword
> ekle (%27). İkisi de over-merge'den bağımsız; Python fuzzy yok.

---

## 4. Veri Kalitesi — Garbage Magnet Master'lar

`sz ≥ 15` olan 288 büyük master'ın **8'i** garbage/aşırı-uzun seed etrafında toplanmış
ve **1.606 kayıt** hapsediyor:

| sz | seed |
|---:|---|
| **1.181** | `Sin Razon Social` (= "ticari unvan yok") |
| 160 | `C R M` |
| 152 | `Razon Social no determinada` |
| 52 | `QHE LOGISTICS … Manzanillo EGM 1 …` (gümrük dizesi) |
| 16 | `OHL` |
| 15 | `A.S` / `DBB` / `P. D. X` |

Ek olarak over-merge havuzunda 28, split'te 25, recall'da 25 grup GARBAGE çıktı
(`M.R.V.L`, `B.V.G`, `#N/A`, `RQMT-00162/2020`, `DDI051109783` gümrük no, salt-baş-harf).

---

## 5. Önce/Sonra Özeti

| Boyut | Önce (06-02) | Sonra (06-03) | Yön |
|---|---|---|---|
| İşlenen hacim | 68.6k | 278.2k | ✅ arttı |
| Over-merge (kontrol FP) | %18 | **%27,5** | 🔴 kötüleşti |
| PHONETIC master over-merge | yüksek | **%95,9** | 🔴 sürüyor |
| NGRAM master over-merge | %95 | **%98,1** | 🔴 sürüyor |
| Max magnet boyutu | 52 | **1.181** | 🔴 kötüleşti |
| Split/under-merge | %72 SHOULD_MERGE | %69,4 (+%19 MIXED) | ➖ benzer/kötü |
| **NEW_MASTER recall kaybı** | (ölçülmedi) | **%81,7** (özdeş-core); ~12.8k saf-kopya grup | 🔴 yeni, kritik |

**Net:** Over-merge guard'ları bu rematch'te işe yaramamış (PHONETIC/NGRAM hâlâ kökten
bozuk) **ve** aynı anda ciddi bir under-merge/recall problemi var. Sistem yanlış sinyale
(ön-ek/kök fonetiği + paylaşılan suffix) kilitleniyor, doğru sinyali (tam çekirdek-marka
+ suffix-normalize edilmiş kanonik form) kaçırıyor.

---

## 6. Önceliklendirilmiş ES-tarafı Öneriler (Faz 4/5)

> **UYGULANAN KARAR (2026-06-03):** PHONETIC_MATCH ve NGRAM_MATCH stage'leri
> `config.STAGES`'te `enabled: False` yapıldı (over-merge'in birincil/ikincil
> kaynağı; sırasıyla master-seviyesi %95,9 / %98,1 yanlış). Reindex gerekmez —
> stage'ler artık aktif sırada koşmaz. Aktif sıra: CANONICAL_EXACT → STRIPPED_EXACT
> → SUFFIX_FUZZY → FUZZY_PHRASE → TOKEN_COVERAGE. Geri açma koşulları aşağıda
> (P0-A) ve config yorumlarında. **Etki ölçümü için rematch + bu QA harness tekrarı bekleniyor.**
>
> Aşağıdaki öneriler ES-tarafı; Python doğrulaması yok. Her biri kanıt + dosya/parametre ile.

### 🔴 P0-A — `double_metaphone max_code_len`'i yükselt (PHONETIC over-merge'in kökü)
- **Kanıt:** §2.4 — `max_code_len` ayarsız → ES varsayılanı 4; `INTERAGUA/INTERFIG/
  ENTRETEX` hepsi `ANTR`'ye çöküyor. PHONETIC master over-merge %95,9. token_count
  coverage tek-token markada no-op (1==1).
- **Eylem (ES-side, Python yok):** `es_manager.phonetic_filter`'a `"max_code_len": 8`
  (veya 10) ekle → kod ayırt ediciliği artar; `INTERAGUA`=`ANTRK…` ≠ `INTERFIG`=`ANTRFK…`
  artık çakışmaz. Tipo toleransı KORUNUR (MANAGMENT/MANAGEMENT → aynı `MNJMNT`). **Reindex
  gerektirir.** Doğrulama: `_analyze` API ile birkaç prefix-kümesi kodunu kontrol et,
  ardından `analysis/live_probe.py` golden-set + bir prefix-collision golden ekle.
- **İkincil:** NGRAM `min_score` 10 → 18-20 (trigram prefix sızıntısı için); NGRAM
  `minimum_should_match` "75%" kısa isimlerde hâlâ gevşek olabilir — band kontrolü.

### 🔴 P0-B — Garbage/geçersiz girdi filtresi (ingest) — magnet'leri kökten kes
- **Kanıt:** `Sin Razon Social` (1.181), `Razon Social no determinada` (152),
  `C R M` (160), QHE gümrük dizesi (52) + 78 garbage grup. ~1.606+ kayıt hapis.
- **Eylem:** `es_ingest.py` Painless / `main_processor` girdi aşamasında **eşleştirmeden
  hariç tut**: placeholder unvanlar (`sin razon social`, `razon social no determinada`,
  `no determinad*`), `#N/A`, salt-sayı, `RQMT-…`/`DDI…` referansları, >60 karakter
  gümrük dizesi, ≤3 harfli baş-harf grupları. Bu kayıtlar `NEW_MASTER`'a bile girmesin
  (kendi master'ları olabilir ama **mıknatıs/seed olmamalı**).

### 🔴 P0-C — NEW_MASTER within-batch dedup (recall'ın %73'ü) — ES-NATIVE olmalı
- **Kanıt:** §3.3 — SHOULD_MERGE NEW_MASTER gruplarının **%73,2'sinin STRIPPED kanonik
  anahtarı ZATEN ÖZDEŞ** (örn. `VGREEN GLOBAL S.A. DE C.V.` vs `…, S.A. DE C.V.` yalnız
  virgül farkı, ayrı master). EXACT havuzu 19.473 grup / ~45k kayıt. STRIPPED_EXACT
  bunları eşleştirmeliydi → aynı batch'te refresh'ten önce ayrı NEW_MASTER olmuşlar.
- **Kök neden:** `_index_new_master` `refresh=False` ile yazıyor; sonraki kanonik-özdeş
  kaydın msearch'ü master'ı periyodik refresh'e (her 50 kayıt) kadar GÖREMİYOR →
  read-after-write boşluğu. Kimlik kararı ZATEN ES'te (STRIPPED/CANONICAL/fingerprint);
  tek sorun görünürlük. **(Python normalize/dedup ANTİ-DESEN — [[no-python-verification-es-side]];
  bu yüzden eski `create_new_masters` ölü koddu.)**
- **SEÇİLEN: Option 2 — ES Transform fingerprint dedup + auto-merge (UYGULANDI 2026-06-03):**
  1. **Fingerprint analyzer güçlendirildi** (`es_manager.py`): built-in `fingerprint` yerine
     özel `fingerprint_analyzer` = `generic_stopwords_global` + `legal_fragment_stop` +
     **`geo_stopwords_global`** (JSON-türetimli ülke-adı token'ları) + `fingerprint`
     (sort+dedup) filtresi. Böylece `ACME DE MEXICO S.A. DE C.V.` ile `ACME, S.A. DE C.V.`
     ve `ACME` AYNI kanonik parmak izine iner. **Reindex gerektirir.**
  2. **Auto-merge modülü** (`dedup_auto_merge.py`): nested composite agg ile aynı
     `variations.name.fingerprint` + `country_code` altındaki ≥2 master'ı gruplar; her grup
     için PG `master_code`'u primary'e **repoint eder** (country HARD FILTER param) +
     ES variations'ı primary'e taşır + secondary doc'ları siler. **Boş fingerprint →
     birleştirme YOK** (garbage magnet önlenir). Grup-bazlı try/except + PG rollback
     (CLAUDE.md §3). `--apply`/`--limit=N`/dry-run. Kimlik kararı %100 ES (Python normalize/
     fuzzy YOK). Mevcut `dedup_reviewer`'ın **PG'yi güncellememe** açığını kapatır.
  - **Çalıştırma sırası:** `es_manager.py --force` (reindex) → `main_processor.py` (rematch) →
    `dedup_auto_merge.py` (önce dry-run, sonra `--apply`). 9 yeni test (RED→GREEN), 132 passed.
  - **Reddedilen Option 1** (refresh=wait_for): sıralı döngüde throughput riski.
    **Reddedilen Python `_canonical_dedup_key`**: normalize-ile-sınıflandırma anti-deseni
    ([[no-python-verification-es-side]]) — geri alındı.

### ⏹️ P0-D — STRIPPED_EXACT'e geo stopword (İPTAL — fingerprint dedup kapsıyor)
- **Kanıt:** §3.3 — kalan kaçırmaların %26,8'i `mexico` geo token'ının STRIPPED anahtarda
  kalmasından. STRIPPED_EXACT zaten 262 synonym/JSON-türevi token (şirket-tipi `cia,
  compania, co, sa…` + article) + `legal_fragment_stop` strip ediyor; **tek eksik geo**.
- **KARAR (2026-06-03): ayrı STRIPPED değişikliği YAPILMADI.** (1) Fingerprint auto-merge
  (P0-C) geo'yu zaten strip edip `SENSATA DE MEXICO`≡`SENSATA`'yı post-hoc birleştiriyor →
  27% kapanıyor. (2) Geo'yu CANLI STRIPPED_EXACT'e eklemek `AUDI`↔`AUDI MEXICO`'yu
  **denetimsiz** birleştirir (parent/subsidiary riski). Post-hoc dedup `--limit`/dry-run
  ile kontrol edilebilir olduğundan daha güvenli. Geo, yalnızca fingerprint katmanında
  ele alınıyor (geo strip fingerprint'te KALIYOR — kullanıcı onayı). Parent/subsidiary
  ayrımı gerekirse P1-B (şehir/`CORP` band) ile.

### 🟠 P1-A — Suffix-truncation toleransı: kanonik formu daha agresif normalize et
- **Kanıt:** HALLIBURTON 9, HULERA TORNEL 11, JABIL/FLEXTRONICS/VALEO/LEVI/SIEMENS
  çok-master'a bölünmüş; kalıp suffix-truncation (`S DE RL` / `S. DE R.` / `S.A. DE C`)
  + `CIA`↔`COMPANIA` + `&`↔`Y`/`DE` + noktalama/spacing.
- **Eylem:** `es_manager` stripped/fingerprint analyzer'ına: (1) truncated yasal-ek
  parçalarını (`s de r`, `s a de c`, `sa de cv`, `sapi`) tam-strip eden char/token
  filter; (2) `&`↔`y`↔`and`, `cia`↔`compania` synonym; (3) noktalama-bağımsız
  fingerprint. Böylece bu varyantlar `STRIPPED_EXACT`/`CANONICAL_EXACT`'te aynı anahtara
  düşer (yeni stage gerekmez).

### 🟠 P1-B — Parent↔subsidiary ve şehir ayrımı (kontrol havuzu FP'leri)
- **Kanıt:** `VF CORP`↔`VF OUTDOOR MEXICO`, `SANMINA CORP`↔`SANMINA-SCI … MEXICO`,
  `MEXICO`↔`MEXICALI` şehir karışması. Bunlar yüksek-örtüşmeli ama farklı tüzel kişi.
- **Eylem:** city_state alanını eşleşme sinyaline ikincil filtre olarak ekle
  (aynı çekirdek + farklı şehir → düşür); `CORP`/`CORPORATION` (parent) vs Mexico
  subsidiary ayrımı için token_count band kontrolü.

### 🟢 P2 — country_code etiket anomalisi (veri kalitesi)
- `WILLIAMS-SONOMA SINGAPORE PTE.LTD` MX etiketli. Cross-country matching riski yok
  (tek ülke) ama veri temizliğinde adı yabancı-ülke + yabancı suffix (`PTE LTD`,
  `GMBH`, `S.A.S.`) olan MX kayıtları işaretle.

---

## 7. Artefaktlar
- Aday havuzları: `C:/tmp/cand2_{over_merge,control,split,nm_exact,nm_loose}.json`
- Batch'ler: `C:/tmp/qa2_batches/` (172), Haiku yargıları: `C:/tmp/qa2_results/` (172, 1.724 yargı)
- Makine-okunur özet: `C:/tmp/qa2_summary.json`
- Üretici betikler: `C:/tmp/qa2_{baseline,pools,make_batches,workflow.js,aggregate,supp}.py`
- Salt-okunur dedektörler: `analysis/detectors.py`
