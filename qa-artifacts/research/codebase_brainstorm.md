# Over/Under-Merge Hata Sınıfı Brainstorm
**Tarih:** 2026-06-15  
**Dayanak:** Round-5/6/7 denetimleri + canlı codebase analizi (es_queries.py, es_manager.py, es_ingest.py, config.py)  
**Kısıt hatırlatma:** Python fuzzy YASAK; country_code hard filter; synonyms_data/ sabit (non_firm_placeholders hariç); master=1 ES doc + variations[].

---

## Hata Sınıfı 1 — Geo-Mıknatıs (STRIPPED_EXACT geo-only birleşme)

**Kök neden:**  
`es_manager.py` satır 173-187: `stripped_search_analyzer_{cc}` ve global `stripped_search_analyzer` zincirlerine `geo_stopwords_global` eklenmemiş. Oysa `geo_stopwords_global` tanımı satır 189-199'da var ama yalnızca `fingerprint_analyzer`'a (satır 219) bağlanmış.

Sonuç: `SAL ARGENTINA S.R.L.` → stripped → `['argentina']`; `R B ARGENTINA` → `['argentina']`; `UNLIMITED ARGENTINA` → `['argentina']`. Hepsi `token_count=1`, tek-geo-token mıknatısı. `_has_distinctive_core` (es_queries.py:77-106) "argentina" = 9-harfli alfabetik `len≥2` → ayırt edici sanıyor → guard geçiyor. Index'te 34.178 `count=1` girişi (Round-7 tanısal).

**Fix Seçeneği A — geo_stopwords'ü stripped zincire ekle (ÖNERİLEN)**  
`es_manager.py` satır 173'teki per-country döngüsünde:  
```python
"filter": base_clean_filters + [filter_name, "legal_fragment_stop", "geo_stopwords_global"]
```
Satır 183-187 global fallback'te de aynı ekleme. `geo_stopwords_global` tanımı (~satır 189) bu döngüden önce (`~satır 157`'ye) taşınmalı (forward ref sorunu).  
- **Artı:** `SAL ARGENTINA` → `[]` → `_has_distinctive_core`=False → MATCH_NONE → NEW_MASTER. Geo-only mıknatıs tamamen ölür. `AUDI ARGENTINA` → `['audi']` → gerçek eşleşmeler korunur.  
- **Eksi:** "geo TOKEN ayırt edici" olan gerçek ticarî isimler yok sayılabilir? → `synonyms_data/*/countries.json`'dan türetildiği için gerçek marka adlarıyla çakışma minimumdur.  
- **Recall etkisi:** NÖTR. `fingerprint_analyzer`'da zaten geo-stop var → semantik olarak tutarlı.  
- **Reindex:** EVET — analyzer zinciri değişiyor; `python es_manager.py --force`.

**Fix Seçeneği B — `_has_distinctive_core` geo-farkındalığı**  
`es_queries.py:77`'deki `_has_distinctive_core` fonksiyonuna ülkeye ait geo listesini (JSON'dan çek) vererek "geo-only residual → False" mantığı Python'da ekle.  
- **Artı:** Reindex gerektirmez; hızlı patch.  
- **Eksi:** CLAUDE.md §1 "fuzzy Python YASAK" ruhuna yakın değil; analyzer çıktısını Python'da yeniden yorumlamak ES-side prensibini çiğner. Ayrıca `_get_stripped_analyzer(country)` zaten ES'i çağırıyor → round-trip sayısı 2'ye çıkar.  
- **Reindex:** HAYIR — ama tasarım açısından Seçenek A tercih edilmeli.

**Fix Seçeneği C — per-country stripped analyzer'a ülke-özel geo list ekle**  
Satır 161-174 döngüsünde `get_country_name_tokens(cc)` zaten çağrılıyor. Bu token'ları `legal_fragment_stop` gibi per-cc stop filter olarak ekle (global değil cc-özel).  
- **Artı:** "Seçici" — AR analyzer "argentina" düşürür ama MX "mexico" düşürmek için kendi listesini alır; çapraz-ülke sentinel isimleri korunur.  
- **Eksi:** A'dan daha karmaşık; config çoğalır; MX'te `mexico` zaten fingerprint_analyzer'da düşüyor → global yeterli.  
- **Reindex:** EVET.

