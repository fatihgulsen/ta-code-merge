# Round-5 Eşleştirme Kalite Denetimi — `p7_firms_v2_ar_pe` (AR + PE) İlk Ölçüm

**Tarih:** 2026-06-10 · **Tablo:** `p7_firms_v2_ar_pe` (PE 229.277 + AR 171.328 = 400.605) · **Index:** `living_companies_v1`
**Snapshot:** 49.700 işlenmiş (%12,4) — rematch denetim sırasında AKTİF koşuyordu → tüm sayılar **kısmi + erken-id-dilimi yanlı**; kıyaslar oran-bazlı.
**Yöntem:** Haiku LLM-judge — önce 400'lük rastgele örneklem, ardından kullanıcı isteğiyle **TAM KAPSAM** (783 eşleşmiş AR kaydının TÜMÜ, 684 master, 38+10 batch) + her iki turda adversarial verify + ES `_analyze`/sorgu canlı doğrulama (salt-oku).

---

## ⛔ EN KRİTİK BULGU — PE EŞLEŞTİRME YAPISAL OLARAK KIRIK (P0, rematch boşa koşuyor)

**PE'de 29.490 işlenmiş kayıtta 0 (SIFIR) eşleşme — hepsi NEW_MASTER.** (AR: 729 eşleşme, 4 stage de çalışıyor.)

**Kök neden (kanıtlı):** `living_companies_v1` index'i `synonyms_data/pe.json` **oluşturulmadan önce** kurulmuş. Bu yüzden index'te
`stripped_search_analyzer_pe` ve `clean_analyzer_PE` **YOK** (AR karşılıkları VAR). `es_queries._get_stripped_analyzer("PE")` artık
(pe.json diskte mevcut olduğundan) `stripped_search_analyzer_pe` döndürüyor → **5 stage'den 4'ü her PE kaydında ES 400 hatasıyla düşüyor**:

```
PE 'APUNTALH S.A.C.':
  CANONICAL_EXACT  -> OK hits=0
  STRIPPED_EXACT   -> ES-400: analyzer [stripped_search_analyzer_pe] not found
  SUFFIX_FUZZY     -> ES-400: analyzer [stripped_search_analyzer_pe] not found
  FUZZY_PHRASE     -> ES-400: analyzer [clean_analyzer_PE] not found
  TOKEN_COVERAGE   -> ES-400: analyzer [clean_analyzer_PE] not found
AR 'FORD ARGENTINA SA': 4/4 stage OK (hits=1)
```

Sonuç PG'de görünür: aynı isimli PE çiftleri ayrı master'lara bölünüyor (`APUNTALH S.A.C.` ×2 → 2 farklı master; `VIRALAB S.A.`, `FARM CROP S.A.C.` vb. aynı durumda). PE'deki size≥2 gruplar yalnızca **batch-içi fingerprint auto-dedup**'tan geliyor (fingerprint_analyzer GLOBAL olduğu için çalışıyor).

