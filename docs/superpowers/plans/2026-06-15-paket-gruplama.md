# Paket Gruplama & main_processor Parçalama — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Düz modül yapısını işlevsel klasörlere (`core/`, `es/`, `dedup/`, `matching/`, `tools/`) gruplamak ve 1298 satırlık `main_processor.py`'yi DB-I/O / ES-yazma / orkestrasyon olarak bölmek — davranış DEĞİŞMEDEN.

**Architecture:** Saf yeniden yapılandırma (refactor). `config.py` ve `main_processor.py` kökte kalır; `main_processor.py` ince bir giriş noktası olur ve `matching.pipeline.process_all_data()` çağırır. Bağımlılık yönü tek yönlüdür: `pipeline → es_writer/db_io` (döngü yok). **Mevcut pytest paketi (~200+ test) regresyon güvencesidir** — yeni test yazılmaz; her adımda mevcut testlerin YEŞİL kalması = başarı (karakterizasyon-testi yaklaşımı, saf taşıma).

**Tech Stack:** Python 3.12, pytest, Elasticsearch (`elasticsearch` py-client), psycopg2. Absolute import'lar kullanılır (`from es.manager import ...`), böylece hem normal import hem `python -m paket.modul` çalışır.

**Dal:** `refactor/paket-gruplama` (zaten mevcut, spec commit'li).

---

## Global Import Yeniden-Yazma Haritası

Aşağıdaki tüm tasklar bu haritayı kullanır. `config` **değişmez** (kökte kalır).

| Eski modül | Yeni dotted path | Yeni dosya |
|---|---|---|
| `core_name` | `core.core_name` | `core/core_name.py` |
| `input_filter` | `core.input_filter` | `core/input_filter.py` |
| `synonym_loader` | `core.synonym_loader` | `core/synonym_loader.py` |
| `es_manager` | `es.manager` | `es/manager.py` |
| `es_ingest` | `es.ingest` | `es/ingest.py` |
| `es_queries` | `es.queries` | `es/queries.py` |
| `es_transform` | `es.transform` | `es/transform.py` |
| `dedup_auto_merge` | `dedup.auto_merge` | `dedup/auto_merge.py` |
| `dedup_reviewer` | `dedup.reviewer` | `dedup/reviewer.py` |

Her import satırı 3 biçimde olabilir; üçü de güncellenir:
- `from <eski> import X` → `from <yeni> import X`
- `import <eski>` → `import <yeni>` (kullanım yerleri de `<eski>.` → `<yeni>.`)
- `import <eski> as alias` → `import <yeni> as alias` (alias korunur)
- `patch("<eski>.X")` / `monkeypatch.setattr("<eski>.X", ...)` → `patch("<yeni>.X")` (test string-target'ları)

---

## Task 0: Baseline — mevcut test durumunu kaydet

**Files:** (yok — yalnızca ölçüm)

> **ÖNEMLİ — baseline temiz DEĞİL.** Refactor'dan ÖNCE ölçülen durum: **192 passed, 1 skipped, 17 failed**. Bu 17 kırık ÖNCEDEN VAR ve bu refactor'ın KAPSAMI DIŞINDADIR — düzeltilmeyecek, ama YENİ kırık da eklenmeyecek:
> - **12 ×** `tests/test_generate_config.py` — `generate_config` modülü repoda yok (`ModuleNotFoundError`).
> - **5 ×** `tests/test_main_processor.py` — `test_batch_end_flush_sql_binds_all_5_columns`, `test_all_pg_updates_appends_use_float_score`, `test_pg_update_flush_sql_uses_safe_identifiers`, `test_excluded_input_isolated_not_matched_not_indexed`, `test_per_batch_dedup_invoked_with_batch_master_ids`. Hepsi `patch.object(mp, "ES_REFRESH_INTERVAL", ...)` yapıyor; ama kaynak (`main_processor.py`) `ES_REFRESH_INTERVAL`'i import/kullanmıyor (yalnızca `config.py`'de tanımlı) → `AttributeError`. Bayat testler.
>
> **BAŞARI KRİTERİ (tüm tasklar):** `192 passed` korunur; yeni FAIL üretilmez. Task 7'den sonra bu 5 main_processor testi yine aynı `ES_REFRESH_INTERVAL` nedeniyle FAIL kalır (yeni hedef `matching.pipeline` namespace'inde de bu sabit yok) — bu bir regresyon DEĞİLDİR, beklenen pre-existing durumdur.

- [ ] **Step 1: Mevcut test sayısını ve durumunu kaydet**

Run:
```bash
python -m pytest -q 2>&1 | tail -5
```
Expected: `192 passed, 1 skipped, 17 failed` (yukarıda listelenen pre-existing kırıklar). Referans: **192 passed** düşmemeli.

