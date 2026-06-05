# Yeni Session Prompt — ROUND 3 QA: Unicode input_filter + Config-Driven Dedup Guard Sonrası

> Bu dosyanın **aşağıdaki "PROMPT" bölümünü** kopyalayıp yeni bir Claude Code session'ına
> yapıştır. İdeal: **TAM rematch bittikten sonra** çalıştır; kısmi veride (id-sıralı yanlı
> dilim) koşulursa ORAN bazlı yargıla ve eksikliği raporda belirt.

---

## PROMPT (kopyala ↓)

# GÖREV: Round-3 Eşleştirme Kalite Denetimi — Unicode-Filter + Config'lenebilir Dedup Guard Sonrası

Sen bir firma-eşleştirme QA denetçisisin. `feat/phonetic-overmerge-guard` branch'inde Round-2'ye
EK olarak şu düzeltmeler uygulandı (ES reindex GEREKMEDİ; yalnız Python/config):
- **P-R2-2 — input_filter Unicode-aware**: `_norm()` regex `[^a-z0-9]` → `[\W_]`. Latin-DIŞI
  (Kiril/CJK/Yunan) gerçek firmalar (`ФОЛЬКСВАГЕН АГ`=Volkswagen AG, SIBUR, Uralkali) artık
  `no_alnum` sayılıp EXCLUDED edilMİYOR → NEW_MASTER oluyor. (Tüm tablo yanlış-no_alnum 139→4.)
- **P-R2-1 — dejenere fingerprint dedup guard, CONFIG'LENEBİLİR**: `dedup_auto_merge`'e
  `_is_distinctive_fingerprint(fp, min_token_len)` eklendi; eşik `config.DEDUP_MIN_FINGERPRINT_TOKEN_LEN`.
  **ŞU AN `1`'de park (guard pratikte KAPALI — yalnız boş fp engelli).** `2` yapılırsa akronim-çökmesi
  magnet'leri (`C.M.S.A.D.C`/`U M S.A. DE C.V.` → fingerprint `'m'`) engellenir, gerçek 2-harfli
  markalar (VF/3M/HM/GM) korunur. Ampirik sınır: ≥2 bile yetersiz — kısa-residue false-merge'ler
  (`'av'`=HUF+P.AV.I, `'adm'`) geçer; kök neden analyzer aşırı-strip'i (tek-harf token atma,
  `HUF` yutma) → asıl çözüm analyzer-side reindex (ertelendi). Bkz.
  `docs/audit/2026-06-03-round2-preliminary-2.9pct.md`.

Görevin: bu round'u **06-02 (phonetic/ngram AÇIK)**, **06-03 (rematch, açık)** ve **Round-2-prelim
(%2,9 kapalı dilim)** ile karşılaştır; **bu oturumdaki iki fix'in işe yarayıp yaramadığını** kanıtla
ölç ve **`DEDUP_MIN_FINGERPRINT_TOKEN_LEN` 1 mi 2 mi olmalı** sorusunu kanıta dayalı yanıtla.
LLM-yargı görevidir; KARAR senin.

## KATI KURALLAR (değişmedi)
- Python'da fuzzy/Levenshtein YASAK; benzerlik kararı SENİN. Token-set yalnızca aday ön-elemesi.
- Python'da eşleşme DOĞRULAMASI yapma; salt PG'den OKU (SELECT), yargı ver. ES `_analyze` API
  (salt-okuma) ile fingerprint kök-neden incelemesi SERBEST.
- `country_code` HARD FILTER (veri tümü MX → COUNTRY_LEAK yapısal olarak imkânsız, raporda belirt).
- Salt-okunur: `p7_firms_v2`'ye YAZMA.
- Hardcoded ülke token'ı yok; her şey synonyms_data/ JSON + config'ten.
- DB: `market_calculus` localhost:5432 (config.DB_CONFIG). dbhub MCP DOWN ise psycopg2'ye düş.
- `PYTHONPATH=C:/All-project/ta-code-merge` + `PYTHONUTF8=1`.

## ÖNCEKİ TEMEL SAYILAR (karşılaştırma için)
- **06-02 (phonetic/ngram AÇIK, 68.6k):** over-merge şüphesi %76,6 gerçek; PHONETIC üye %80,
  NGRAM %95; split %72 SHOULD_MERGE; kontrol FP %18.
