# TOKEN_COVERAGE Çift Yönlü Tam-Kanonik Eşleşme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TOKEN_COVERAGE stage'ini, iki ismin tam-kanonik token multiset'i birebir aynıysa (sıra serbest, legal/geo + çokluk dahil) eşleyecek; ayırt edici çekirdeği olmayan isimleri hiç eşleştirmeyecek şekilde yeniden yaz.

**Architecture:** Saf-ES "A′" yaklaşımı. Yeni `variations.name.canonical_full` multi-field'ı (clean-analyzer zinciri + `fingerprint_token_filter` sort+dedup → tam kanonik token kümesi) ile mevcut `variations.name.token_count` (toplam token sayısı) birlikte `term`-eşitliği → pratikte multiset eşitliği. Yazma yolları (es_writer/pipeline) DEĞİŞMEZ; alanlar ES mapping'iyle pasif türetilir. Çekirdek-gate TOKEN_COVERAGE'a özel olarak `fingerprint_analyzer` (legal+article stripli) boş-mu kontrolüne taşınır.

**Tech Stack:** Python 3.12 (.venv), Elasticsearch (per-country index + alias), pytest. ES analyzer'ları `es/manager.py`, query DSL `es/queries.py`.

---

## Önemli Bağlam (uygulayan okusun)

- **İki analyzer, iki rol:**
  - `fingerprint_analyzer` (GLOBAL, ülke-bağımsız tek isim): legal_fragment_stop + article_stop + fingerprint(sort/dedup). **GATE** için: legal/article atıldıktan sonra token kalıyor mu? `S. S. DE R.L. DE C.V.` → `[]` (boş → çekirdek yok).
  - `canonical_full_analyzer_<cc>` (YENİ, per-country + `_common`): clean-analyzer zinciri (synonym_graph + flatten_graph + article_stop, **legal KORUNUR**) + fingerprint(sort/dedup). **MATCH KEY** için: tam kanonik token kümesinin sıralı-tekil tek-token temsili. `ELEKTROKONTAKT SRL DE C.V.` → tek token `"cv de elektrokontakt rl s"`.
- **`term` on text:** `fingerprint_token_filter` tek bir token üretir (kelimeler boşlukla, sıralı, tekil). `term` sorgusu bu tek indexlenmiş token'la birebir eşleşir. Query tarafı da aynı analyzer'dan `_analyze` ile aynı tek-token string'i üretir.
- **token_count** alanı `enable_position_increments=False` ile clean analyzer token sayısını verir; query tarafı `_get_token_count(..., _get_analyzer(country), ...)` ile aynı sayıyı üretir → simetrik.
- **es=None:** Yeni TOKEN_COVERAGE exact-match için `_analyze` gerektirir; `es` yoksa anlamlı sorgu kurulamaz → `MATCH_NONE` döner (gerçek pipeline her zaman `es` geçirir; yalnız bazı birim testleri `es`siz çağırıyordu — bunlar güncellenir).
- **Kapsam dışı bırakılan:** `_has_distinctive_core` (CANONICAL_EXACT/FUZZY_PHRASE kullanıyor) ve `_core_coverage_filter` (FUZZY_PHRASE kullanıyor) DOKUNULMAZ. Yalnız TOKEN_COVERAGE'daki kullanımları kaldırılır.

Çalıştırma ortamı: **her zaman** `.venv\Scripts\python.exe` (Windows). Bash örneklerinde `.venv/Scripts/python.exe`.

---

## File Structure

| Dosya | Sorumluluk | Değişiklik |
| :-- | :-- | :-- |
| `es/manager.py` | ES analyzer + index mapping | `canonical_full_analyzer_common` + `canonical_full_analyzer_<cc>` analyzer; `variations.name.canonical_full` multi-field |
| `es/queries.py` | Query DSL üreticileri | `_analyze_single_token` + `_get_canonical_full` + `_fingerprint_token` helper'ları; `_get_canonical_full_analyzer`; `TOKEN_COVERAGE` yeniden yazımı; `clear_token_count_cache` yeni cache'i de temizler |
| `tests/test_es_manager.py` | Manager şema testleri | `canonical_full` analyzer + multi-field testleri |
| `tests/test_es_queries.py` | Query DSL testleri | Eski TOKEN_COVERAGE testleri güncellenir; yeni canonical_full+token_count+gate testleri |
| `analysis/live_probe.py` | Canlı regresyon probe | Golden set'e 3 negatif vaka |
| `CLAUDE.md`, `README.md` | Dokümantasyon | TOKEN_COVERAGE açıklaması |

