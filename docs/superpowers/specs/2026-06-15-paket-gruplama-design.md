# Paket Gruplama & Kod Düzenleme — Tasarım (Design Spec)

**Tarih:** 2026-06-15
**Konu:** Düz (flat) modül yapısını işlevsel klasörlere gruplama + `main_processor.py`'nin parçalanması
**Tür:** Saf yeniden yapılandırma (refactor) — davranış DEĞİŞMEZ

---

## 1. Amaç & Problem

Mevcut kod tabanı düz bir yapıda: 13 kök `.py` modülü birbirini `from config import ...` gibi düz import'larla çağırıyor. Sorunlar:

- `main_processor.py` **1298 satır** — 800-satır kuralını aşıyor; DB I/O, ES-yazma ve orkestrasyon tek dosyada.
- Modüller temasına göre gruplanmadığı için ekleme/düzenleme zahmetli.
- Paketleme yok (`pyproject.toml`/`setup.py` yok).

**Hedef:** Modülleri işlevsel klasörlere gruplamak ve `main_processor.py`'yi mantıksal parçalara bölmek; böylece ekleme/güncelleme/düzenleme kolaylaşsın. Katı pip-paket makinesi (installable package) **kapsam dışı** — pragmatik klasörleme + kod düzenlemesi.

## 2. Kapsam Kararları (onaylı)

- **Yaklaşım:** Hafif gruplama (Yaklaşım A) — alana göre klasörler; `config.py` ve `main_processor.py` kökte kalır.
- **Çalıştırma:** `python main_processor.py` aynen çalışır. Kurulum script'leri `python -m es.manager` / `python -m es.ingest` olur.
- **`main_processor.py`:** Parçalanır (DB I/O / ES-yazma / orkestrasyon).
- **Paketleme:** Katı installable paket YOK; sadece klasör + `__init__.py`.
- **Dokunulmaz:** `synonyms_data/` (65 ülke JSON) ve tüm eşleştirme mantığı/davranışı.

## 3. Hedef Klasör Yapısı

```
ta-code-merge/
├── config.py                 # kökte kalır — `from config import ...` satırları DEĞİŞMEZ
├── main_processor.py         # kökte ince orkestratör; `python main_processor.py`
│
├── core/                     # isim normalizasyonu & girdi
│   ├── __init__.py
│   ├── core_name.py
│   ├── input_filter.py
│   └── synonym_loader.py
│
├── es/                       # tüm Elasticsearch katmanı (es_ ön eki düşürülür)
│   ├── __init__.py
│   ├── manager.py            # was es_manager.py
│   ├── ingest.py             # was es_ingest.py
│   ├── queries.py            # was es_queries.py
│   └── transform.py          # was es_transform.py
│
├── dedup/                    # duplicate yönetimi (dedup_ ön eki düşürülür)
│   ├── __init__.py
│   ├── auto_merge.py         # was dedup_auto_merge.py
│   └── reviewer.py           # was dedup_reviewer.py
│
├── matching/                 # main_processor.py'den ÇIKARILAN parçalar
│   ├── __init__.py
│   ├── db_io.py              # get_db_connection, ensure_stage_log_table,
│   │                         #   validate_db_schema, write_matched_to_pg,
│   │                         #   write_stage_log, _make_pg_update_tuple
│   ├── es_writer.py          # update_es_variations, _append_list_fields,
│   │                         #   build_new_master_doc, create_new_masters,
│   │                         #   _index_new_master, _add_variation_to_master
│   └── pipeline.py           # run_stage, _execute_msearch, _select_winner,
│                             #   _build_stage_body, match_single_record,
│                             #   match_records_batch, process_all_data
│
├── tools/                    # bağımsız yardımcı script'ler
│   ├── __init__.py
│   ├── reset_matching.py
│   └── analyze_mismatches.py
│
├── analysis/                 # MEVCUT — yerinde kalır, import yolları güncellenir
├── tests/                    # MEVCUT — import yolları güncellenir
└── synonyms_data/            # SABİT — dokunulmaz
```

**Detaylar:**
- `es_` / `dedup_` ön ekleri klasör içinde düşürülür (`es.manager`, `dedup.auto_merge`) — `es.es_manager` tekrarını önler.
- `__init__.py` dosyaları **boş** kalır (sihirli re-export yok).
- `utils/` (boş klasör) kaldırılır.

## 4. Import Yeniden-Yazma Haritası

Tüm `*.py` + `tests/` + `analysis/` genelinde mekanik değişiklik:

| Eski | Yeni |
|---|---|
| `from config import …` / `import config` | **değişmez** |
| `from core_name import …` | `from core.core_name import …` |
| `from input_filter import …` / `import input_filter` | `from core.input_filter import …` / `import core.input_filter` |
| `from synonym_loader import …` | `from core.synonym_loader import …` |
| `from es_manager import …` | `from es.manager import …` |
| `from es_ingest import …` / `import es_ingest` | `from es.ingest import …` / `import es.ingest` |
| `from es_queries import …` / `import es_queries` (`as _eq` dahil) | `from es.queries import …` |
| `from es_transform import …` | `from es.transform import …` |
| `from dedup_auto_merge import …` | `from dedup.auto_merge import …` |
| `from dedup_reviewer import …` | `from dedup.reviewer import …` |
| `main_processor` içindeki taşınan fonksiyonlar | `from matching.pipeline import process_all_data` (vb.) |

`main_processor.py` (kök) yalnızca ince orkestratör olur:
```python
from matching.pipeline import process_all_data

if __name__ == "__main__":
    process_all_data()
```

## 5. Uygulama Sırası (davranış değişmeden)

1. Klasörleri + boş `__init__.py`'leri oluştur; dosyaları `git mv` ile taşı (git geçmişi korunur).
2. `main_processor.py`'yi 3 modüle böl (`matching/db_io.py`, `matching/es_writer.py`, `matching/pipeline.py`); kökte ince `main_processor.py` bırak.
3. İmport satırlarını Bölüm 4 haritasına göre güncelle (kaynak + test + analysis).
4. `utils/` boş klasörünü kaldır.
5. CLAUDE.md komut tablosunu + dosya yapısı tablosunu güncelle (`python -m es.manager`, `python -m es.ingest`; `python main_processor.py` aynı).

## 6. Doğrulama (Başarı Kriteri)

- İmport smoke testi: `python -c "import main_processor"`, `python -m es.manager`, `python -m es.ingest`.
- **`pytest -v`** — mevcut ~200+ test paketi yeşil kalmalı. Saf taşıma olduğu için davranış değişmemeli; testlerin geçmesi = başarı.

## 7. Kapsam Dışı (YAGNI)

- Katı installable paket (`pyproject.toml`, console_scripts entry points).
- Eşleştirme mantığı / Query DSL / analyzer / `synonyms_data/` değişiklikleri.
- Yeni özellik veya performans iyileştirmesi.
- `analysis/` ve `tests/` içindeki dosyaların yeniden gruplanması (sadece import yolları güncellenir).

## 8. Riskler

- **Döngüsel import (circular import):** `main_processor.py` bölünürken `pipeline` ↔ `es_writer` ↔ `db_io` arası bağımlılıklar dikkatle tek yöne akmalı (`pipeline` → `es_writer`/`db_io`; tersi olmamalı). Smoke test bunu erken yakalar.
- **Kaçırılan import:** Haritada olmayan dinamik/gizli import. `pytest` + `python -c "import ..."` ile kapsanır.
- **CLAUDE.md drift:** Komut değişikliği belgelenmezse karışıklık. Adım 5 bunu kapatır.
