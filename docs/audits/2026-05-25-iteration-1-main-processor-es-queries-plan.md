# İterasyon 1: main_processor.py + es_queries.py Audit & Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `main_processor.py` ve `es_queries.py` modüllerinde sistematik bug avı: pytest baseline → statik audit raporları → kullanıcı onaylı bulgular için TDD ile düzeltme.

**Architecture:** İki faz. Faz A (planlı, sıralı): baseline + audit raporu üretimi. Faz B (dinamik, bulgu bazlı): her onaylanmış bulgu için RED test → GREEN fix → commit micro-cycle'ı.

**Tech Stack:** Python 3, pytest, unittest.mock (MagicMock), Elasticsearch DSL (Python tarafı), PostgreSQL (psycopg2). Mevcut testler ES/PG'yi mock'lar — canlı altyapı gerekmez.

**Reference Spec:** [docs/audits/2026-05-25-module-audit-tdd-loop-design.md](2026-05-25-module-audit-tdd-loop-design.md)

---

## File Structure

**Yeni dosya yok.** Çıktılar:

- `docs/audits/2026-05-25-main-processor-findings.md` — main_processor.py bulgu raporu
- `docs/audits/2026-05-25-es-queries-findings.md` — es_queries.py bulgu raporu
- `tests/test_main_processor.py` — yeni RED testler eklenir (mevcut dosyaya append)
- `tests/test_es_queries.py` — yeni RED testler eklenir (mevcut dosyaya append)
- `main_processor.py`, `es_queries.py` — onaylanan bulgular için fix'ler

**Kapsam dışı:** `debug_match.py`, `synonyms_data/*.json`, `.venv/`.

---

## FAZ A — Baseline + Audit (planlı)

### Task 1: pytest Baseline

**Files:**
- Read-only: tüm `tests/`

- [ ] **Step 1: Tam test suite'ini çalıştır ve sonucu kaydet**

Run:
```bash
cd c:/All-project/ta-code-merge && pytest -v --tb=short 2>&1 | tee /tmp/pytest-baseline.txt
```

Expected: Tüm testlerin pass/fail durumu, kaç test koşmuş, kaç saniye sürmüş.

- [ ] **Step 2: Baseline özetini chat'e yaz**

Format:
```
Baseline: <N> passed, <M> failed, <K> skipped, <T>s
Failed tests (bulgu olarak işaretlenecek):
  - tests/path::test_name — kısa hata özeti
```

Eğer kırmızı test varsa, her biri otomatik olarak HIGH severity bulgu sayılır ve Faz B'de düzeltme adayıdır.

- [ ] **Step 3: Eğer ES/PG bağlantı hatası varsa kullanıcıya danış**

Bazı testler canlı ES/PG bekleyebilir. Connection refused / module not found gibi hatalar çıkarsa:
- Hatalı testleri raporla
- Kullanıcıya sor: "skip et / mock ekle / şimdilik görmezden gel"
- Karar gelmeden Faz A devam etmesin

**Commit yok** (sadece okuma).

---

### Task 2: main_processor.py Statik Audit

**Files:**
- Read-only: `main_processor.py` (1174 satır)
- Create: `docs/audits/2026-05-25-main-processor-findings.md`

- [ ] **Step 1: Dosyayı baştan sona oku**

Run:
```bash
wc -l c:/All-project/ta-code-merge/main_processor.py
```
Dosya 1174 satır. `Read` aracıyla 0–1174 aralığını oku (gerekirse parça parça).

- [ ] **Step 2: Her şüpheli yer için bulgu formatında not al**

Bulgu formatı:
```markdown
## [SEVERITY] dosya:satır — kısa başlık

**Kanıt:**
```python
<kod alıntısı>
```

**Neden problem:** <açıklama>

**Önerilen düzeltme:** <kısa>

**CLAUDE.md ihlali:** <varsa kural numarası, yoksa "—">

**Test edilebilir mi?** <evet/hayır — TDD ile düzeltilebilir mi?>
```

