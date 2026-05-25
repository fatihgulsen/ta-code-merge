# main_processor.py Audit Bulguları

**Tarih:** 2026-05-25
**Dosya:** main_processor.py (1174 satır)
**Audit eden:** Claude (subagent, sonnet)
**Baseline:** 71 passed, 5 failed (test_es_queries.py — kapsam dışı), 2 collection errors (kapsam dışı)

---

## Özet
- CRITICAL: 2
- HIGH: 3
- MEDIUM: 4
- LOW: 1

---

## Checklist Durumu

### CLAUDE.md kuralları

- **country_code filter & routing:** ❌ — Bkz. CRITICAL-1 (SQL injection + f-string interpolation ile `where_clause` oluşturma; `COUNTRY_CODE_FILTER` değeri doğrudan SQL metnine yerleştirilmekte). ES tarafında routing her yerde doğru (`country.upper()`), ancak SQL filtresi güvensiz.
- **Python fuzzy/Levenshtein imports:** ✅ — `rapidfuzz`, `Levenshtein`, `fuzzywuzzy`, `difflib` import'u yok. Fuzzy mantığı ES Query DSL'e bırakılmış.
- **Parametric SQL (no f-string interpolation):** ❌ — Bkz. CRITICAL-1 ve CRITICAL-2. `COUNTRY_CODE_FILTER` ve tablo/sütun adları f-string ile SQL metnine eklenmekte. `execute_values` içindeki parametre kısmı (`%s` placeholders) doğru, ama f-string template kısımları SQL injection riskidir.
- **Batch error handling (try/except + rollback + continue):** ❌ — Bkz. HIGH-1. `process_all_data` içindeki per-row döngüsünde (`for row in rows`) try/except yoktur. Tek bir satırda exception tüm batch'i durdurur; rollback sadece en üst `except Exception` bloğunda yapılmaktadır.
- **synonyms_data writes:** ✅ — `synonyms_data/` dizinine herhangi bir yazma işlemi yok.
- **Index/mapping creation only in es_manager.py:** ✅ — `create_index(es)` çağrısı `es_manager.py`'den import ediliyor. Doğrudan `es.indices.create(...)` çağrısı main_processor.py içinde yok.

### Genel kalite

- **Functions >50 lines:**
  - `process_all_data`: satır 882–1167, ~286 satır — kritik derecede uzun
  - `create_new_masters`: satır 501–712, ~212 satır — çok uzun
  - `_add_variation_to_master`: satır 817–874, ~58 satır — sınırda
  - `run_stage`: satır 164–236, ~72 satır
  - `match_single_record`: satır 723–778, ~56 satır
- **In-place mutation concerns:** ❌ — Bkz. MEDIUM-3. `_add_variation_to_master` fonksiyonu ES'ten gelen `source` dict'ini doğrudan mutate ederek `es.index(...)` ile geri yazar. `source["variations"]` ve `source[field]` listelerine `append` yapılmakta.
- **Silent exception swallowing:** ❌ — Bkz. HIGH-2 ve HIGH-3. `update_es_variations` içinde `except Exception: logger.debug(...)` ile ES bulk hatası yutulmakta. `_add_variation_to_master` içinde tüm exception'lar `logger.debug` ile yutulmakta.
- **Hardcoded thresholds:** ❌ — Bkz. MEDIUM-1. `NEW_MASTER_SUBBATCH_SIZE = 200` (satır 76), `ES_REFRESH_INTERVAL = 50` (satır 720), `stage_order` olarak `7` ve `2` sabit değerleri `create_new_masters` içinde (satır 537, 665), `int(es_score)` truncation `pg_updates` append'lerinde.
- **Deep nesting (>4):** ❌ — Bkz. MEDIUM-2. `process_all_data` içinde `while True → for row → if winner → if winner.get(...)` zinciri 5+ indent seviyesi.
- **Missing helper imports (debug_match.py pattern):** ✅ — CLAUDE.md §4'te belirtilen `_clean_labels`, `_tokenize`, `_symmetric_token_coverage` fonksiyonları main_processor.py'de tanımlanmamış veya import edilmemiş, bu doğru davranış. main_processor.py'de eksik import hatası yok.

