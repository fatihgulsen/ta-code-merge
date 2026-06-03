# Yeni Session Prompt — ROUND 2 QA: PHONETIC/NGRAM Kapalı + Dedup + Garbage Filtresi Sonrası

> Bu dosyanın **aşağıdaki "PROMPT" bölümünü** kopyalayıp yeni bir Claude Code session'ına
> yapıştır. **TAM rematch BİTTİKTEN sonra** çalıştır (reset → es_manager --force → main_processor).

---

## PROMPT (kopyala ↓)

# GÖREV: Round-2 Eşleştirme Kalite Denetimi — Düzeltmeler Sonrası Önce/Sonra + Recall + Dedup Doğrulama

Sen bir firma-eşleştirme QA denetçisisin. `feat/phonetic-overmerge-guard` branch'inde şu
düzeltmeler uygulandı, ES yeniden indekslendi ve **sıfırdan tam rematch** koşuldu:
- **PHONETIC_MATCH + NGRAM_MATCH stage'leri KAPATILDI** (over-merge'in birincil/ikincil kaynağı)
- **Güçlendirilmiş `fingerprint_analyzer`** (yasal-ek + jenerik + **geo** stop → sort/dedup)
- **Batch-içi otomatik dedup** (`dedup_auto_merge`, main_processor içinde her batch sonu;
  aynı kanonik fingerprint master'ları ES-side birleştirir + PG repoint)
- **Boundary garbage filtresi** (`input_filter`): YALNIZCA tamamen anlamsız girdiler
  (`empty/no_alnum/#N/A/null/placeholder 'sin razon social' vb.`) `match_type='EXCLUDED'`
  ile izole, ES'e indekslenmez. Kod/sayı/baş-harf/uzun isim KASITLI dışlanmaz (NEW_MASTER olur).

Görevin: bu round'un kalitesini **2026-06-02 (phonetic/ngram AÇIK)** ve **2026-06-03
(rematch, hâlâ açık)** raporlarıyla karşılaştırmak ve **düzeltmelerin işe yarayıp
yaramadığını** kanıtla ölçmek. LLM-yargı görevidir; KARAR senin.

## KATI KURALLAR (değişmedi)
- Python'da fuzzy/Levenshtein YASAK; benzerlik kararı SENİN. Token-set yalnızca aday ön-elemesi.
- Python'da eşleşme DOĞRULAMASI yapma; salt PG'den OKU (SELECT), yargı ver.
- `country_code` HARD FILTER (veri tümü MX → COUNTRY_LEAK yapısal olarak imkânsız, raporda belirt).
- Salt-okunur: `p7_firms_v2`'ye YAZMA.
- Hardcoded ülke token'ı yok; her şey synonyms_data/ JSON + config'ten.
- DB: `market_calculus` localhost:5432 (config.DB_CONFIG). dbhub MCP DOWN ise psycopg2'ye düş.
- `PYTHONPATH=C:/All-project/ta-code-merge` + `PYTHONUTF8=1`.

## ÖNCEKİ TEMEL SAYILAR (karşılaştırma için)
- **2026-06-02 (phonetic/ngram AÇIK, 68.6k işlenmiş):** over-merge şüphelilerinin %76,6'sı
  gerçek; PHONETIC üye %80, NGRAM %95; split %72 SHOULD_MERGE; kontrol FP %18.
- **2026-06-03 (rematch, hâlâ AÇIK, 278.2k işlenmiş):** PHONETIC master over-merge %95,9,
  NGRAM %98,1; kontrol FP %27,5; max magnet 1.181 (`Sin Razon Social`); NEW_MASTER recall
  kaybı (özdeş-geo-core) %81,7; 19.473 saf-NM grup (~45k kayıt). Rapor:
  `docs/audit/2026-06-03-llm-judge-rematch-comparison.md`.

## ADIM 0 — Rematch doğrulama (düzeltmeler GERÇEKTEN devrede mi?)
`p7_firms_v2` üzerinde kontrol et ve **beklentiyle** kıyasla:
1. `match_type` dağılımı:
   - **PHONETIC_MATCH ve NGRAM_MATCH ≈ 0 OLMALI** (stage'ler kapalı). Değilse → reindex/rematch
     eski kodla koşmuş, DUR ve bildir.
   - **EXCLUDED** match_type görünmeli (garbage filtresi çalıştı). Sayısını ve örneklerini al.
3. master grup-boyutu dağılımı + **max master boyutu**: garbage magnetler (`Sin Razon Social`
   1.181, `Razon Social no determinada`, `C R M`) **KAYBOLMALI / EXCLUDED olmalı**.
4. distinct master, NEW_MASTER oranı, toplam işlenmiş (tam rematch ise ~530k).
5. main_processor özet log'unda `total_deduped` (batch-içi dedup) ve `total_excluded` not et.

## ADIM 1 — Aday havuzları (mevcut araçları YENİDEN KULLAN)
Mevcut betikler (gerekirse küçük ayar): `C:/tmp/qa2_baseline.py`, `qa2_pools.py`,
`qa2_make_batches.py`, `qa2_workflow.js`, `qa2_aggregate.py` (over-merge/control/split/recall),
ve NEW_MASTER-arası recall için `qa3_nm_only.py`, `qa3_workflow.js`, `qa3_aggregate.py`,
`qa3_cause.py`. `analysis/detectors.py` + `core_name.normalize_core`.
- **A) OVER-MERGE:** üyesi >1 master grupları, düşük token-örtüşme. Beklenti: PHONETIC/NGRAM
  kapalı olduğundan over-merge **çarpıcı biçimde DÜŞMELİ**. Kalan over-merge hangi stage'den?
  (STRIPPED_EXACT/SUFFIX_FUZZY/TOKEN_COVERAGE/FUZZY_PHRASE)
- **B) SPLIT / under-merge:** `detect_splits`.
- **C) ★ NEW_MASTER-arası recall (`qa3`):** özdeş geo-core'lu, hepsi NEW_MASTER, ayrı master
  gruplar. Beklenti: batch-içi dedup sonrası bunlar **DÜŞMELİ** (HALLIBURTON 9→1, HULERA TORNEL
  11→1, JABIL/SIEMENS/LEVI STRAUSS birleşmiş olmalı). %73 (özdeş-stripped) çözülmüş mü?