Severity:
- CRITICAL: güvenlik / veri kaybı / production-down (örn. raw SQL interpolation, country_code by-pass)
- HIGH: bug / yanlış sonuç / batch hatası tüm batch'i durduruyor
- MEDIUM: bakım / code smell / DRY ihlali
- LOW: stil / küçük öneri

- [ ] **Step 3: Özel kontrol listesi (her bulguda bunlara bak)**

CLAUDE.md kuralları:
- [ ] `country_code` her ES sorgusunda filter olarak gidiyor mu? `_routing` her zaman büyük harfli country_code mı?
- [ ] PostgreSQL sorgularında raw f-string interpolation var mı? (`f"... '{val}' ..."`) — parametrik `%s` ve `execute_values` kullanılmalı.
- [ ] Batch döngülerinde tek kayıt hatası tüm batch'i durduruyor mu? Try/except + rollback + continue pattern'i var mı?
- [ ] `RapidFuzz`, `Levenshtein` veya benzeri import var mı? (YASAK)
- [ ] `synonyms_data/*.json` dosyalarına yazma denemesi var mı? (YASAK)

Genel kalite:
- [ ] Fonksiyon >50 satır var mı?
- [ ] Mutation pattern'i (in-place değişiklik) var mı?
- [ ] Sessizce yutulan exception (`except: pass` veya `except Exception: pass`) var mı?
- [ ] Magic number / hardcoded threshold var mı? (`config.py`'a taşınmalı)
- [ ] Deep nesting (>4 seviye) var mı?

- [ ] **Step 4: Bulguları dosyaya yaz**

Dosya başlığı:
```markdown
# main_processor.py Audit Bulguları

**Tarih:** 2026-05-25
**Dosya:** main_processor.py (1174 satır)
**Audit eden:** Claude
**Baseline:** [Task 1 sonucu özet]

## Özet
- CRITICAL: <N>
- HIGH: <N>
- MEDIUM: <N>
- LOW: <N>

## Bulgular
[her bulgu Step 2 formatında]
```

- [ ] **Step 5: Commit**

```bash
cd c:/All-project/ta-code-merge && git add docs/audits/2026-05-25-main-processor-findings.md && git commit -m "docs: add main_processor.py audit findings"
```

---

### Task 3: es_queries.py Statik Audit

**Files:**
- Read-only: `es_queries.py` (316 satır)
- Create: `docs/audits/2026-05-25-es-queries-findings.md`

- [ ] **Step 1: Dosyayı tam oku**

`Read` aracıyla `es_queries.py` 1–316 satır.

- [ ] **Step 2: Bulguları Task 2 Step 2 formatında not al**

- [ ] **Step 3: Özel kontrol listesi (es_queries.py'ye özgü)**

- [ ] Her query generator fonksiyonu `country_code` parametresi alıyor mu ve bunu `bool.filter` içine koyuyor mu? (mevcut test pattern'i `_get_country_filter` ile bunu doğruluyor)
- [ ] Country-specific analyzer kullanımı tutarlı mı? (`test_canonical_exact_uses_country_analyzer` örneğine bak)
- [ ] Painless script'lerde hardcoded threshold var mı?
- [ ] `fuzziness` ayarı her yerde tutarlı mı? (`AUTO` kullanımı vs sabit sayı)
- [ ] Duplicate / kopyala-yapıştır kod bloğu var mı (DRY ihlali)?
- [ ] Nested query path'leri ve inner_hits tutarlı mı?
- [ ] Stage isimleri `config.py`'daki `STAGES` ile birebir mi?

- [ ] **Step 4: Bulguları dosyaya yaz**

Aynı format, başlık:
```markdown
# es_queries.py Audit Bulguları

**Tarih:** 2026-05-25
**Dosya:** es_queries.py (316 satır)
...
```

- [ ] **Step 5: Commit**

```bash
cd c:/All-project/ta-code-merge && git add docs/audits/2026-05-25-es-queries-findings.md && git commit -m "docs: add es_queries.py audit findings"
```

---

### Task 4: Bulguları Kullanıcıya Sun, Onay Al

- [ ] **Step 1: İki bulgu dosyasını kısa özetle**

Chat'te:
```
İterasyon 1 audit tamamlandı:
- main_processor.py: <N> bulgu (C: <c>, H: <h>, M: <m>, L: <l>)
- es_queries.py: <N> bulgu (C: <c>, H: <h>, M: <m>, L: <l>)

Tam raporlar:
- docs/audits/2026-05-25-main-processor-findings.md
- docs/audits/2026-05-25-es-queries-findings.md

En riskli ilk 5 bulgu (severity + kısa başlık):
1. ...
```

- [ ] **Step 2: AskUserQuestion ile cherry-pick**

Sorular:
1. "Hangi bulguları bu iterasyonda düzeltelim?" — multi-select, severity sırasıyla listele. "Hepsi CRITICAL+HIGH", "Sadece CRITICAL", "Manuel seçim", "Şimdilik düzeltme, sadece raporla" gibi opsiyonlar.
2. "Düzeltme sırası nasıl olsun?" — "Severity yüksekten düşüğe (önerilen)", "Dosya bazlı grupla", "Bağımlılığa göre".

- [ ] **Step 3: Onaylanan bulgu listesini chat'te tekrar göster ve Faz B'ye geç**

Faz B her bulgu için aynı micro-cycle'ı tekrarlar (aşağıdaki Task 5 şablonu).

---

## FAZ B — Düzeltme Döngüsü (dinamik, bulgu başına Task 5 tekrarı)

### Task 5 (her onaylanan bulgu için tekrarlanır): TDD Fix Micro-cycle

> **Not:** Bu task, Faz A Task 4'te onaylanan her bulgu için bir kez koşar. Şablon birebir aynı; sadece bulguya özgü test ve fix kodu değişir.

**Files (örnek — bulguya göre değişir):**
- Modify: `<bulgu dosyası>:<satır>`
- Test: `tests/test_<modul>.py` (mevcut dosyaya append)

- [ ] **Step 1: Bulguyu tekrar oku ve test stratejisini netleştir**

İlgili bulgu dosyasındaki "Test edilebilir mi?" alanını kontrol et. Eğer "hayır" ise:
- Statik analiz / manuel doğrulama planı yap, kullanıcıya bildir
- Bu task'ı atla, kullanıcı kararını bekle

Eğer "evet" ise: hangi MagicMock kurulumuyla testin RED olacağını planla.

- [ ] **Step 2: RED test yaz**

`tests/test_<modul>.py` dosyasının sonuna ekle. Mevcut pattern'i izle:

```python
def test_<bulgu_kısa_isim>():
    """<bulgunun ne yakaladığını açıklayan docstring>"""
    import <modul> as m
    # ... MagicMock kurulumu (mevcut _make_es_hit / _make_msearch_response yardımcılarına bak) ...
    # ... çağrı + assert ...
```

- [ ] **Step 3: Testi koş, FAIL ettiğini doğrula**

Run:
```bash
cd c:/All-project/ta-code-merge && pytest tests/test_<modul>.py::test_<bulgu_kısa_isim> -v
```

Expected: FAIL. Hata mesajı bulgunun açıkladığı yanlış davranışı göstermeli.

Eğer test ilk denemede PASS olursa: test yeterince spesifik değil. Step 2'ye dön ve testi daha hassas yaz (örn. tam değer eşitliği yerine substring kontrol ediliyorsa).

- [ ] **Step 4: Fix'i uygula**

`Edit` aracıyla bulgu dosyasında **minimum** değişikliği yap. Kapsamı bulgu sınırlarına kilitle — etrafta refactor yapma.

- [ ] **Step 5: Tek testi tekrar koş, GREEN olduğunu doğrula**

Run:
```bash
cd c:/All-project/ta-code-merge && pytest tests/test_<modul>.py::test_<bulgu_kısa_isim> -v
```

Expected: PASS.

- [ ] **Step 6: Tüm suite'i koş, regression olmadığını doğrula**

Run:
```bash
cd c:/All-project/ta-code-merge && pytest -v --tb=short
```

Expected: Baseline'daki yeşillerin tamamı hâlâ yeşil + yeni test yeşil. Eğer eskiden yeşilken şimdi kırmızı olan varsa:
- Fix yan etki yarattı → Step 4'e dön, daha dar bir düzeltme dene
- Veya kullanıcıya danış

- [ ] **Step 7: Commit**

Bulgu türüne göre prefix:
- Bug fix → `fix:`
- Refactor → `refactor:`
- Sadece test ekleme → `test:`

```bash
cd c:/All-project/ta-code-merge && git add tests/test_<modul>.py <modul>.py && git commit -m "fix(<modul>): <bulgu kısa başlığı>"
```

- [ ] **Step 8: Bulgu raporunu güncelle**

İlgili bulgu dosyasında bulgunun başına `**Durum:** ✅ Düzeltildi (<commit-sha>)` ekle. Commit'e dahil etme — bir sonraki bulgu commit'inde toplu güncellenir, ya da Faz B sonunda tek seferde commit'lenir.

---

### Task 6: İterasyon 1 Kapanış

- [ ] **Step 1: Bulgu raporlarını son durumla commit et**

```bash
cd c:/All-project/ta-code-merge && git add docs/audits/2026-05-25-*.md && git commit -m "docs: mark fixed findings in iteration 1 audit reports"
```

- [ ] **Step 2: Kısa retro chat'te**

Format:
```
İterasyon 1 kapanış:
- main_processor.py: <N> bulgu / <K> düzeltildi / <L> açık kaldı
- es_queries.py: <N> bulgu / <K> düzeltildi / <L> açık kaldı
- Commits: <M> (fix: <a>, refactor: <b>, test: <c>, docs: <d>)
- pytest: <P> passed, <F> failed (baseline ile karşılaştırma)
- Açık kalan bulgular: [liste]
```

- [ ] **Step 3: Sonraki adımı kullanıcıya sor**

AskUserQuestion:
- "Aynı modüllerde kalan bulgulara devam edelim mi?"
- "Bir sonraki modüle geçelim mi? (es_manager / es_ingest / synonym_loader / config)"
- "Şimdilik dural?"

---

## Self-Review

**1. Spec coverage:** Spec'teki 6 adım (Baseline → Statik Audit → Onay Kapısı → TDD Fix → Commit → Sonraki) bu planda Task 1, 2-3, 4, 5, 5 step 7, 6 ile karşılanıyor. ✅

**2. Placeholder scan:**
- "TBD" / "TODO" / "implement later" yok.
- Task 5 şablon olduğu için `<bulgu_kısa_isim>`, `<modul>` gibi placeholder'lar var — bu kasıtlı (her bulgu için bir kez koşan template). Açıkça "her onaylanan bulgu için tekrar" notu eklendi.
- "Add error handling" gibi vague step yok.

**3. Type consistency:**
- Test helper isimleri (`_make_es_hit`, `_make_msearch_response`) mevcut `tests/test_main_processor.py` ile birebir uyumlu. ✅
- `_get_country_filter` helper ismi `tests/test_es_queries.py` ile uyumlu. ✅
- Commit message prefix'leri (`fix:`, `refactor:`, `test:`, `docs:`) global git-workflow rule ile uyumlu. ✅

**4. Risk noktaları (planın kendi içinden):**
- Task 1 Step 3 — ES/PG canlı bağımlılık varsa kullanıcı kararı bekleniyor, plan donmaz.
- Task 5 Step 3 — RED test ilk seferde PASS ederse fallback yolu var (testi daraltma).
- Task 5 Step 6 — Regression varsa fallback yolu var (dar fix dene / kullanıcıya danış).
- Synonym JSON ihlali bulunursa: bulgunun "Önerilen düzeltme" alanında `config.py` (`SUFFIX_TYPO_MAP`) çözümü zorunlu (CLAUDE.md §1.4).
- Python'da fuzzy import bulunursa: CRITICAL severity + ES tarafı çözüm önerisi (CLAUDE.md Önemli).

Plan tamam.