**→ Öneri: Fix A** — tek satır değişiklik + taşıma; en temiz, recall-nötr, tek reindex penceresine giriyor.

---

## Hata Sınıfı 2 — Token Tekrarı (`PERNOD RICARD` ⇸ `RICARD RICARD ARGENTINA`, `ADIDAS ADIDAS`)

**Kök neden:**  
`es_ingest.py` Painless clean script (satır 51-95) ardışık token dedup YAPMIYOR. Kaynak veride `RICARD RICARD ARGENTINA` gibi yinelenen token'lar `variations` / `variations_stripped`'a ham biçimde giriyor. `TOKEN_COVERAGE` `operator:and` kullandığı için `RICARD RICARD` → sorgu `['ricard']` eşleşiyor (`PERNOD RICARD` master'ındaki tek `ricard` token'ını karşılıyor). Skor 27 (Round-7 en yüksek over-merge skoru).

**Fix Seçeneği A — Painless'e ardışık-yinelenen-token dedup ekle (ÖNERİLEN)**  
`es_ingest.py:_build_clean_script()` içinde mevcut "Çift boşluk temizliği" adımından sonra, result string'e eklemeden önce space-split + ardışık-tekrar atma:  
```
// Painless pseudocode:
def tokens = text.split(' ');
def deduped = new ArrayList();
for (t in tokens) { if (deduped.isEmpty() || deduped.get(deduped.size()-1) != t) deduped.add(t); }
text = String.join(' ', deduped);
```
Hem `variations` hem `variations_stripped` pipeline'ını etkiler (aynı `ctx.variations` üzerinden).  
- **Artı:** `RICARD RICARD ARGENTINA` → `RICARD ARGENTINA` → stripped → `['argentina']` (Sınıf 1 fix ile birlikte `[]`) veya en azından tek-RICARD → PERNOD RICARD çekirdeğiyle token_count eşitliği bozulur (1≠2).  
- **Eksi:** Gerçek adı `COTO CENTRO CENTRO` olan (kasıtlı tekrar) firma varsa bilgi kaybı — pratikte yok.  
- **Recall etkisi:** NÖTR.  
- **Reindex:** EVET (ingest pipeline değişiyor; `python es_ingest.py` + `--force`).

**Fix Seçeneği B — ES `unique` token filter (analyzer-side)**  
`es_manager.py` zincirlerine `unique` built-in token filter ekle (clean_analyzer ve stripped). Bu arama-zamanında tekrar token'ları eler.  
- **Artı:** Hiçbir ingest değişikliği yok; var olan dokümanlar etkilenir (arama zamanı).  
- **Eksi:** `unique` index-time ile arama-time arasında token_count asimetrisi yaratır (INDEX'te `ricard ricard` 2 token ama ARAMA'da 1). `token_count` filtresi bozulur.  
- **Reindex:** Kısmi (mapping güncellenmeli; `update_by_query` yetersiz → tam reindex).

**Fix Seçeneği C — `_core_coverage_filter` unique-aware skor**  
Mevcut `token_count` filtresi tekrarlı kayıtları yakalamıyor (kaynak 2 token, hedef 2 token — count eşit). Kaynak `RICARD RICARD` 2 token, master `PERNOD RICARD` 2 token → count eşit → gate geçiyor. Arama zamanında `script_score` ile unique token sayısı hesapla.  
- **Artı:** Reindex gerektirmez.  
- **Eksi:** Script_score pahalı; karmaşık; "token_count" yerleşik alanı unique count'u YANSITMAZ. ES-side ama fazla karmaşık.  
- **Reindex:** HAYIR.

**→ Öneri: Fix A** — temiz; kök neden kaynakta (ingest) çözülüyor; fingerprint kalitesini de iyileştirir; zaten zorunlu olan reindex penceresine giriyor.

---

## Hata Sınıfı 3 — Subset/Truncation (`BANCO MACRO` ⇸ `BANCO MACRO BANSUD`, `ASOCIACION CASA EDITORA` ⇸ `...SUDAMERICANA`)