---

## Task 1: manager — `canonical_full` analyzer + multi-field

**Files:**
- Modify: `es/manager.py` (analyzer tanımları ~satır 140-161; `variations_fields` ~satır 170-191; `tc_analyzer` seçimi ~satır 165-169)
- Test: `tests/test_es_manager.py`

- [ ] **Step 1: Write the failing test**

`tests/test_es_manager.py` sonuna ekle:

```python
def test_canonical_full_analyzer_keeps_legal_and_sorts():
    """canonical_full_analyzer clean-zincirini + fingerprint_token_filter'ı kullanmalı,
    legal_fragment_stop İÇERMEMELİ (legal korunur), fingerprint_token_filter SON olmalı."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    analyzers = s["settings"]["analysis"]["analyzer"]
    assert "canonical_full_analyzer_MX" in analyzers
    assert "canonical_full_analyzer_common" in analyzers
    chain = analyzers["canonical_full_analyzer_MX"]["filter"]
    assert "legal_fragment_stop" not in chain, "legal korunmalı (strip YOK)"
    assert chain[-1] == "fingerprint_token_filter", "sort/dedup en sonda olmalı"
    assert "article_stop" in chain
    # synonym_graph zinciri clean ile aynı kaynaktan: synonym filter + flatten_graph içermeli
    assert any(f.startswith("synonym_filter_") for f in chain)
    assert "flatten_graph" in chain


def test_variations_name_has_canonical_full_subfield():
    """variations.name altında canonical_full multi-field'ı, per-country analyzer ile."""
    from es.manager import build_index_settings
    s = build_index_settings(es=None, country_code="MX")
    fields = s["mappings"]["properties"]["variations"]["properties"]["name"]["fields"]
    assert "canonical_full" in fields
    cf = fields["canonical_full"]
    assert cf["type"] == "text"
    assert cf["analyzer"] == "canonical_full_analyzer_MX"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_manager.py::test_canonical_full_analyzer_keeps_legal_and_sorts tests/test_es_manager.py::test_variations_name_has_canonical_full_subfield -v`
Expected: FAIL — `canonical_full_analyzer_MX` analyzer'da yok / `canonical_full` field yok (KeyError/assert).

- [ ] **Step 3: Implement — common analyzer ekle**

`es/manager.py` içinde `analyzers["clean_analyzer_common"] = {...}` bloğunun (biten satır ~130) HEMEN ALTINA ekle:

```python
    # canonical_full (common): clean_analyzer_common ile AYNI zincir + sort/dedup.
    # Legal KORUNUR (legal_fragment_stop YOK); tam kanonik token kümesinin tek-token temsili.
    # TOKEN_COVERAGE'ın multiset eşitlik anahtarı (variations.name.canonical_full).
    analyzers["canonical_full_analyzer_common"] = {
        "tokenizer": "standard",
        "char_filter": ["acronym_glue", "punctuation_remover"],
        "filter": base_clean_filters
        + ["synonym_filter_common", "flatten_graph", "article_stop", "fingerprint_token_filter"],
    }
```

- [ ] **Step 4: Implement — per-country analyzer ekle**

`es/manager.py` içinde `if country_code and country_code not in ("__common__", "__COMMON__"):` bloğunda, `analyzers[analyzer_name] = {...}` atamasının (biten satır ~161) HEMEN ALTINA (hâlâ `if` bloğu içinde, aynı girinti) ekle:

```python
        analyzers[f"canonical_full_analyzer_{cc}"] = {
            "tokenizer": "standard",
            "char_filter": ["acronym_glue", "punctuation_remover"],
            "filter": base_clean_filters
            + [filter_name, "flatten_graph", "article_stop", "fingerprint_token_filter"],
        }
```

- [ ] **Step 5: Implement — multi-field ekle**

`es/manager.py` içinde `tc_analyzer = (...)` atamasının (biten satır ~169) HEMEN ALTINA ekle:

```python
    cf_analyzer = (
        f"canonical_full_analyzer_{country_code.upper()}"
        if country_code and country_code not in ("__common__", "__COMMON__")
        else "canonical_full_analyzer_common"
    )
```

Ardından `variations_fields = { ... }` dict'i içine, `"fingerprint": {...}` girdisinin ALTINA ekle:

```python
        # canonical_full: tam kanonik token kümesi (legal korunur) → sort/dedup tek token.
        # token_count ile birlikte TOKEN_COVERAGE multiset eşitliğini verir (term-eşitliği).
        "canonical_full": {
            "type": "text",
            "analyzer": cf_analyzer,
        },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_manager.py -v`
Expected: PASS (yeni 2 test + mevcut manager testleri).

- [ ] **Step 7: Commit**

```bash
git add es/manager.py tests/test_es_manager.py
git commit -m "feat(es): canonical_full analyzer + multi-field (TOKEN_COVERAGE multiset anahtari)"
```

---

## Task 2: queries — `_analyze_single_token` + `_get_canonical_full` + `_fingerprint_token` helper'ları

**Files:**
- Modify: `es/queries.py` (cache tanımları ~satır 45-49; `clear_token_count_cache` ~satır 58-61; yeni helper'lar `_core_coverage_filter`'dan önce)
- Test: `tests/test_es_queries.py`

- [ ] **Step 1: Write the failing test**

`tests/test_es_queries.py` sonuna ekle:

```python
def _es_by_analyzer(mapping, default=None):
    """body['analyzer'] adına göre farklı token listesi döndüren MagicMock es."""
    from unittest.mock import MagicMock
    es = MagicMock()
    def _analyze(index=None, body=None):
        analyzer = (body or {}).get("analyzer")
        toks = mapping.get(analyzer, default if default is not None else [])
        return {"tokens": [{"token": t} for t in toks]}
    es.indices.analyze.side_effect = _analyze
    return es


def test_get_canonical_full_returns_single_token():
    """_get_canonical_full, canonical_full_analyzer çıktısının ilk (tek) token'ını döner."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"canonical_full_analyzer_MX": ["cv de elektrokontakt rl s"]})
    assert es_queries._get_canonical_full(es, "ELEKTROKONTAKT SRL DE C.V.", "MX") == "cv de elektrokontakt rl s"


def test_get_canonical_full_uses_country_analyzer_name():
    """Bilinmeyen ülke → canonical_full_analyzer_common."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"canonical_full_analyzer_common": ["acme"]})
    assert es_queries._get_canonical_full(es, "ACME", "XX") == "acme"


def test_fingerprint_token_empty_for_legal_only():
    """fingerprint_analyzer boş token üretirse _fingerprint_token '' döner."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({"fingerprint_analyzer": []})
    assert es_queries._fingerprint_token(es, "S. S. DE R.L. DE C.V.", "MX") == ""


def test_analyze_single_token_inert_without_es():
    """es None ise '' döner (graceful)."""
    assert es_queries._get_canonical_full(None, "ACME", "MX") == ""
    assert es_queries._fingerprint_token(None, "ACME", "MX") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_queries.py::test_get_canonical_full_returns_single_token -v`
Expected: FAIL — `module 'es.queries' has no attribute '_get_canonical_full'`.

- [ ] **Step 3: Implement — cache + helper'lar**

`es/queries.py` içinde `_DISTINCTIVE_CORE_CACHE` tanımının (~satır 49) ALTINA ekle:

```python
# Perf: (analyzer, name) → tek-token analyzer çıktısı (canonical_full / fingerprint). '' geçerli sonuç.
_SINGLE_TOKEN_CACHE: dict[tuple[str, str], str] = {}
```

