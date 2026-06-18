# Plan 4 — Stripping'i Kaldır (Synonym-Kanonik Tam Form Eşleşme) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest pipeline'ın token-SİLME davranışını (`variations_stripped` / `variations_suffix`) tamamen kaldırmak; tüm eşleşmeyi synonym-kanonikleştirilmiş TAM isim (`variations[].name`) üzerinden yapmak. Silme, ayırt edici token'ların yanlışlıkla atılıp farklı firmaları birleştirmesine (Round 8 kök-neden) yol açıyordu; synonym sözlüğü token'ları siler değil KANONİKLEŞTİRİR.

**Architecture:** Index başına tek ülke (Plan 1). `variations[].name` = synonym-kanonik tam form (clean_analyzer + synonym_graph). Eşleşme stage'leri: `CANONICAL_EXACT`, `FUZZY_PHRASE`, `TOKEN_COVERAGE` — hepsi `variations[].name` üzerinde. Gate'ler (distinctive-core, coverage) artık silme-analyzer'ı yerine **synonym-sınıf üyeliği** (legal∪article∪geo∪sector) + `variations.name.token_count` kullanır. Fingerprint dedup `variations.name.fingerprint`'e taşınır. `variations_stripped`/`variations_suffix` ve ilgili analyzer/filtre/stage tamamen silinir.

**Davranış sonucu (kabul edilen):** `ACME LIMITED`↔`ACME LTD` yine eşleşir (synonym); `ACME LTD`≠`ACME SA`, `ACME LTD`≠`ACME`, `ACME MEXICO`≠`ACME` (precision↑, recall↓).

**Tech Stack:** Python 3.12, Elasticsearch (per-country index), Painless ingest, psycopg2, pytest.

---

## KISITLAR (bu branch'e özel)
- **HİÇBİR TEST KOŞULMAZ** (kullanıcı talebi). Doğrulama: `.venv\Scripts\python.exe -m py_compile <dosya>` + `python -c "import ..."` (sanity, pytest DEĞİL). Testler YAZILIR ama KOŞULMAZ.
- **MEVCUT KODU YENİDEN BİÇİMLENDİRME.** Cerrahi Edit'ler; testleri dosya SONUNA ekle.
- **Reindex zorunlu** (mapping + ingest değişir). Bu plan reindex YAPMAZ; kod değişikliğinden ibaret.

## Bağlam (önceki planlar)
- Plan 1: per-country index + alias; `_analyze_index(country)`.
- Plan 2a: `canonicalize_phonetic` → `variations[].name`'e yazılır (artık BİRİNCİL alan; uyumlu kalır).
- Plan 3: `is_address_dirty` (şu an stripped analyzer kullanıyor → bu planda clean_analyzer + jenerik-üyeliğe taşınır).

## Kapsam Dışı
- Synonym içerik yenileme (ayrı), diğer ülke SA-taraması.

---

## File Structure & Sorumluluk

| Dosya | Değişim |
| :--- | :--- |
| `core/synonym_loader.py` | `get_generic_tokens(cc)` = legal∪article∪geo∪sector (gate distinctiveness) |
| `es/ingest.py` | pipeline'dan `stripped_form` + `suffix_form` processor'ları çıkar; yalnız `light_clean` |
| `es/manager.py` | mapping: `variations.name` → `fingerprint` alt-alan + per-country `token_count`; `variations_stripped`/`variations_suffix` ve `stripped_search_analyzer*`/`generic_stopwords*`/`geo_stopwords*` sil |
| `config.py` | STAGES: yalnız CANONICAL_EXACT/FUZZY_PHRASE/TOKEN_COVERAGE |
| `es/queries.py` | gate'ler + token_count + coverage + is_address_dirty → clean_analyzer + jenerik-üyelik; stripped/suffix/phonetic/ngram fonksiyonları sil |
| `dedup/auto_merge.py`, `es/transform.py` | fingerprint alanı `variations.name.fingerprint`, nested path `variations` |
| `matching/es_writer.py`, `matching/pipeline.py` | yeni-master doc'tan `variations_stripped:[]` çıkar |
| `tests/*`, `CLAUDE.md` | güncelle |

