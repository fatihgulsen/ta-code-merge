# Detaylı Uygulama Planı — Eşleştirme Kalitesi & %100 Yakınsama

**Tarih:** 2026-06-15
**Kapsam:** [Master yol haritasının](2026-06-15-master-iyilestirme-yol-haritasi.md) adım-adım, TDD'li, kabul-kriterli uygulama planı.
**Çalışma kuralı:** Her değişiklik TDD (RED→GREEN), her kod sonrası `pytest` yeşil. Python fuzzy YASAK. synonyms_data/ sabit. country_code hard filter.
**Durum (2026-06-15):** SUFFIX_FUZZY disable + **A1 (geo-stop, HIGH-1 simetri fix dahil) + A2 (token-dedup) + A3 (AUTO_DEDUP demote)** kod+test TAMAM (suite 209 passed, commit edilmedi). A4 (max-cluster cap) kullanıcı kararıyla GERİ ALINDI (boyut bloklamaz). Code-review yapıldı, HIGH-1/HIGH-2/MEDIUM-1 giderildi. **A5 (batch-içi dedup) ERTELENDİ** — Round-8'de ölçüm sonrası karar: AUTO_DEDUP_PER_BATCH zaten fingerprint-eşit within-batch duplikaları birleştiriyor; gerçek boşluk chunk-içi FUZZY çiftler. Sıradaki: Aşama B (commit + tek reindex + rematch) → Round-8 ölçüm.

---

## 0. Ön-Uçuş Doğrulama (kod yazmadan ÖNCE — yarım gün)

Planın varsayımlarını canlı teyit et; biri tutmazsa ilgili maddeyi revize et.

- [ ] **V1 — `variations_stripped.name` mapping analyzer'ı.** `geo_stopwords_global`'ı yalnızca analyzer'a eklemek hem index-time hem query-time tokenizasyonu kapsıyor mu? `es_manager.py` mapping'inde `variations_stripped.name`'in `analyzer`/`search_analyzer` değerini doğrula. Eğer alan ingest-string'i farklı analyzer ile indeksliyorsa, geo-strip'i `es_ingest._build_stripped_script`'e DE eklemek gerekebilir (tutarlılık).
- [ ] **V2 — token_count tutarlılığı.** `variations_stripped.name.token_count` (`es_manager.py:333`) `stripped_search_analyzer` (global) kullanıyor; A1 sonrası geo-stop bu sayıyı da düşürecek (geo-only → 0). `_core_coverage_filter`'ın `count<=0` graceful davranışı (es_queries.py:155) bunu zaten kaldırıyor mu doğrula.
- [ ] **V3 — golden set envanteri.** R5-R7 adversarial-verify çıktılarından (qa-artifacts/round*/verdicts, verify_out) doğrulanmış SAME + DIFFERENT çiftlerini topla → `tests/golden/` veya `live_probe` golden seti. Bu, A1-A4'ün regresyon ölçümünün temeli.
- [ ] **V4 — yedek.** Reindex öncesi `p7_firms_v2_ar_pe`'nin `master_code, match_type, match_score, match_details` kolonlarının PG snapshot'ı (rollback için). `CREATE TABLE p7_firms_v2_ar_pe_bak_20260615 AS SELECT ta_code, master_code, match_type, match_score FROM p7_firms_v2_ar_pe;`

---

## AŞAMA A — Kod Değişiklikleri (reindex ÖNCESİ, paralel geliştirilebilir)

### A1 — Geo-token'ı stripped analyzer'a ekle  🔴 EN YÜKSEK ETKİ  ✅ KOD TAMAM (reindex bekliyor)

> **Durum 2026-06-15:** Uygulandı. `es_manager.py` (geo def taşındı + global/per-country stripped zincire `geo_stopwords_global`) + `es_ingest.py:_build_stripped_script` (geo strip, `get_country_name_tokens`). Testler: `test_stripped_analyzers_include_geo_stop`, `test_stripped_script_strips_geo_tokens`. Suite 205 passed. Canlı etki Aşama B reindex + G2 geçidinde doğrulanacak. Henüz commit edilmedi.