- **06-03 (rematch, AÇIK, 278.2k):** PHONETIC master over-merge %95,9, NGRAM %98,1; kontrol FP
  %27,5; max magnet 1.181 (`Sin Razon Social`); NEW_MASTER recall kaybı %81,7.
  `docs/audit/2026-06-03-llm-judge-rematch-comparison.md`.
- **Round-2-prelim (%2,9, phonetic/ngram KAPALI):** yapısal teyit — PHONETIC=0, NGRAM=0, EXCLUDED
  aktif; recall mekaniği çalışıyor (H&M/VF OUTDOOR doğru merge). İki bug bulundu (P-R2-1/P-R2-2,
  bu oturumda düzeltildi). `docs/audit/2026-06-03-round2-preliminary-2.9pct.md`.

## ADIM 0 — Doğrulama (her iki fix GERÇEKTEN canlı rematch'te devrede mi?)
`p7_firms_v2` üzerinde kontrol et:
1. `match_type` dağılımı + işlenmiş oran (tam rematch ~530k). PHONETIC/NGRAM **≈ 0 OLMALI**.
2. **★ P-R2-2 teyidi**: `match_type='EXCLUDED'` kayıtlarında **Latin-dışı (Kiril/CJK) firma OLMAMALI**
   (hepsi `Sin Razon Social`/`#N/A`/placeholder olmalı). Latin-dışı EXCLUDED sayısı (`ord(c)>0x400`)
   → 0 beklenir. >0 ise rematch ESKİ input_filter ile koşmuş, DUR ve bildir. Ayrıca Kiril firma
   örneklerinin (Volkswagen AG vb.) NEW_MASTER olduğunu doğrula.
3. **★ P-R2-1 / config teyidi**: `config.DEDUP_MIN_FINGERPRINT_TOKEN_LEN` değerini oku (1 mi 2 mi).
   `1` ise guard kapalı → akronim magnetleri BEKLENİR (aşağıda ölç).
4. master grup-boyutu dağılımı + **max master boyutu** + dağılımın kuyruğu (en büyük 10 grup).
5. main_processor özet log'unda `total_deduped` / `total_excluded` not et.

## ADIM 1 — Aday havuzları (mevcut araçları YENİDEN KULLAN)
`C:/tmp/qa2_baseline.py`, `qa2_pools.py`, `qa2_make_batches.py`, `qa2_workflow.js`,
`qa2_aggregate.py`; NEW_MASTER recall için `qa3_*`. `analysis/detectors.py` + `core_name.normalize_core`.
- **A) OVER-MERGE:** üyesi >1, düşük token-örtüşme. Kalan over-merge hangi stage'den?
- **B) SPLIT / under-merge:** `detect_splits`.
- **C) ★ NEW_MASTER-arası recall (qa3):** özdeş geo-core, hepsi NEW_MASTER, ayrı master.
- **D) ★ Dedup doğrulama:** bölünmüş örnek firmalar (HALLIBURTON, HULERA TORNEL, FLEXTRONICS,
  KUEHNE+NAGEL, VF OUTDOOR, SIEMENS, LEVI STRAUSS) ŞİMDİ kaç master? Tek master'a indi mi?
- **E) ★★ AKRONİM/DEJENERE-FINGERPRINT MAGNET (bu round'un ANA sorusu):** `config min=1`
  olduğundan dejenere-fp guard kapalı. Noktalı-akronim/baş-harf isimlerden oluşan büyük master
  gruplarını KENDİN bul (grup-boyutu dağılımının kuyruğunu tara; üyeleri salt baş-harf/nokta
  olan gruplar). Her aday magnet için ES `_analyze fingerprint_analyzer` ile kanonik fingerprint'i
  çıkar (tek-harf/kısa residue → magnet işareti). Bu gruplar gerçek mi, magnet mi → Haiku yargıla;
  sayı + üye dağılımını ölç.
- **F) ★ Latin-dışı recall:** Kiril/CJK firmalar artık NEW_MASTER; aralarında özdeş olanlar
  (örn. iki `ФОЛЬКСВАГЕН АГ`) doğru eşleşiyor mu yoksa under-merge mı? (analyzer Latin-dışını
  nasıl işliyor — bonus.)
- **G) ★ Garbage doğrulama:** `Sin Razon Social`/`#N/A` EXCLUDED mi (magnet bitti mi).

