# Plan 1 — Per-Country Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tek ortak ES index'ini (`living_companies_v2`) ülke-başına fiziksel index + alias yapısına (`living_companies_<cc>_v3` + alias `living_companies_<cc>`) taşımak; eşleştirme mantığını değiştirmeden.

**Architecture:** Her ülke kendi fiziksel index'ini alır; üstünde versiyonsuz alias. Tüm okuma/yazma alias üzerinden. Her index YALNIZCA o ülkenin + common + global-fallback analyzer'larını taşır (65× analyzer şişmesi biter). `_routing` kaldırılır (index zaten ülke). Geçersiz/bilinmeyen ülke kodu `EXCLUDED (invalid_country)` olur. **Analyzer adları `_cc` sonekiyle KALIR** (queries.py minimal değişir); generic-ad temizliği Plan 2'ye ertelenir. Eşleştirme alanları (`variations_stripped`) AYNEN korunur.

**Tech Stack:** Python 3.12, elasticsearch-py, psycopg2, pytest.

---

## Kapsam Dışı (Plan 2/3'e ait)
- Token sınıflandırma, `variations_core`, synonym yenileme, fonetik (Plan 2).
- Analyzer adlarını generic'e çevirme, `country_code` term filtresini kaldırma (Plan 2).
- `DIRTY_DATA` (Plan 3).

