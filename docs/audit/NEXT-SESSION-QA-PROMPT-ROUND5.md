# GÖREV: Round-5 Eşleştirme Kalite Denetimi — YENİ TABLO `p7_firms_v2_ar_pe` (Arjantin + Peru) İlk Ölçüm + A/C Düzeltmelerinin Çok-Ülkeli Doğrulaması + AR↔PE COUNTRY_LEAK Kontrolü

Sen bir firma-eşleştirme QA denetçisisin. Sistem artık **MX değil, AR (Arjantin) + PE (Peru)** verisinde çalışıyor (`config.RAW_TABLE_NAME = "p7_firms_v2_ar_pe"`). Round-4'te MX üzerinde kodlanan iki düzeltme (A = ayırt-edici-çekirdek coverage gate, C = JSON placeholder) **CANLI**; D (min_score) recall'ı kırdığı için GERİ ALINMIŞTI. Görevin: bu YENİ tabloda **ilk QA ölçümünü** yapmak, A+C'nin **MX-dışı iki ülkede** de işe yaradığını kanıtlamak, **AR↔PE çapraz-ülke sızıntısını** (artık yapısal olarak MÜMKÜN — aşağıda) ölçmek ve AR/PE için **ülke-bazlı precision temeli** kurmak. LLM-yargı görevidir; KARAR senin.

> [!IMPORTANT]
> **EN KRİTİK YENİ BOYUT — AR↔PE COUNTRY_LEAK GERÇEKTİR.** Önceki tüm turlar %100 MX idi → çapraz-ülke sızıntı YAPISAL OLARAK İMKÂNSIZDI (LLM coğrafi kelimeyi sızıntı sanarsa NOT düşülürdü). Şimdi tabloda **iki ülke var (PE 229.277 + AR 171.328)**. `country_code` HARD FILTER ve `_routing` büyük-harf `country_code` DOĞRU çalışmazsa bir Arjantin firması bir Peru firmasıyla eşleşebilir. **Bu turun BİRİNCİL yeni testi: hiçbir master AR + PE üyesini KARIŞTIRMAMALI.** Her stage sorgusunda `country_code` term filtresi var mı + master gruplarında tek ülke mi → KANITLA.

---
## ÖNCEKİ DURUM (Round-4, MX — oran-bazlı kıyas temeli)
- **MX kalibre rastgele precision = %90,0** (40/400). Stage: STRIPPED_EXACT %98,6 · FUZZY_PHRASE %83,6 · TOKEN_COVERAGE %53,3 · SUFFIX_FUZZY %100(n=9).
- A-sınıfı (akronim magnet) KAPANDI: 0 magnet/635 size≥5 master (eski 13/207), max master 72→19.
- Hata sınıfları MX'te: D1 truncation-shell · D2 subset/kısa-marka · D3 jenerik-farklı-marka (baskın kalan) · D4 kişi-adı (TOKEN_COVERAGE) · D5 garbage.
- A (core-coverage gate) MX'te kanıtlı: SPM/VALEO/WORLDWIDE LOGISTICS hits 7/59/66→**0**, SIEMENS kontrol 13→1; live_probe over-merge 1→0, recall 8/10 KORUNDU. D (min_score 5→9/3→11) recall 8/10→4/10 kırdı → GERİ ALINDI.
- **Round-5 = AR/PE için İLK ölçüm; MX baseline yok → hem A/C doğrula hem AR/PE temelini kur. Beklenti: A+C ülke-bağımsız çalışır; ama AR/PE legal-suffix + placeholder + persona-física farkları yeni hata desenleri çıkarabilir.**