`clear_token_count_cache` fonksiyonunu (~satır 58-61) şununla DEĞİŞTİR:

```python
def clear_token_count_cache() -> None:
    """Token-count + çekirdek-gate + tek-token cache'lerini temizler (test izolasyonu / reindex sonrası)."""
    _TOKEN_COUNT_CACHE.clear()
    _DISTINCTIVE_CORE_CACHE.clear()
    _SINGLE_TOKEN_CACHE.clear()
```

`_core_coverage_filter` fonksiyonunun (~satır 179) HEMEN ÜSTÜNE ekle:

```python
def _get_canonical_full_analyzer(country: str) -> str:
    """clean_analyzer_<cc> ↔ canonical_full_analyzer_<cc> (aynı ülke-çözümü, paralel isim)."""
    return _get_analyzer(country).replace("clean_analyzer_", "canonical_full_analyzer_")


def _analyze_single_token(es: Elasticsearch, name: str, analyzer: str, country: str) -> str:
    """ES _analyze ile tek-token (fingerprint tarzı) analyzer çıktısını döner; boşsa ''.

    (analyzer, name) ile memoize edilir. es/text yoksa veya hata olursa '' (cache'lenmez).
    """
    if not es or not name:
        return ""
    key = (analyzer, name)
    cached = _SINGLE_TOKEN_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": name})
        tokens = [t.get("token", "") for t in res.get("tokens", [])]
    except Exception:
        return ""
    value = tokens[0] if tokens else ""
    if len(_SINGLE_TOKEN_CACHE) < _TOKEN_COUNT_CACHE_MAX:
        _SINGLE_TOKEN_CACHE[key] = value
    return value


def _get_canonical_full(es: Elasticsearch, name: str, country: str) -> str:
    """İsmin tam-kanonik token kümesinin sıralı-tekil tek-token temsili (canonical_full_analyzer)."""
    return _analyze_single_token(es, name, _get_canonical_full_analyzer(country), country)


def _fingerprint_token(es: Elasticsearch, name: str, country: str) -> str:
    """İsmin legal+article-stripli kanonik parmak izi (fingerprint_analyzer); boşsa '' → çekirdek yok."""
    return _analyze_single_token(es, name, "fingerprint_analyzer", country)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_queries.py -k "canonical_full or fingerprint_token or single_token" -v`
Expected: PASS (4 yeni test).

- [ ] **Step 5: Commit**

```bash
git add es/queries.py tests/test_es_queries.py
git commit -m "feat(es): _get_canonical_full + _fingerprint_token helper'lari (cache'li _analyze)"
```

---

## Task 3: queries — `TOKEN_COVERAGE` yeniden yazımı (canonical_full + token_count + fingerprint gate)

**Files:**
- Modify: `es/queries.py` (`TOKEN_COVERAGE` ~satır 267-311)
- Test: `tests/test_es_queries.py`

- [ ] **Step 1: Write the failing test**

`tests/test_es_queries.py` sonuna ekle:

```python
def _nested_filter_terms(q, field):
    """Nested variations bool.filter içindeki `field` term değerlerini toplar."""
    out = []
    for c in q.get("query", {}).get("bool", {}).get("must", []):
        nested = c.get("nested")
        if nested and nested.get("path") == "variations":
            for f in nested["query"]["bool"].get("filter", []):
                t = f.get("term", {})
                if field in t:
                    out.append(t[field])
    return out


def test_token_coverage_uses_canonical_full_and_token_count():
    """TOKEN_COVERAGE canonical_full + token_count term-eşitliği kurar (operator:and YOK)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": ["acme gida"],
        "canonical_full_analyzer_MX": ["acme gida sa"],
        "clean_analyzer_MX": ["acme", "gida", "sa"],  # token_count = 3
    })
    q = es_queries.TOKEN_COVERAGE("ACME GIDA SA", "MX", es=es)
    assert q != es_queries.MATCH_NONE
    assert _nested_filter_terms(q, "variations.name.canonical_full") == ["acme gida sa"]
    assert _nested_filter_terms(q, "variations.name.token_count") == [3]
    assert es_queries._get_country_filter(q) == "MX" if hasattr(es_queries, "_get_country_filter") else _get_country_filter(q)
    # operator:and artık kullanılmamalı
    import json
    assert "\"operator\": \"and\"" not in json.dumps(q)


def test_token_coverage_match_none_when_fingerprint_empty():
    """Ayırt edici çekirdek yok (fingerprint boş) → MATCH_NONE (S. S. DE R.L. DE C.V.)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": [],  # boş çekirdek
        "canonical_full_analyzer_MX": ["cv de rl s"],
        "clean_analyzer_MX": ["s", "s", "de", "rl", "de", "cv"],
    })
    q = es_queries.TOKEN_COVERAGE("S. S. DE R.L. DE C.V.", "MX", es=es)
    assert q == es_queries.MATCH_NONE


def test_token_coverage_match_none_when_fingerprint_non_alpha():
    """fingerprint sadece sayısalsa loose-match yapılmaz (require_alpha semantiği korunur)."""
    es_queries.clear_token_count_cache()
    es = _es_by_analyzer({
        "fingerprint_analyzer": ["12345"],
        "canonical_full_analyzer_MX": ["12345 sa"],
        "clean_analyzer_MX": ["12345", "sa"],
    })
    q = es_queries.TOKEN_COVERAGE("12345 SA", "MX", es=es)
    assert q == es_queries.MATCH_NONE


def test_token_coverage_match_none_without_es():
    """es yoksa exact-match kurulamaz → MATCH_NONE."""
    assert es_queries.TOKEN_COVERAGE("apple trading", "US") == es_queries.MATCH_NONE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_queries.py::test_token_coverage_uses_canonical_full_and_token_count -v`
Expected: FAIL — eski TOKEN_COVERAGE `match`/operator:and üretiyor; canonical_full term yok.

- [ ] **Step 3: Implement — TOKEN_COVERAGE'ı yeniden yaz**

`es/queries.py` içindeki `TOKEN_COVERAGE` fonksiyonunu (~satır 267-311) TAMAMEN ŞUNUNLA DEĞİŞTİR:

```python
def TOKEN_COVERAGE(name: str, country: str, es: Elasticsearch = None, **kwargs) -> dict:
    """Tam-kanonik token multiset eşitliği (sıra serbest, legal/geo + çokluk dahil).

    canonical_full (sıralı-tekil tam kanonik token kümesi) term-eşitliği VE token_count
    (toplam token sayısı) eşitliği birlikte → pratikte multiset eşitliği. operator:and +
    token_count proxy'si KALDIRILDI (alt-küme/sayı-çakışması over-merge'ü).

    GATE (TOKEN_COVERAGE'a özel): fingerprint_analyzer (legal+article stripli) boş token
    üretirse ya da yalnızca alfabetik-olmayan çekirdek kalırsa → MATCH_NONE (S. S. DE R.L.
    DE C.V., saf-legal S.A. DE C.V., salt-sayı). Pipeline'dan dışlamaz: CANONICAL_EXACT birebir
    formu yakalar, yoksa NEW_MASTER. es yoksa exact-match kurulamaz → MATCH_NONE.

    Args:
        name: Sorgu firma adı.
        country: Ülke kodu.
        es: Elasticsearch istemcisi (gate + canonical_full/token_count için ZORUNLU).

    Returns:
        ES query body dict ya da MATCH_NONE.
    """
    if es is None:
        return MATCH_NONE
    # GATE: ayırt edici (legal/article dışı, alfabetik) çekirdek yoksa loose-match yapma.
    fp = _fingerprint_token(es, name, country)
    if not fp or not any(c.isalpha() for c in fp):
        return MATCH_NONE
    canonical_full = _get_canonical_full(es, name, country)
    if not canonical_full:
        return MATCH_NONE
    token_count = _get_token_count(es, name, _get_analyzer(country), country)
    if token_count <= 0:
        return MATCH_NONE
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations",
                            "query": {
                                "bool": {
                                    "filter": [
                                        {"term": {"variations.name.canonical_full": canonical_full}},
                                        {"term": {"variations.name.token_count": token_count}},
                                    ]
                                }
                            },
                        }
                    }
                ],
                "filter": [{"term": {"country_code": country.upper()}}],
            }
        },
        "size": 1,
    }
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_queries.py -k "token_coverage_uses_canonical_full or token_coverage_match_none" -v`
Expected: PASS (4 yeni TOKEN_COVERAGE testi).