| | |
|--|--|
| **Amaç** | `SAL ARGENTINA`→`[]`→NEW_MASTER; geo-only mıknatısı yapısal öldür. `AUDI ARGENTINA`→`['audi']` korunur; `GM`=`GM DE ARGENTINA`→`['gm']` birleşir. |
| **Dosya** | `es_manager.py` |
| **HARDCODE YOK** | Yeni token listesi EKLENMİYOR. `geo_stopwords_global` filtresi `es_manager.py:196`'da zaten var ve içeriği `synonyms_data/countries.json`'dan (`get_country_name_tokens`) derleniyor; `de/del/of` gibi bağlaçlar `common.json`/`<cc>.json` `articles`'tan (`get_article_stopwords`). A1 yalnızca filtre **adını** analyzer zincirine ekler. Token eksikse → ilgili JSON'a eklenir, Python'a ASLA hardcode edilmez. |
| **Değişiklik** | (1) `geo_tokens_global`/`geo_stopwords_global` tanımını (~:193-199) per-country stripped analyzer döngüsünden **ÖNCE** taşı (~:157). (2) Per-country stripped analyzer (~:173): `filter` → `base_clean_filters + [filter_name, "legal_fragment_stop", "geo_stopwords_global"]`. (3) Global stripped analyzer (:186): `... + ["generic_stopwords_global", "legal_fragment_stop", "geo_stopwords_global"]`. (4) V1 sonucuna göre gerekiyorsa `es_ingest._build_stripped_script`'e de geo-strip ekle (yine JSON-türevli token listesiyle). |
| **TDD (RED)** | `tests/test_es_manager.py`: `test_stripped_analyzer_has_geo_stop()` — `build_index_settings()` çıktısında `stripped_search_analyzer_ar` ve global `stripped_search_analyzer` filter listesinde `"geo_stopwords_global"` olmalı. (Önce kırmızı.) |
| **TDD (entegrasyon, reindex sonrası)** | `live_probe`: `SAL ARGENTINA S.R.L.`/`R B ARGENTINA`/`UNLIMITED ARGENTINA` → `_analyze` boş veya non-geo; `AUDI ARGENTINA`→`['audi']`; `GM BRASIL` ve `GM DE ARGENTINA`→`['gm']` (aynı). |
| **Kabul kriteri** | Unit test yeşil + reindex sonrası `SAL ARGENTINA` ailesi NEW_MASTER, `AUDI ARGENTINA` recall korunur. |
| **Reindex** | EVET (Aşama B) |
| **Rollback** | geo_stopwords_global'ı zincirden çıkar + reindex. |
| **Efor** | ~1 saat kod + test |

### A2 — Token-tekrar dedup (ingest Painless)  ✅ KOD TAMAM (reindex bekliyor)

> **Durum 2026-06-15:** Uygulandı. `es_ingest.py:_build_clean_script` çift-boşluk temizliğinden sonra ardışık-tekrar dedup (adım 7, prevTok karşılaştırması). Yalnızca ardışık tekrar elenir. Test: `test_clean_script_collapses_consecutive_dup_tokens`. Suite 206 passed. Davranış Aşama B / G3 geçidinde. Henüz commit edilmedi.


| | |
|--|--|
| **Amaç** | `RICARD RICARD`→`RICARD`; ardışık yinelenen token skor şişirmesini önle. |
| **Dosya** | `es_ingest.py:_build_clean_script()` (:51) — `variations` ve `variations_stripped` ikisini de besler. |
| **Değişiklik** | Mevcut boşluk-temizliği adımından sonra, sonuç string'i üretmeden: `split(' ')` → ardışık-tekrar atla → `join(' ')`. (Painless: önceki token ile aynıysa ekleme.) |
| **TDD (RED)** | `tests/test_es_ingest.py`: `test_clean_script_collapses_consecutive_dup_tokens()` — script gövdesi ardışık-dedup mantığı içermeli; mümkünse `_simulate`/birim ile `"RICARD RICARD ARGENTINA"`→`"RICARD ARGENTINA"`. |
| **Kabul kriteri** | Unit yeşil; reindex sonrası `RICARD RICARD ARGENTINA` ile `PERNOD RICARD` artık eşleşmiyor (token_count 1≠2). |
| **Reindex** | EVET (Aşama B) |
| **Rollback** | Dedup bloğunu kaldır + reindex. |
| **Efor** | ~1 saat |