---
## ADIM 0 — Yeni kod + yeni tablo + index canlı mı (KAPI)
DB: `config.DB_CONFIG` (market_calculus, localhost:5432; dbhub DOWN ise psycopg2). Salt-OKU. **Tablo/ülke/index'i HARDCODE ETME** — `config.RAW_TABLE_NAME`, `config.ES_INDEX`'ten oku; ülkeyi her satırın `country_code`'undan al.
1. **Config:** `RAW_TABLE_NAME=="p7_firms_v2_ar_pe"`, `ENABLE_CORE_COVERAGE_GATE==True`, `ENABLE_CORE_GATE==True`, `MATCH_CORE_MIN_TOKEN_LEN==2`, `DEDUP_MIN_FINGERPRINT_TOKEN_LEN==2`, `COUNTRY_CODE_FILTER` (None ise tüm ülkeler işlenir), `ES_INDEX`.
2. **ES glue/analyzer canlı:** `es_manager.acronym_glue_active(es)`→True. `_analyze` (salt-oku) AR/PE örnekleriyle: `S.A.C.`→`[]` (PE yasal-ek strip), `S.R.L.`→`[]`, `E.I.R.L.`→`[]`, dotted-akronim örn `Y.P.F.`→`['ypf']`. Ülke-özgü stripped analyzer: `stripped_search_analyzer_ar` / `_pe` var mı (es_manager).
3. **match_type dağılımı + işlenmiş oran** (`config.RAW_TABLE_NAME` üzerinden). PHONETIC/NGRAM≈0 olmalı. **Snapshot anı: ~46.2k/400.6k işlenmiş (%11,5) — rematch ERKEN/yeni başlamış olabilir; eşleşmeler çok az (STRIPPED 463, FUZZY 82, TOKEN 32, SUFFIX 80).** Rematch < ~400k ise HÂLÂ ÇALIŞIYOR/erken → oran-bazlı ölç, "kısmi + erken-id-dilimi yanlı" notu düş; precision için yeterli eşleşme YOKSA (örn <300 toplam matched) rematch'in ilerlemesini BEKLE veya kullanıcıdan iste.
4. **★ Ülke dağılımı + ülke-bazlı match_type:** AR ve PE için ayrı ayrı NEW_MASTER/STRIPPED/FUZZY/TOKEN/SUFFIX. Erken aşamada NEW_MASTER oranı yapay yüksek olur (kısmi).
5. **★ COUNTRY_LEAK KAPISI (en kritik):** Her `master_code` grubunda KAÇ farklı `country_code` var? `SELECT master_code, count(DISTINCT country_code) FROM <tbl> WHERE master_code IS NOT NULL GROUP BY master_code HAVING count(DISTINCT country_code) > 1`. **Sonuç 0 OLMALI.** >0 ise → çapraz-ülke sızıntı VAR → DUR, kök-neden (es_queries country_code filter / main_processor _routing) bildir.
6. **EXCLUDED / placeholder:** AR/PE placeholder'ları (`synonym_loader.get_non_firm_placeholders('AR')` / `'PE'`: `sin razon social`, `consumidor final` [AR], `publico en general`, + common `same as`/`same as cnee`) TAM eşleşmeyle EXCLUDED oluyor mu? `input_filter.classify_input('consumidor final','AR')`/`('same as cnee','PE')`→placeholder doğrula (salt-oku).
7. **master grup-boyutu dağılımı + max master + en büyük 10** (ülke-bazlı). main_processor özet log'unda total_deduped/total_excluded.
> Gate/glue aktif DEĞİLSE veya COUNTRY_LEAK>0 → DUR, bildir.

---
## ADIM 1 — ★ HEADLINE: Kalibre RASTGELE precision, ÜLKE-BAZLI (AR ayrı, PE ayrı)
MX naming kuralları AR/PE'ye UYMAZ → Haiku judge kurallarını ülkeye göre AYARLA. `qa4_random_precision.py` + `qa4_workflow.js` (40 Haiku batch) + `qa4_aggregate.py` desenini KULLAN ama: (a) tabloyu `config.RAW_TABLE_NAME`'den oku (script zaten öyle), (b) örneklemi **AR ve PE için ayrı** çek (her ülkeden ~200 matched, toplam ~400) ya da iki ayrı koşu, (c) judge prompt'una ülke-özgü kuralları koy. **Yeterli matched yoksa (kısmi rematch) örneklem küçülür → "n=X, kısmi" işaretle.**