- [ ] **Step 5: Eski TOKEN_COVERAGE testlerini güncelle**

Aşağıdaki eski testler artık geçersiz; `tests/test_es_queries.py` içinde GÜNCELLE/KALDIR:

1. `test_token_coverage_uses_and_operator` (~satır 55-60) → TAMAMEN SİL (operator:and kaldırıldı).
2. `test_token_coverage_adds_core_coverage_filter` (~satır 185-191) → TAMAMEN SİL (yerini `test_token_coverage_uses_canonical_full_and_token_count` aldı).
3. `test_core_coverage_inert_without_es` (~satır 202-207) → İçindeki TOKEN_COVERAGE satırlarını (q2 ile ilgili 2 satır) SİL; yalnız FUZZY_PHRASE kısmı kalsın:

```python
def test_core_coverage_inert_without_es():
    """es yoksa FUZZY_PHRASE core-coverage filtresi eklenmez (graceful)."""
    q = es_queries.FUZZY_PHRASE("apple trading", "US")
    assert _core_filter_terms(q) == []
```

- [ ] **Step 6: Run full query test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_es_queries.py -v`
Expected: PASS (tüm dosya; silinen testler yok, FUZZY_PHRASE/CANONICAL_EXACT testleri değişmeden geçer).

- [ ] **Step 7: Commit**

```bash
git add es/queries.py tests/test_es_queries.py
git commit -m "feat(matching): TOKEN_COVERAGE cift-yonlu canonical_full+token_count eslesme + fingerprint gate"
```

---

## Task 4: Tam birim test koşusu (regresyon kontrolü)

**Files:**
- Test: tüm `tests/`

- [ ] **Step 1: Tüm testleri koştur**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (0 fail). Olası kırılma: TOKEN_COVERAGE'a dolaylı bağlı testler. Kırılan varsa, davranış değişikliğiyle tutarlıysa testi güncelle (TOKEN_COVERAGE artık operator:and/_core_coverage_filter kullanmaz), implementasyonu değil.

- [ ] **Step 2: py_compile sağlık kontrolü**

Run: `.venv/Scripts/python.exe -m py_compile es/queries.py es/manager.py analysis/live_probe.py`
Expected: hata yok.

- [ ] **Step 3 (kırılma olduysa): Commit**

```bash
git add -A
git commit -m "test: TOKEN_COVERAGE davranis degisikligine bagli testleri guncelle"
```

---

## Task 5: live_probe — 3 negatif vaka golden set'e

**Files:**
- Modify: `analysis/live_probe.py` (`GOLDEN_GROUPS` ~satır 36-66)

- [ ] **Step 1: Golden gruplarına 3 farklı-firma vakası ekle**

`analysis/live_probe.py` içinde `GOLDEN_GROUPS` dict'ine, kapanış `}` öncesine ekle (her grup AYRI firma → birbirleriyle EŞLEŞMEMELİ):

```python
    # --- TOKEN_COVERAGE cift-yonlu kanonik eslesme kurbanlari: hepsi FARKLI firma ---
    # (2026-06-18 spec; canonical_full+token_count + fingerprint gate ile ayrismalilar)
    "elektrokontakt": ["ELEKTROKONTAKT SRL DE C.V."],
    "ss_initials": ["S. S. DE R.L. DE C.V."],          # bos cekirdek → hicbir seye eslesmemeli
    "agro_acolchados": ["AGRO Y ACOLCHADOS, S.A. DE C.V."],
    "viotti": ["VIOTTI S.A. DE C.V."],
    "delarub": ["DELARUB MEXICO, S.A. DE C.V."],
    "deleites": ["DELEITES DE MEXICO S.A. DE C.V."],