## Önkoşul
- `.venv\Scripts\python.exe` kullanılır (sistem python'ı değil).
- Testler: `\.venv\Scripts\python.exe -m pytest -v`.

---

## File Structure

| Dosya | Sorumluluk | Değişim |
| :--- | :--- | :--- |
| `config.py` | Index adı çözümleme | `index_for_country`, `alias_for_country`, `ES_ANALYZE_INDEX_OVERRIDE`; `ES_INDEX` kaldırılır (son task) |
| `es/manager.py` | Per-country index+alias+analyzer kurulumu | `build_index_settings(es, country_code)`, `create_index` ülke döngüsü, `_routing` kalkar, `acronym_glue_active(es, cc)` |
| `es/queries.py` | `_analyze` hedefi | `_analyze_index(country)` indirection; `_get_token_count` + `_has_distinctive_core` per-country index |
| `matching/es_writer.py` | Master-doc yazımı | `index=alias_for_country(cc)`, `routing` kalkar |
| `matching/pipeline.py` | Orkestrasyon | `msearch`/`refresh` per-country, `_routing` kalkar, DEFAULT reddi |
| `dedup/auto_merge.py` | Fingerprint dedup | per-country index iterasyonu, `routing` kalkar |
| `es/transform.py` | Continuous transform | kaynak index `living_companies_*` wildcard |
| `dedup/reviewer.py` | İnteraktif dedup | `country_code` ile per-country index |
| `analysis/es_verify.py` | Doğrulama aracı | `alias_for_country(country)` |
| `analysis/live_probe.py` | Offline probe | `ES_ANALYZE_INDEX_OVERRIDE` ile probe |
| `tests/*` | Testler | `ES_INDEX` patch'leri → alias tabanlı |
| `CLAUDE.md`, `README.md` | Dok. | per-country index notu |

---

## Task 1: config.py — Index adı çözümleyiciler

**Files:**
- Modify: `config.py` (66. satır civarı, `ES_INDEX` tanımı)
- Test: `tests/test_config.py`

- [ ] **Step 1: Failing test yaz**

`tests/test_config.py` sonuna ekle:

```python
def test_index_for_country_physical_name():
    from config import index_for_country
    assert index_for_country("tr") == "living_companies_tr_v3"
    assert index_for_country("MX") == "living_companies_mx_v3"


def test_alias_for_country_versionless():
    from config import alias_for_country
    assert alias_for_country("tr") == "living_companies_tr"
    assert alias_for_country("MX") == "living_companies_mx"


def test_analyze_index_override_default_none():
    import config
    assert config.ES_ANALYZE_INDEX_OVERRIDE is None
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_config.py -k "index_for_country or alias_for_country or analyze_index_override" -v`
Expected: FAIL — `ImportError: cannot import name 'index_for_country'`

- [ ] **Step 3: config.py'yi düzenle**

`config.py` içinde `ES_INDEX = "living_companies_v2"` satırını **KORU** (Task 9'a kadar
importer'lar kırılmasın diye deprecated olarak kalır) ve hemen ALTINA şunları EKLE:

```python
# --- Elasticsearch index isimlendirme (per-country) ---
# NOT: Yukarıdaki ES_INDEX deprecated; tüm importer'lar Task 9'da migrate edilince kaldırılır.
INDEX_PREFIX = "living_companies"
INDEX_VERSION = "v3"


def index_for_country(country_code: str) -> str:
    """Ülkenin FİZİKSEL ES index adı (oluşturma/silme için)."""
    return f"{INDEX_PREFIX}_{country_code.lower()}_{INDEX_VERSION}"


def alias_for_country(country_code: str) -> str:
    """Ülkenin alias adı (sorgu/yazım bunu kullanır; alias-swap ile reindex)."""
    return f"{INDEX_PREFIX}_{country_code.lower()}"


# _analyze hedef override'ı — yalnızca analysis/live_probe.py diagnostiği içindir.
# None ise normal alias_for_country(country) kullanılır.
ES_ANALYZE_INDEX_OVERRIDE = None
```

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_config.py -k "index_for_country or alias_for_country or analyze_index_override" -v`
Expected: PASS (3 test)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): per-country index/alias cozumleyicileri + analyze override"
```

---

## Task 2: es/manager.py — Per-country index + alias + tek-ülke analyzer

**Files:**
- Modify: `es/manager.py`
- Test: `tests/test_es_manager.py`

`build_index_settings` artık tek ülke için çalışır: yalnızca `common` + `global-fallback` + verilen ülkenin filter/analyzer'ları üretilir (65× döngü kalkar). `create_index` tüm ülkeler için fiziksel index + alias kurar. `_routing.required` kalkar.

- [ ] **Step 1: Failing test yaz**

`tests/test_es_manager.py` içindeki ÇOKLU-ülke testlerini tek-ülke imzasına göre GÜNCELLE ve yenilerini ekle. Şu testleri DEĞİŞTİR:

```python
def test_stripped_search_analyzer_global_fallback_exists():
    """build_index_settings(es, cc) global stripped_search_analyzer üretmeli."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    filters = settings["settings"]["analysis"]["filter"]
    assert "stripped_search_analyzer" in analyzers
    assert "generic_stopwords_global" in filters


def test_only_target_country_analyzer_built():
    """Tek-ülke settings YALNIZCA o ülkenin clean_analyzer'ını içermeli (65x sismez)."""
    from es.manager import build_index_settings
    from core.synonym_loader import get_all_country_codes
    settings = build_index_settings(es=None, country_code="TR")
    analyzers = settings["settings"]["analysis"]["analyzer"]
    assert "clean_analyzer_tr" in analyzers
    assert "clean_analyzer_common" in analyzers  # default + token_count
    # Başka ülkeler GELMEMELİ
    others = [c for c in get_all_country_codes() if c != "TR"][:3]
    for cc in others:
        assert f"clean_analyzer_{cc.lower()}" not in analyzers


def test_routing_not_required_in_mapping():
    """Per-country index'te _routing required OLMAMALI."""
    from es.manager import build_index_settings
    settings = build_index_settings(es=None, country_code="TR")
    assert "_routing" not in settings["mappings"]
```

`test_per_country_stripped_analyzers_exist` testini SİL (çoklu-ülke tek settings artık geçersiz).

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_manager.py -v`
Expected: FAIL — `build_index_settings()` `country_code` argümanı almıyor

- [ ] **Step 3: build_index_settings imzasını ve gövdesini düzenle**

`es/manager.py` başındaki import'a ekle (zaten çoğu var):

```python
from config import ES_HOST, alias_for_country, index_for_country
from core.synonym_loader import (
    get_all_company_type_tokens,
    get_all_country_codes,
    get_all_legal_suffix_fragments,
    get_article_stopwords,
    get_company_type_tokens,
    get_country_geo_stopwords,
    get_geo_stopword_tokens,
    load_synonyms_for_country,
)
```

`build_index_settings(es: Elasticsearch | None = None)` imzasını şu şekilde değiştir:

```python
def build_index_settings(es: Elasticsearch | None = None, country_code: str = "__common__") -> dict:
```

Fonksiyon içindeki **per-country DÖNGÜLERİNİ** (iki adet `for cc in get_all_country_codes():`) kaldır ve TEK ülke bloklarıyla değiştir. Stripped analyzer döngüsünü şununla DEĞİŞTİR:

```python
    # ── Verilen ülkenin Stripped Search Analyzer'ı (tek ülke) ──
    if country_code and country_code not in ("__common__", "__COMMON__"):
        cc = country_code.upper()
        cc_tokens = list(get_company_type_tokens(cc))
        article_tokens = list(get_article_stopwords(cc))
        filter_name = f"generic_stopwords_{cc.lower()}"
        geo_filter_name = f"geo_stopwords_{cc.lower()}"
        analyzer_name = f"stripped_search_analyzer_{cc.lower()}"
        filters[filter_name] = {"type": "stop", "stopwords": cc_tokens + article_tokens}
        filters[geo_filter_name] = {"type": "stop", "stopwords": sorted(get_country_geo_stopwords(cc))}
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            "filter": base_clean_filters + [filter_name, "legal_fragment_stop", geo_filter_name],
        }
```

Ülkeye özgü synonym analyzer döngüsünü (`for cc in get_all_country_codes(): ... clean_analyzer_{cc}`) şununla DEĞİŞTİR:

```python
    # ── Verilen ülkenin synonym analyzer'ı (tek ülke) ──
    if country_code and country_code not in ("__common__", "__COMMON__"):
        cc = country_code.upper()
        country_synonyms = list(load_synonyms_for_country(cc))
        filter_name = f"synonym_filter_{cc}"
        analyzer_name = f"clean_analyzer_{cc}"
        filters[filter_name] = {"type": "synonym_graph", "synonyms": country_synonyms, "lenient": True}
        analyzers[analyzer_name] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            "filter": base_clean_filters + [filter_name],
        }