## ADIM 2 — Yargılama (Haiku alt-ajanlar, Workflow, 10'ar batch)
`qa2_workflow.js` / `qa3_workflow.js` desenini kullan (schema ile yapısal çıktı + aggregate).
MX kuralları Haiku prompt'una: yasal ekler (S.A. DE C.V. …) ve geo (MEXICO/MEXICANA) AYIRT EDİCİ
DEĞİL; jenerik kelime (COMERCIALIZADORA/GRUPO/TRADING) + farklı ayırt edici = FARKLI firma;
**salt baş-harf/akronim çorbası (`I.L.M.S.D.C`, `M.P`) ayırt edici çekirdek taşımaz → aynı
fingerprint'te toplanmaları MAGNET (yanlış-merge)**; placeholder/kod/kişi-adı sınıflandırması.

## ADIM 3 — ÖNCE/SONRA tablosu (dört tur)
| Metrik | 06-02 (açık) | 06-03 (açık rematch) | R2-prelim (%2,9) | **Round-3 (Unicode+config min=1)** |
- over-merge oranı (genel + stage) · kontrol FP · split SHOULD_MERGE · NEW_MASTER recall kaybı
  (qa3) · **max magnet boyutu + akronim-magnet sayısı/üye** · EXCLUDED sayısı (Latin-dışı=0 mı) ·
  total_deduped. Hangi sorun kapandı, hangisi açıldı (akronim magnet min=1 yüzünden)?

## ADIM 4 — ★ KARAR: `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` = 1 mi 2 mi? (kanıta dayalı)
Adım 1-E bulgularıyla:
- min=1'de akronim magnetlerin SAYISI ve büyüklüğü ne? Kaç gerçek firma yanlış birleşiyor?
- min=2'ye çekince: kaç magnet kapanır (kazanç) vs kaç gerçek 2-harfli marka/özdeş kısa-fp
  birleşmesi engellenir (kayıp)? `_is_distinctive_fingerprint(fp, 2)` ile aday gruplar üzerinde
  simüle et (salt-okuma; PG'ye yazma).
- **Net öneri ver**: 1'de kalsın mı, 2 mi yapılsın, yoksa analyzer-side kök çözüm (reindex)
  beklensin mi? Trade-off'u sayıyla göster.

## ADIM 5 — Kalan over-merge / analyzer kök-neden / yeni öneriler
- Kalan over-merge üreten stage(ler) için ES-side (Python doğrulaması YOK) öneri.
- **Analyzer aşırı-strip kök-nedeni (P-R2-1 §3):** `_analyze` ile doğrula — akronim isimler neden
  tek harfe çöküyor, `HUF`/2-3 harfli gerçek token neden yutuluyor? Hedefli analyzer-side öneri
  (strip degenerate residue bırakıyorsa orijinali koru; reindex planı). KOD DEĞİŞTİRME, raporla.

## ÇIKTI
`docs/audit/` altına tarihli rapor:
1. Round-3 temel metrikleri + dört-tur karşılaştırma tablosu.
2. P-R2-2 doğrulama (Latin-dışı firmalar artık NEW_MASTER, EXCLUDED değil — kanıtla).
3. ★ Akronim/dejenere-fp magnet ölçümü (sayı/üye/örnek + ES fingerprint kanıtı).
4. ★ `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` kararı (1 vs 2, trade-off sayılı) + analyzer kök-neden önerisi.
5. NEW_MASTER recall + dedup doğrulama (bölünmüş firmalar) + garbage/EXCLUDED.
Sonunda 3-5 maddelik "en yüksek etki" özeti + onay iste.

## NOTLAR
- Branch: `feat/phonetic-overmerge-guard`. Bu oturum değişiklikleri (commit bekliyor olabilir):
  `input_filter.py` (Unicode `_norm`), `dedup_auto_merge.py` (`_is_distinctive_fingerprint` +
  config), `config.py` (`DEDUP_MIN_FINGERPRINT_TOKEN_LEN=1`), testler (188 passed).
- Önceki commit'ler: `84f069e` (phonetic/ngram off + fingerprint + dedup), `f70cfb0` (garbage),
  `ddcd716` (input filter daraltma + per-batch dedup), `203e9d5`/`2155a67` (QA-prompt + ES mapping).
- Memory: `match-quality-fix-roadmap`, `no-hardcoded-country-tokens`, `no-python-verification-es-side`.
- Karşılaştırmayı ORAN bazlı yap (id-sıralı dilim yanlı; tam rematch ~530k → mutlak sayılar büyür).

## PROMPT (kopyala ↑)