```

- [ ] **Step 2: py_compile**

Run: `.venv/Scripts/python.exe -m py_compile analysis/live_probe.py`
Expected: hata yok.

- [ ] **Step 3: Commit**

```bash
git add analysis/live_probe.py
git commit -m "test(probe): TOKEN_COVERAGE cift-yonlu eslesme golden vakalari (3 negatif cift)"
```

---

## Task 6: Canlı reindex + doğrulama (operasyonel — TDD değil)

**Files:** kod değişikliği yok; ES'e karşı doğrulama.

> ÖN KOŞUL: ES `http://localhost:9200` ayakta. Bu görev canlı index'i `--force` ile YENİDEN OLUŞTURUR (boş index + yeni şema). Tam veri yeniden doldurma (rematch) ayrı/sonraki adımdır; aşağıdaki probe doğrulaması geçici index kullanır, prod veriyi gerektirmez.

- [ ] **Step 1: Yeni mapping/analyzer'larla index'leri yeniden oluştur**

Run: `.venv/Scripts/python.exe -m es.manager --force`
Expected: per-country index'ler yeniden oluşturulur; hata yok. (Not: bu adım veriyi siler — yalnızca dev/probe ortamında veya rematch öncesi çalıştır.)

- [ ] **Step 2: canonical_full analyzer'ın canlı doğrulaması**

Run:
```bash
curl -s "http://localhost:9200/living_companies_mx/_analyze" -H 'Content-Type: application/json' \
  -d '{"analyzer":"canonical_full_analyzer_MX","text":"ELEKTROKONTAKT SRL DE C.V."}' \
  | .venv/Scripts/python.exe -c "import sys,json;print([t['token'] for t in json.load(sys.stdin)['tokens']])"
```
Expected: tek token, içinde `elektrokontakt` geçen sıralı string (örn. `['cv de elektrokontakt rl s']`).

- [ ] **Step 3: live_probe ile precision/recall**

Run: `.venv/Scripts/python.exe -m analysis.live_probe`
Expected:
- `Over-merge ihlali: 0` — özellikle elektrokontakt/ss_initials/agro/viotti/delarub/deleites HİÇBİRİ farklı firmaya eşleşmemeli.
- `Under-merge recall` — vibracoustic/ceva/dhl grupları korunmalı (önceki seviyeden düşmemeli).

- [ ] **Step 4: 3 vakanın doğrudan TOKEN_COVERAGE tanısı (probe index üzerinde)**

`C:\tmp\tc_verify.py` oluştur:

```python
"""TOKEN_COVERAGE 3-vaka dogrulama (probe index, salt-okuma)."""
import config
import es.queries as q
from es.manager import get_es_client
from es.ingest import build_pipeline_body, pipeline_name
from es.manager import build_index_settings

CC, IDX = "MX", "living_companies_probe"
es = get_es_client()
config.ES_ANALYZE_INDEX_OVERRIDE = IDX
if es.indices.exists(index=IDX):
    es.indices.delete(index=IDX, ignore=[404])
es.options(request_timeout=120).indices.create(index=IDX, body=build_index_settings(es, country_code=CC))
es.ingest.put_pipeline(id=pipeline_name(CC), body=build_pipeline_body(CC))
masters = ["ELEKTROKONTAKT SRL DE C.V.", "AGRO Y ACOLCHADOS, S.A. DE C.V.", "DELARUB MEXICO, S.A. DE C.V."]
for i, m in enumerate(masters):
    es.index(index=IDX, id=f"m{i}", pipeline=pipeline_name(CC),
             document={"master_id": f"m{i}", "variations": [{"name": m}], "country_code": CC})
es.indices.refresh(index=IDX)
for inp in ["S. S. DE R.L. DE C.V.", "VIOTTI S.A. DE C.V.", "DELEITES DE MEXICO S.A. DE C.V."]:
    body = q.TOKEN_COVERAGE(inp, CC, es=es); body["size"] = 5
    if body == q.MATCH_NONE:
        print(f"{inp!r:40} → MATCH_NONE"); continue
    hits = es.search(index=IDX, body=body)["hits"]["hits"]
    print(f"{inp!r:40} → {len(hits)} hit: {[h['_source']['variations'][0]['name'] for h in hits]}")
es.indices.delete(index=IDX, ignore=[404])
config.ES_ANALYZE_INDEX_OVERRIDE = None
```