- **D) ★ Dedup doğrulama:** 2026-06-03'te bölünmüş örnek firmaların (HALLIBURTON, COMPANIA
  HULERA TORNEL, FLEXTRONICS, KUEHNE+NAGEL, VF OUTDOOR, SIEMENS, LEVI STRAUSS) ŞİMDİ kaç
  master'da olduğunu doğrudan sorgula → tek master'a indi mi?
- **E) ★ Garbage doğrulama:** `Sin Razon Social`/`#N/A`/`C R M` kayıtları EXCLUDED mı, hâlâ
  magnet mi? `match_type='EXCLUDED'` sayısı + örnek.

## ADIM 2 — Yargılama (Haiku alt-ajanlar, Workflow, 10'ar batch)
`qa2_workflow.js` / `qa3_workflow.js` desenini kullan (schema ile yapısal çıktı, sonuç
dosyaları + aggregate). MX kuralları Haiku prompt'una: yasal ekler (S.A. DE C.V. …) ve geo
(MEXICO/MEXICANA) AYIRT EDİCİ DEĞİL; jenerik kelime (COMERCIALIZADORA/GRUPO/TRADING) +
farklı ayırt edici = FARKLI firma; placeholder/kod/kişi-adı = GARBAGE.

## ADIM 3 — ÖNCE/SONRA tablosu (üç tur)
| Metrik | 06-02 (açık) | 06-03 (açık, rematch) | **Round-2 (kapalı+dedup+garbage)** |
- over-merge oranı (genel + stage) · kontrol FP · split SHOULD_MERGE ·
  **NEW_MASTER-arası recall kaybı** (qa3, %81,7 → ?) · max magnet boyutu · EXCLUDED sayısı ·
  total_deduped. Hangi sorun kapandı, hangisi kaldı?

## ADIM 4 — P1-B değerlendirmesi (kanıta dayalı karar)
Kontrol havuzunda **parent↔subsidiary** (`VF CORP`↔`VF OUTDOOR MEXICO`, `SANMINA CORP`↔…) ve
**şehir** (`MEXICO`↔`MEXICALI`) over-merge'leri PHONETIC/NGRAM kapalıyken **hâlâ anlamlı mı?**
- Eğer büyük ölçüde KAYBOLDUYSA → P1-B gereksiz, kapat.
- Hâlâ varsa → kalan GERÇEK vakaları listele; hedefli ES-side öneri (subset/symmetric core
  coverage guard; city_state ikincil sinyal). KOD DEĞİŞTİRME, raporla.

## ADIM 5 — Kalan over-merge / yeni öneriler
PHONETIC/NGRAM kapalıyken kalan over-merge üreten stage(ler) için ES-side (Python doğrulaması
YOK) öneri. Dedup'ın yanlış birleştirdiği (false-merge) grup var mı? (fingerprint çok agresif
mi — örn. geo-strip parent/subsidiary'yi yanlış birleştirdi mi?) Örnek vaka + kanıt.

## ÇIKTI
`docs/audit/` altına tarihli rapor:
1. Round-2 temel metrikleri + üç-tur karşılaştırma tablosu.
2. Over-merge düşüşü (genel + stage), kalan kaynaklar.
3. NEW_MASTER recall + dedup doğrulama (bölünmüş firmalar birleşti mi; %73 kapandı mı).
4. Garbage/EXCLUDED doğrulama (magnetler bitti mi).
5. P1-B kararı (gerekli mi, kanıtla) + kalan öneriler.
Sonunda 3-5 maddelik "en yüksek etki" özeti + onay iste.

## NOTLAR
- Branch: `feat/phonetic-overmerge-guard`. Commit'ler: `84f069e` (phonetic/ngram off + fingerprint
  + dedup), `f70cfb0` (garbage filter), `ddcd716` (input filter daraltma + per-batch dedup).
- Memory: `match-quality-fix-roadmap`, `no-hardcoded-country-tokens`, `no-python-verification-es-side`.
- Karşılaştırmayı ORAN bazlı yap (tam rematch ~530k → mutlak sayılar büyür).

## PROMPT (kopyala ↑)
