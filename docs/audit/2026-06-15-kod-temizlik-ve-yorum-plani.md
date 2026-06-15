# Kod Temizliği & Yorum Standardizasyonu Planı

**Tarih:** 2026-06-15
**Amaç:** (A) Ölü/kullanılmayan kodu güvenle temizlemek, (B) aktif dosyaların yorum satırlarını başka bir mühendisin rahat okuyabileceği tutarlı bir standarda getirmek.
**İlke:** Davranış değişmez. Her adım TDD güvenlik ağıyla (mevcut 209 test) + statik analizle doğrulanır. Silmeden önce kanıt; entry-point script ≠ ölü kod.

---

## A. Ölü/Kullanılmayan Kod Temizliği

### A.0 — Kanıt: kök modül kullanım envanteri (prod import sayısı; test/qa hariç)

| Modül | prod-import | Tür | Karar |
|-------|:-----------:|-----|-------|
| `config.py` | 13 | çekirdek | KAL |
| `es_manager.py` | 8 | çekirdek | KAL |
| `synonym_loader.py` | 6 | çekirdek | KAL |
| `es_queries.py` | 5 | çekirdek | KAL |
| `es_ingest.py` | 2 | çekirdek | KAL |
| `core_name.py` | 2 | yardımcı | **KOŞULLU** (aşağıda) |
| `main_processor.py` | 1 | orkestrasyon (entry) | KAL |
| `input_filter.py` | 1 | çekirdek | KAL |
| `es_transform.py` | 1 | çekirdek | KAL |
| `dedup_auto_merge.py` | 1 | çekirdek + CLI | KAL |
| `analyze_mismatches.py` | 0 | CLI script | **İNCELE** |
| `debug_match.py` | 0 | CLI script | **BOZUK — onar/kaldır** |
| `dedup_reviewer.py` | 0 | CLI script (aktif araç) | KAL (entry-point) |
| `reset_matching.py` | 0 | CLI script | **İNCELE** |

> **Önemli:** 0-import demek ölü demek DEĞİL — dördü de `__main__` entry-point (elle çalıştırılan CLI araç). Yalnızca import edilmiyorlar.

### A.1 — `debug_match.py` (BOZUK legacy — P1)
- **Kanıt:** CLAUDE.md §4: `main_processor`'dan kaldırılmış `_clean_labels`/`_tokenize`/`_symmetric_token_coverage` fonksiyonlarını import etmeye çalışıyor → çalıştırıldığında ImportError.
- **Adım:** `python debug_match.py "A" "B" -c AR` ile bozuk olduğunu doğrula → ya (a) `synonym_loader`/ES `_analyze` ile ÇALIŞIR hale onar, ya da (b) tamamen kaldır. Öneri: **kaldır** (offline debug ihtiyacı `analysis/live_probe.py` ile karşılanıyor).
- **Risk:** Yok (zaten çalışmıyor, hiçbir şey import etmiyor).

### A.2 — `core_name.py` + kapalı PHONETIC/NGRAM alt-sistemi (KOŞULLU — P2, KARAR GEREKİR)
- **Kanıt:** `core_name.normalize_core` yalnızca (1) `es_queries.NGRAM_MATCH` + `PHONETIC_MATCH` — **ikisi de `config.STAGES`'te `enabled=False`** — ve (2) `analysis/detectors.py` (QA) tarafından çağrılıyor.
- **Bağlı ölü-kod kümesi** (phonetic/ngram kalıcı kapalıysa): `es_queries.PHONETIC_MATCH`/`NGRAM_MATCH` fonksiyonları + `config` PHONETIC/NGRAM stage girdileri + sabitleri + `es_manager` `phonetic_analyzer`/`ngram_analyzer`/filtreleri + `NGRAM/PHONETIC_MIN_CORE_TOKENS`.
- **KARAR GEREKİR:** PHONETIC/NGRAM bir daha açılacak mı? 
  - **Hayır →** alt-sistemi topluca kaldır; `core_name` yalnızca `analysis/`'e kalır (oraya taşınabilir).
  - **Belki →** olduğu gibi bırak (kodda ölü ama re-enable için hazır), yalnızca yorumlarını netleştir.
- **Risk:** Orta — birden çok dosyaya dokunur; reindex etkilemez (kapalı zaten). TDD + live_probe ile doğrulanır.

### A.3 — `analyze_mismatches.py`, `reset_matching.py` (İNCELE — P3)
- **Adım:** Her birinin ne yaptığını oku + son kullanım/güncellik kontrolü. `reset_matching.py` muhtemelen `master_code=NULL` resetleyen operasyonel yardımcı (KAL ama belgele). `analyze_mismatches.py` QA döngüsünün parçasıysa KAL, değilse `archive/`'e taşı.
- **Risk:** Düşük (entry-point, import edilmiyor).