**Kök neden:**  
`TOKEN_COVERAGE` (es_queries.py:316) ve `FUZZY_PHRASE` (es_queries.py:360) zaten `_core_coverage_filter` (satır 351, 391) kullanıyor. STRIPPED token_count eşitliği zorluyor. ANCAK `SUFFIX_FUZZY` (satır 268-313) `_core_coverage_filter` ÇAĞIRMIYOR (R7 §2.2 kesin kanıt). Bu stage `enabled=False` (config.py:227) olduğu için şu an KAPATILMIŞ — ama gelecekte açılırsa veya subset hataları başka mekanizmayla sızıyorsa:

`_core_coverage_filter` mantığı (es_queries.py:131-164): `STRIPPED_EXACT` global analyzer ile token_count hesaplıyor; eşleşen master'ın `variations_stripped.name.token_count` NESTEDe bu count'a EŞİT olmalı. `BANCO MACRO` (2 token) ⊂ `BANCO MACRO BANSUD` (3 token) → 2≠3 → filtreli stage'lerde geçmiyor. ✓ Doğru çalışıyor.

Kalan subset sızıntıları için:

**Fix Seçeneği A — `_core_coverage_filter`'a `minimum` (≥ sorgu_count) modu ekle (ÖNERİLEN)**  
Mevcut filtre EŞİTLİK (=) zorluyor. "Ayırt edici token tamamen örtüşüyor ama master daha uzun" durumu (meşru variant: `BANCO MACRO` → `BANCO MACRO SA`) zaten STRIPPED_EXACT'e düşüyor. Eşitlik FUZZY/TOKEN için doğru. Ekstra güvenlik: `token_count >= sorgu_count` (≥ mod) ile uzun-master da kabul et:  
```python
# variations_stripped.name.token_count >= count (range query)
{"range": {"variations_stripped.name.token_count": {"gte": count}}}
```
  Bu "truncated kayıt master'a giremesin" kuralını korur (kısa girdi ≥ count gerektiriyor).  
- **Artı:** `ASOCIACION CASA EDITORA SUDAMERICANA` master'ı, `ASOCIACION CASA EDITORA` (kısa) sorguyla hâlâ eşleşmez (5 < 7 ≥ 5 → geçer!). Hayır, bu ≥ kuralı subset için KÖTÜ — `BANCO MACRO` (2 token) `BANCO MACRO BANSUD` (3 token) → 3≥2 → geçiyor → over-merge devam eder. Yani `≥` modu hatalı.  
- **Sonuç:** EŞİTLİK (=) doğru; zaten uygulanmış. Sınıf 3 aslında FUZZY/TOKEN için ÇÖZÜLMÜŞ; yalnızca SUFFIX_FUZZY (kapalı) sorunlu.  
- **Reindex:** HAYIR (mevcut logic doğru).

**Fix Seçeneği B — SUFFIX_FUZZY'ye `_core_coverage_filter` ekle (kısa vadeli — ama stage kapalı)**  
Stage şu an `enabled=False`. Yeniden açılacaksa R7 R2 önerisini uygula:  
```python
"must": [
    nested_match_phrase_on_variations_stripped,
    *_core_coverage_filter(es, name, country),  # ← EKLE
],
```
- **Artı:** Stage açıldığında subset/truncation sızıntısı kapanır; diğer stage'lerle simetrik hale gelir.  
- **Eksi:** Stage şu an kapalı; öncelik düşük.  
- **Reindex:** HAYIR (`variations_stripped.name.token_count` alanı mevcut).

**Fix Seçeneği C — Ayırt edici token kayıp tespiti (`BANSUD` gibi)**  
Bazı subset hatalarında kaybolan token (`BANSUD`, `SUDAMERICANA`) gerçekten ayırt edicidir. Token sayısı EŞİT ama anlam farklı durumu (Sınıf 4 ile örtüşür). Bu için: sorgu token'larının master varyantında %100 presence'ını nested `terms` query ile zorla.  
- **Artı:** `BANCO MACRO` ⊂ `BANCO MACRO BANSUD`: master varyantı `banco macro bansud` (3 token) vs sorgu 2 token → eşitlik zaten yakalar. `BANSUD` sorgu token'ı değil; tersinden sorulduğunda (sorgu=`BANCO MACRO BANSUD`, master=`BANCO MACRO`) → 3≠2 → eşitlik engelliyor.  
- **Sonuç:** Yine eşitlik (=) zaten doğru; ekstra fix gereksiz.