**İkincil stale-index kanıtı (AR + PE recall'ı da etkiliyor):**
- `fp('Y.P.F. SOCIEDAD ANONIMA')` = `'anonima sociedad ypf'` ≠ `fp('YPF S.A.')` = `'ypf'` — ar.json'daki `sociedad anonima=>sa` kuralı index'e yansımamış (ar.json index kurulumundan sonra değişmiş, git'te `M`).
- `fp('GLORIA DEL PERU S.A.C.')` = `'gloria peru'` ≠ `'gloria'` — `peru` geo-stop listesinde yok (pe.json yokken kurulmuş).
- Global stripped analyzer `E.I.R.L.`→`['eirl']`, `S.A.A.`→`['saa']` STRIP ETMİYOR (pe.json legal_suffixes global listede yok).

**Önerilen aksiyon (kullanıcı pipeline'ı — ben dokunmadım):**
1. Rematch'i DURDUR (PE kayıtları boşa NEW_MASTER oluyor; her geçen batch yeniden işlenecek iş üretiyor).
2. `python es_manager.py --force` (pe.json + güncel ar.json/common.json ile analyzer'ları yeniden kur) → `python es_ingest.py` → reindex.
3. Rematch'i sıfırdan başlat (en azından PE + eşleşmesi stale analyzer'a denk gelen AR dilimi için).
4. Doğrulama: `_analyze` ile `stripped_search_analyzer_pe('S.A.C.')→[]`, `('E.I.R.L.')→[]` ve PE'de STRIPPED_EXACT > 0 görülmeli.

> Not: A+C düzeltmeleri (core-coverage gate + JSON placeholder) hâlâ **commit edilmemiş** (config.py, es_queries.py, input_filter.py, synonym_loader.py, synonyms_data/* modified; pe.json untracked). Reindex öncesi commit önerilir.

---

## 1. ADIM 0 — Kapı doğrulamaları

| Kontrol | Sonuç |
|---|---|
| `RAW_TABLE_NAME` | `p7_firms_v2_ar_pe` ✓ |
| `ENABLE_CORE_COVERAGE_GATE` / `ENABLE_CORE_GATE` | True / True ✓ |
| `MATCH_CORE_MIN_TOKEN_LEN` / `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` | 2 / 2 ✓ |
| `COUNTRY_CODE_FILTER` | None (iki ülke birden işleniyor) ✓ |
| `acronym_glue_active(es)` | **True** ✓ |
| `_analyze`: `S.A.C.`→`[]`, `S.R.L.`→`[]`, `Y.P.F.`→`['ypf']` | ✓ (glue canlı) |
| `_analyze`: `E.I.R.L.`→`['eirl']` (beklenen `[]`) | ✗ → stale index (yuk. bkz.) |
| `stripped_search_analyzer_ar` | VAR ✓ · `_pe` **YOK** ✗ |
| **★ COUNTRY_LEAK kapısı** (`master_code` başına >1 ülke) | **0 — SIFIR sızıntı** ✓ |
| Stage sorgularında `country_code` term filtresi | 7/7 sorgu fonksiyonunda var (es_queries) ✓ |
| `_routing` büyük-harf `country.upper()` | main_processor'da tutarlı ✓ |
| PHONETIC/NGRAM | disabled (0 kayıt) ✓ |
| ES index ülke dağılımı | MX 96.112 (eski tur) + PE 27.612 + AR 18.466 — country filter ayırıyor ✓ |

**İşlenmiş / match_type (snapshot, kısmi %12,4):**

| | AR | PE |
|---|---|---|
| işlenmiş | 20.210 (%11,8) | 29.490 (%12,9) |
| NEW_MASTER | 19.481 (%96,4) | 29.490 (**%100 — kırık**) |
| STRIPPED_EXACT | 523 | 0 |
| FUZZY_PHRASE | 87 | 0 |
| SUFFIX_FUZZY | 84 | 0 |
| TOKEN_COVERAGE | 35 | 0 |
| EXCLUDED | 0 | 0 |

**EXCLUDED=0 meşru:** tabloda TAM-eşleşme placeholder yalnız 4 satır var (`same as` ×2, `same as consignee` ×2 — hiçbiri henüz işlenmemiş dilimde değil). ≥20 tekrarlı placeholder-benzeri isim YOK — AR/PE verisi MX'ten dramatik temiz. `input_filter.classify_input` canlı doğrulandı: `('consumidor final','AR')`→placeholder, `('same as cnee','PE')`→placeholder, `('sin razon social','PE')`→placeholder, gerçek firma `('GLORIA S.A.','PE')`→None ✓. Yeni placeholder önerisi: **gerek yok** (gözlem boş döndü).

---

## 2. ADIM 1 — ★ Precision: TAM KAPSAM (örneklem değil, popülasyon)

**PE: ÖLÇÜLEMEZ** (0 eşleşme — yapısal bloker). **AR: TÜM eşleşmiş kayıtlar yargılandı** — 783 kayıt / 684 master (snapshot; rematch koşarken büyüyen popülasyonun o anki tamamı). İki tur: Haiku judge (38+10 batch; 20 batch oturum-limiti kesintisi sonrası 18:30 reset'inde tamamlandı) + adversarial verify (77 bayraklı master'ın **38'i çürütüldü** — ilk-tur Haiku "S.A. vs S.R.L. farklı tüzel kişilik" diyerek kuralı çiğniyor; verify suffix-only itirazları eliyor).

### AR TAM-KAPSAM precision = **%95,9** (751/783 kayıt) · master-level clean %94,3 (645/684) · COUNTRY_LEAK 0/684

| Stage | AR R5 (popülasyon) | n | yanlış | MX R4 (ref, örneklem) |
|---|---|---|---|---|
| STRIPPED_EXACT | **%98,6** | 567 | 8 | %98,6 |
| FUZZY_PHRASE | **%94,4** | 90 | 5 | %83,6 |
| TOKEN_COVERAGE | **%94,3** | 35 | 2 | %53,3 |
| SUFFIX_FUZZY | **%81,3** | 91 | **17** | %100 (n=9) |
| **Birleşik** | **%95,9** | 783 | 32 | **%90,0** |

- Ön-koşulan 400'lük rastgele örneklem %95,8 vermişti → popülasyon %95,9 ile **örneklem doğrulandı**; ama tam kapsam SUFFIX_FUZZY'nin gerçek zayıflığını ortaya çıkardı (örneklemde %90,9 görünüyordu, popülasyonda **%81,3**).
- **Yanlışların %53'ü (17/32) SUFFIX_FUZZY'den** geliyor — oysa eşleşmelerin yalnız %11,6'sını taşıyor. Desen istisnasız subset/bileşik-isim: `OCEAN WAY`⊂`SUN OCEAN WAY`, `AIR`⊂`AIR COMPUTERS`, `BANCO MACRO`⊂`BANCO MACRO BANSUD`, `CG`⊂`SCHRO-CG`, `WORLDWIDE LOGISTICS`⊂`HELLMAN WORLDWIDE LOGISTICS`, `S. COLOR`⊂`CAPI COLOR`, + bileşik master'lar (`FEET BIT INTL/SOUTHBAY`, `LEURU C/O LEVI STRAUSS`, `UCSA-ROTTIO U.T.E.`). **A-gate bu stage'e uygulanmıyor — en yüksek-getirili düzeltme.**
- TOKEN_COVERAGE %53→%94 (MX→AR): A-gate'in en net etkisi.
- Hata desen dağılımı (32 yanlış): D3 generic-diff-brand 20 · D5 garbage 8 · D1 truncation 2 · D2 subset 2.

---

## 3. ADIM 2 — A ve C düzeltmeleri AR/PE'de kanıt

### A (core-coverage gate) — AR'da KANITLI ✓
Canlı OFF→ON (modül-içi toggle, salt-oku):

| Probe | Stage | Gate OFF | Gate ON | Beklenti |
|---|---|---|---|---|
| `VANGUARD` (⊂ VANGUARD LOGISTICS SERVICES) | FUZZY+TOKEN | 10 | **0** | 0 ✓ |
| `RAIZEN` (⊂ RAIZEN PARAGUAY) | FUZZY+TOKEN | 21 | **0** | 0 ✓ |
| `LOGISTICS SERVICES` (jenerik subset) | FUZZY+TOKEN | 18-19 | **0** | 0 ✓ |
| `FORD` | FUZZY+TOKEN | 11 | **1** (`ford inc.` — aynı 1-token çekirdek, meşru) | ✓ |
| KONTROL `VANGUARD LOGISTICS SERVICES` | FUZZY+TOKEN | 10 | **1** | ≥1 ✓ |
| KONTROL `FORD ARGENTINA SA` | FUZZY+TOKEN | 1 | **1** | ≥1 ✓ |

**Token-count hizası (gate global stripped kullanıyor):** 300 AR isimde global vs `_ar` farkı **3 (%1)** (örn. `COOPERATIVA LTDA`: global 2, ar 3 — global birlik daha agresif strip ediyor). Gate hem sorgu hem indekslenmiş `token_count` tarafında AYNI global analyzer'ı kullandığından **iç tutarlı** — fark raporluk, düzeltme gerektirmiyor. PE için `_pe` yok → kıyas yapılamadı (rebuild sonrası tekrar bakılmalı).

### Magnet taraması (A-sınıfı) — her iki ülkede 0 ✓
- **AR:** size≥5 master 16, magnet **0**. En büyükler meşru: `TLP S.A COMPL-xxxx` / `RAIZEN PARAGUAY COMPL-xxxx` grupları — fingerprint COMPL numarasını içeriyor (`'2731 compl tlp'`), aynı numara birleşiyor, farklı numara ayrılıyor. (Not: TLP-2731 / TLP-5330 / TLP-1759 muhtemelen AYNI firma TLP → **under-merge**; COMPL gümrük-kodu address_terms benzeri temizlik adayı — JSON'a `compl` pattern önerisi değerlendirilebilir, kör ekleme yapılmadı.)
- **PE:** size≥5 master 2, magnet **0**. Büyükler adres-yüklü DHL/VANGUARD duplikatları — fingerprint dedup doğru birleştirmiş.
- Akronim-çökmesi magnet'i (MX R2'deki `'m'` tipi) AR/PE'de OLUŞMUYOR.

### C (placeholder) — çalışıyor, bu tabloda iş yükü yok ✓
`get_non_firm_placeholders('AR')` 15 / `('PE')` 14 girdi yüklüyor; classify_input TAM eşleşmede placeholder döndürüyor (canlı test ✓). Tabloda yalnız 4 placeholder satırı var (işlenmemiş) → magnet riski yok. MX'teki `Sin Razon Social` (1.181 üye) benzeri durum AR/PE'de YOK.

---

## 4. ADIM 3+4 — Hata desenleri (AR), D yeniden değerlendirme, yeni sınıflar

**17 gerçek yanlış** (400'de) desen dağılımı: D5_garbage 8 · D3_generic_diff_brand 5 · D2_subset 2 · E_person_merge 1 · veri-gürültüsü 1 (POLIRESINAS, muhtemelen doğru).

Öne çıkan ham örnekler ve kök nedenler:

| Desen | Örnek | Kök neden |
|---|---|---|
| D5 (geo-only çöp) | `BUENOS` + `CABA` + `CABA S.A.` aynı grupta; `ARGENTINA` → `AC ARGENTINA SA` | Stripped analyzer **geo token'ı STRIP ETMİYOR** → `buenos`/`caba` ≥2-harf alfabetik çekirdek sayılıyor, core-gate geçiyor. Yeni AR-özgü çöp alt-sınıfı: **çıplak coğrafi isim**. |
| D5 (kod) | `USA - 015` ↔ `USA-015` | Gümrük kodu; input_filter salt-kod desenine girmiyor (harf+sayı karışık). |
| D5 (adres) | `AV ALICIA MOREAU DE JUSTO 1720 1` ↔ aynı adres `...1 A` | Adres-string firma değil; FUZZY_PHRASE eşleşmiş (skor 5-9, düşük). |
| D3 | `GRUPO R Y A S.R.L.` ↔ `GRUPO LP. S.R.L.`; `UP QUIMICA LTDA` ↔ `QUIMICA R&F/D&D`; `STAR LTD SRL` ↔ `DG STAR S.R.L.` | Tek-harf ayırt ediciler (`R Y A`, `LP`, `DG`, `D&D`) analyzer'da düşüyor → kalan çekirdek jenerik kelime. MX'teki D3'ün AR varyantı: **baş-harfli şahıs/aile kısaltmaları + jenerik kelime**. |
| D2 | `WORLDWIDE LOGISTICS SA` ↔ `HELLMAN WORLDWIDE LOGISTICS` (SUFFIX_FUZZY); `SPORT ICON SA` ↔ `SPORT ICON S.A./ QMI INDUSTRIAL CO.LTD` | **SUFFIX_FUZZY A-gate KAPSAMI DIŞINDA** — MX R4'te FUZZY/TOKEN'da kapanan subset deseni burada SUFFIX_FUZZY'den sızıyor. |
| E (yeni sınıf) | `L Y B SERVICIOS S.A.` ↔ `S.H. SERVICIOS S.A.` ↔ `E L A SERVICIOS S.A.` | Farklı kişi baş-harfleri + ortak `SERVICIOS`; baş-harfler tek-harf token olarak düşünce çekirdek `servicios` kalıyor. D3'ün persona-física görünümü. |

**Persona física/EIRL genel durumu:** Meşru şahıs-firmalar (judge kuralı gereği garbage sayılmadı) ağırlıkla DOĞRU gruplanmış; tek E-sınıfı vakası yukarıdaki baş-harf deseninde. MX'in slash-format kişi-çöpü AR/PE'de gözlenmedi.

**D (min_score) yeniden değerlendirme — YİNE GEREKSİZ, AÇMA:**
- FUZZY doğru: min 8 / med 26; yanlış: 5-9 bandında 3/4 (ama 1 yanlış 48'de!) → eşik hem recall keser hem yüksek-skorlu yanlışı yakalayamaz.
- TOKEN doğru: min 21; tek yanlış 4,0 → sinyal var ama n=1; MX R4'te min_score 11 recall'ı 8/10→4/10 kırmıştı.
- SUFFIX yanlışları 10-15 bandında doğruların (8-27) İÇİNDE → eşik ayrıştırmıyor.
- **Karar: D kapalı kalsın.** Kalan over-merge'in doğru adresi skor eşiği değil; aşağıdaki iki yapısal öneri.

**Öneriler (kod değişikliği YAPILMADI — onaya sunulur):**
1. **A-gate'i SUFFIX_FUZZY'ye genişlet** (4/17 hata bu stage'den; FUZZY/TOKEN'daki aynı ES-side `token_count` filtresi; live_probe ile recall doğrulaması şart).
2. **Core-gate'e geo-stop eklemeyi değerlendir** (PHONETIC guard'daki `drop_geo` deseni): `BUENOS`/`CABA`/`ARGENTINA` tek-başına-geo isimleri loose stage'lerde NEW_MASTER'a düşürür (D5 geo-only çöpünün 3 vakası kapanır). Token'lar `synonyms_data/*.json` cities/countries'ten türetilmeli (Rule 4, hardcode yok).
3. `live_probe.py` golden setine AR/PE örnekleri ekle (mevcut MX golden'a dokunmadan) — rebuild sonrası recall regresyonunu yakalamak için.

---

## 5. ADIM 5 — Karşılaştırma tablosu (MX R4 referans · AR/PE R5)

| Metrik | MX R4 (ref, örneklem) | **AR R5 (TAM KAPSAM)** | **PE R5** | AR+PE |
|---|---|---|---|---|
| Precision | %90,0 (40/400 örneklem) | **%95,9** (32/783, popülasyon) | **ÖLÇÜLEMEZ** (0 eşleşme — analyzer bloker) | yalnız AR ölçülebildi |
| STRIPPED_EXACT | %98,6 | %98,6 (n=567) | — | — |
| FUZZY_PHRASE | %83,6 | %94,4 (n=90) | — | — |
| TOKEN_COVERAGE | %53,3 | %94,3 (n=35) | — | — |
| SUFFIX_FUZZY | %100 (n=9) | **%81,3** (n=91, 17 yanlış — A-gate kapsam dışı) | — | — |
| **COUNTRY_LEAK** | yapısal imkânsız (tek ülke) | **0** ✓ | **0** ✓ | **0 / kapı GEÇTİ** |
| Max master boyutu | 19 | 15 (TLP COMPL — meşru dedup) | 6 (DHL adres-dup — meşru) | — |
| Akronim magnet (size≥5) | 0/635 | **0/16** | **0/2** | 0 ✓ |
| EXCLUDED (placeholder) | çalışıyor (MX'te yüklü) | 0 (veride placeholder yok — meşru) | 0 (aynı) | C canlı, iş yükü yok |
| NEW_MASTER oranı (kısmi) | — | %96,4 (erken dilim) | %100 (**kırık**) | — |
| Baskın hata sınıfı | D3 jenerik-farklı-marka | D5 çöp (geo-only/kod/adres) + D3 baş-harf | — | — |
| A-gate etkisi | SPM/VALEO/WW 7/59/66→0 | VANGUARD/RAIZEN/generic 10/21/18→**0**, kontroller 1 ✓ | doğrulanamadı (sorgular 400) | A ülke-bağımsız ✓ |
| C-placeholder etkisi | Sin Razon Social magnet kapandı | classify canlı ✓, veri temiz | classify canlı ✓ | ✓ |

**MX'ten farklar:** (1) iki-ülke COUNTRY_LEAK riski gerçekleşmedi (filter+routing sağlam); (2) persona-física meşru kabulü yeni E-sınıfını küçük tuttu (1 vaka); (3) AR/PE verisi placeholder açısından çok temiz; (4) AR'a özgü `COMPL-xxxx` gümrük-kodu deseni fingerprint'i bölüyor (under-merge); (5) PE legal-suffix seti (SAC/SAA/EIRL) stale index yüzünden hiç devreye girmedi.

---

## En yüksek etkili 5 madde (özet)

1. **[P0] PE eşleştirme tamamen kırık** — index `pe.json`'suz kurulmuş; `stripped_search_analyzer_pe`/`clean_analyzer_PE` yok → 29.490 PE kaydının tamamı hatalı NEW_MASTER. **Rematch'i durdur → `es_manager.py --force` → reindex → PE'yi yeniden eşleştir.** (AR'da da `sociedad anonima`/geo stale — rebuild ikisini de düzeltir.)
2. **[KANIT] A-gate ülke-bağımsız çalışıyor:** AR subset probe'ları 10-21 hit→0, kontroller korunuyor; magnet 0/16 (AR) + 0/2 (PE); TOKEN_COVERAGE precision %53→%94 (MX→AR).
3. **[KANIT] COUNTRY_LEAK = 0** — iki-ülkeli tabloda hiçbir master ülke karıştırmıyor (term filter 7/7 sorguda + uppercase routing).
4. **[TEMEL] AR TAM-KAPSAM precision %95,9** (783 kaydın tümü yargılandı; MX R4 örneklem %90,0'dan iyi). **Yanlışların %53'ü SUFFIX_FUZZY'den (stage precision %81,3)** — desen istisnasız subset/bileşik-isim, A-gate bu stage'i kapsamıyor. **En yüksek-getirili düzeltme: A-gate'i SUFFIX_FUZZY'ye genişlet** (tahmini etki: toplam precision %95,9→~%98). İkincil: core-gate'e geo-stop (JSON-türevli). **D (min_score) yine gereksiz — açma.**
5. **[HİJYEN] A+C kodu hâlâ commit edilmemiş** (12 modified + pe.json untracked) — rebuild öncesi commit önerilir.

**Onay istenen kararlar:** (a) rematch durdurulup index rebuild yapılacak mı; (b) A-gate SUFFIX_FUZZY genişletmesi denensin mi (TDD + live_probe ile); (c) geo-stop core-gate önerisi araştırılsın mı; (d) live_probe golden setine AR/PE eklensin mi.
