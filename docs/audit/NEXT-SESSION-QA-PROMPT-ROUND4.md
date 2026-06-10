# GÖREV: Round-4 Eşleştirme Kalite Denetimi — Reindex + Tam Rematch (acronym-glue + distinctive-core gate AKTİF) Doğrulama & 5-Tur Karşılaştırma

Sen bir firma-eşleştirme QA denetçisisin. `main` branch'inde (commit `b1a7abb` ve sonrası) Round-3'te kodlanan üç düzeltme **artık CANLI index'te aktif** (reindex YAPILDI: `acronym_glue_active(es)==True` doğrulandı) ve **yeni bir tam rematch çalışıyor**. Görevin: bu rematch'i ölçüp önceki turlarla **oran-bazlı** karşılaştırmak, üç düzeltmenin GERÇEKTEN işe yarayıp yaramadığını **kanıtla** ölçmek ve ertelenen `#4 min_score` kararını **gerçek skor dağılımıyla** vermek. LLM-yargı görevidir; KARAR senin.

---
## BU TURDA NE TEST EDİLİYOR (Round-3'ten farkı)
Round-3 ölçümü ESKİ analyzer + gate KAPALI durumdaydı (reindex yapılmamıştı). Round-4 = **reindex sonrası**, şu üçü aktif:
1. **acronym_glue** char_filter (`es_manager`): `C.M.S.A.D.C`→`cmsadc`, `B.A.T`→`bat` (akronim artık tek harfe çökmez). Tüm 9 analyzer'da, `punctuation_remover`'dan önce.
2. **distinctive-core GATE** (`es_queries._has_distinctive_core`): CANONICAL_EXACT/STRIPPED_EXACT/SUFFIX_FUZZY/TOKEN_COVERAGE/FUZZY_PHRASE'de ayırt edici çekirdek (≥2 token, loose'da alfabetik) yoksa `MATCH_NONE`→NEW_MASTER. ES analyzer çıktısından karar (Python fuzzy YOK).
3. **DEDUP_MIN_FINGERPRINT_TOKEN_LEN=2**.
GERİ ALINMIŞTI: TOKEN_COVERAGE token_count eşitliği (recall 8/10→4/10 düşürmüştü). #4 min_score kalibrasyonu ERTELENDİ → **bu turun ana kararı**.

---
## ÖNCEKİ TEMEL SAYILAR (oran-bazlı karşılaştırma için)
- **06-02** (phonetic/ngram AÇIK, 68.6k): over-merge %76,6; PHONETIC üye %80, NGRAM %95; split %72 SHOULD_MERGE; kontrol FP %18.
- **06-03** (rematch AÇIK, 278.2k): PHONETIC master OM %95,9, NGRAM %98,1; kontrol FP %27,5; max magnet **1.181**; NEW_MASTER recall kaybı %81,7.
- **R2-prelim** (%2,9, kapalı): PHONETIC/NGRAM=0 yapısal teyit.
- **★ Round-3** (%31, 166.5k, ESKİ analyzer + gate KAPALI — `docs/audit/2026-06-05-DURUM-RAPORU-dogruluk-ve-hata-kaynaklari.md`):
  - **Kalibre RASTGELE precision = ~%90,3** (400 rastgele eşleşme; ~2.955/30.582 yanlış).
  - Stage precision: STRIPPED_EXACT **%97,5** · FUZZY_PHRASE **%75,7** · TOKEN_COVERAGE **%61,8** · SUFFIX_FUZZY **%71,4**.
  - Hata kaynağı payı: FUZZY_PHRASE %48 · TOKEN_COVERAGE %29 · STRIPPED_EXACT %19 (akronim) · SUFFIX_FUZZY %5.
  - Şüpheli-havuz over-merge %67,3; kontrol FP %48,3; split SHOULD_MERGE %85,8; recall kaybı (nme) %84,6.
  - max magnet **72**; **13 akronim magnet / 207 üye** (size≥5).
  - Hata sınıfları: **A**=akronim çökmesi (STRIPPED) · **B**=`#N/A`/harf-parçası (TOKEN_COVERAGE) · **C**=farklı-marka jenerik-kelime (CLARIANT≠LESCHACO, FUZZY/TOKEN) — en büyük kalan.