### A3 — AUTO_DEDUP `match_type` demote + izleme kör noktası  ✅ KOD TAMAM

> **Durum 2026-06-15:** Uygulandı. `config.py` `MatchType.AUTO_DEDUP`; `dedup_auto_merge.py:_repoint_pg` tek atomik UPDATE'te `match_type = CASE WHEN match_type='NEW_MASTER' THEN 'AUTO_DEDUP' ELSE match_type END` (variant'lar korunur). Testler: `test_auto_dedup_match_type_exists`, güncellenmiş `test_apply_merge_repoints...`. Suite 207→210. Watch-query UUID-join düzeltmesi manuel SQL (kod değil). Mevcut 830 demote = rematch sonrası moot. Reindex GEREKMEZ. Henüz commit edilmedi.


| | |
|--|--|
| **Amaç** | 830 duplike NEW_MASTER'ı görünür kıl; watch query kör noktasını kapat. |
| **Dosya** | `config.py:7` (MatchType), `main_processor.py` (dedup sonrası), `dedup_auto_merge.py` |
| **Değişiklik** | (1) `MatchType.AUTO_DEDUP = "AUTO_DEDUP"` ekle. (2) `auto_merge_duplicates` birleştirme sonrası ikincil kayıtların `match_type`'ını `AUTO_DEDUP` yap (PG UPDATE, parametrik). (3) Watch query'yi `v.master_code = m.master_code` UUID self-join + `HAVING count(*) FILTER (WHERE match_type='NEW_MASTER') > 1` ile düzelt. |
| **TDD (RED)** | `tests/test_config.py`: `test_auto_dedup_match_type_exists()`. `tests/test_dedup_auto_merge.py`: birleştirme sonrası ikincil kaydın `match_type==AUTO_DEDUP` olduğunu doğrula (mock PG). |
| **Kabul kriteri** | Yeni testler yeşil; geriye-dönük tek-seferlik temizlik scripti mevcut 830'u günceller. |
| **Reindex** | HAYIR |
| **Rollback** | UPDATE geri alınabilir (yedekten); sabit zararsız. |
| **Efor** | ~2 saat |

### A4 — Max-cluster-size guard  ❌ GERİ ALINDI (kullanıcı kararı 2026-06-15)

> **Karar:** Sabit boyut tavanı (matching-time hard-gate) **iptal edildi.** Gerekçe: boyut tek başına hata değil — 2M kayıt gerçekten aynı firmaysa hepsi birleşmeli; sabit tavan meşru dev kümeleri zorla böler → **under-merge**. Asıl sorun ZAYIF KENAR (geo/jenerik token), ki A1+A2+`_core_coverage_filter` kök seviyede çözer. Büyük küme = **izleme sinyali** (engellenmez): C6 monitör SQL + dedup_reviewer (C3) ile insan denetimine işaretlenir. Kod/test/config geri alındı; yerine `test_select_winner_no_size_cap_huge_cluster_still_wins` (5000-variation master yine kazanır). Boyut tespiti **yalnızca izleme** (C6), eşleştirme yolunda hard-gate YOK.


| | |
|--|--|
| **Amaç** | Bir master `MAX_VARIATIONS_PER_MASTER`'ı aşınca yeni eşleşme bağlanmasın → gri kuyruğa. Microclustering: büyük küme = hata. |
| **Dosya** | `config.py` (`MAX_VARIATIONS_PER_MASTER = 100`, başlangıç değeri veriye göre kalibre), `main_processor.py` kazanan-seçimi |
| **Değişiklik** | Kazanan master seçilirken `variation_count > MAX_VARIATIONS_PER_MASTER` ise o master'ı aday-dışı bırak; kayıt NEW_MASTER veya `needs_review` olarak işaretlensin (C2/C3 ile bağlanır). Eşik ülke bazında ayarlanabilir. |
| **TDD (RED)** | `tests/test_main_processor.py`: büyük-master adayı verildiğinde kazanan seçilmediğini / review'a düştüğünü doğrula (mock). |
| **Kabul kriteri** | Test yeşil; reindex sonrası hiçbir master eşik üstüne çıkıp büyümeye devam etmiyor; aşanlar kuyrukta. |
| **Reindex** | HAYIR (çalışma-zamanı), ama etkisi rematch'te görülür |
| **Rollback** | Eşiği çok yükselt veya guard'ı flag ile kapat (`ENABLE_MAX_CLUSTER_GUARD`). |
| **Efor** | ~2 saat |