```

`settings["mappings"]` içindeki `_routing` bloğunu KALDIR:

```python
        "mappings": {
            # NOT: _routing kaldırıldı — per-country index'te ülke izolasyonu fiziksel.
            "properties": {
```

- [ ] **Step 4: create_index'i per-country döngüye çevir**

`acronym_glue_active` ve `create_index` fonksiyonlarını şununla DEĞİŞTİR:

```python
def acronym_glue_active(es: Elasticsearch, country_code: str | None = None) -> bool | None:
    """Canlı index analyzer zincirinde acronym_glue ETKİN mi? (reindex doğrulaması)

    country_code verilmezse ilk bilinen ülke alias'ı kullanılır (şema tüm
    per-country index'lerde aynıdır). Dönüş: True/False/None (bkz. eski docstring)."""
    if country_code is None:
        codes = get_all_country_codes()
        if not codes:
            return None
        country_code = codes[0]
    target = alias_for_country(country_code)
    try:
        res = es.indices.analyze(index=target, body={"analyzer": "fingerprint_analyzer", "text": "K.W.M"})
        tokens = [t["token"] for t in res.get("tokens", [])]
    except Exception:
        return None
    if tokens == ["kwm"]:
        return True
    if len(tokens) > 1:
        return False
    return None


def _create_country_index(es: Elasticsearch, cc: str, force_recreate: bool) -> None:
    """Tek ülke için fiziksel index + alias oluşturur."""
    physical = index_for_country(cc)
    alias = alias_for_country(cc)
    if es.indices.exists(index=physical):
        if force_recreate:
            es.indices.delete(index=physical, ignore=[404])
            import time
            for _ in range(30):
                if not es.indices.exists(index=physical):
                    break
                time.sleep(1)
        else:
            return
    settings = build_index_settings(es, country_code=cc)
    settings["aliases"] = {alias: {}}
    es.options(request_timeout=120).indices.create(index=physical, body=settings)


def create_index(es: Elasticsearch, force_recreate: bool = False) -> None:
    """Tüm ülkeler için per-country fiziksel index + alias oluşturur."""
    codes = get_all_country_codes()
    print(f"{len(codes)} ulke icin per-country index olusturuluyor...")
    created = 0
    for cc in codes:
        before = es.indices.exists(index=index_for_country(cc))
        _create_country_index(es, cc, force_recreate)
        if force_recreate or not before:
            created += 1
    try:
        from es.queries import clear_token_count_cache
        clear_token_count_cache()
    except Exception:
        logger.warning("es_queries cache temizlenemedi — surec yeniden baslatilmali")
    features = ["synonym", "fingerprint", "ngram"]
    if _check_plugin_installed(es, "analysis-icu"):
        features.append("ICU")
    if _check_plugin_installed(es, "analysis-phonetic"):
        features.append("phonetic")
    print(f"{created} index olusturuldu/yenilendi, ozellikler: {', '.join(features)}")
```

`es/manager.py` en altındaki `from config import ES_HOST, ES_INDEX` satırından `ES_INDEX` zaten kaldırıldı (Step 3 import bloğu). `__main__` bloğu aynı kalır (`create_index(es, force_recreate=force)`).

- [ ] **Step 5: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_manager.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add es/manager.py tests/test_es_manager.py
git commit -m "feat(es): per-country index+alias kurulumu, tek-ulke analyzer, _routing kaldirildi"
```

---

## Task 3: es/queries.py — `_analyze` hedefini per-country yap

**Files:**
- Modify: `es/queries.py`
- Test: `tests/test_es_queries.py`

`_analyze` çağrıları `config.ES_INDEX` yerine `_analyze_index(country)` kullanır. `country_code` term filtresi ve `_get_analyzer` ülke-dallanması **AYNEN KALIR** (Plan 2'de temizlenecek).

- [ ] **Step 1: Failing test yaz**

`tests/test_es_queries.py` sonuna ekle:

```python
def test_analyze_index_uses_country_alias():
    from es.queries import _analyze_index
    assert _analyze_index("tr") == "living_companies_tr"


def test_analyze_index_respects_override(monkeypatch):
    import config
    monkeypatch.setattr(config, "ES_ANALYZE_INDEX_OVERRIDE", "probe_idx")
    from es.queries import _analyze_index
    assert _analyze_index("tr") == "probe_idx"
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_queries.py -k "analyze_index" -v`
Expected: FAIL — `cannot import name '_analyze_index'`

- [ ] **Step 3: queries.py'yi düzenle**

`es/queries.py` içine `clear_token_count_cache` fonksiyonunun ÜSTÜNE ekle:

```python
def _analyze_index(country: str) -> str:
    """`_analyze` çağrıları için hedef index: override varsa o, yoksa ülke alias'ı."""
    from config import ES_ANALYZE_INDEX_OVERRIDE, alias_for_country
    return ES_ANALYZE_INDEX_OVERRIDE or alias_for_country(country)
```

`_has_distinctive_core` içindeki şu satırları:

```python
        from config import ES_INDEX
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": analyzer, "text": name})
```
şununla DEĞİŞTİR:

```python
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": name})
```

`_get_token_count` imzasını `country` alacak şekilde değiştir:

```python
def _get_token_count(es: Elasticsearch, text: str, analyzer: str, country: str) -> int:
```
ve içindeki:

```python
        from config import ES_INDEX
        res = es.indices.analyze(index=ES_INDEX, body={"analyzer": analyzer, "text": text})
```
şununla DEĞİŞTİR:

```python
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": text})
```

TÜM `_get_token_count(es, ...)` çağrılarına `country` ekle:
- `CANONICAL_EXACT`: `_get_token_count(es, name, analyzer, country)`
- `STRIPPED_EXACT`: `_get_token_count(es, name, analyzer, country)`
- `_core_coverage_filter`: `_get_token_count(es, name, "stripped_search_analyzer", country)`
- `PHONETIC_MATCH`: `_get_token_count(es, name, _get_stripped_analyzer(country), country)`

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_queries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add es/queries.py tests/test_es_queries.py
git commit -m "feat(es): _analyze hedefi per-country alias (override destekli)"
```

---

## Task 4: matching/es_writer.py — Yazımları per-country index'e taşı

**Files:**
- Modify: `matching/es_writer.py`
- Test: `tests/test_main_processor.py` (es_writer testleri varsa)

- [ ] **Step 1: Failing test yaz**

`tests/test_main_processor.py` sonuna ekle:

```python
def test_index_new_master_uses_country_alias_no_routing():
    from unittest.mock import MagicMock
    from matching.es_writer import _index_new_master
    es = MagicMock()
    rec = {"raw_name": "ACME LTD", "country": "TR", "phone": "", "address": ""}
    _index_new_master(es, rec)
    _, kwargs = es.index.call_args
    assert kwargs["index"] == "living_companies_tr"
    assert "routing" not in kwargs
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_main_processor.py -k "index_new_master_uses_country" -v`
Expected: FAIL — index `living_companies_v2` veya routing var

- [ ] **Step 3: es_writer.py'yi düzenle**

Import satırını değiştir:

```python
from config import alias_for_country
from es.ingest import pipeline_name
```

`update_es_variations` içindeki iki `"_index": ES_INDEX, ... "routing": ...` bloğunu (variations + `_append_list_fields`) şu desene çevir — `_index` alias olur, `routing` SİLİNİR:

```python
                    "update": {
                        "_index": alias_for_country(info["country"]),
                        "_id": master_id,
                    }
```
ve `_append_list_fields` içinde:
```python
                    "update": {
                        "_index": alias_for_country(country),
                        "_id": master_id,
                    }
```
(`country = info["country"].upper()` zaten var; `alias_for_country` lower'a çevirir.)

`build_new_master_doc` içindeki doc'tan `_index`/`_routing`'i alias'a/temize çevir:
```python
    doc = {
        "_index": alias_for_country(country),
        "_id": master_id,
        "_source": {
            "master_id": master_id,
            "variations": [{"name": name}],
            "variations_stripped": [],
            "country_code": country.upper(),
        },
    }
```

`_index_new_master` içindeki iki `es.index(index=ES_INDEX, ..., routing=...)` çağrısını DEĞİŞTİR — `routing` kaldırılır:
```python
        es.index(
            index=alias_for_country(rec["country"]),
            id=master_id,
            body=doc,
            pipeline=pipeline_name(rec["country"]),
        )
```
ve except bloğundaki ikinci çağrı:
```python
        es.index(
            index=alias_for_country(rec["country"]),
            id=master_id,
            body=doc,
        )
```

`_add_variation_to_master` içindeki `es.get(index=ES_INDEX, id=master_doc_id, routing=cc)` ve `es.index(index=ES_INDEX, ..., routing=cc, ...)` çağrılarından `routing` kaldır, index'i `alias_for_country(cc)` yap:
```python
        doc = es.get(index=alias_for_country(cc), id=master_doc_id)
        ...
        es.index(
            index=alias_for_country(cc),
            id=master_doc_id,
            body=body,
            pipeline=pipe,
        )
```

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_main_processor.py -k "index_new_master_uses_country" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add matching/es_writer.py tests/test_main_processor.py
git commit -m "feat(es-writer): master-doc yazimi per-country alias, routing kaldirildi"
```

---

## Task 5: matching/pipeline.py — msearch/refresh per-country + DEFAULT reddi

**Files:**
- Modify: `matching/pipeline.py`
- Test: `tests/test_main_processor.py`

- [ ] **Step 1: Failing test yaz**

`tests/test_main_processor.py` sonuna ekle:

```python
def test_invalid_country_excluded_not_default():
    """Geçersiz ülke kodu DEFAULT'a düşmemeli; EXCLUDED(invalid_country) olmalı."""
    from matching.pipeline import _is_indexable_country
    assert _is_indexable_country("TR") is True
    assert _is_indexable_country("XX") is False   # bilinmeyen
    assert _is_indexable_country("DEFAULT") is False
    assert _is_indexable_country("1A") is False    # yapısal gecersiz
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_main_processor.py -k "invalid_country_excluded" -v`
Expected: FAIL — `cannot import name '_is_indexable_country'`

- [ ] **Step 3: pipeline.py'yi düzenle**

Import bloğunda `ES_INDEX`'i kaldır, ekle:

```python
from config import (
    BATCH_SIZE,
    COLUMN_MAPPING,
    alias_for_country,
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
from core.synonym_loader import get_all_country_codes
```

`logger = logging.getLogger(__name__)` altına ekle:

```python
_INDEXABLE_CC: set[str] | None = None


def _is_indexable_country(country: str) -> bool:
    """Ülke kodu geçerli (2 harf) VE bir index'i var mı (synonyms_data'da)?"""
    global _INDEXABLE_CC
    if _INDEXABLE_CC is None:
        _INDEXABLE_CC = set(get_all_country_codes())
    cc = (country or "").strip().upper()
    return len(cc) == 2 and cc.isalpha() and cc in _INDEXABLE_CC
```

`_execute_msearch` içindeki header'ı değiştir (routing kalkar):
```python
            query, country, _ = queries[idx]
            body.append({"index": alias_for_country(country)})
            body.append(query)
```

`_build_stage_body` içindeki header'ı değiştir:
```python
        body.append({"index": alias_for_country(rec["country"])})
        body.append(q)
```

`create_new_masters` içindeki NEW_MASTER doc'unda `_index`/`_routing`'i değiştir:
```python
                "_index": alias_for_country(rec["country"]),
                "_id": master_id,
                "pipeline": pipeline_name(rec["country"]),
                "_source": {
```
(`_routing` satırını SİL.)

`create_new_masters` içindeki `es.indices.refresh(index=ES_INDEX)` çağrısını şununla değiştir — yalnız bu chunk'taki ülkeleri refresh et:
```python
            for _cc in {d["_index"] for d in es_docs}:
                es.indices.refresh(index=_cc)
```

`process_all_data` içindeki üç `es.indices.refresh(index=ES_INDEX)` çağrısı: bu döngüler çoklu ülkeyi kapsayabilir. Her birini, o turda dokunulan ülkelerin alias'larını refresh edecek şekilde değiştir. Refresh'ten hemen önce işlenen kayıtların ülkelerini topla. En basit ve doğru yol: chunk/batch sonunda dokunulan ülke kümesini izleyip refresh et. `process_all_data` başında (pbar'dan sonra) ekle:
```python
        touched_ccs: set[str] = set()
```
Apply-pass içinde, her kaydın ülkesini ekle (winner VEYA new master sonrası, `pbar.update(1)`'dan önce):
```python
                        touched_ccs.add(alias_for_country(country))
```
Üç `es.indices.refresh(index=ES_INDEX)` çağrısının HER BİRİNİ şununla değiştir:
```python
                for _idx in touched_ccs:
                    es.indices.refresh(index=_idx)
                touched_ccs.clear()
```

`acronym_glue_active` çağrısı: `glue = acronym_glue_active(es)` AYNEN kalır (artık ilk ülke alias'ını probe eder).

DEFAULT reddi: parse-pass içindeki şu bloğu:
```python
                        country = (
                            (row[col_country] or "").strip().upper()
                            if col_country
                            else "DEFAULT"
                        )
                        if len(country) != 2 or not country.isalpha():
                            country = "DEFAULT"
                        raw_name = (row[col_name] or "").strip()
                        if not raw_name:
                            total_skipped += 1
                            pbar.update(1)
                            continue
```
şununla DEĞİŞTİR:
```python
                        country = (row[col_country] or "").strip().upper() if col_country else ""
                        raw_name = (row[col_name] or "").strip()
                        if not raw_name:
                            total_skipped += 1
                            pbar.update(1)
                            continue
                        # Geçersiz/bilinmeyen ülke → index'lenemez → EXCLUDED(invalid_country)
                        if not _is_indexable_country(country):
                            master_id = str(uuid.uuid4())
                            pg_updates.append(
                                _make_pg_update_tuple(
                                    master_id, 0, "EXCLUDED", "EXCLUDED: invalid_country", row_id
                                )
                            )
                            total_excluded += 1
                            total_processed += 1
                            pbar.update(1)
                            continue
```

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_main_processor.py -k "invalid_country_excluded" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add matching/pipeline.py tests/test_main_processor.py
git commit -m "feat(pipeline): msearch/refresh per-country alias, routing kaldirildi, DEFAULT reddi"
```

---

## Task 6: dedup/auto_merge.py — Per-country index iterasyonu

**Files:**
- Modify: `dedup/auto_merge.py`
- Test: `tests/test_dedup_auto_merge.py`

- [ ] **Step 1: Failing test yaz**

`tests/test_dedup_auto_merge.py` içindeki routing assertion'ını GÜNCELLE. Mevcut:
```python
        assert c.kwargs.get("routing") == "MX"
```
şununla DEĞİŞTİR (artık index alias, routing yok):
```python
        assert c.kwargs.get("routing") is None
        assert c.kwargs.get("index") == "living_companies_mx"
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dedup_auto_merge.py -v`
Expected: FAIL — routing hâlâ "MX"

- [ ] **Step 3: auto_merge.py'yi düzenle**

Import'u değiştir:
```python
from config import DB_CONFIG, alias_for_country, RAW_TABLE_NAME, COLUMN_MAPPING, DEDUP_MIN_FINGERPRINT_TOKEN_LEN, MatchType
from core.synonym_loader import get_all_country_codes
```

`_distinct_countries` fonksiyonunu SİL ve `iter_duplicate_groups` içinde kullanımını değiştir. `iter_duplicate_groups` içindeki:
```python
    for cc in (countries if countries is not None else _distinct_countries(es)):
```
şununla DEĞİŞTİR:
```python
    for cc in (countries if countries is not None else get_all_country_codes()):
```

`iter_duplicate_groups` içindeki `resp = es.search(index=ES_INDEX, body=body)` çağrısını şununla değiştir:
```python
            resp = es.search(index=alias_for_country(cc), body=body)
```
Bu sorgu artık tek ülke index'inde çalıştığından `{"term": {"country_code": cc}}` filtresi gereksiz ama ZARARSIZ — AYNEN bırak (Plan 2'de temizlenir).

`apply_merge` içindeki ES çağrılarından `routing` kaldır, index alias yap:
```python
        for sec_id in secondaries:
            sec = es.get(index=alias_for_country(cc), id=sec_id)["_source"]
            es.update(
                index=alias_for_country(cc), id=primary,
                body={"script": {
                    "source": _MERGE_SCRIPT,
                    "params": {
                        "new_vars": sec.get("variations", []),
                        "new_stripped": sec.get("variations_stripped", []),
                    },
                }},
            )
            es.delete(index=alias_for_country(cc), id=sec_id)
```

`auto_merge_duplicates` sonundaki global refresh'i ülke-başına yap:
```python
    if refresh and not dry_run:
        for cc in (countries if countries is not None else get_all_country_codes()):
            try:
                es.indices.refresh(index=alias_for_country(cc))
            except Exception:
                pass
```

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dedup_auto_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dedup/auto_merge.py tests/test_dedup_auto_merge.py
git commit -m "feat(dedup): auto_merge per-country index iterasyonu, routing kaldirildi"
```

---

## Task 7: es/transform.py — Kaynak index wildcard

**Files:**
- Modify: `es/transform.py`
- Test: `tests/test_es_transform.py` (yoksa oluştur)

Transform tüm ülke index'lerini kapsamalı; `country_code` ile zaten grupluyor. Kaynak `living_companies_*` wildcard yapılır (DEST `potential_duplicates` bu desene uymaz).

- [ ] **Step 1: Failing test yaz**

`tests/test_es_transform.py` oluştur:

```python
from unittest.mock import MagicMock
from es.transform import create_dedup_transform, TRANSFORM_ID


def test_transform_source_is_wildcard():
    es = MagicMock()
    es.indices.exists.return_value = True
    es.transform.get_transform.side_effect = Exception("yok")
    create_dedup_transform(es)
    _, kwargs = es.transform.put_transform.call_args
    src = kwargs["body"]["source"]["index"]
    assert src == ["living_companies_*"]
```

- [ ] **Step 2: Testi çalıştır, FAIL gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_transform.py -v`
Expected: FAIL — kaynak `["living_companies_v2"]`

- [ ] **Step 3: transform.py'yi düzenle**

Import'tan `ES_INDEX`'i kaldır:
```python
from config import INDEX_PREFIX
```
`transform_body` içindeki `"source": {"index": [ES_INDEX]}` satırını DEĞİŞTİR:
```python
        "source": {
            "index": [f"{INDEX_PREFIX}_*"],
        },
```

- [ ] **Step 4: Testi çalıştır, PASS gör**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_es_transform.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add es/transform.py tests/test_es_transform.py
git commit -m "feat(transform): kaynak index living_companies_* wildcard (tum ulkeler)"
```

---

## Task 8: reviewer.py + analysis/* — Per-country index uyarlaması

**Files:**
- Modify: `dedup/reviewer.py`, `analysis/es_verify.py`, `analysis/live_probe.py`
- Test: manuel (interaktif/diagnostik araçlar)

- [ ] **Step 1: reviewer.py — country ile index seç**

Import'tan `ES_INDEX`'i kaldır:
```python
from config import alias_for_country
```
`review_duplicates` içindeki `es.get(index=ES_INDEX, id=mid)` çağrısını, grubun ülkesini kullanacak şekilde değiştir (`cc = dup["country_code"]` zaten mevcut döngüde erişilebilir):
```python
                    doc = es.get(index=alias_for_country(dup["country_code"]), id=mid)
```
`_merge_masters` imzasına `country` ekle ve çağrısını güncelle:
```python
def _merge_masters(es: Elasticsearch, primary_id: str, secondary_ids: list[str], country: str) -> None:
```
İçindeki `es.get/update/delete(index=ES_INDEX, ...)` çağrılarını `index=alias_for_country(country)` yap. Çağrı yerini güncelle:
```python
                _merge_masters(es, primary, secondaries, dup["country_code"])
```

- [ ] **Step 2: analysis/es_verify.py — alias kullan**

Import'u değiştir:
```python
from config import alias_for_country
```
`es.search(index=ES_INDEX, body=body, routing=country.upper())` çağrısını DEĞİŞTİR:
```python
    resp = es.search(index=alias_for_country(country), body=body)
```

- [ ] **Step 3: analysis/live_probe.py — override ile probe**

`live_probe.py` artık `config.ES_INDEX`'i swap edemez (kaldırıldı). Bunun yerine `ES_ANALYZE_INDEX_OVERRIDE` kullanılır ve probe index'i alias-bağımsız olur. Şu bloğu:
```python
    original_index = config.ES_INDEX
    config.ES_INDEX = PROBE_INDEX
    try:
        ...
    finally:
        config.ES_INDEX = original_index
```
şununla DEĞİŞTİR:
```python
    original_override = config.ES_ANALYZE_INDEX_OVERRIDE
    config.ES_ANALYZE_INDEX_OVERRIDE = PROBE_INDEX
    try:
        ...
    finally:
        config.ES_ANALYZE_INDEX_OVERRIDE = original_override
```
Ayrıca probe index'e indeksleme/sorgu yapan `es.index(index=PROBE_INDEX, ..., routing=COUNTRY)` ve `es.search(index=PROBE_INDEX, ..., routing=COUNTRY)` çağrılarındaki `routing=COUNTRY` argümanlarını KALDIR (PROBE_INDEX tek-ülke probe; `build_index_settings`'e `country_code=COUNTRY` geçilmeli):
```python
    es.indices.create(index=PROBE_INDEX, body=build_index_settings(es, country_code=COUNTRY))
```

- [ ] **Step 4: Smoke import testi**

Run: `\.venv\Scripts\python.exe -c "import dedup.reviewer, analysis.es_verify, analysis.live_probe; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add dedup/reviewer.py analysis/es_verify.py analysis/live_probe.py
git commit -m "feat: reviewer + analysis araclari per-country index/alias + analyze override"
```

---

## Task 9: ES_INDEX patch'lerini temizle + tam test suite

**Files:**
- Modify: `tests/test_main_processor.py` (9 adet `patch.object(..., "ES_INDEX", ...)`)
- Test: tüm suite

`ES_INDEX` artık yok; ona bağlı `patch.object(mp, "ES_INDEX", "test_index")` / `patch.object(pipeline, "ES_INDEX", "test_index")` patch'leri `AttributeError` verir.

- [ ] **Step 1: Tam suite çalıştır, kırılanları gör**

Run: `\.venv\Scripts\python.exe -m pytest -v`
Expected: `ES_INDEX` patch'li testler FAIL (AttributeError) + ES_INDEX import eden başka kırıklar.

- [ ] **Step 2: config.py'den ES_INDEX'i kaldır + test patch'lerini temizle**

Artık hiçbir üretim modülü `ES_INDEX` kullanmıyor (Task 2-8 migrate etti). `config.py`'deki
deprecated `ES_INDEX = "living_companies_v2"` satırını SİL.

`tests/test_main_processor.py` içindeki HER `patch.object(mp, "ES_INDEX", "test_index"),` ve `patch.object(pipeline, "ES_INDEX", "test_index"),` satırını SİL. Bu testler `es` client'ı mock'ladığından gerçek index adı önemsizdir; testte index adına dair bir assertion varsa (`"test_index"` bekleyen) onu ilgili ülkenin alias'ına (`living_companies_<cc>`) göre güncelle. Her testin kullandığı ülke koduna bak (genelde mock rec'lerde `country`), assertion'ı `alias_for_country(cc)` beklentisine çevir.

Worked example — bir test şuna benziyorsa:
```python
with patch.object(mp, "ES_INDEX", "test_index"), patch(...):
    ...
    es.index.assert_called_with(index="test_index", ...)
```
şuna çevir:
```python
with patch(...):
    ...
    assert es.index.call_args.kwargs["index"] == "living_companies_mx"  # rec country=MX
```

- [ ] **Step 3: Grep ile artık ES_INDEX kalmadığını doğrula**

Run: `\.venv\Scripts\python.exe -m pytest -v` ve ayrıca kod tabanında `ES_INDEX` araması yap (docs/qa-artifacts hariç hiçbir `.py` kalmamalı).
Expected: Üretim `.py` dosyalarında `ES_INDEX` referansı YOK; tüm testler PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: ES_INDEX patch'leri kaldirildi, per-country alias assertion'lari"
```

---

## Task 10: Dokümantasyon + entegrasyon smoke

**Files:**
- Modify: `CLAUDE.md`, `README.md`
- Test: canlı ES'e karşı manuel smoke (opsiyonel, ES varsa)

- [ ] **Step 1: CLAUDE.md güncelle**

CLAUDE.md §2 tablosundaki `es/manager.py` satırına ve §1 kurallarına per-country index notu ekle:
```
> [!IMPORTANT]
> **PER-COUNTRY INDEX**: Her ülke kendi fiziksel index'ine (`living_companies_<cc>_v3`) sahiptir,
> üstünde alias `living_companies_<cc>`. Tüm okuma/yazma alias üzerinden; `_routing` KULLANILMAZ
> (ülke izolasyonu fizikseldir). Geçersiz/bilinmeyen ülke kodu EXCLUDED(invalid_country) olur.
```
§3 çalıştırma komutlarındaki index açıklamasını güncelle (eski tek-index ifadelerini per-country'e çevir).

- [ ] **Step 2: README.md güncelle**

README'deki `living_companies_v2` / tek-index ve `routing` ifadelerini per-country + alias açıklamasıyla değiştir.

- [ ] **Step 3: (Opsiyonel, ES varsa) Entegrasyon smoke**

```bash
\.venv\Scripts\python.exe -m es.ingest
\.venv\Scripts\python.exe -m es.manager --force
\.venv\Scripts\python.exe -c "from es.manager import get_es_client; from config import alias_for_country; es=get_es_client(); print(es.indices.exists(index=alias_for_country('tr')))"
```
Expected: `True` (TR alias mevcut). Birkaç kaydı `main_processor.py` ile işleyip PG'de master_code dolduğunu doğrula.

- [ ] **Step 4: Final commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: per-country index + alias mimarisi (Plan 1)"
```

---

## Self-Review Notları (yazar kontrolü)

- **Spec kapsamı (Madde 1):** per-country index ✓ (Task 2), alias+versiyon ✓ (Task 1/2), routing kaldırma ✓ (Task 2/4/5/6), DEFAULT reddi ✓ (Task 5), tüm tooling per-country ✓ (Task 6/7/8).
- **Ertelenenler (bilinçli):** analyzer generic-ad + `country_code` filtre temizliği → Plan 2; `variations_stripped` adı korunur → Plan 2.
- **Tip tutarlılığı:** `index_for_country` (fiziksel) vs `alias_for_country` (sorgu/yazım) ayrımı tüm task'larda tutarlı; `_get_token_count(es, text, analyzer, country)` imzası tüm çağrılarda güncellendi.
- **Migrasyon:** Plan sonunda `python -m es.manager --force` ile tüm ülke index'leri kurulur; tam rematch gerekir (eski `living_companies_v2` manuel silinmeli: `es.indices.delete(index="living_companies_v2")`).