### A.4 — Dosya-içi ölü fonksiyon/import taraması (P2)
- **Araç:** `ruff check --select F401` (kullanılmayan import) + `vulture .` (kullanılmayan fonksiyon/değişken; %80 confidence). Tespit edilenleri kanıtla doğrula (grep) → kaldır.
- **Bilinen aday:** `main_processor.build_new_master_doc`/`create_new_masters` etrafındaki "dead code" notları (geçmiş audit'lerde `create_new_masters` ölü deniyordu) — doğrula.

### A.5 — Yöntem & güvenlik ağı
1. `ruff check --select F401,F811` + `vulture . --min-confidence 80` → aday listesi.
2. Her aday için: `grep -rn` ile kullanım kanıtı (prod + test + CLI).
3. Kaldır → `pytest` (209) yeşil + `analysis/live_probe.py` recall korunur.
4. `refactor-cleaner` agent'ı bu adımları yürütebilir (kullanıcının global agent kuralı).
5. Her temizlik ayrı küçük commit (`refactor(cleanup): ...`); kolay geri alma.

---

## B. Yorum Standardizasyonu

### B.1 — Mevcut sorunlar (config.py vb.)
- `# ====` ASCII-art banner başlıkları (modül docstring yerine).
- Çok uzun satır-içi gerekçe/audit anlatıları (örn. `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` üstünde 15+ satır changelog/audit referansı kod içinde).
- Dil karışıklığı (TR ağırlıklı, yer yer EN).
- Tarih/karar/audit-dosyası referansları kod yorumuna gömülü → "changelog in code" anti-pattern.
- WHAT açıklayan gereksiz yorumlar (kodun zaten söylediğini tekrar).

### B.2 — Hedef standart (öneri)
1. **Dil:** Tek dil — **Türkçe** (ekip TR; mevcut ağırlık TR). Tutarlı uygula.
2. **Modül başlığı:** `# ===` banner yerine **modül docstring** (`"""..."""`): tek paragraf — modülün sorumluluğu.
3. **Fonksiyon:** PEP 257 docstring — kısa amaç + (gerekirse) Args/Returns. Uzun gerekçe değil.
4. **Satır-içi yorum:** Yalnızca **NEDEN** (niyet/tuzak), WHAT değil. Kısa, tek satır tercih.
5. **Changelog/audit kod DIŞINA:** "P-R2-1", "docs/audit/...", tarih-karar anlatıları koddan çıkar → ilgili `docs/audit/*.md`'ye taşı; kodda en fazla tek satır `# Neden: ... (bkz docs/audit/X)` referansı.
6. **Ölü/geçici yorum yok:** yorumlanmış kod blokları, "TODO eski" notları temizlenir.

### B.3 — Uygulama sırası (en çok kullanılan → az)
`config.py` → `synonym_loader.py` → `es_queries.py` → `es_manager.py` → `es_ingest.py` → `main_processor.py` → `dedup_auto_merge.py` → `input_filter.py` → `es_transform.py` → `core_name.py` → CLI scriptleri.

### B.4 — Güvenlik & doğrulama
- **Yalnızca yorum/docstring değişir — kod davranışı DEĞİŞMEZ.** Her dosya sonrası `pytest` yeşil (yorum değişikliği testi bozmamalı → regresyon kanıtı).
- Dosya başına ayrı commit (`docs(comments): <dosya> yorum standardizasyonu`) → diff incelenebilir, kolay geri alma.
- `ruff` (varsa docstring kuralları) ile tutarlılık kontrolü.

### B.5 — Örnek dönüşüm (config.py)
**Önce** (banner + gömülü changelog):
```python
# ============================================================================
# config.py — ...
# ============================================================================
# A3 (2026-06-15): fingerprint auto-merge ... watch query ... (uzun anlatı)
AUTO_DEDUP = "AUTO_DEDUP"
```
**Sonra** (kısa NEDEN + docs referansı):
```python
# Fingerprint auto-merge ile birleştirilen ikincil NEW_MASTER anchor'ı bu tipe
# demote edilir (watch-query kör noktası). Bkz. docs/audit/2026-06-15-*.
AUTO_DEDUP = "AUTO_DEDUP"
```

---

## C. Önerilen Sıra & Onay

1. **A.1** `debug_match.py` doğrula → kaldır (hızlı, risksiz).
2. **A.4** ruff/vulture taraması → ölü import/fonksiyon temizliği.
3. **B** yorum standardizasyonu (en çok kullanılan dosyalardan başla; her dosya ayrı commit).
4. **A.2** PHONETIC/NGRAM+core_name kararı — kullanıcı onayına bağlı (re-enable edilecek mi?).
5. **A.3** CLI scriptleri incele.

> Her adım küçük, ayrı commit + PR; davranış değişmez; `pytest` 209 yeşil korunur.

**KARAR GEREKEN:** (1) PHONETIC/NGRAM kalıcı kapalı mı (A.2 kapsamı)? (2) Yorum dili Türkçe sabit mi? (3) Hangi adımdan başlayalım?