> **Aşama A çıkışı:** `pytest` tamamen yeşil (şu an 203 passed); 4 değişiklik commit'lenebilir ama **reindex gerektirenler (A1, A2) Aşama B'ye kadar canlı DEĞİL.**

---

## AŞAMA B — Tek Reindex Penceresi (runbook)

> **Önkoşul:** Aşama A merge'li, `pytest` yeşil, V4 yedeği alınmış. PE'siz başka iş yok (uzun sürer).

```bash
# 1. Ingest pipeline'larını güncelle (A2)
python es_ingest.py

# 2. Index'i geo-stop (A1) + PE analyzer (B1) ile yeniden kur
python es_manager.py --force

# 3. DOĞRULAMA GEÇİTLERİ (reindex sonrası, rematch ÖNCESİ):
#    - PE analyzer: _analyze {stripped_search_analyzer_pe} → 200 (400 DEĞİL)
#    - A1: SAL ARGENTINA → boş/non-geo; AUDI ARGENTINA → ['audi']
#    - A2: RICARD RICARD ARGENTINA → tek ricard
#    Geçit başarısızsa DUR, rematch'e geçme.

# 4. Tam rematch (AR %35 + PE %40 → %100)
python main_processor.py
```

| Geçit | Beklenen | Başarısızsa |
|-------|----------|-------------|
| G1 PE analyzer | `_analyze pe` → 200 | es_manager loglarını incele; get_all_country_codes PE içeriyor mu |
| G2 geo-stop | `SAL ARGENTINA`→boş core | A1 analyzer zinciri / V1 ingest-strip kontrol |
| G3 token-dedup | `RICARD RICARD`→tek | A2 Painless kontrol |
| G4 rematch tamamlanma | AR+PE NULL ≈ 0 | main_processor loglarını izle (durmuş mu) |

**Süre:** ~saatler (reindex 743k doc + rematch ~400k kayıt). Arka planda izle.

---

## AŞAMA C — Ölçüm + Güvenlik Ağı + İnce Ayar (reindex SONRASI)

### C1 — Round-8 QA (P0, ilk iş)
- Haiku census (over-merge) + **zorunlu adversarial verify** (R5-R7 dersine göre tüzel-ek önyargısını düzelt).
- Before/after: AR precision (hedef ~%96-97), PE ilk ölçüm, `SAL ARGENTINA` ailesi NEW_MASTER mı doğrula.
- Golden-set regresyon: önceki turda doğru olan vaka bozulduysa kritik alarm.

### C2 — Dual-threshold güven bandı (P1)
- `main_processor.py`: `best_score > T_HIGH` → auto-commit; `T_LOW < score < T_HIGH` → PG'ye `match_confidence='REVIEW'`; altı → NEW_MASTER.
- `T_HIGH`/`T_LOW`'u golden-set'te stage başına F1/MCC maksimize ederek kalibre et.
- PG: `match_confidence` kolonu (HIGH/MEDIUM/REVIEW). TDD: `tests/test_main_processor.py` band yönlendirme testleri.

### C3 — `dedup_reviewer.py` güvenlik ağı (P1)
- Öncelik-sıralı kuyruk: `priority = güven_eksikliği×3 + küme_riski×2 + ülke_kritiklik×1 + bekleme×0.5`.
- Kategori etiketi (hangi tetikleyici: max-cluster / düşük-güven / slash-multi-entity).
- `split` komutu (mıknatıs bölme) + kararların PG geri-yazımı (`reviewed`, `reviewer_decision`).
- Kaynak: A4 karantinası + C2 gri bölge + ES Transform fingerprint çakışmaları buraya akar.