---

## Task 1: synonym_loader — get_generic_tokens

**Files:** Modify `core/synonym_loader.py`; Test `tests/test_synonym_loader.py`

- [ ] **Step 1: test yaz (KOŞMA)**
```python
def test_get_generic_tokens_union_excludes_brand():
    from core.synonym_loader import get_generic_tokens
    g = get_generic_tokens("TR")
    assert "ltd" in g          # legal
    assert "trading" in g      # sector
    assert "the" in g          # article
    assert "apex" not in g     # marka jenerik degil
```

- [ ] **Step 2: fonksiyon ekle**
`core/synonym_loader.py`'a, `get_business_sector_tokens` ALTINA ekle (mevcut loader'ları birleştirir):
```python
@lru_cache(maxsize=None)
def get_generic_tokens(country_code: str) -> frozenset:
    """Gate 'ayırt edicilik' için jenerik token kümesi: legal ∪ article ∪ geo ∪ sector.

    Bu kümeye GİRMEYEN token 'ayırt edici çekirdek' sayılır. address DAHİL DEĞİL
    (o DIRTY_DATA için ayrı). Tamamen JSON'dan türetilir.
    """
    cc = country_code.upper()
    return (
        get_legal_suffix_tokens(cc)
        | get_article_stopwords(cc)
        | get_country_geo_stopwords(cc)
        | get_business_sector_tokens(cc)
    )
```

- [ ] **Step 3: py_compile + sanity + commit**
Run: `.venv\Scripts\python.exe -m py_compile core/synonym_loader.py`
Run: `.venv\Scripts\python.exe -c "from core.synonym_loader import get_generic_tokens as g; t=g('TR'); print('ltd' in t,'trading' in t,'the' in t,'apex' not in t)"` → `True True True True`
```
git add core/synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat(synonym): get_generic_tokens (legal+article+geo+sector birlesimi) gate icin"
```

---

## Task 2: es/ingest.py — stripping processor'larını kaldır

**Files:** Modify `es/ingest.py`; Test `tests/test_es_ingest.py`

- [ ] **Step 1: test güncelle (KOŞMA)**
`tests/test_es_ingest.py` içinde `variations_stripped`/`variations_suffix` üreten processor'ları bekleyen testleri bul. Pipeline'ın artık YALNIZ `light_clean` processor'ı içerdiğini doğrulayan teste çevir (varsa stripped/suffix bekleyen assertion'ları sil), ve şu testi ekle:
```python
def test_pipeline_only_has_light_clean_processor():
    from es.ingest import build_pipeline_body
    body = build_pipeline_body("TR")
    descs = [list(p.values())[0].get("description", "") for p in body["processors"]]
    assert any("light_clean" in d for d in descs)
    assert not any("stripped" in d for d in descs)
    assert not any("suffix" in d for d in descs)
    assert len(body["processors"]) == 1
```

- [ ] **Step 2: build_pipeline_body'yi sadeleştir**
`es/ingest.py` `build_pipeline_body` fonksiyonunu ŞUNUNLA değiştir (yalnız light_clean):
```python
def build_pipeline_body(country_code: str) -> dict:
    """Ülkeye özgü ingest pipeline tanım sözlüğünü oluşturur (yalnız light_clean).

    NOT: stripped/suffix SİLME processor'ları kaldırıldı (Plan 4). Eşleşme artık
    synonym-kanonik tam form (variations[].name) üzerinden; token silinmez.
    """
    return {
        "description": f"Firma ismi temizleme pipeline'i ({country_code.upper()})",
        "processors": [
            {
                "script": {
                    "description": f"light_clean for {country_code.upper()}",
                    "source": _build_clean_script(country_code),
                }
            },
        ],
    }
```
Ardından kullanılmayan `_build_stripped_script` ve `_build_suffix_script` fonksiyonlarını SİL (ve artık gereksizse ilgili import'ları: `get_country_geo_stopwords`, `get_article_stopwords` — yalnız bu iki fonksiyon kullanıyorsa kaldır; `get_legal_suffix_tokens` `build_pipeline_body`'de artık kullanılmıyorsa onu da kaldır). Import temizliğini py_compile + bir grep ile doğrula.