- **Round-4 (BU TUR)**: reindex+rematch, glue+gate AKTİF. **Beklenti: A+B sınıfı kapanır → precision ~%93-94; #4 min_score sonrası ~%97-98.**

---
## ADIM 0 — Yeni kod GERÇEKTEN canlı mı + rematch durumu (KAPI)
`p7_firms_v2` (market_calculus, localhost:5432, `config.DB_CONFIG`; dbhub DOWN ise psycopg2). Salt-OKU.
1. `es_manager.acronym_glue_active(es)` → **True** olmalı. Ayrıca ES `_analyze` (salt-oku): `C.M.S.A.D.C`→`['cmsadc']`, `B.A.T`→`['bat']`, `S.A.P.I.`→`[]` (yasal-ek hâlâ strip), `VF OUTDOOR MEXICO S.A.`→`['outdoor','vf']`.
2. `config`: DEDUP_MIN_FINGERPRINT_TOKEN_LEN=2, ENABLE_CORE_GATE=True, MATCH_CORE_MIN_TOKEN_LEN=2, MATCH_CORE_FUZZY_REQUIRE_ALPHA=True.
3. match_type dağılımı + işlenmiş oran. **PHONETIC/NGRAM≈0** olmalı. Rematch < ~530k ise HÂLÂ ÇALIŞIYOR → oran-bazlı ölç, "kısmi" notu düş (id-sıralı dilim yanlı). (Snapshot anı: ~119.5k/530.9k idi, artmış olabilir.)
4. **★ Gate kanıtı**: degenere isimler (`M S.A.`→`m`, `R S.A. M`, `#N/A 300`, tek-harf akronim) artık çok-üyeli master'a GİRMEMELİ → NEW_MASTER olmalı. Round-3'teki magnet master'ları (fp `m`/`g`/`t`, 72/31/28 üye) **KAYBOLMALI veya çok küçülmeli**.
5. **★ EXCLUDED ANOMALİSİ İNCELE**: Round-3'te 166k'da 1342 EXCLUDED vardı; bu rematch'te çok düşük göründü (snapshot'ta 3). Neden? input_filter davranışı mı değişti, gate degenere'leri EXCLUDED yerine NEW_MASTER'a mı yönlendiriyor, yoksa farklı id-dilimi mi? `Sin Razon Social`/`#N/A` placeholder'ların hâlâ EXCLUDED olduğunu doğrula (garbage magnet dönmesin).
6. master grup-boyutu dağılımı + max master + kuyruk (en büyük 10). main_processor özet log'unda total_deduped/total_excluded.

> Gate veya glue aktif DEĞİLSE (acronym_glue_active False / magnetler duruyor) → DUR, bildir; rematch eski şemada koşmuş olabilir.

---
## ADIM 1 — ★ HEADLINE: Kalibre RASTGELE precision (qa4 deseni) — vs %90,3
`C:/tmp/qa4_random_precision.py` (rastgele 400 gerçek eşleşme, master-grup yargısı) + `C:/tmp/qa4_workflow.js` (40 batch Haiku) + son oturumdaki agregasyon (record-level + stage-weighted). **YENİDEN KULLAN, sıfırdan yazma.** Çıktı: genel precision + stage-bazlı (STRIPPED_EXACT/FUZZY_PHRASE/TOKEN_COVERAGE/SUFFIX_FUZZY) + hata-kaynağı payı. **Round-3 %90,3'e göre arttı mı?** (beklenti ~%93-94).