**Haiku judge — AR/PE NAMING KURALLARI (qa4_workflow.js RULES'u bununla değiştir):**
- **country_code HARD FILTER ve İKİ ÜLKE VAR:** Bir grupta AR ve PE üyesi BİRLİKTE ise → `COUNTRY_LEAK` (gerçek hata, NOT değil). Aynı ülke içi coğrafi kelime sızıntı DEĞİL.
- **Legal suffix'ler AYIRT EDİCİ DEĞİL (yoksay):**
  - **AR:** `S.A.`/`SA`, `S.A.U.`/`SAU`, `S.R.L.`/`SRL`, `S.A.S.`/`SAS`, `S.C.A.`, `S.H.` (sociedad de hecho), `S.C.`, `S.E.`, `coop`/`cooperativa`, `mutual`, `A.C.`/`asociacion civil`, `fundacion`, `sucursal`, `U.T.E.`, `CIA`/`compañia`, `hnos`/`hermanos`, `empresa`, `empresa unipersonal`/`persona fisica`/`persona humana`/`E.U.`/`E.I.`.
  - **PE:** `S.A.C.`/`SAC` (EN YAYGIN), `S.A.A.`/`SAA`, `S.A.`/`SA`, `S.R.L.`/`SRL`, `E.I.R.L.`/`EIRL`, `S.A.C.S.`, `S.C.`, `sociedad civil`, `sucursal`, `coop`, `asociacion`, `fundacion`, `E.P.S.`, `empresa publica`, `CIA`, `hnos`, `consorcio`.
- **Coğrafi token'lar AYIRT EDİCİ DEĞİL (yoksay):** AR: `ARGENTINA`,`ARGENTINA S.A.`,`BUENOS AIRES`,`CABA`,`CORDOBA`,`ROSARIO`,`MENDOZA`… · PE: `PERU`,`DEL PERU`,`PERUANA`,`LIMA`,`CALLAO`,`AREQUIPA`,`TRUJILLO`,`CUSCO`…
- **CORE BRAND kimliği belirler.** Truncation/typo/spacing/word-order/punctuation/kısaltma = AYNI firma.
- **★ PERSONA FÍSICA / EIRL / EMPRESA UNIPERSONAL = MEŞRU FİRMA:** AR'da `persona física/humana`, `empresa unipersonal`; PE'de `E.I.R.L.` ve şahıs adları GERÇEK tek-kişilik firmadır. **Kişi adı görünce otomatik GARBAGE deme** (MX Round-4'ten FARK — orada slash-format çöptü; AR/PE'de şahıs-firma yaygın ve meşru). Yalnızca açıkça anlamsız (boş/`#N/A`/salt-noktalama) olanı garbage say. İki kişi-adı varyantı (sıra farkı) AYNI kişi/firma ise SAME.
- **Paylaşılan JENERİK kelime ≠ kimlik:** `IMPORTADORA`,`COMERCIAL`,`DISTRIBUIDORA`,`GRUPO`,`INVERSIONES`,`SERVICIOS`,`CONSTRUCTORA`,`TRANSPORTES`,`AGRO`,`MINERA` + FARKLI ayırt edici kelime = FARKLI firma.
- **GARBAGE:** `#N/A`, salt-sayı, tek/çift harf, çekirdeksiz nokta-çorbası, gümrük dizeleri (`same as`,`consignee`).

Çıktı: **AR precision + PE precision + birleşik** + stage-bazlı (her ülke) + hata-kaynağı payı + **COUNTRY_LEAK sayısı**. (record-level + stage-weighted, seed sabit.)

---
## ADIM 2 — ★ A ve C düzeltmeleri AR/PE'de çalışıyor mu? (kanıt)
- **A (core-coverage gate) çok-ülkeli doğrulama:** `qa4_verify_coverage.py` desenini KULLAN ama `"MX"`→ AR ve PE; tabloyu config'ten oku. AR/PE'den GERÇEK subset over-merge adayları seç (kısa isim ⊂ uzun master). Gate OFF vs ON hit sayısı: subset→0, tam-isim kontrol→1 olmalı. **Modül-içi `es_queries.ENABLE_CORE_COVERAGE_GATE` toggle'la (config import-by-value).** STRIPPED token_count alanı `stripped_search_analyzer` (global) ile hizalı mı — AR/PE isimlerinde de doğrula (Round-4 MX'te per-country==global idi; AR/PE için `_get_token_count` global vs `_..._ar`/`_pe` karşılaştır, FARK varsa raporla — gate global kullanıyor).
- **Magnet taraması (A-sınıfı) ülke-bazlı:** `qa4_magnet_scan.py` desenini KULLAN, country_code filtreli, ES `fingerprint_analyzer` ile size≥5 master'larda degenere-fp oranı. AR/PE'de akronim magnet OLUŞMUYOR mu? (≈0 beklenir; oluşuyorsa AR/PE'ye özgü akronim deseni var mı incele — örn `Y.P.F.`, `S.A.C.` çökmesi).
- **C (placeholder) çalışıyor mu:** EXCLUDED kayıtlarda AR `consumidor final`/`sin razon social`, PE `publico en general`, common `same as cnee` var mı? Bunlar master magnet OLUŞTURMUYOR mu (EXCLUDED → indekslenmez).
- **AR/PE'ye özgü YENİ placeholder var mı:** EXCLUDED dışı NEW_MASTER/eşleşmelerde sık tekrar eden firma-olmayan ifade (örn `varios`, `cliente`, `proveedor`, `s/d`, `sin datos`, AR/PE gümrük) tara → tespit edersen `synonyms_data/ar.json|pe.json` veya `common.json` `non_firm_placeholders`'a **öneri** (CLAUDE.md Rule 4: hardcode YOK, JSON'a; kör ekleme yapma, gözlemle).

---
## ADIM 3 — Recall + glue (kısmi veri uyarısıyla)
- Rematch erken/kısmi → NEW_MASTER oranı yapay yüksek; **mutlak recall ölçme**, oran/yapısal teyitle yetin.
- **Glue/fingerprint tutarlılığı (yapısal, ES `_analyze`):** AR/PE varyant çiftleri aynı fingerprint'e iniyor mu? Örn `YPF S.A.`/`Y.P.F. SOCIEDAD ANONIMA`→aynı; `BACKUS S.A.A.`/`UNION DE CERVECERIAS BACKUS` farklı (marka). Suffix/geo varyantları tutarlı mı (AR `... ARGENTINA S.A.` / PE `... DEL PERU S.A.C.`).
- **Gate recall maliyeti:** core-coverage gate AR/PE'de gerçek-kesik firmaları NEW_MASTER yapıyor mu? `analysis/live_probe.py` AR/PE golden set ile koşulabilir mi? (live_probe MX golden içeriyorsa AR/PE örnekleriyle genişletmeyi ÖNER, kör değiştirme.)

---
## ADIM 4 — Hata desenleri (AR/PE) + min_score gerekli mi (D yeniden değerlendir)
- MX'teki D1-D5 desenlerinin AR/PE'de hangileri baskın? `qa4_dump_wrong.py`/`qa4_show_wrong.py` desenini KULLAN (config tablo + country). Ham isimlerle (kısaltmasız) yanlışları stage-bazlı listele, her birine kök-neden yaz.
- **D (min_score) AR/PE'de farklı mı?** Round-4'te MX'te D recall'ı kırdı (geri alındı). AR/PE skor dağılımını çıkar (FUZZY/TOKEN, doğru vs yanlış histogramı); A zaten over-merge'i kapatıyorsa D yine GEREKSİZ olmalı — DOĞRULA, kör açma. ALCATEL-tipi subset AR/PE'de A ile kapanıyor mu?
- **AR/PE'ye özgü desen:** persona-física/EIRL kişi-firma varyantları (MX'te garbage'dı, burada meşru) doğru gruplanıyor mu, yoksa farklı kişiler mi birleşiyor? Bu yeni bir hata sınıfı (E?) olabilir.

---
## ADIM 5 — Karşılaştırma tablosu + temel kurma
| Metrik | MX R4 (ref) | **AR R5** | **PE R5** | AR+PE birleşik |
Satırlar: kalibre precision · stage precision (4) · max magnet · akronim-magnet/üye · **COUNTRY_LEAK sayısı** · EXCLUDED (placeholder) · NEW_MASTER oranı (kısmi) · baskın hata sınıfı · A-gate etki (subset→0 kanıtı) · C-placeholder etki. MX ile FARKLAR (legal-suffix, persona-física, iki-ülke) vurgula.

---
## ARAÇLAR (token-optimize: YENİDEN KULLAN, sıfırdan yazma — ama HARDCODE'u config'e çevir)
- `C:/tmp/qa4_random_precision.py` (RAW_TABLE_NAME kullanıyor ✓ — ülke-bazlı örneklem için MATCH_STAGES filtresine `country_code` ekle) · `qa4_workflow.js` (RULES'u AR/PE ile değiştir, model:'haiku', 40 batch, schema) · `qa4_make_batches.py` · `qa4_aggregate.py`.
- `qa4_magnet_scan.py` / `qa4_verify_coverage.py` / `qa4_show_wrong.py` / `qa4_dump_wrong.py`: **hardcoded `p7_firms_v2` → `config.RAW_TABLE_NAME`; `"MX"` → AR/PE (satır country_code'undan)**. Mevcut MX dilimine ait eski batch/result dosyalarını TEMİZLE, yeniden üret.
- `qa4_probe_isolate.py` (gate/min_score izolasyon, live_probe 4-config) · `analysis/detectors.py` · `analysis/live_probe.py` · ES `_analyze` (salt-oku).
- `synonym_loader.get_non_firm_placeholders(cc)`, `get_legal_suffixes`/analyzer çıktısı — ülke token'ları için TEK kaynak (hardcode YOK).
- `PYTHONUTF8=1 PYTHONPATH=C:/All-project/ta-code-merge`.

## KATI KURALLAR
- **country_code HARD FILTER — ARTIK İKİ ÜLKE.** AR≠PE; COUNTRY_LEAK gerçek hata. `_routing` büyük-harf country_code. Bir master tek ülke.
- Python'da fuzzy/Levenshtein YASAK; benzerlik/identity ES-side; benzerlik yalnız aday ön-elemesi.
- Python'da eşleşme DOĞRULAMASI yapma; salt PG'den OKU (SELECT). ES `_analyze` salt-oku SERBEST.
- **Hardcoded ülke token'ı YOK** (CLAUDE.md Rule 4): legal-suffix/geo/placeholder daima `synonyms_data/*.json` + `synonym_loader`'dan. `non_firm_placeholders` kategorisi eklemeye AÇIK (common/ar/pe.json) — gözlemle, kör ekleme.
- `p7_firms_v2_ar_pe`'ye YAZMA (salt-okunur). main_processor'ı SEN çalıştırma (yazma = kullanıcının pipeline'ı).

## TOKEN/MALİYET OPTİMİZASYONU
- Mevcut `C:/tmp` scriptlerini KULLAN; sıfırdan kurma (yoksa kur). Tüm yargı Haiku (`model:'haiku'`), 10'ar batch, schema'lı yapısal çıktı, offline aggregate.
- Karşılaştırma ORAN-bazlı (rematch kısmi/erken ise mutlak sayılar büyür/yanlı).
- Pool cap'leri koru (random ~400 = AR ~200 + PE ~200; over 600 / control 120 / split 500).
- Büyük dosyaları gereksiz RE-READ etme; hedefli grep/SELECT.
- Rematch erken/koşuyorsa: snapshot'ta ölç + "kısmi/oran-bazlı/erken-id-yanlı" işaretle; yeterli matched yoksa kullanıcıya ilerleme sor.

## ÇIKTI
`docs/audit/2026-06-XX-round5-ar-pe-validation.md`:
1. ADIM 0 doğrulama (glue+gate canlı; **COUNTRY_LEAK kapısı sonucu**; ülke dağılımı; kısmi-rematch notu; EXCLUDED placeholder kanıtı).
2. Kalibre precision (AR + PE ayrı + birleşik) + 4-stage tablo.
3. ★ A (core-coverage) + C (placeholder) AR/PE'de çalışıyor kanıtı (subset→0, magnet≈0, EXCLUDED).
4. AR/PE hata desenleri (ham isim + kök-neden) + persona-física yeni sınıf + min_score(D) gereksiz mi.
5. MX-R4 vs AR vs PE karşılaştırma tablosu + 3-5 maddelik "en yüksek etki" özeti + onay iste.

## NOTLAR / DURUM
- Son iş: A+C TDD ile uygulandı (203 test); D geri alındı (recall-safe); `NON_FIRM_PLACEHOLDERS` config-hardcode'dan `synonyms_data/*.json` `non_firm_placeholders` kategorisine taşındı (synonym_loader/input_filter refactor, CLAUDE.md Rule 4); `core_name.py` suffix-fragment ülke-bilinçli (`_SUFFIX_FRAGMENTS_BY_COUNTRY`). A+C **commit edilmemiş olabilir** — git durumunu kontrol et.
- Tablo: `p7_firms_v2_ar_pe` (PE 229.277 + AR 171.328); işlenmiş ~46.2k (%11,5, erken). `ES_INDEX=living_companies_v1` (AR/PE oraya indekslenmiş olmalı — KAPI'da doğrula; MX verisiyle aynı index'te ise country filter ayırır).
- Memory: `match-quality-fix-roadmap` (Round-4 A+C+D detayı), `no-python-verification-es-side`, `no-hardcoded-country-tokens`, `subagent-model-selection`.
- Referans raporlar: `docs/audit/2026-06-10-round4-reindex-rematch-validation.md`, `docs/audit/2026-06-10-round4-yanlis-eslesme-analizi.md`.