**→ Öneri:** FUZZY/TOKEN sınıfı 3 **ÇÖZÜLMÜŞ** (eşitlik gate aktif). Geriye yalnızca SUFFIX_FUZZY kalıyor — stage açıldığında Fix B uygulanmalı. Ayrı reindex gerektirmez.

---

## Hata Sınıfı 4 — Eşit-Token Farklı-Marka (`ALL OVER SHIPPING` ⇸ `ALL IN SHIPPING`, `OCEAN EXPORT` ⇸ `OCEAN IMPORT`)

**Kök neden:**  
`_core_coverage_filter` token_count EŞİTLİĞİ zorluyor ama token KİMLİĞİNİ doğrulamıyor. `ALL OVER SHIPPING` (3 token) = `ALL IN SHIPPING` (3 token) → count eşit → gate geçiyor. Ama `OVER ≠ IN` (yüksek-bilgi taşıyan token). ES `TOKEN_COVERAGE` `operator:and` sorgu token'larının master'da var olduğunu doğruluyor (müzik: ALL + IN + SHIPPING) ama `OVER` yerine `IN` farklı; bu nedenle `ALL OVER SHIPPING` sorgusu `ALL IN SHIPPING` master'ına 3/3 token ile eşleşiyor çünkü `in` de common kelime.

Daha derin neden: `operator:and` "sorgunun TÜM token'ları master'da var mı" soruyor — ama küçük değişkenlerin (OVER/IN/EXPORT/IMPORT) nadir mi yaygın mı olduğunu bilmiyor.