---
## ADIM 2 — ★ A ve B sınıfları KAPANDI mı? (kanıt)
- **A (akronim magnet)**: size≥5 degenere-fp master'ları KENDİN say (ES `fingerprint_analyzer` ile üye fp'leri çıkar; ≥%50 üye tek-harf fp → magnet). Round-3: 13 magnet/207 üye, max 72. **Beklenti ~0.** Düşmediyse neden (glue boşluk-ayrılmış tek-harfi `M S.A.`→`m` çözmez; gate onu yakalamalı — gate çalışıyor mu?).
- **B (`#N/A`/harf-parçası sızma)**: TOKEN_COVERAGE/FUZZY eşleşmelerinde `#N/A 300`, `I.I.Q`, `WI SC` gibi çöp üyeler gerçek master'a hâlâ giriyor mu? Gate (require_alpha) bunları engellemeli. Örnek tara.
- **C (farklı-marka)**: CLARIANT≠LESCHACO, BANCO MEXICO≠SANTANDER tipi. A+B kapanınca **C artık baskın kalan hata sınıfı mı**? Payını ölç.

---
## ADIM 3 — Recall iki yönlü
- **Gate recall MALİYETİ**: gate degenere'leri NEW_MASTER yaptı → under-merge ARTTI mı? NEW_MASTER oranı + split SHOULD_MERGE'i Round-3 (%85,6 / %84,6) ile kıyasla.
- **★ Glue recall KAZANCI**: reindex akronim/suffix-truncation varyantlarını tutarlı fingerprint'e indirdi → bölünmüş firmalar TOPARLANDI mı? `HALLIBURTON, HULERA TORNEL, FLEXTRONICS(78 master), KUEHNE+NAGEL, VF OUTDOOR, SIEMENS(8), LEVI STRAUSS, CUMMINS(74), JOHN DEERE` ŞİMDİ kaç master? (Round-3 sayıları DURUM-RAPORU §4'te.) Azaldı mı? Dedup doğrulama (qa2_pools split + qa3 nm-recall).