- [ ] **Step 3: py_compile + commit**
Run: `.venv\Scripts\python.exe -m py_compile es/ingest.py`
Run: `.venv\Scripts\python.exe -c "from es.ingest import build_pipeline_body as b; print(len(b('TR')['processors']))"` → `1`
```
git add es/ingest.py tests/test_es_ingest.py
git commit -m "feat(ingest): token-silme (stripped/suffix) processor'lari kaldirildi, yalniz light_clean"
```

---

## Task 3: es/manager.py — mapping & analyzer sadeleştirme

**Files:** Modify `es/manager.py`; Test `tests/test_es_manager.py`

`variations.name`'e `fingerprint` alt-alanı eklenir ve `token_count` analyzer'ı per-country clean_analyzer olur. `variations_stripped`/`variations_suffix` nested/alan tanımları ve `stripped_search_analyzer*`, `generic_stopwords_{cc}`, `geo_stopwords_{cc}`, global geo/generic stop filtreleri kaldırılır. `clean_analyzer_*`, `fingerprint_analyzer`, `legal_fragment_stop`, ngram/phonetic (varsa, ama stage yoksa da zararsız — bu planda KALDIR) yönetilir.

- [ ] **Step 1: test güncelle (KOŞMA)**
`tests/test_es_manager.py`'da `variations_stripped` / `stripped_search_analyzer` / `generic_stopwords` bekleyen testleri SİL veya tersine çevir. Ekle:
```python
def test_variations_name_has_fingerprint_and_token_count():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    vfields = s["mappings"]["properties"]["variations"]["properties"]["name"]["fields"]
    assert "fingerprint" in vfields
    assert "token_count" in vfields


def test_no_variations_stripped_field():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    props = s["mappings"]["properties"]
    assert "variations_stripped" not in props
    assert "variations_suffix" not in props


def test_no_stripped_search_analyzer():
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="TR")
    analyzers = s["settings"]["analysis"]["analyzer"]
    assert "stripped_search_analyzer" not in analyzers
    assert "stripped_search_analyzer_tr" not in analyzers
```

- [ ] **Step 2: build_index_settings'i düzenle**
`es/manager.py` `build_index_settings` içinde:
  1. Stripped/geo per-country bloğunu (filter `generic_stopwords_{cc}`, `geo_stopwords_{cc}`, analyzer `stripped_search_analyzer_{cc}`) ve global fallback `stripped_search_analyzer` + `generic_stopwords_global` + `geo_stopwords_global` tanımlarını **SİL**.
  2. `fingerprint_analyzer` KALIR (legal_fragment_stop + fingerprint_token_filter); artık `variations.name.fingerprint` için kullanılacak. `generic_stopwords_global` referansını fingerprint_analyzer filtresinden çıkar (silindi) — yerine sadece `legal_fragment_stop` + `fingerprint_token_filter` bırak (base_clean_filters + bunlar).
  3. `variations_fields` (variations.name alt-alanları) sözlüğüne ekle:
     - `token_count` analyzer'ını per-country yap: `clean_analyzer_{cc}` (cc=country_code.upper()); `__common__` ise `clean_analyzer_common`.
     - `fingerprint` alt-alanı ekle: `{"type": "text", "analyzer": "fingerprint_analyzer", "fielddata": True}`.
  4. `mappings.properties`'ten `variations_stripped` ve `variations_suffix` nested/alan tanımlarını **SİL**.
  5. ngram/phonetic analyzer ve `variations_fields`'daki `ngram`/`phonetic`/`unidecode` alt-alanları: stage'leri kalktığı için KALDIR (sadeleştir). `icu_analyzer` clean için gerekiyorsa kalsın; değilse kaldır.