- [ ] **Step 2: Çalışma ağacının temiz olduğunu doğrula**

Run:
```bash
git status --short
```
Expected: Çıktı boş (yalnızca spec commit'li, başka değişiklik yok).

---

## Task 1: `core/` paketi (core_name, input_filter, synonym_loader)

**Files:**
- Create: `core/__init__.py` (boş)
- Move: `core_name.py` → `core/core_name.py`, `input_filter.py` → `core/input_filter.py`, `synonym_loader.py` → `core/synonym_loader.py`
- Modify (importer'lar): `core/core_name.py` (synonym_loader import'u), `core/input_filter.py` (synonym_loader import'u), `es_queries.py`, `es_ingest.py`, `es_manager.py`, `main_processor.py`, `analysis/detectors.py`, `tests/test_core_name.py`, `tests/test_input_filter.py`, `tests/test_synonym_loader.py`, `tests/test_config.py`, `tests/test_es_ingest.py`, `tests/test_es_manager.py`

> Not: `core_name` modülü `synonym_loader`'ı import eder; `input_filter` da `synonym_loader`'ı import eder. Bu ikisi `core/` içinde sibling olur → `from core.synonym_loader import ...`.

- [ ] **Step 1: Paket klasörünü ve boş `__init__.py`'yi oluştur**

Run:
```bash
mkdir core
ni core/__init__.py -ItemType File   # PowerShell; bash'te: touch core/__init__.py
```

- [ ] **Step 2: Dosyaları git ile taşı (geçmiş korunur)**

Run:
```bash
git mv core_name.py core/core_name.py
git mv input_filter.py core/input_filter.py
git mv synonym_loader.py core/synonym_loader.py
```

- [ ] **Step 3: Taşınan modüllerin iç sibling import'larını güncelle**

`core/core_name.py` ve `core/input_filter.py` içindeki:
- `from synonym_loader import ...` → `from core.synonym_loader import ...`

(`config` import'ları varsa DEĞİŞMEZ.)

- [ ] **Step 4: Dış importer'ları güncelle (kaynak)**

Şu dosyalarda `from synonym_loader import` → `from core.synonym_loader import`, `from core_name import` → `from core.core_name import`, `from input_filter import` → `from core.input_filter import`:
- `es_queries.py` (core_name + synonym_loader)
- `es_ingest.py` (synonym_loader)
- `es_manager.py` (synonym_loader)
- `main_processor.py` (input_filter → `from core.input_filter import classify_input`)
- `analysis/detectors.py` (core_name)

- [ ] **Step 5: Test importer'larını güncelle**

Şu test dosyalarında aynı haritayı uygula (import satırları + varsa `patch("synonym_loader...")`/`monkeypatch.setattr("synonym_loader...")` gibi string target'lar):
- `tests/test_core_name.py` (`from core_name import normalize_core` → `from core.core_name import normalize_core`)
- `tests/test_input_filter.py` (`import input_filter as inf` → `import core.input_filter as inf`)
- `tests/test_synonym_loader.py`, `tests/test_config.py`, `tests/test_es_ingest.py`, `tests/test_es_manager.py` (synonym_loader import'ları)

Kalan referansları bul:
```bash
grep -rnE "(from (core_name|input_filter|synonym_loader) import|import (core_name|input_filter|synonym_loader)\b|\"(core_name|input_filter|synonym_loader)\.)" --include="*.py" . | grep -v -E "\.venv|__pycache__|/core/"
```
Expected: Çıktı boş (hiç eski referans kalmadı).

- [ ] **Step 6: Import smoke + testler**

Run:
```bash
python -c "import core.core_name, core.input_filter, core.synonym_loader; print('core OK')"
python -m pytest -q
```
Expected: `core OK` ve Task 0'daki test sayısı kadar PASS (düşme yok).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(core): core_name/input_filter/synonym_loader -> core/ paketi"
```

---

## Task 2: `es/` paketi (manager, ingest, queries, transform)

**Files:**
- Create: `es/__init__.py` (boş)
- Move: `es_manager.py`→`es/manager.py`, `es_ingest.py`→`es/ingest.py`, `es_queries.py`→`es/queries.py`, `es_transform.py`→`es/transform.py`
- Modify (importer'lar): `es/manager.py` (es_queries iç import'u), `es/ingest.py` (es_manager iç import'u), `es/transform.py` (es_manager iç import'u), `main_processor.py`, `dedup_auto_merge.py`, `dedup_reviewer.py`, `reset_matching.py`, `analysis/es_verify.py`, `analysis/live_probe.py`, `tests/test_es_manager.py`, `tests/test_es_queries.py`, `tests/test_es_ingest.py`, `tests/test_config.py`

> Task 1 tamamlanmış olmalı (es modülleri `core.*`'ı import ediyor). `es/` içi bağımlılıklar: `es.manager` → `es.queries`; `es.ingest` → `es.manager`; `es.transform` → `es.manager`. Hepsi sibling, tek yönlü.

- [ ] **Step 1: Paket + `__init__.py`**

Run:
```bash
mkdir es
ni es/__init__.py -ItemType File   # bash: touch es/__init__.py
```

- [ ] **Step 2: git mv**

Run:
```bash
git mv es_manager.py es/manager.py
git mv es_ingest.py es/ingest.py
git mv es_queries.py es/queries.py
git mv es_transform.py es/transform.py
```

- [ ] **Step 3: `es/` içi sibling import'ları güncelle**

- `es/manager.py`: `import es_queries` / `from es_queries import ...` → `es.queries`
- `es/ingest.py`: `from es_manager import ...` → `from es.manager import ...`
- `es/transform.py`: `from es_manager import ...` → `from es.manager import ...`
- Üçünde de `from core_name import` / `from synonym_loader import` zaten Task 1'de `core.*`'a güncellendiyse dokunma; değilse güncelle.

- [ ] **Step 4: Dış importer'ları güncelle (kaynak)**

`es_manager`→`es.manager`, `es_ingest`→`es.ingest`, `es_queries`→`es.queries`, `es_transform`→`es.transform` haritasıyla:
- `main_processor.py`: `from es_manager import create_index, get_es_client` → `from es.manager import ...`; `from es_ingest import register_all_pipelines, pipeline_name` → `from es.ingest import ...`; `import es_queries as _es_queries` → `import es.queries as _es_queries`; ayrıca fonksiyon içindeki `from es_manager import acronym_glue_active` → `from es.manager import acronym_glue_active`.
- `dedup_auto_merge.py`: `from es_manager import ...` → `from es.manager import ...`
- `dedup_reviewer.py`: `from es_manager import ...`, `from es_transform import ...` → `es.manager` / `es.transform`
- `reset_matching.py`: `from es_manager import ...` → `from es.manager import ...`
- `analysis/es_verify.py`: `from es_manager import ...`, `import es_queries` → `es.manager` / `es.queries`
- `analysis/live_probe.py`: `from es_manager import ...`, `from es_ingest import ...`, `import es_queries` → `es.*`

- [ ] **Step 5: Test importer'larını güncelle**

- `tests/test_es_manager.py`: `from es_manager import build_index_settings`, `from synonym_loader import ...` (Task 1) → `es.manager` / `core.synonym_loader`; ayrıca `patch("es_manager...")` / `monkeypatch.setattr("es_manager...", ...)` string target'ları → `es.manager...`
- `tests/test_es_queries.py`: `import es_queries`, `from es_manager import get_es_client` → `es.queries` / `es.manager`; string patch target'ları → `es.queries.` / `es.manager.`
- `tests/test_es_ingest.py`: `import es_ingest`, `from es_ingest import ...` → `es.ingest`; patch target'ları → `es.ingest.`
- `tests/test_config.py`: `import es_queries`, `from synonym_loader import ...` → `es.queries` / `core.synonym_loader`

Kalan referansları bul:
```bash
grep -rnE "(from (es_manager|es_ingest|es_queries|es_transform) import|import (es_manager|es_ingest|es_queries|es_transform)\b|\"(es_manager|es_ingest|es_queries|es_transform)\.)" --include="*.py" . | grep -v -E "\.venv|__pycache__|/es/"
```
Expected: Çıktı boş.

- [ ] **Step 6: Import smoke + testler**

Run:
```bash
python -c "import es.manager, es.ingest, es.queries, es.transform; print('es OK')"
python -m pytest -q
```
Expected: `es OK` + test sayısı korunur (PASS).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(es): es_manager/ingest/queries/transform -> es/ paketi"
```

---

## Task 3: `dedup/` paketi (auto_merge, reviewer)

**Files:**
- Create: `dedup/__init__.py` (boş)
- Move: `dedup_auto_merge.py`→`dedup/auto_merge.py`, `dedup_reviewer.py`→`dedup/reviewer.py`
- Modify: `main_processor.py`, `tests/test_dedup_auto_merge.py` (+ `dedup/reviewer.py` iç import'ları)

- [ ] **Step 1: Paket + `__init__.py`**

Run:
```bash
mkdir dedup
ni dedup/__init__.py -ItemType File   # bash: touch dedup/__init__.py
```

- [ ] **Step 2: git mv**

Run:
```bash
git mv dedup_auto_merge.py dedup/auto_merge.py
git mv dedup_reviewer.py dedup/reviewer.py
```

- [ ] **Step 3: İç import'lar (Task 2 sonrası zaten es.* olmalı)**

`dedup/auto_merge.py` ve `dedup/reviewer.py` içinde `from es_manager import`/`from es_transform import` Task 2'de güncellenmediyse → `es.manager` / `es.transform`. (`config` değişmez.)

- [ ] **Step 4: Dış importer'ı güncelle**

- `main_processor.py`: `from dedup_auto_merge import auto_merge_duplicates` → `from dedup.auto_merge import auto_merge_duplicates`

- [ ] **Step 5: Test importer'ı güncelle**

- `tests/test_dedup_auto_merge.py`: `from dedup_auto_merge import ...` → `from dedup.auto_merge import ...`; `patch("dedup_auto_merge...")` → `patch("dedup.auto_merge...")`

Kalan referans:
```bash
grep -rnE "(from (dedup_auto_merge|dedup_reviewer) import|import (dedup_auto_merge|dedup_reviewer)\b|\"(dedup_auto_merge|dedup_reviewer)\.)" --include="*.py" . | grep -v -E "\.venv|__pycache__|/dedup/"
```
Expected: Çıktı boş.

- [ ] **Step 6: Import smoke + testler**

Run:
```bash
python -c "import dedup.auto_merge, dedup.reviewer; print('dedup OK')"
python -m pytest -q
```
Expected: `dedup OK` + test sayısı korunur.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(dedup): dedup_auto_merge/reviewer -> dedup/ paketi"
```

---

## Task 4: `tools/` paketi + boş `utils/` kaldır

**Files:**
- Create: `tools/__init__.py` (boş)
- Move: `reset_matching.py`→`tools/reset_matching.py`, `analyze_mismatches.py`→`tools/analyze_mismatches.py`
- Delete: `utils/` (boş klasör)

> `reset_matching` ve `analyze_mismatches` hiçbir kaynak/test tarafından import EDİLMİYOR (yalnızca `python` ile çalıştırılır). Bu yüzden dış importer güncellemesi yok; sadece kendi import'ları Task 1-3 ile güncellenmiş olur.

- [ ] **Step 1: Paket + `__init__.py`**

Run:
```bash
mkdir tools
ni tools/__init__.py -ItemType File   # bash: touch tools/__init__.py
```

- [ ] **Step 2: git mv + iç import'lar**

Run:
```bash
git mv reset_matching.py tools/reset_matching.py
git mv analyze_mismatches.py tools/analyze_mismatches.py
```
Sonra her ikisinde kalan eski import varsa Global Harita ile güncelle:
- `tools/reset_matching.py`: `from es_manager import ...` → `from es.manager import ...`
- `tools/analyze_mismatches.py`: `from analysis.detectors import ...` (DEĞİŞMEZ — analysis paketi sabit) ve varsa diğer eski modüller.

Kalan referans:
```bash
grep -nE "(from (es_manager|es_ingest|es_queries|es_transform|core_name|input_filter|synonym_loader|dedup_auto_merge|dedup_reviewer) import|import (es_manager|core_name|synonym_loader)\b)" tools/reset_matching.py tools/analyze_mismatches.py
```
Expected: Çıktı boş.

- [ ] **Step 3: Boş `utils/` klasörünü kaldır**

Run:
```bash
git rm -r --ignore-unmatch utils 2>$null; if (Test-Path utils) { Remove-Item -Recurse -Force utils }
```
(utils git'te izlenmiyorsa `git rm` no-op olur; fiziksel boş klasör silinir.)

- [ ] **Step 4: Çalıştırma smoke (modül olarak import edilebilirlik)**

Run:
```bash
python -c "import tools.reset_matching, tools.analyze_mismatches; print('tools OK')"
python -m pytest -q
```
Expected: `tools OK` + test sayısı korunur.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(tools): reset_matching/analyze_mismatches -> tools/, bos utils/ kaldirildi"
```

---

## Task 5: `analysis/` import yollarını doğrula/tamamla

**Files:** `analysis/detectors.py`, `analysis/es_verify.py`, `analysis/live_probe.py`, `analysis/run_qa.py`, `tests/test_analysis_detectors.py`

> Çoğu Task 1-2'de güncellendi; bu task kalanları yakalar (`run_qa.py` → `from analysis.detectors import ...` zaten paket-içi, DEĞİŞMEZ).

- [ ] **Step 1: Kalan eski referansları tara**

Run:
```bash
grep -rnE "(from (es_manager|es_ingest|es_queries|es_transform|core_name|input_filter|synonym_loader|dedup_auto_merge|dedup_reviewer) import|import (es_manager|es_ingest|es_queries|es_transform|core_name|input_filter|synonym_loader)\b|\"(es_manager|es_ingest|es_queries|es_transform|core_name|input_filter|synonym_loader|dedup_auto_merge|dedup_reviewer)\.)" --include="*.py" analysis tests
```
Expected: Çıktı boş. Çıktı varsa Global Harita ile düzelt.

- [ ] **Step 2: Smoke + testler**

Run:
```bash
python -c "import analysis.detectors, analysis.es_verify, analysis.live_probe, analysis.run_qa; print('analysis OK')"
python -m pytest -q
```
Expected: `analysis OK` + test sayısı korunur.

- [ ] **Step 3: Commit (değişiklik varsa)**

```bash
git add -A
git commit -m "refactor(analysis): import yollari yeni paket yapisina guncellendi" || echo "degisiklik yok, atlandi"
```

---

## Task 6: `main_processor.py`'yi `matching/` altında 3 modüle böl

**Files:**
- Create: `matching/__init__.py` (boş), `matching/db_io.py`, `matching/es_writer.py`, `matching/pipeline.py`
- Modify: `main_processor.py` (ince giriş noktasına indirgenir)

> **Bağımlılık yönü (döngü yok):** `db_io` ve `es_writer` yapraktır (yalnızca config/es/psycopg2). `pipeline`, `db_io` + `es_writer`'ı import eder. `main_processor` yalnızca `pipeline`'ı import eder.

**Fonksiyon yerleşimi (mevcut `main_processor.py`'den birebir taşıma, gövde DEĞİŞMEZ):**
- `matching/db_io.py`: `_make_pg_update_tuple`, `get_db_connection`, `ensure_stage_log_table`, `validate_db_schema`, `write_matched_to_pg`, `write_stage_log`
- `matching/es_writer.py`: `update_es_variations`, `_append_list_fields`, `build_new_master_doc`, `_index_new_master`, `_add_variation_to_master`
- `matching/pipeline.py`: `run_stage`, `_execute_msearch`, `_select_winner`, `_build_stage_body`, `match_single_record`, `match_records_batch`, `create_new_masters`, `process_all_data`

- [ ] **Step 1: Paket + `__init__.py`**

Run:
```bash
mkdir matching
ni matching/__init__.py -ItemType File   # bash: touch matching/__init__.py
```

- [ ] **Step 2: `matching/db_io.py` oluştur**

Başlık import'ları:
```python
"""PostgreSQL I/O: bağlantı, şema doğrulama, eşleşme/stage-log yazımı."""
import logging
from typing import Any

import psycopg2
import psycopg2.sql
from psycopg2.extras import execute_values

from config import (
    RAW_TABLE_NAME,
    DB_CONFIG,
    COLUMN_MAPPING,
    MANDATORY_READ_COLUMNS,
    MANDATORY_UPDATE_COLUMNS,
    AUTO_CREATE_UPDATE_COLUMNS,
)

logger = logging.getLogger(__name__)
```
Ardından mevcut `main_processor.py`'den şu fonksiyonların **gövdesini değiştirmeden** taşı: `_make_pg_update_tuple`, `get_db_connection`, `ensure_stage_log_table`, `validate_db_schema`, `write_matched_to_pg`, `write_stage_log`.

- [ ] **Step 3: `matching/es_writer.py` oluştur**

Başlık import'ları:
```python
"""Elasticsearch master-doc yazımı: varyasyon/meta ekleme, yeni master indeksleme."""
import logging
import uuid

from config import ES_INDEX
from es.ingest import pipeline_name

logger = logging.getLogger(__name__)
```
Ardından şu fonksiyonları **gövdesini değiştirmeden** taşı: `update_es_variations`, `_append_list_fields`, `build_new_master_doc`, `_index_new_master`, `_add_variation_to_master`.

- [ ] **Step 4: `matching/pipeline.py` oluştur**

Başlık import'ları (tqdm fallback shim dahil — mevcut `main_processor.py` satır 14-34'ten birebir taşınır):
```python
"""Eşleştirme orkestrasyonu: stage çalıştırma, msearch, kazanan seçimi, ana döngü."""
import logging
import uuid
from typing import Any

import psycopg2
import psycopg2.sql
from psycopg2.extras import DictCursor, execute_values
from elasticsearch import helpers

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover

    class tqdm:  # type: ignore[misc]
        """tqdm yoksa sessizce devam eder; gerçek progress bar için tqdm kurun."""

        def __init__(self, iterable=None, **kwargs):
            self._iterable = iterable

        def __iter__(self):
            return iter(self._iterable) if self._iterable is not None else iter([])

        def update(self, n=1):
            pass

        def set_postfix_str(self, s="", refresh=True):
            pass

        def close(self):
            pass


from config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    ES_INDEX,
    RAW_TABLE_NAME,
    COUNTRY_CODE_FILTER,
    STAGES,
    MSEARCH_CHUNK_SIZE,
    SUFFIX_FUZZY_SCORE,
    LOG_ALL_STAGES,
    NEW_MASTER_SUBBATCH_SIZE,
    ENABLE_INPUT_FILTER,
    AUTO_DEDUP_PER_BATCH,
    AUTO_DEDUP_EVERY_N_BATCHES,
    MATCH_BATCH_SIZE,
)
from es.manager import create_index, get_es_client
from es.ingest import register_all_pipelines, pipeline_name
import es.queries as _es_queries
from core.input_filter import classify_input
from dedup.auto_merge import auto_merge_duplicates

from matching.db_io import (
    _make_pg_update_tuple,
    get_db_connection,
    ensure_stage_log_table,
    validate_db_schema,
    write_matched_to_pg,
    write_stage_log,
)
from matching.es_writer import (
    update_es_variations,
    _index_new_master,
    _add_variation_to_master,
)

logger = logging.getLogger(__name__)
```
Ardından şu fonksiyonları **gövdesini değiştirmeden** taşı: `run_stage`, `_execute_msearch`, `_select_winner`, `_build_stage_body`, `match_single_record`, `match_records_batch`, `create_new_masters`, `process_all_data`.

> `process_all_data` içindeki inline `from es_manager import acronym_glue_active` satırı `from es.manager import acronym_glue_active` olarak kalır (Task 2'de güncellendi). Diğer hiçbir gövde satırı değişmez.

- [ ] **Step 5: `main_processor.py`'yi ince giriş noktasına indirge**

`main_processor.py`'nin TÜM içeriğini şununla değiştir:
```python
"""Giriş noktası: Firma Eşleştirme orkestrasyonunu başlatır.

Gerçek mantık matching/ paketindedir (db_io, es_writer, pipeline).
"""
import logging
import sys

from matching.pipeline import process_all_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("elasticsearch").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Firma Eşleştirme Sistemi başlatılıyor...")
    logger.info("=" * 60)
    process_all_data()
```

- [ ] **Step 6: Import smoke (döngüsel import kontrolü)**

Run:
```bash
python -c "import matching.db_io, matching.es_writer, matching.pipeline, main_processor; print('matching OK')"
```
Expected: `matching OK`. ImportError/circular import HATASI ALINIRSA: bağımlılık yönünü doğrula (`pipeline` → `db_io`/`es_writer`; tersi OLMAMALI; `es_writer`/`db_io` birbirini import ETMEMELİ).

> Bu adımda `test_main_processor.py` HENÜZ kırık (eski `import main_processor as mp` ile fonksiyonları arıyor) — Task 7 düzeltecek. Burada yalnızca import smoke yeterli; tam pytest Task 7 sonunda.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(matching): main_processor 3 module bolundu (db_io/es_writer/pipeline)"
```

---

## Task 7: `tests/test_main_processor.py`'yi yeni modüllere taşı

**Files:** `tests/test_main_processor.py`

> Her test fonksiyonu kendi içinde lokal `import main_processor as mp` yapıyor. Aşağıdaki tabloya göre her testin lokal import'unu ve string patch-target'larını güncelle. Kural: **`process_all_data`/`create_new_masters`/`run_stage`/`match_*`/`_select_winner` çağıran ya da bunların bağımlılıklarını patch'leyen testler `matching.pipeline`'ı hedefler** (çünkü bu fonksiyonlar pipeline namespace'inde aranır). **DB fonksiyonu testi `matching.db_io`'yu, es_writer fonksiyonlarını DOĞRUDAN çağırıp logger'ını patch'leyen testler `matching.es_writer`'ı hedefler.**

| Test fonksiyonu (satır) | `import ... as mp` | `"main_processor.X"` → |
|---|---|---|
| `test_run_stage_returns_matched_and_unmatched` (25) | `matching.pipeline` | `matching.pipeline.` |
| `test_run_stage_respects_min_score` (53) | `matching.pipeline` | `matching.pipeline.` |
| `test_country_code_filter_uses_parametric_sql` (74) | `matching.pipeline` | `matching.pipeline.` |
| `test_validate_db_schema_uses_safe_identifiers` (141) | `matching.db_io` | `matching.db_io.` |
| `test_create_new_masters_produces_5_element_tuple` (187) | `matching.pipeline` | `matching.pipeline.` (özellikle `helpers.bulk`) |
| `test_batch_end_flush_sql_binds_all_5_columns` (226) | `matching.pipeline` | `matching.pipeline.` |
| `test_per_row_exception_does_not_halt_batch` (313) | `matching.pipeline` | `matching.pipeline.` (logger dahil — process_all_data logger'ı) |
| `test_es_bulk_failure_logs_at_warning_with_exc_info` (425) | `matching.es_writer` | `matching.es_writer.` (logger dahil — `update_es_variations`) |
| `test_add_variation_to_master_logs_es_failure_at_warning_with_exc_info` (483) | `matching.es_writer` | `matching.es_writer.` (logger dahil) |
| `test_add_variation_preserves_existing_variations_stripped_and_suffix` (533) | `matching.es_writer` | — (string patch yok) |
| `test_all_pg_updates_appends_use_float_score` (607) | `matching.pipeline` | `matching.pipeline.` |
| `test_pg_update_flush_sql_uses_safe_identifiers` (718) | `matching.pipeline` | `matching.pipeline.` |
| `test_main_processor_does_not_hardcode_thresholds` (797) | `matching.pipeline` | `matching.pipeline.` |
| `test_create_new_masters_variation_shape_matches_add_variation` (852) | **İKİ alias** (aşağıya bak) | `matching.pipeline.` (helpers.bulk) |
| `test_excluded_input_isolated_not_matched_not_indexed` (952) | `matching.pipeline` | `matching.pipeline.` |
| `test_input_filter_disabled_processes_normally` (1004) | `matching.pipeline` | `matching.pipeline.` |
| `test_per_batch_dedup_invoked_with_batch_master_ids` (1043) | `matching.pipeline` | `matching.pipeline.` (dedup: `matching.pipeline.auto_merge_duplicates`) |
| `test_match_records_batch_equivalent_to_single` (1110) | `matching.pipeline` | `matching.pipeline.` |
| `test_match_records_batch_empty_and_no_stages` (1160) | `matching.pipeline` | `matching.pipeline.` |
| `test_select_winner_no_size_cap_huge_cluster_still_wins` (1168) | `matching.pipeline` | `matching.pipeline.` |

- [ ] **Step 1: Pipeline-hedefli testleri güncelle**

Yukarıdaki tabloda `matching.pipeline` olan her test için:
- Lokal `import main_processor as mp` → `import matching.pipeline as mp`
- O test gövdesindeki tüm `"main_processor.` string'lerini `"matching.pipeline.` yap (ör. `patch("main_processor.get_es_client")` → `patch("matching.pipeline.get_es_client")`, `patch("main_processor.helpers.bulk")` → `patch("matching.pipeline.helpers.bulk")`, `patch("main_processor.logger")` → `patch("matching.pipeline.logger")`).
- `patch.object(mp, "...")` satırları DEĞİŞMEZ (mp artık `matching.pipeline`; `_index_new_master`, `_add_variation_to_master`, `match_records_batch`, `match_single_record` adları pipeline namespace'ine import edildiği için çözülür).

- [ ] **Step 2: db_io-hedefli testi güncelle**

`test_validate_db_schema_uses_safe_identifiers`:
- `import main_processor as mp` → `import matching.db_io as mp`
- Varsa `"main_processor.` → `"matching.db_io.`
- `mp.validate_db_schema(...)` çağrısı aynı kalır.

- [ ] **Step 3: es_writer-hedefli testleri güncelle**

`test_es_bulk_failure_logs_at_warning_with_exc_info`, `test_add_variation_to_master_logs_es_failure_at_warning_with_exc_info`, `test_add_variation_preserves_existing_variations_stripped_and_suffix`:
- `import main_processor as mp` → `import matching.es_writer as mp`
- `patch("main_processor.logger")` → `patch("matching.es_writer.logger")`
- `mp.update_es_variations(...)` / `mp._add_variation_to_master(...)` çağrıları aynı kalır.

- [ ] **Step 4: İki-alias testini güncelle**

`test_create_new_masters_variation_shape_matches_add_variation` (852): bu test hem pipeline (create_new_masters) hem es_writer (build_new_master_doc, _add_variation_to_master) fonksiyonlarına dokunur. `import main_processor as mp` satırını şununla değiştir:
```python
import matching.pipeline as pipeline
import matching.es_writer as es_writer
```
Sonra çağrıları yönlendir:
- `mp.create_new_masters(...)` → `pipeline.create_new_masters(...)`
- `mp.build_new_master_doc(...)` → `es_writer.build_new_master_doc(...)`
- `mp._add_variation_to_master(...)` → `es_writer._add_variation_to_master(...)`
- `patch("main_processor.helpers.bulk", ...)` → `patch("matching.pipeline.helpers.bulk", ...)`

- [ ] **Step 5: Kalan eski referansları tara**

Run:
```bash
grep -nE "main_processor" tests/test_main_processor.py
```
Expected: Çıktı boş (hiç `main_processor` referansı kalmadı — yorum satırlarındaki açıklama metinleri varsa zararsız; ama `import`/`patch`/`mp.` kullanımı kalmamalı).

- [ ] **Step 6: Tam test paketi**

Run:
```bash
python -m pytest -q 2>&1 | tail -8
```
Expected: **`192 passed`** korunur. Kırık sayısı yine **17** (pre-existing): 12 `test_generate_config` + 5 `test_main_processor` `ES_REFRESH_INTERVAL` testi. Bu 5 test Task 7 sonrası `matching.pipeline` hedefiyle de aynı `ES_REFRESH_INTERVAL` nedeniyle FAIL kalır — beklenen, regresyon değil.

Beklenenden FAZLA FAIL olursa (192 passed düştüyse): o testin hangi fonksiyonu çağırdığını ve hangi namespace'i patch'lediğini kontrol et — patch, fonksiyonun ARANDIĞI namespace'i hedeflemeli (pipeline-resident fonksiyon çağrıları için `matching.pipeline`, doğrudan es_writer/db_io çağrıları için ilgili modül).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test(matching): test_main_processor patch hedefleri yeni modullere tasindi"
```

---

## Task 8: Dokümantasyon (CLAUDE.md + README) + final doğrulama

**Files:** `CLAUDE.md`, `README.md`

- [ ] **Step 1: CLAUDE.md dosya-yapısı tablosunu güncelle**

CLAUDE.md Bölüm 2'deki modül tablosunda dosya yollarını yeni paketlere göre güncelle (ör. `main_processor.py` → ince giriş + `matching/pipeline.py`; `es_queries.py` → `es/queries.py`; `es_manager.py` → `es/manager.py`; `synonym_loader.py` → `core/synonym_loader.py`; `es_transform.py` → `es/transform.py`; `dedup_reviewer.py` → `dedup/reviewer.py`). `matching/db_io.py`, `matching/es_writer.py` için yeni satırlar ekle.

- [ ] **Step 2: CLAUDE.md çalıştırma komutlarını güncelle**

Bölüm 3'teki komutları güncelle:
```bash
# Ingest pipeline kur
python -m es.ingest

# Index kur ve mapping güncelle (synonym değişirse --force kullanın)
python -m es.manager

# Eşleştirmeyi başlat
python main_processor.py
```

- [ ] **Step 3: README.md güncelle (varsa eski yol/komut referansları)**

Run (önce tara):
```bash
grep -nE "es_manager|es_ingest|es_queries|es_transform|synonym_loader|dedup_reviewer|dedup_auto_merge|core_name|input_filter" README.md
```
Bulunan eski dosya-adı/komut referanslarını yeni paket yollarına güncelle. Eşleştirme davranışını anlatan metinler değişmez.

- [ ] **Step 4: Final doğrulama — tüm smoke + tam test**

Run:
```bash
python -c "import core.core_name, core.input_filter, core.synonym_loader; import es.manager, es.ingest, es.queries, es.transform; import dedup.auto_merge, dedup.reviewer; import matching.db_io, matching.es_writer, matching.pipeline; import main_processor, tools.reset_matching, tools.analyze_mismatches, analysis.detectors; print('ALL IMPORTS OK')"
python -m pytest -q 2>&1 | tail -8
```
Expected: `ALL IMPORTS OK` + **`192 passed`** korunur (17 pre-existing FAIL değişmez).

- [ ] **Step 5: Çalışma ağacı temiz mi + nihai yapı**

Run:
```bash
git add -A && git commit -m "docs: CLAUDE.md/README paket yapisi ve calistirma komutlari guncellendi"
git status --short
ls core es dedup matching tools
```
Expected: Commit başarılı; `git status` temiz; klasörler beklenen dosyaları içeriyor.

---

## Notlar

- **Davranış değişmezliği:** Hiçbir fonksiyon gövdesi, Query DSL, analyzer, eşik değeri veya `synonyms_data/` içeriği değişmedi. Tek "davranışsal" fark: `python es_manager.py`/`python es_ingest.py` artık `python -m es.manager`/`python -m es.ingest` ile çalışır (CLAUDE.md güncellendi).
- **Geri alınabilirlik:** Her task ayrı commit; sorun çıkarsa task bazında `git revert` mümkün.
- **`build_new_master_doc`** muhtemelen yalnızca testlerde referanslanıyor (üretim akışı `_index_new_master`/`create_new_masters` kullanıyor); kaldırma bu refactor'ın KAPSAMI DIŞINDA — yerinde (`es_writer.py`) korunur.