**Fix Seçeneği A — IDF-ağırlıklı `match` → `rare` token penalty (ÖNERİLEN)**  
ES `match` query zaten IDF kullanıyor (`operator:and` ile birlikte TF-IDF skoru). Sorun min_score eşiği düşük — `ALL IN SHIPPING` ↔ `ALL OVER SHIPPING` skorları yakın. `min_score` artırılsa recall da düşer (Round-4'te kanıtlandı: 3.0→11.0 recall yarıya indi). Gerçek çözüm: **nadir token'a script_score ile ağırlık** (rescore window).  
- Artı: Nadir token (OVER≠IN) büyük fark yaratır; skor uçurumu açılır.  
- Eksi: `script_score` + rescore pahalı; tüm eşleşmelere uygulanır; parametre kalibrasyonu gerekir.  
- **Reindex:** HAYIR (query-time).

**Fix Seçeneği B — Nested `terms` filtresi: "sorgu token'larının tamamı master varyantında bulunmalı"**  
Şu an `TOKEN_COVERAGE` sorgu-token'larının master'da varlığını `match ... operator:and` ile sağlıyor ama bu nested query sırası bağımlı. `_core_coverage_filter`'a ek: `nested` filter içinde `match_phrase` `slop:0` yerine token kimliği kontrolü.  
- Artı: Basit; mevcut altyapıya ekleme.  
- Eksi: `OCEAN EXPORT/IMPORT` gibi yüksek-frekanslı token çiftlerini yine ayırt etmez (her ikisi de yaygın).  
- **Reindex:** HAYIR.

**Fix Seçeneği C — En-az-1-nadir-token zorunluluğu (IDF script filter)**  
Rescore window'da: kazanmak için en az 1 token'ın IDF'i belirli bir eşiğin üzerinde olmalı. `significant_terms` ile "bu çiftte en ayırt edici token nedir?" ES-side hesaplanabilir (offline term stats).  
- Artı: Gerçek "anlamlılık" sinyali kullanıyor.  
- Eksi: `significant_terms` online query'de kullanmak zor; ayrı aşama/önhesaplama gerekir; karmaşıklık yüksek.  
- **Reindex:** HAYIR, ama offline stats index'i ayrı gerekebilir.

**→ Öneri:** Bu sınıf **düşük hacim** (R7'de 2 onaylanmış örnek). İ1 geo-stop + token_count eşitliği sonrası kalan örnek sayısını yeniden ölç (Round-8). Hacim hâlâ yüksekse Fix A (min_score kalibrasyonu + rescore ağırlığı) dene. Acil değil; Round-8 sonrası karar ver.

---

## Hata Sınıfı 5 — Aşırı-Strip / Dejenere Çekirdek (427-token global stopword birleşimi)

**Kök neden:**  
`es_manager.py:177`: `generic_stopwords_global` = TÜM ülke `company_type_tokens` birleşimi. Bu ~427 token içeriyor. AR'da `SAL` (Sociedad Anónima limitada kısaltması) bu listede; `UNLIMITED` bazı ülkelerin company_type'ı olarak geçebilir. Sonuç: `SAL ARGENTINA` → SAL de sıyrılıyor (company_type AR listesinde), ARGENTINA Sınıf 1 ile sıyrılırsa geriye `[]` kalıyor → NEW_MASTER (istenilen sonuç, ama SAL'ın meşru firma kısmı olduğu durum için).

`es_ingest.py:_build_stripped_script()` (satır 98-143): ülkeye-özel `get_legal_suffix_tokens(cc)` + `get_article_stopwords(cc)` kullanıyor (per-country, doğru). Ama `stripped_search_analyzer` global zinciri `generic_stopwords_global` (tüm ülkeler birleşimi) kullanıyor → arama-zamanında çok agresif.

**Fix Seçeneği A — Per-country stripped search analyzer'ı her zaman kullan, global fallback'i son çare yap (ÖNERİLEN)**  
`_get_stripped_analyzer(country)` (es_queries.py:49-56) ülke biliniyorsa cc-özel, bilinmiyorsa global döndürüyor. Kod doğru ama `_core_coverage_filter` (satır 154): **her zaman `stripped_search_analyzer` (global) kullanıyor**, cc-özel değil. Bu tutarsızlık: `_get_stripped_analyzer` cc-özel döndürürken `_core_coverage_filter` global sayıyor → token_count mismatch.  
Düzeltme: `_core_coverage_filter` imzasına `country` ekle, `_get_stripped_analyzer(country)` çağır.  
- Artı: Arama-zamanı ve count-hesabı aynı analyzer'ı kullanır → token_count tutarlı.  
- Eksi: Küçük imza değişikliği (`es_queries.py` + çağıranlar güncellenmeli).  
- **Reindex:** HAYIR (query-time fix; ingest token_count alanı global stripped ile indekslenmiş → count hesabında da global kullanmak daha tutarlı. Aslında ingest `stripped_search_analyzer` (global) ile token_count indeksliyor → global tutmak DOĞRU. Bu fix YANLIŞLIKLA öncelikli görünüyor).

Gerçek durum: `variations_stripped.name.token_count` alanı `es_manager.py:333` → `"analyzer": "stripped_search_analyzer"` (global) ile tanımlı. `_core_coverage_filter` de global kullanıyor → **tutarlı**. Per-country fark R5'te 300 örnekde %1 olarak raporlandı — ihmal edilebilir.

**Fix Seçeneği B — `generic_stopwords_global`'ı ülkeler kesişimiyle sınırla (yüksek-emin stopwords)**  
Tüm ülke listelerinin KESIŞIMINDE olan token'lar (ör. "sa", "ltda", "inc") → global; YALNIZCA bir ülkede geçen token'lar (ör. AR-özgü "sal") → o ülkenin cc-özel stripped analyzer'ına (zaten ekleniyor), global'dan çıkar.  
- Artı: Aşırı-strip azalır; "SAL" gibi token'lar yalnızca AR stripped'ında düşürülür, global'da değil.  
- Eksi: Kesişim hesabı karmaşık; `get_all_company_type_tokens()` yeniden yapılandırılmalı.  
- **Reindex:** EVET.

**Fix Seçeneği C — `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` ≥ 3 yap**  
`config.py:148`: şu an `2`. Tek 2-harfli kalıntı üzerinden dejenere dedup engellenmiş ama 2-harfli gerçek markalar (VF, GM, 3M) korunuyor. Bazı aşırı-strip sonuçları 2-harfli kalıntı üretiyor (`'av'`, `'ad'`) → magnet. `≥3`'e çıkarmak bu kalıntıları da engeller.  
- Artı: Kolay; kod değişikliği, reindex yok.  
- Eksi: `GM`, `VF` gibi 2-harfli gerçek markalar zarar görür (fingerprint dedup çalışmaz). R2 audit: "≥2 bile yetersiz — asıl çözüm analyzer-side" diye raporlandı. Bu bir workaround, kök neden değil.  
- **Reindex:** HAYIR.

**→ Öneri:** Aşırı-strip'in asıl çözümü Fix A (Sınıf 1 ile birlikte geo-stop) + per-country stripped analyzer tutarlılığı. Fix C workaround; Fix B uzun vadeli hijyen. Şu an bu sınıf kritik değil (dejenere dedup magnet'leri Round-5'te 0 ölçüldü).

---

## Hata Sınıfı 6 — PE Blocker (analyzer index'te yok → 0 eşleşme)

**Kök neden:**  
`es_manager.py:161-174` her ülke için `stripped_search_analyzer_{cc}` ve `clean_analyzer_{cc}` üretiyor. Ama index `pe.json` oluşturulmadan önce kurulmuş → PE analyzer'ları index'e girmemiş. `_get_stripped_analyzer("PE")` artık `stripped_search_analyzer_pe` döndürüyor (pe.json diskte var) → ES `_analyze` 400 hatası → her PE kaydı sessizce NEW_MASTER.

Canlı kanıt (R7 §2.1): `POST /living_companies_v1/_analyze {"analyzer":"stripped_search_analyzer_pe"}` → 400.

**Fix Seçeneği A — `python es_manager.py --force` (ÖNERİLEN, tek gerekli fix)**  
Kod değişikliği YOKTUR. Sadece `--force` reindex.  
- `build_index_settings(es)` PE analyzer'larını otomatik üretir (kod doğru, index stale).  
- Aynı komut İ1 (geo-stop) + İ3 (token-dedup) + İ2 (PE) hepsini tek seferde canlıya alır.  
- **Artı:** Sıfır kod değişikliği; kesin çözüm.  
- **Eksi:** Uzun süre (saatler); mevcut eşleştirmeler silinip yeniden üretilir (zaten %35-40 yarım, kayıp önemsiz).  
- **Reindex:** EVET (zorunlu).

**Fix Seçeneği B — `_get_stripped_analyzer` fallback'ini agresifleştir**  
`es_queries.py:50-56`: bilinmeyen ülke `stripped_search_analyzer` (global) döndürüyor. PE biliniyor ama analyzer yok → 400. Global'a düşmek yerine hata yakalanıp skip edilseydi sessiz NEW_MASTER üretilmezdi ama sorun çözülmezdi.  
- **Bu bir workaround** değil, teşhis kolaylığı. Asıl fix Seçenek A.  
- **Reindex:** HAYIR — ama yanlış anlam.

**Fix Seçeneği C — Index sağlık kontrolü: startup'ta analyzer varlığını doğrula**  
`main_processor.py` başlangıcında `es.indices.analyze` ile bilinen ülkelerin analyzer'larını test et; eksik varsa warn/abort.  
- **Artı:** Kör nokta kapanır; reindex yapılmadan yanlış veri üretilmez.  
- **Eksi:** Ek startup maliyeti; pe.json'u çözmez.  
- **Reindex:** HAYIR — ama anlamsız tek başına.

**→ Öneri:** Fix A (reindex) zorunlu; Fix C iyi-mühendislik gereği eklenebilir ama bağımsız tasklarda ele alınmalı.

---

## Hata Sınıfı 7 — Under-Merge / Recall (noktalama-only AR varyantları, PE tam-duplar)

**Kök neden:**  
a) `DAVICA S.A. I C A I` → `es_ingest.py` Painless (satır 82): `[^\w\s&.\-]` özel karakter temizliği `I C A I` kısmını "özel karakter" sanıp silmiyor (harf+boşluk) ama `I`, `C`, `A`, `I` tek-harf token'lar → `legal_fragment_stop` (es_manager.py:140) yasal-ek parça olarak düşürüyor → stripped `['davica']`. Başka varyant `DAVICA SA` → stripped `['davica']`. Bunlar aynı; STRIPPED_EXACT yakalıyor. Kök sorun değil; bu belki doğru birleşiyor.  
b) PE tam-duplar (sim=1.0): PE analyzer 0 çalıştığından `STRIPPED_EXACT` 400 hatasıyla düşüyor → batch-içi fingerprint auto-dedup yakalıyor ama farklı batch'lerde yakalayamıyor. Fix: Sınıf 6 çözümü (reindex).  
c) AR'da `COMPL-xxxx` gümrük kodu varyantları (R5 §3): `TLP S.A COMPL-XXXX` ×3 → fingerprint `'compl tlp xxxx'` (numara içeriyor) → farklı COMPL numaralı kayıtlar ayrı master → under-merge. `COMPL` token'ını article/stopword olarak synonym'e veya ingest strip'e ekle.