---
## ADIM 4 — ★ KARAR: #4 min_score kalibrasyonu (gerçek skor dağılımıyla)
Ertelenen iş. Artık reindex+gate'li gerçek rematch skorları var.
1. FUZZY_PHRASE ve TOKEN_COVERAGE eşleşmelerinin **`match_score` dağılımını** çıkar; LLM-onaylı DOĞRU vs YANLIŞ (Adım 1/2 verdict'leri) eşleşmelerin skor histogramını ayır.
2. C-sınıfını kesen ama recall'ı korumayan **min_score eşiği öner** (FUZZY_PHRASE şu an 5.0, TOKEN_COVERAGE 3.0 — `config.STAGES`). Kayıp/kazanç sayıyla.
3. `ALCATEL ⊂ ALCATEL LUCENT` subset over-merge'i hâlâ var mı (TOKEN_COVERAGE)? Net öneri: min_score'u kaç yap, yoksa ayrı çekirdek-coverage tasarımı mı gerekir (clean-analyzer token_count GÜVENLİ DEĞİL — synonym genişlemesi; STRIPPED tabanlı düşün).

---
## ADIM 5 — 5-TUR ÖNCE/SONRA tablosu + yol haritası
| Metrik | 06-02 | 06-03 | R3 (%31, eski) | **R4 (reindex+gate)** |
Satırlar: kalibre precision · stage precision (4) · şüpheli over-merge · kontrol FP · split SHOULD_MERGE · recall kaybı · max magnet · akronim-magnet sayısı/üye · EXCLUDED · A/B/C sınıf durumu. Hangi sorun kapandı (A/B), hangisi baskın kaldı (C), gate recall'a ne yaptı.

---
## ARAÇLAR (token-optimize: YENİDEN KULLAN, sıfırdan yazma)
- `C:/tmp/qa2_pools.py` → pools (over_merge/control/split/nm_exact/nm_loose); `qa2_make_batches.py`→batches; `qa2_workflow.js`→172 Haiku judge (model:'haiku'); `qa2_aggregate.py`→metrikler.
- `C:/tmp/qa4_random_precision.py`→rastgele 400; `qa4_workflow.js`→40 judge; agregasyon son oturum desenli (record-level + stage-weighted, seed=20260605).
- `analysis/detectors.py` (load_matched_rows, detect_over_merge, detect_splits) · `core_name.normalize_core` · `dedup_auto_merge.iter_duplicate_groups`/`_is_distinctive_fingerprint` · ES `_analyze` (salt-oku fingerprint kök-neden).
- DB: `config.DB_CONFIG`; `PYTHONPATH=C:/All-project/ta-code-merge` + `PYTHONUTF8=1`.
- Pool'lar mevcut DB durumuna göre YENİDEN üretilmeli (qa2_pools.py + qa2_make_batches.py + qa4_random_precision.py tekrar koş — eski batch dosyaları Round-3 dilimine ait).

## KATI KURALLAR (değişmedi)
- Python'da fuzzy/Levenshtein YASAK; benzerlik/identity kararı ES-side; benzerlik yalnız aday ön-elemesi.
- Python'da eşleşme DOĞRULAMASI yapma; salt PG'den OKU (SELECT). ES `_analyze` (salt-oku) SERBEST.
- `country_code` HARD FILTER (veri %100 MX → COUNTRY_LEAK yapısal imkânsız; LLM isimdeki coğrafi kelimeyi sızıntı sanırsa NOT düş).
- `p7_firms_v2`'ye YAZMA (salt-okunur). Hardcoded ülke token'ı yok (synonyms_data JSON + config).

## TOKEN/MALİYET OPTİMİZASYONU (zorunlu)
- Mevcut `C:/tmp` scriptlerini KULLAN; pool/workflow'u sıfırdan kurma.
- Tüm yargı Haiku (`model:'haiku'`), 10'ar batch, schema'lı yapısal çıktı, offline aggregate.
- Karşılaştırma ORAN-bazlı (rematch < 530k ise kısmi; mutlak sayılar büyür).
- Pool cap'leri koru (over 600 / control 120 / split 500 / nm 300+200 / random 400).
- Büyük kaynak dosyaları gereksiz yere RE-READ etme; hedefli grep/SELECT kullan.
- Rematch hâlâ koşuyorsa: mevcut snapshot'ta ölç, "kısmi/oran-bazlı" işaretle; gerekiyorsa tamamlanmayı bekleyip tek seferde ölç.

## ÇIKTI
`docs/audit/2026-06-XX-round4-reindex-rematch-validation.md`:
1. ADIM 0 doğrulama (glue+gate canlı kanıtı; EXCLUDED anomali açıklaması).
2. Kalibre precision + 5-tur karşılaştırma tablosu.
3. ★ A/B sınıf kapanma kanıtı (magnet sayısı/üye + ES fingerprint; #N/A sızma kontrolü) + C'nin baskınlığı.
4. Gate recall maliyeti + glue recall kazancı (bölünmüş firmalar).
5. ★ #4 min_score kararı (skor-dağılımı + sayılı trade-off) + ALCATEL subset durumu.
6. Sonunda 3-5 maddelik "en yüksek etki" özeti + onay iste.

## NOTLAR
- Son commit'ler: `b1a7abb` (merge), `a866d52` (review-fix: gate pre-reindex/stale-cache guard + startup probe + cache-clear-on-reindex), `89f975d` (gate), `3b3385e` (acronym-glue), `bc4e8b9` (Unicode input + dedup config).
- `main_processor.py`'de önemsiz uncommitted boşluk farkı olabilir (SQL string indent) — yok say veya commit'le.
- Startup probe (`acronym_glue_active`) reindex'siz rematch'i durdurur → rematch koştuysa reindex KESİN yapılmış.
- Memory: `match-quality-fix-roadmap`, `no-python-verification-es-side`, `no-hardcoded-country-tokens`, `subagent-model-selection`.
- Raporlar: `docs/audit/2026-06-05-round3-unicode-config-dedup.md`, `docs/audit/2026-06-05-DURUM-RAPORU-dogruluk-ve-hata-kaynaklari.md`.