### C4 — Eşit-token-farklı-marka (P2, ölçüme bağlı)
- `ALL OVER`vs`ALL IN` → A1 sonrası **hacmi yeniden ölç** (Round-8). Düşükse ERTELE.
- Yüksekse: IDF-ağırlıklı `script_score` rescore (nadir token = yüksek ağırlık), ES-side Painless.

### C5 — `COMPL-xxxx` gümrük-kodu strip (P2, AR under-merge)
- `input_filter.py` veya Painless ile `COMPL-\d+` deseni temizle (synonyms_data sabit kuralına dokunmadan).

### C6 — Regresyon otomasyonu (P1)
- Her reindex'te golden-set'i çalıştır; herhangi stage precision %3+ düşerse alarm. `audit_batch.ps1` altyapısı.
- Mıknatıs erken-uyarı SQL: `GROUP BY master_code HAVING count(*) > 30`.

### Orta/Uzun Vade (literatürden, opsiyonel)
- **IDF-ağırlıklı token coverage** (Painless rescore) — C4'ün genel hali.
- **EMBEDDING_KNN stage** (ES dense_vector + HNSW; offline inference) — kısaltmalar (`IAE`≈`International Aero Engines`).
- **ES+LLM hybrid validation** — gri bölgeyi Haiku ile daralt (~$0.50/20k).

---

## Bağımlılık & Geçit Grafiği

```
ÖN-UÇUŞ (V1-V4) ──► AŞAMA A (A1,A2,A3,A4 paralel, her biri TDD+pytest yeşil)
                          │
                          ▼
                    AŞAMA B  [GEÇİT: pytest yeşil + V4 yedek]
                    es_ingest → es_manager --force → [G1,G2,G3 geçitleri] → rematch → [G4]
                          │
                          ▼
                    C1 Round-8 ölçüm  [GEÇİT: precision ~%96-97, regresyon yok]
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        C2 dual-thr   C3 reviewer   C6 regresyon
              └─────► C4/C5 (ölçüme bağlı) ─────► orta vade (IDF/embedding/LLM)
```

**Kritik kurallar:**
1. A1+A2+PE **aynı tek reindex'te** (ayrı reindex YOK).
2. Aşama B geçitleri (G1-G3) geçmeden rematch'e **geçme**.
3. C2/C3 (güvenlik ağı) **acil %100 için zorunlu** — otomatik kalanı %96-97'de kalır; %99+ auto-zone ancak gri bölge insana ayrılınca.

---

## Tamamlanma Tanımı (Definition of Done)

- [ ] A1-A4 kod + testler yeşil (`pytest`), commit'li.
- [ ] Reindex + rematch %100 tamamlandı; G1-G4 geçti.
- [ ] Round-8: AR auto-zone precision >%95, `SAL ARGENTINA` ailesi ayrı, PE çalışıyor, COUNTRY_LEAK 0, regresyon yok.
- [ ] C2 güven bandı + C3 reviewer kuyruğu operasyonel; gri bölge <%5 ve %100 insan kapsamasında.
- [ ] C6 regresyon otomasyonu kurulu (her reindex'te before/after).

---

## Risk & Rollback Özeti

| Risk | Azaltma / Rollback |
|------|--------------------|
| Reindex sonrası recall düşüşü | V3 golden-set before/after; A1 recall-nötr beklenir, kanıtlanmazsa geo-stop geri al |
| Rematch yarıda durur (geçmiş gibi) | G4 izleme; main_processor durursa neden araştır (resume mantığı) |
| A4 eşiği çok agresif → meşru büyük gruplar kuyruğa | `ENABLE_MAX_CLUSTER_GUARD` flag + eşiği veriye göre kalibre (Round-8 dağılımından) |
| Geo-stop bazı gerçek markaları siler | synonyms_data countries.json türevli; marka çakışması minimum; golden-set'te doğrula |
| PG güncellemeleri (A3/C2) | V4 yedek tablosu; parametrik UPDATE + rollback |

**Tahmini toplam efor:** Aşama A ~1 gün · Aşama B ~yarım gün (çoğu bekleme) · Aşama C ~2-3 gün (C2/C3 dahil).