**Fix Seçeneği A — PE reindex (Sınıf 6 Fix A ile aynı)**  
PE tam-duplar otomatik çözülür.  
- **Reindex:** EVET.

**Fix Seçeneği B — `COMPL` token'ını `input_filter` veya stripped stop list'e ekle**  
`get_legal_suffix_tokens("AR")` veya `get_article_stopwords("AR")` aracılığıyla `compl` token'ı stripped listesine (synonyms_data/ar.json). Ama `synonyms_data/ SABİT` kuralı var; bu durumda `SUFFIX_TYPO_MAP` veya `config.py`'de hardcode alternatifleri düşün. CLAUDE.md §1.4 uyarınca `non_firm_placeholders` dışı JSON ekleme yasak — ama `compl` bir placeholder değil. Bu durumda `input_filter.py`'de regex ile "isim COMPL-\\d+" → COMPL+numara strip.  
- **Artı:** Under-merge kapanır; TLP tüm varyantları birleşir.  
- **Eksi:** JSON'a dokunulmadan `input_filter` veya Painless'te çözülmeli (tasarım kısıtı).  
- **Reindex:** EVET (ingest değişirse).

**Fix Seçeneği C — `CANONICAL_EXACT` synonym genişlemesi**  
`synonyms_data/ar.json`'da `complejo, complemento, compl => compl` synonym kuralı. Ama bu yine SABİT JSON kuralını gevşetiyor.  
- **Eksi:** CLAUDE.md §1 kuralı çiğner; riskli.  
- **→ Öneri:** Fix A (PE açılır) + Fix B (`compl` pattern'ı `input_filter` veya Painless ile strip).

---

## Hata Sınıfı 8 — 830 Duplike NEW_MASTER (AUTO_DEDUP match_type demote eksikliği)

**Kök neden:**  
`config.py:131` `AUTO_DEDUP_PER_BATCH = True`. `dedup_auto_merge` (main_processor.py veya ayrı fonksiyon) aynı fingerprint'li NEW_MASTER'ları birleştiriyor ama `match_type` alanını güncellemeden bırakıyor → her kayıt `match_type=NEW_MASTER` olarak kalıyor. Watch query `match_type != NEW_MASTER` üzerinden kurulu → birleşmiş kayıtlar `NEW_MASTER` olduğu için gözden kaçıyor. R7'de 830 duplike NEW_MASTER, R6'da 727; artıyor.

**Fix Seçeneği A — AUTO_DEDUP sonrası `match_type` demote et (ÖNERİLEN)**  
`dedup_auto_merge` tamamlandığında merged variation'ların (artık tek master'a bağlı) `match_type`'ını `AUTO_DEDUP` veya `DEDUP_MERGED` olarak güncelle (PG `UPDATE`).  
- Artı: Watch query kör noktası kapanır; raporlama doğrulanır.  
- Eksi: Yeni `MatchType` sabiti gerekir (`config.py:7-21`'e ekle); `AUTO_DEDUP` = `"AUTO_DEDUP"`.  
- **Reindex:** HAYIR.

**Fix Seçeneği B — Watch query'yi `master_code` UUID self-join'iyle güncelle**  
R7 §6: `v.master_code = m.master_code` UUID join. `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` bloğu ekle.  
- Artı: DB katmanında hızlı; kod değişikliği yok.  
- Eksi: Kök neden (`match_type` yanlış) düzeltilmez; raporlama geçici.  
- **Reindex:** HAYIR.

**Fix Seçeneği C — Duplicate NEW_MASTER'ı cron/offline job ile merge et**  
`dedup_reviewer.py` veya yeni bir `dedup_batch.py` scripti: PG'de `master_code` bazında `count(*) > 1` AND `match_type=NEW_MASTER` olanları toplu güncelle.  
- Artı: Mevcut 830'ı temizler (geriye dönük).  
- Eksi: Tekrarlı iş; kök neden kalıcı düzeltilmez.  
- **Reindex:** HAYIR.

**→ Öneri: Fix A + Fix B birlikte** — A kök nedeni kapatır, B watch query'yi hemen düzeltir. Fix C mevcut 830'ı temizlemek için bir seferlik çalıştırılabilir.

---

## Özet Tablo

| Hata Sınıfı | Önerilen Fix | Dosya:Satır | Reindex? |
|-------------|-------------|-------------|----------|
| 1. Geo-mıknatıs | `geo_stopwords_global`'ı `stripped_search_analyzer_{cc}` zincirine ekle | `es_manager.py:173,186` | **EVET** |
| 2. Token tekrarı | Painless clean script'e ardışık-tekrar dedup ekle | `es_ingest.py:_build_clean_script()` | **EVET** |
| 3. Subset/truncation | FUZZY/TOKEN'da `_core_coverage_filter` ÇÖZÜLDÜ; SUFFIX_FUZZY açılırsa oraya ekle | `es_queries.py:268-313` | HAYIR (stage kapalı) |
| 4. Eşit-token farklı-marka | Round-8 sonrası hacim ölç; gerekirse IDF rescore | `es_queries.py:316,360` | HAYIR |
| 5. Aşırı-strip/dejenere | Sınıf 1 fix'iyle örtüşür; cc-özel stripped tutarlılığı | `es_manager.py:173,_core_coverage_filter` | **EVET (Sınıf 1 ile)** |
| 6. PE blocker | `python es_manager.py --force` | `es_manager.py:433` | **EVET** |
| 7. Under-merge/recall | PE reindex (Sınıf 6); `compl` pattern ingest strip | `es_ingest.py`, `input_filter.py` | **EVET (kısmi)** |
| 8. 830 duplike NEW_MASTER | `dedup_auto_merge` sonrası `match_type=AUTO_DEDUP` + watch query UUID join | `config.py:7`, `main_processor.py` | HAYIR |

**Reindex gerektiren sınıflar: 1, 2, 5, 6, 7** — hepsi TEK reindex penceresinde (İ6) birleştirilebilir.

---

## Uygulama Sırası (Önerilen)

**Aşama A — Kod (reindex öncesi):**
1. `es_manager.py`: `geo_stopwords_global` tanımını satır ~157'ye taşı + Sınıf 1 Fix A (stripped zincirlere geo-stop ekle)
2. `es_ingest.py`: Sınıf 2 Fix A (Painless ardışık-tekrar dedup)
3. `config.py`: Sınıf 8 Fix A için `MatchType.AUTO_DEDUP = "AUTO_DEDUP"` ekle
4. `main_processor.py` (veya ilgili dedup fn): AUTO_DEDUP sonrası `match_type` güncelle

**Aşama B — Tek Reindex:**
```bash
python es_ingest.py        # Sınıf 2 + pipeline güncelle
python es_manager.py --force   # Sınıf 1 geo-stop + Sınıf 6 PE + Sınıf 5
python main_processor.py   # %35-40 → %100 rematch
```

**Aşama C — Reindex Sonrası:**
- Round-8 QA (haiku census + adversarial verify)
- Sınıf 4 hacim ölçümü → gerekirse IDF rescore
- Sınıf 8 watch query UUID join düzeltmesi
- Sınıf 7 `compl` pattern (düşük öncelik)