Run: `PYTHONPATH=/c/All-project/ta-code-merge .venv/Scripts/python.exe C:/tmp/tc_verify.py`
Expected: üç girdi de ya `MATCH_NONE` ya `0 hit` (master'larına ASLA eşleşmemeli). `S. S. …` → `MATCH_NONE`.

- [ ] **Step 5: Bulguyu kaydet (kod commit yok)**

Çıktıyı not al. Tam rematch (prod veriyi yeniden doldurma) kullanıcı onayıyla ayrı çalıştırılır: `.venv/Scripts/python.exe main_processor.py`.

---

## Task 7: Dokümantasyon güncellemesi

**Files:**
- Modify: `CLAUDE.md` (TOKEN_COVERAGE'ın geçtiği "TOKEN SİLİNMEZ" NOTE bloğu ~satır 45, "Aktif stage'ler" cümlesi)
- Modify: `README.md` (stage tablosu ~satır 99)

- [ ] **Step 1: README stage tablosunu güncelle**

`README.md` satır 99 civarındaki TOKEN_COVERAGE satırını ŞUNUNLA DEĞİŞTİR:

```markdown
| **3** | `TOKEN_COVERAGE` | Order-independent exact match: full canonical token **multiset** must be identical on both sides (`canonical_full` set-equality + `token_count` equality). Names with no distinctive core (empty `fingerprint_analyzer`) return MATCH_NONE. |
```

- [ ] **Step 2: CLAUDE.md "Aktif stage'ler" notunu güncelle**

`CLAUDE.md` içindeki son IMPORTANT bloğunda `Aktif stage'ler: CANONICAL_EXACT, FUZZY_PHRASE, TOKEN_COVERAGE.` cümlesinin ardına ekle:

```markdown
> TOKEN_COVERAGE artık tam-kanonik token MULTISET eşitliği ister (canonical_full küme-eşitliği +
> token_count eşitliği; sıra serbest, legal/geo dahil). Ayırt edici çekirdeği olmayan isimler
> (fingerprint_analyzer boş: S. S. DE R.L. DE C.V., saf-legal S.A. DE C.V.) MATCH_NONE. Eski
> operator:and + _core_coverage_filter token_count proxy'si KALDIRILDI (alt-küme/sayı-çakışması
> over-merge'ü). Bkz. docs/superpowers/specs/2026-06-18-token-coverage-cift-yonlu-kanonik-eslesme-design.md.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: TOKEN_COVERAGE cift-yonlu multiset eslesme aciklamasi"
```

---

## Self-Review notları (uygulayan için)

- **Spec kapsamı:** canonical_full+token_count (Task 1,3) ✓; fingerprint gate (Task 3) ✓; eski operator:and+_core_coverage_filter kaldırma (Task 3) ✓; reindex+probe doğrulama (Task 6) ✓; docs (Task 7) ✓.
- **Kapsam kararı:** Gate, spec'teki `_has_distinctive_core` değişikliği yerine TOKEN_COVERAGE'a özel `_fingerprint_token` kontrolüyle yapıldı → CANONICAL_EXACT/FUZZY_PHRASE regresyonu YOK. Semantik aynı.
- **Tip tutarlılığı:** `_get_canonical_full(es,name,country)->str`, `_fingerprint_token(es,name,country)->str`, `_get_token_count(es,name,analyzer,country)->int`, analyzer adları `canonical_full_analyzer_<cc>` / `clean_analyzer_<cc>` / `fingerprint_analyzer`.
- **Çakışma sınıfı** (aynı küme+sayı, farklı çokluk): kabul edilen teorik artık; firma adlarında pratikte oluşmaz, gate ile örtüşür.
```