Token_count analyzer per-country örnek:
```python
    tc_analyzer = (
        f"clean_analyzer_{country_code.upper()}"
        if country_code and country_code not in ("__common__", "__COMMON__")
        else "clean_analyzer_common"
    )
    variations_fields = {
        "keyword": {"type": "keyword", "ignore_above": 512},
        "token_count": {
            "type": "token_count",
            "analyzer": tc_analyzer,
            "enable_position_increments": False,
        },
        "fingerprint": {"type": "text", "analyzer": "fingerprint_analyzer", "fielddata": True},
    }
```

- [ ] **Step 3: py_compile + sanity + commit**
Run: `.venv\Scripts\python.exe -m py_compile es/manager.py`
Run: `.venv\Scripts\python.exe -c "from es.manager import build_index_settings as b; s=b(None,'TR'); p=s['mappings']['properties']; print('variations_stripped' in p, 'fingerprint' in p['variations']['properties']['name']['fields'])"` → `False True`
```
git add es/manager.py tests/test_es_manager.py
git commit -m "feat(es): mapping sadelestirme - variations.name fingerprint+per-country token_count, stripped alan/analyzer kaldirildi"
```

---

## Task 4: config.py — STAGES sadeleştir

**Files:** Modify `config.py`; Test `tests/test_config.py`

- [ ] **Step 1: test yaz (KOŞMA)**
```python
def test_stages_only_canonical_fuzzy_coverage():
    from config import STAGES
    names = {s["name"] for s in STAGES}
    assert names == {"CANONICAL_EXACT", "FUZZY_PHRASE", "TOKEN_COVERAGE"}
```

- [ ] **Step 2: STAGES listesini düzenle**
`config.py` `STAGES` listesinden `STRIPPED_EXACT`, `SUFFIX_FUZZY`, `PHONETIC_MATCH`, `NGRAM_MATCH` dict'lerini **SİL**. Yalnız `CANONICAL_EXACT`, `FUZZY_PHRASE`, `TOKEN_COVERAGE` kalsın (order alanlarını 1,2,3 olarak yeniden numarala). `SUFFIX_FUZZY_SCORE` ve ilgili `MatchType` etiketleri (STRIPPED_EXACT/SUFFIX_FUZZY/PHONETIC_MATCH/NGRAM_MATCH) `MatchType` sınıfında KALABİLİR (geçmiş PG verisi için zararsız) — silme.

- [ ] **Step 3: py_compile + commit**
Run: `.venv\Scripts\python.exe -m py_compile config.py`
```
git add config.py tests/test_config.py
git commit -m "feat(config): STAGES sadelestirme - yalniz CANONICAL_EXACT/FUZZY_PHRASE/TOKEN_COVERAGE"
```

---

## Task 5: es/queries.py — gate'ler + stage'ler clean_analyzer'a

**Files:** Modify `es/queries.py`; Test `tests/test_es_queries.py`