---

## Bulgular

---

## [CRITICAL] main_processor.py:923-929 — COUNTRY_CODE_FILTER f-string ile SQL'e ekleniyor (SQL injection)

**Kanıt:**
```python
where_clause = f"{col_master} IS NULL"
if COUNTRY_CODE_FILTER:
    where_clause += f" AND {col_country} = '{COUNTRY_CODE_FILTER}'"
    logger.info(f"Ülke Filtresi Aktif: {COUNTRY_CODE_FILTER}")

count_cur.execute(f"SELECT COUNT(*) FROM {RAW_TABLE_NAME} WHERE {where_clause}")
```

**Neden problem:** `COUNTRY_CODE_FILTER` değeri f-string ile doğrudan SQL metnine yerleştirilmekte, `%s` parametresi kullanılmamaktadır. `config.py`'de şu an `None` olsa da, bu değer ortam değişkeninden, config dosyasından ya da ilerideki bir değişiklikle geldiğinde SQL injection açığı oluşturur. Aynı `where_clause` string'i `count_cur.execute` ve `read_cur.execute` içinde de tekrar tekrar f-string ile kullanılmaktadır (satır 929, 956–965). CLAUDE.md §1.1 doğrudan ihlali.

**Önerilen düzeltme:** `where_clause` için sabit SQL şablonu kullanın, `COUNTRY_CODE_FILTER` değerini parametre listesine ekleyin: `base_params = [last_id]` + koşullu `params.append(COUNTRY_CODE_FILTER)`. Tablo/sütun adları için whitelist doğrulaması uygulayın (bunlar zaten `COLUMN_MAPPING`'den geliyor, dış veri değil; ancak `COUNTRY_CODE_FILTER` dış kaynaklı olabilir).

**CLAUDE.md ihlali:** §1.1 — "raw string interpolation (`f"SELECT ... '{val}'"`) kullanılmamalıdır. Her zaman parametrik sorgular (`%s`) tercih edilmeli"

**Test edilebilir mi?** Evet — `COUNTRY_CODE_FILTER = "'; DROP TABLE firms; --"` değeri ile `process_all_data`'yı mock DB üzerinde çağırarak üretilen SQL'i kontrol eden bir test yazılabilir.

---

## [CRITICAL] main_processor.py:146-148 — ALTER TABLE f-string SQL injection (`validate_db_schema`)

**Kanıt:**
```python
cursor.execute(
    f"ALTER TABLE {RAW_TABLE_NAME} ADD COLUMN {db_col} {col_type};"
)
```

**Neden problem:** `db_col` değeri `COLUMN_MAPPING`'ten gelmekte, `col_type` ise kısmi bir dict lookup + sabit değerler içermektedir. Her ne kadar şu an bu değerler güvenli kaynaklardan gelse de, `COLUMN_MAPPING` ileride dış yapılandırmadan beslenirse (`db_col` içinde `; DROP TABLE` gibi bir değer) DDL injection mümkündür. `RAW_TABLE_NAME` de f-string ile eklenmekte. `ALTER TABLE` için `psycopg2`'nin `%s` parametresi DDL identifier'ları için çalışmaz; ancak `psycopg2.sql` modülü (`sql.Identifier`) bu durumu güvenli şekilde çözer.

**Önerilen düzeltme:** `psycopg2.sql` modülünü kullanın: `cursor.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(sql.Identifier(RAW_TABLE_NAME), sql.Identifier(db_col), sql.SQL(col_type)))`. `col_type` için whitelist doğrulaması ekleyin.

**CLAUDE.md ihlali:** §1.1 — "raw string interpolation kullanılmamalıdır"

**Test edilebilir mi?** Evet — `COLUMN_MAPPING` mock'una zararlı değer eklenerek üretilen SQL string'i assertion ile doğrulanabilir.

---

## [HIGH] main_processor.py:978-1082 — Per-row döngüde try/except yok, tek hata tüm batch'i durdurur

**Kanıt:**
```python
for row in rows:
    row_id = row[col_id]
    last_id = row_id
    # ... rec oluştur ...
    match_res = match_single_record(es, rec, active_stages)
    winner = match_res["winner"]
    # ... pg_updates.append(...)
    # Hiçbir try/except yok
```

**Neden problem:** `match_single_record`, `_index_new_master`, `_add_variation_to_master` çağrıları exception fırlatabileceği halde per-row try/except bloğu yoktur. Tek bir satırda hata alındığında tüm `while True` döngüsü kırılır, en üst `except Exception` bloğuna düşer ve `write_conn.rollback()` çağrılır — bu, o batch içinde daha önce başarıyla işlenmiş ama henüz commit edilmemiş `pg_updates`'in kaybolmasına yol açar. CLAUDE.md §1.3 doğrudan ihlali.

**Önerilen düzeltme:** `for row in rows:` bloğunu `try/except Exception as exc: logger.error(...); write_conn.rollback(); continue` ile sarın. `_index_new_master` exception'ını yakalayıp o kaydı atlamak ve devam etmek yeterlidir; commit'lenmiş batch'ler korunur.

**CLAUDE.md ihlali:** §1.3 — "Hata loglanmalı, veritabanı rollback edilerek diğer kayıtlar için işlem devam etmelidir."

**Test edilebilir mi?** Evet — `match_single_record`'u ikinci çağrıda exception fırlatacak şekilde mock'layarak, birinci kaydın pg_updates'e eklenip eklenip eklenmediğini ve döngünün devam edip etmediğini doğrulayan bir pytest yazılabilir.

---

## [HIGH] main_processor.py:349-354 — ES bulk varyasyon hatası sessizce yutulmakta

**Kanıt:**
```python
    if bulk_body:
        try:
            es.bulk(body=bulk_body, refresh=False)
        except Exception:
            logger.debug("ES variations update basarisiz, devam ediliyor")
```

**Neden problem:** `es.bulk(...)` başarısız olduğunda sadece `logger.debug` çağrılmakta, hata loglanmakta fakat `WARNING` veya `ERROR` seviyesinde değil. Production ortamında debug logları genellikle kapalıdır, bu nedenle kayıp hiç fark edilmez. ES'te varyasyon eksikliği ilerki duplicate eşleşme kalitesini düşürür; sessiz hata veri tutarsızlığına yol açar.

**Önerilen düzeltme:** `logger.debug` yerine `logger.warning` kullanın ve exception bilgisini `exc_info=True` ile loglayın. Kısmi başarıyı takip etmek için hata sayacı eklenebilir.

**CLAUDE.md ihlali:** § — (CLAUDE.md'de doğrudan madde yok, genel error handling kuralı)

**Test edilebilir mi?** Evet — `es.bulk` exception fırlatacak şekilde mock'lanarak `logger.warning` veya `logger.debug`'ın çağrılıp çağrılmadığı test edilebilir.

---

## [HIGH] main_processor.py:873-874 — `_add_variation_to_master` tüm exception'ları sessizce yutmakta

**Kanıt:**
```python
    except Exception:
        logger.debug(f"Varyasyon ekleme basarisiz: {v_lower[:50]}")
```

**Neden problem:** `es.get(...)`, `es.index(...)` dahil her türlü exception (network hatası, auth hatası, ES cluster down) `logger.debug` ile yutulmaktadır. Bu fonksiyon, eşleşen kayıtlar için variations ve meta bilgileri güncellemekten sorumludur; sessiz hata veri kaybına yol açar. Hatanın `logger.debug` seviyesinde loglanması production'da görünmez.

**Önerilen düzeltme:** `logger.warning(f"Varyasyon ekleme basarisiz: {v_lower[:50]}", exc_info=True)` ile değiştirin. Kritik ES hatalarını (örn. `ConnectionError`) ayrıca yakalayıp `logger.error` ile loglayın.

**CLAUDE.md ihlali:** — (genel error handling standartları; CLAUDE.md §1.3 batch hatalarına odaklanıyor ama genel kural her exception'ın loglanmasını gerektirir)

**Test edilebilir mi?** Evet — `es.get` exception fırlatacak şekilde mock'lanarak `logger.warning` veya `logger.debug`'ın çağrılıp çağrılmadığını assert eden bir test yazılabilir.

---

## [MEDIUM] main_processor.py:76, 720, 537, 665 — Hardcoded magic number'lar config'de olmalı

**Kanıt:**
```python
NEW_MASTER_SUBBATCH_SIZE = 200          # satır 76 — modül seviyesi sabit
ES_REFRESH_INTERVAL = 50               # satır 720 — modül seviyesi sabit
duplicate_logs.append((..., 7, ...))    # satır 537 — NEW_MASTER stage_order hardcoded
..., "CANONICAL_EXACT", 2, ...          # satır 665 — CANONICAL_EXACT stage_order hardcoded
```

**Neden problem:** `NEW_MASTER_SUBBATCH_SIZE` ve `ES_REFRESH_INTERVAL` modül seviyesinde sabitler olarak tanımlanmış, `config.py`'de değiller. CLAUDE.md'e göre eşik değerleri `config.py`'de (`TOKEN_COVERAGE_THRESHOLD` örneği) yaşamalıdır. Daha kritik olarak, `stage_order` değerleri `7` ve `2` olarak hardcoded yazılmıştır — bunlar `STAGES` konfigürasyonu değiştiğinde senkrondan çıkar.

**Önerilen düzeltme:** `NEW_MASTER_SUBBATCH_SIZE` ve `ES_REFRESH_INTERVAL`'ı `config.py`'e taşıyın. `stage_order` sabitlerini `next(s["order"] for s in STAGES if s["name"] == "NEW_MASTER")` ile dinamik olarak hesaplayın.

**CLAUDE.md ihlali:** — (CLAUDE.md §2: "eşik değerleri config.py içerisinde" kuralına yakın ihlal)

**Test edilebilir mi?** Evet — `config.STAGES`'i farklı order değerleriyle patch'leyerek `match_stages_log`'a yazılan `stage_order` değerinin tutarlı olup olmadığı test edilebilir.

---

## [MEDIUM] main_processor.py:882-1167 — `process_all_data` fonksiyonu 286 satır, çok fazla sorumluluk

**Kanıt:**
```python
def process_all_data() -> None:  # satır 882
    # ES setup, PG bağlantı açma, schema validasyon, where_clause oluşturma,
    # progress bar yönetimi, per-row eşleştirme, periyodik flush,
    # batch sonu flush, final özet — hepsi tek fonksiyon
    ...  # satır 1167
```

**Neden problem:** Fonksiyon 286 satır uzunluğundadır ve en az 6 farklı sorumluluğu vardır: bağlantı yönetimi, schema validasyon, sayfalama döngüsü, per-row işleme, periyodik flush ve final raporlama. Bakımı ve test edilmesi zordur. Coding style kuralları <50 satır öngörüyor.

**Önerilen düzeltme:** `_setup_connections()`, `_build_where_clause()`, `_process_batch(rows, ...)`, `_flush_pending_writes(...)`, `_log_final_summary(...)` gibi yardımcı fonksiyonlara ayırın.

**CLAUDE.md ihlali:** — (CLAUDE.md kodlama stili: "Functions are focused (<50 lines)")

**Test edilebilir mi?** Evet — alt fonksiyonlara ayırıldığında her biri bağımsız olarak test edilebilir hale gelir.

---

## [MEDIUM] main_processor.py:826-844 — `_add_variation_to_master` ES source dict'ini in-place mutate ediyor

**Kanıt:**
```python
source = doc["_source"]
existing_variations = source.get("variations", [])
# ...
existing_variations.append({"name": variation})
source["variations"] = existing_variations
source["variations_stripped"] = []
source["variations_suffix"] = []
# ...
existing.append(val)
source[field] = existing
```

**Neden problem:** `es.get(...)` ile alınan `source` dict'i doğrudan mutate edilerek `es.index(...)` ile geri yazılmaktadır. Bu pattern, değiştirilmesi gereken alanların (`variations_stripped`, `variations_suffix`) ES'teki mevcut değerlerinin üzerine boş liste yazması anlamına gelir — dolayısıyla her varyasyon ekleme işlemi bu alanları sıfırlar. Ayrıca exception durumunda partial state kalabilir.

**Önerilen düzeltme:** Yeni bir dict oluşturun: `new_source = {**source, "variations": [...], "variations_stripped": [], ...}`. In-place `append` yerine yeni liste kullanın.

**CLAUDE.md ihlali:** — (coding-style.md: "ALWAYS create new objects, NEVER mutate existing ones")

**Test edilebilir mi?** Evet — `es.get` mock'unu belirli bir `source` döndürecek şekilde ayarlayarak `es.index` çağrısına giden body'nin orijinal `source`'tan farklı bir nesne olup olmadığı kontrol edilebilir.

---

## [MEDIUM] main_processor.py:561-596 — `create_new_masters` içinde varyasyon formatı `run_stage` ile uyumsuz

**Kanıt:**
```python
# create_new_masters içinde (satır 572-573):
"variations": [{"name": rec["raw_name"]}],  # dict formatı

# build_new_master_doc fonksiyonunda (satır 487):
"variations": [name],  # string formatı
```

**Neden problem:** `create_new_masters` fonksiyonu `variations` alanını `[{"name": "..."}]` (dict listesi) formatında oluştururken, `build_new_master_doc` aynı alanı `[name]` (string listesi) formatında oluşturmaktadır. `_add_variation_to_master` ise her iki formatı da desteklemeye çalışmaktadır (`isinstance(v, dict)` kontrolü satır 836). Bu tutarsızlık, farklı path'lerden oluşturulan master doc'ların format tutarsızlığına yol açar ve ES mapping'de sorunlara neden olabilir.

**Önerilen düzeltme:** Tek bir `build_new_master_doc` fonksiyonu kullanarak her iki yerde de aynı formatı garanti altına alın. `create_new_masters` içindeki inline doc oluşturmayı `build_new_master_doc` fonksiyonuna delege edin.

**CLAUDE.md ihlali:** — (DRY ihlali, veri tutarlılığı sorunu)

**Test edilebilir mi?** Evet — `create_new_masters` ile `build_new_master_doc` çıktılarını karşılaştıran bir unit test yazılabilir.

---

## [LOW] main_processor.py:1117-1135 — Batch sonu flush SQL şablonu periyodik flush'tan farklı (match_details eksik)

**Kanıt:**
```python
# Periyodik flush (satır 1086-1094) — 5 sütun:
SET {col_master} = d.mc, {COLUMN_MAPPING["match_score"]} = d.ms,
    {COLUMN_MAPPING["match_type"]} = d.mt, {COLUMN_MAPPING["match_details"]} = d.md
FROM (VALUES %s) AS d(mc, ms, mt, md, id)

# Batch sonu flush (satır 1118-1127) — 4 sütun, match_details YOK:
SET {col_master} = d.mc, {COLUMN_MAPPING["match_score"]} = d.ms,
    {COLUMN_MAPPING["match_type"]} = d.mt
FROM (VALUES %s) AS d(mc, ms, mt, id)
```

**Neden problem:** Periyodik flush `match_details` sütununu yazarken, batch sonu flush yazmamaktadır. `pg_updates` listesi her iki yerde de 5-elemanlı tuple ile doldurulmaktadır (satır 1014-1015: `(master_id, int(es_score), stage_name, details, row_id)`), dolayısıyla batch sonu flush sırasında `details` değeri tuple'da var ama SQL'de kullanılmamaktadır. Bu, batch'in son refresh aralığından sonraki kayıtların `match_details` sütununun güncellenmemesi anlamına gelir.

**Önerilen düzeltme:** Batch sonu flush SQL şablonunu periyodik flush ile aynı hale getirin (`match_details` ekleyin) veya tek bir `_flush_pg_updates(write_cursor, write_conn, pg_updates, log_rows, audit_rows)` yardımcı fonksiyonu oluşturun.

**CLAUDE.md ihlali:** — (DRY ihlali, veri eksikliği)

**Test edilebilir mi?** Evet — `ES_REFRESH_INTERVAL`'dan fazla kayıt işlendiğinde batch sonu flush'ta `match_details` değerinin DB'ye yazılıp yazılmadığı mock cursor üzerinden doğrulanabilir.