- [ ] **Step 1: test güncelle (KOŞMA)**
Stripped-bazlı stage testlerini (STRIPPED_EXACT/SUFFIX_FUZZY/PHONETIC/NGRAM) SİL. Ekle:
```python
def test_distinctive_core_uses_clean_analyzer(monkeypatch):
    import es.queries as q
    from unittest.mock import MagicMock
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "ltd."}]}  # yalniz jenerik
    # 'ltd.' jenerik (legal) → ayirt edici cekirdek YOK
    assert q._has_distinctive_core(es, "acme ltd", "TR", require_alpha=True) is False
```
(NOT: gerçek 'apex ltd' canlı analyzer'da 'apex' üretir → True; mock ile jenerik-only False doğrulanır.)

- [ ] **Step 2: gate'leri repoint et**
`es/queries.py`:
  1. `_get_stripped_analyzer` fonksiyonunu SİL; yerine kullanılan her yerde `_get_analyzer(country)` (clean) kullan.
  2. `_has_distinctive_core`: `_analyze` analyzer'ı `_get_analyzer(country)` (clean) olsun; jenerik kontrolü `get_business_sector_tokens` yerine `get_generic_tokens(country)` (legal∪article∪geo∪sector) kullansın — yani "ayırt edici" = token NOT in generic AND len≥MIN AND (require_alpha→alpha). Import'a `get_generic_tokens` ekle.
  3. `_get_token_count`: değişiklik yok (analyzer parametre olarak gelir) — çağrı yerlerinde clean analyzer geçilecek.
  4. `_core_coverage_filter`: artık `variations.name.token_count` üzerinden çalışsın (stripped yerine). Token sayısı `_get_token_count(es, name, _get_analyzer(country), country)` ile; nested path `variations`, alan `variations.name.token_count`.
  5. `CANONICAL_EXACT`: değişmez (zaten clean + variations + token_count).
  6. `FUZZY_PHRASE` ve `TOKEN_COVERAGE`: zaten `variations` + clean kullanıyor; `_core_coverage_filter` çağrısı artık variations token_count'a göre.
  7. `STRIPPED_EXACT`, `SUFFIX_FUZZY`, `PHONETIC_MATCH`, `NGRAM_MATCH` fonksiyonlarını **SİL**.
  8. `is_address_dirty`: analyzer'ı `_get_analyzer(country)` (clean) yap; tokens artık synonym-kanonik tam form (legal/geo dahil). Address kontrolü aynı (`get_address_tokens`); distinctiveness kontrolü `get_generic_tokens`'a göre — yani "address dışı ayırt edici" = token NOT in (address ∪ generic) AND len≥MIN AND alpha. `generic = get_generic_tokens(country)` kullan (önceki `get_business_sector_tokens` yerine — artık legal/geo de jenerik sayılır, doğru).

- [ ] **Step 3: py_compile + sanity + commit**
Run: `.venv\Scripts\python.exe -m py_compile es/queries.py`
Run: `.venv\Scripts\python.exe -c "import es.queries as q; print(hasattr(q,'STRIPPED_EXACT'), hasattr(q,'_get_stripped_analyzer'))"` → `False False`
```
git add es/queries.py tests/test_es_queries.py
git commit -m "feat(es): gate'ler+coverage+is_address_dirty clean_analyzer'a; stripped/suffix/phonetic/ngram stage fonksiyonlari silindi"
```

---

## Task 6: dedup/auto_merge.py + es/transform.py — fingerprint alanı

**Files:** Modify `dedup/auto_merge.py`, `es/transform.py`; Test `tests/test_dedup_auto_merge.py`

- [ ] **Step 1: test (KOŞMA)** — `tests/test_dedup_auto_merge.py`'da fingerprint alan adına dair assertion varsa güncelle; yoksa ekle:
```python
def test_fingerprint_field_is_variations_name():
    import dedup.auto_merge as a
    assert a._FINGERPRINT_FIELD == "variations.name.fingerprint"
    assert a._FINGERPRINT_NESTED_PATH == "variations"
```

- [ ] **Step 2: auto_merge.py**
`_FINGERPRINT_FIELD = "variations_stripped.name.fingerprint"` → `"variations.name.fingerprint"`.
`_FINGERPRINT_NESTED_PATH = "variations_stripped"` → `"variations"`.
`_MERGE_SCRIPT` içinde `variations_stripped` referanslarını kaldır (yalnız `variations` birleştir):
```python
_MERGE_SCRIPT = """
for (v in params.new_vars) { if (!ctx._source.variations.contains(v)) { ctx._source.variations.add(v); } }
"""
```
`apply_merge` içindeki `"new_stripped": sec.get("variations_stripped", [])` parametresini ve script'teki kullanımını SİL.

- [ ] **Step 3: transform.py**
`create_dedup_transform` içinde `group_by.fingerprint.terms.field` = `"variations_stripped.name.fingerprint"` → `"variations.name.fingerprint"`.

- [ ] **Step 4: py_compile + commit**
Run: `.venv\Scripts\python.exe -m py_compile dedup/auto_merge.py es/transform.py`
```
git add dedup/auto_merge.py es/transform.py tests/test_dedup_auto_merge.py
git commit -m "feat(dedup): fingerprint variations.name.fingerprint'e tasindi (stripped kalkti)"
```

---

## Task 7: es_writer + pipeline — yeni-master doc'tan variations_stripped çıkar

**Files:** Modify `matching/es_writer.py`, `matching/pipeline.py`

- [ ] **Step 1: es_writer.py** — `_index_new_master` ve `build_new_master_doc` doc'larından `"variations_stripped": []` satırını SİL. `_add_variation_to_master`'da `body["variations_stripped"] = ...` ve `body["variations_suffix"] = ...` satırlarını SİL (sadece variations güncellenir).

- [ ] **Step 2: pipeline.py** — `create_new_masters` içindeki NEW_MASTER doc `_source`'undan `"variations_stripped": []` satırını SİL.

- [ ] **Step 3: py_compile + sanity + commit**
Run: `.venv\Scripts\python.exe -m py_compile matching/es_writer.py matching/pipeline.py`
Run: `.venv\Scripts\python.exe -c "import matching.es_writer, matching.pipeline; print('ok')"` → `ok`
```
git add matching/es_writer.py matching/pipeline.py
git commit -m "feat(matching): yeni-master doc'tan variations_stripped kaldirildi"
```

---

## Task 8: Dokümantasyon

**Files:** Modify `CLAUDE.md`, `README.md`

- [ ] **Step 1: CLAUDE.md** — token-silme yerine synonym-kanonik tam form eşleşmesini anlat; `variations_stripped` referanslarını güncelle; §1'e not:
```
> [!IMPORTANT]
> **TOKEN SİLİNMEZ — synonym KANONİKLEŞTİRİR:** Eşleşme synonym-kanonik tam isim
> (variations[].name) üzerinden yapılır. legal/article/geo/sector token'ları SİLİNMEZ;
> synonym_graph onları kanonik forma çevirir. Silme (eski variations_stripped) ayırt edici
> token'ları atıp yanlış birleştirme ürettiği için kaldırıldı (Plan 4). Gate'ler 'ayırt edici
> çekirdek'i synonym-sınıf üyeliğiyle (get_generic_tokens) belirler. Sonuç: ACME LTD≠ACME SA,
> ACME LTD≠ACME (precision-öncelikli).
```
- [ ] **Step 2: README.md** — `variations_stripped`/stripped-analyzer/STRIPPED_EXACT ifadelerini güncelle.
- [ ] **Step 3: commit**
```
git add CLAUDE.md README.md
git commit -m "docs: stripping kaldirildi - synonym-kanonik tam form eslesme (Plan 4)"
```

---

## Self-Review Notları (yazar kontrolü)
- **Hedef:** token-silme tamamen kaldırıldı (Task 2 ingest + Task 3 mapping/analyzer + Task 4 STAGES). Eşleşme `variations[].name` synonym-kanonik (Task 5).
- **Gate rederivation:** distinctive-core + coverage + is_address_dirty → clean_analyzer + `get_generic_tokens` (Task 1, Task 5). Sektör jenerik sayılır (gate için), ama matchable formda KALIR → "Apex Pharma"≠"Apex Steel" korunur (loose stage'de coverage token_count eşitliği + FUZZY_PHRASE phrase yapısı).
- **token_count asimetri fix:** per-country index'te token_count analyzer = clean_analyzer_{cc} (Task 3) → query (clean_analyzer_{cc}) ile simetrik.
- **Plan 2a uyumu:** fonetik `variations[].name`'e yazıyor (birincil alan) — uyumlu.
- **Plan 3 uyumu:** is_address_dirty clean_analyzer'a taşındı; generic seti genişledi (legal/geo dahil) → daha doğru "address dışı çekirdek" kararı.
- **Tip tutarlılığı:** `get_generic_tokens(cc)->frozenset`; `_FINGERPRINT_FIELD="variations.name.fingerprint"`; `_get_analyzer(country)` her gate'te.
- **⚠️ REINDEX + TESTLER:** mapping+ingest değişti → `python -m es.manager --force` + tam rematch ZORUNLU; test-izinli ortamda tam suite koşulmalı.
- **Recall etkisi:** suffix/geo farklı kayıtlar artık eşleşmez — bilinçli (kullanıcı kararı). Rematch sonrası QA ile precision/recall ölçülmeli.
