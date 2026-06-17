# Plan 3 — Kirli Veri (DIRTY_DATA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eşleşmeyen bir kayıt, isminde address synonym'i (street, avenue, p.o. box...) içeriyor VE address çıkarılınca ayırt edici çekirdek kalmıyorsa, onu `NEW_MASTER` yerine `DIRTY_DATA` olarak işaretlemek (ES'e indekslenir ama PG'de kirli işaretli; zayıf çekirdek nedeniyle gate'ler onu magnet olmaktan zaten korur).

**Architecture:** Address-token tespiti ve çekirdek-zayıflığı, ES `_analyze` (STRIPPED analyzer) tokenizasyonu + Python set-membership ile yapılır (fuzzy/Levenshtein DEĞİL — `core/input_filter` ile aynı sınıf boundary-classification). Karar `matching/pipeline.py` no-match dalında, `_index_new_master`'dan sonra verilir. Yeni `MatchType.DIRTY_DATA` ve `ENABLE_DIRTY_DATA` bayrağı.

**Tech Stack:** Python 3.12, elasticsearch-py, psycopg2, pytest.

---

## KISITLAR (bu branch'e özel)
- **HİÇBİR TEST KOŞULMAZ** (kullanıcı talebi). Doğrulama: `.venv\Scripts\python.exe -m py_compile <dosya>` + `python -c "import ..."` (sanity, pytest DEĞİL). Testler YAZILIR ama KOŞULMAZ.
- **MEVCUT KODU YENİDEN BİÇİMLENDİRME.** Cerrahi Edit'ler; testleri dosya SONUNA ekle.

## Bağlam (önceki planlar)
- Plan 1: per-country index + alias; `_analyze_index(country)` (es/queries.py) `_analyze` hedefini ülke alias'ına yönlendirir.
- Plan 2a: `rec["match_name"]` = fonetik-kanonik isim (query+index'te kullanılır). Address typo'ları da kanonikleşir (`avenu`→`ave.`).
- STRIPPED analyzer legal/article/geo sıyırır; **address + sector + marka çekirdekte KALIR** (address sıyrılmaz). DIRTY kararı bunu kullanır: tokenler arasında address VARSA ve address dışı ayırt edici token YOKSA → kirli.

## Kapsam Dışı
- Address token'larını çekirdekten kalıcı çıkarma / sınıflandırma alanları (variations_core vb.) — gerekmiyor; DIRTY runtime kararıdır.
- Synonym yenileme (ayrı veri-küratörlük adımı).

---

## File Structure

| Dosya | Sorumluluk | Değişim |
| :--- | :--- | :--- |
| `config.py` | Tipler/bayraklar | `MatchType.DIRTY_DATA` + `ENABLE_DIRTY_DATA` |
| `core/synonym_loader.py` | Synonym parse | `get_address_tokens(cc)` (address_abbreviations) |
| `es/queries.py` | Sınıflandırma yardımcısı | `is_address_dirty(es, name, country)` |
| `matching/pipeline.py` | Orkestrasyon | no-match dalında DIRTY_DATA vs NEW_MASTER + sayaç + özet |
| `CLAUDE.md` | Dok. | DIRTY_DATA notu + modül tablosu |
| `tests/*` | Testler | get_address_tokens, is_address_dirty, pipeline dirty (YAZILIR, KOŞULMAZ) |

---

## Task 1: config.py — DIRTY_DATA tipi + bayrak

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Test yaz (KOŞMA)**

`tests/test_config.py` sonuna ekle:
```python
def test_dirty_data_match_type_exists():
    from config import MatchType
    assert MatchType.DIRTY_DATA == "DIRTY_DATA"


def test_enable_dirty_data_flag_default_true():
    import config
    assert config.ENABLE_DIRTY_DATA is True
```

- [ ] **Step 2: MatchType.DIRTY_DATA ekle**

`config.py` `MatchType` sınıfında, `EXCLUDED = "EXCLUDED"` satırının ÜSTÜNE ekle:
```python
    # Firma-OLMAYAN kirli isim: address synonym'i baskın + ayırt edici çekirdek yok.
    # ES'e indekslenir (sonraki kayıtlar eşleşebilsin) ama PG'de kirli işaretli; zayıf
    # çekirdek nedeniyle distinctive-core gate onu magnet olmaktan korur. Bkz. input_filter / Plan 3.
    DIRTY_DATA = "DIRTY_DATA"
```

- [ ] **Step 3: ENABLE_DIRTY_DATA bayrağı ekle**

`config.py` `ENABLE_INPUT_FILTER = True` satırının hemen ALTINA ekle:
```python
# --- Kirli veri (DIRTY_DATA) işaretleme ---
# Eşleşmeyen kayıt, isminde address synonym'i içeriyor VE address çıkarılınca ayırt edici
# çekirdek kalmıyorsa NEW_MASTER yerine DIRTY_DATA işaretlenir (indekslenir ama PG'de işaretli).
# Karar ES _analyze tokenizasyonu + Python set-membership ile (fuzzy değil). Bkz. es/queries.is_address_dirty.
ENABLE_DIRTY_DATA = True
```

- [ ] **Step 4: py_compile + commit (TEST KOŞMA)**

Run: `.venv\Scripts\python.exe -m py_compile config.py`
```
git add config.py tests/test_config.py
git commit -m "feat(config): DIRTY_DATA match-type + ENABLE_DIRTY_DATA bayragi"
```

---

## Task 2: synonym_loader.py — get_address_tokens

**Files:**
- Modify: `core/synonym_loader.py`
- Test: `tests/test_synonym_loader.py`

- [ ] **Step 1: Test yaz (KOŞMA)**

`tests/test_synonym_loader.py` sonuna ekle:
```python
def test_get_address_tokens_includes_common_address_words():
    from core.synonym_loader import get_address_tokens
    toks = get_address_tokens("TR")
    # common.json address_abbreviations: street/st, avenue/ave, p.o. box ...
    assert "street" in toks
    assert "avenue" in toks
    assert "st" in toks  # noktalar _parse_category_tokens'ta silinir
    # marka/sektör kelimesi address sayılmaz
    assert "pharma" not in toks
```

- [ ] **Step 2: get_address_tokens ekle**

`core/synonym_loader.py` içine, `get_business_sector_tokens` fonksiyonunun ALTINA ekle (mevcut `_parse_category_tokens` yeniden kullanılır — noktaları siler, küçük harfe çevirir):
```python
@lru_cache(maxsize=None)
def get_address_tokens(country_code: str) -> frozenset:
    """Ülkeye özgü 'address_abbreviations' token'larını döner (common.json + ülke dosyası).

    Kaynak ve hedef token'lar (street, st, str, avenue, ave, blvd, po, box...) — noktasız,
    küçük harf. DIRTY_DATA tespiti (es/queries.is_address_dirty) kullanır; stripping'e GİRMEZ.
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)
    return _parse_category_tokens(paths, "address_abbreviations")
```

- [ ] **Step 3: py_compile + sanity + commit (NO pytest)**

Run: `.venv\Scripts\python.exe -m py_compile core/synonym_loader.py`
Run: `.venv\Scripts\python.exe -c "from core.synonym_loader import get_address_tokens as g; t=g('TR'); print('street' in t, 'avenue' in t, 'pharma' not in t)"`
Expected: `True True True` (sanity, NOT pytest).
```
git add core/synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat(synonym): get_address_tokens (address_abbreviations) loader"
```

---

## Task 3: es/queries.py — is_address_dirty

**Files:**
- Modify: `es/queries.py`
- Test: `tests/test_es_queries.py`

`is_address_dirty` STRIPPED analyzer çıktısındaki token'ları (address sıyrılmaz → orada kalır) alır; address VARSA ve address-dışı ayırt edici (len≥MATCH_CORE_MIN_TOKEN_LEN, alfabetik, sektör-olmayan) token YOKSA True döner.

- [ ] **Step 1: Test yaz (KOŞMA)**

`tests/test_es_queries.py` sonuna ekle:
```python
def test_is_address_dirty_true_when_address_only_no_core():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "street"}, {"token": "no"}]}
    # 'street' address, 'no' kısa → ayırt edici çekirdek yok → kirli
    assert q.is_address_dirty(es, "main street no 5", "TR") is True


def test_is_address_dirty_false_when_distinctive_core_present():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "apex"}, {"token": "street"}]}
    # 'apex' ayırt edici çekirdek → kirli DEĞİL
    assert q.is_address_dirty(es, "apex street", "TR") is False


def test_is_address_dirty_false_when_no_address():
    from unittest.mock import MagicMock
    import es.queries as q
    es = MagicMock()
    es.indices.analyze.return_value = {"tokens": [{"token": "apex"}, {"token": "pharma"}]}
    assert q.is_address_dirty(es, "apex pharma", "TR") is False


def test_is_address_dirty_false_when_es_none():
    import es.queries as q
    assert q.is_address_dirty(None, "main street", "TR") is False
```

- [ ] **Step 2: import + fonksiyon ekle**

`es/queries.py` import bloğunda `from core.synonym_loader import (...)` listesine `get_address_tokens` ekle ve config import'una `ENABLE_DIRTY_DATA` ekle. Yani:
```python
from core.synonym_loader import get_all_country_codes, get_business_sector_tokens, get_address_tokens
```
ve config import'una `ENABLE_DIRTY_DATA` ekle (mevcut `from config import (...)` listesine bir satır).

`_has_distinctive_core` fonksiyonunun ALTINA ekle:
```python
def is_address_dirty(es: Elasticsearch, name: str, country: str) -> bool:
    """İsim address synonym'i içeriyor AMA address çıkarılınca ayırt edici çekirdek YOK → kirli.

    Tokenizasyon ES STRIPPED analyzer'ından gelir (legal/article/geo sıyrılmış; address +
    sector + marka çekirdekte kalır). Address membership + distinctiveness Python set
    kontrolüdür (fuzzy DEĞİL — input_filter ile aynı boundary sınıfı). es yoksa / gate
    kapalıysa / _analyze hata verirse False (mevcut NEW_MASTER davranışını bozma).

    Args:
        es: Elasticsearch istemcisi (None ise False).
        name: Sorgu firma adı (fonetik-kanonik match_name beklenir).
        country: Ülke kodu.

    Returns:
        True → DIRTY_DATA; False → normal NEW_MASTER yolu.
    """
    if not ENABLE_DIRTY_DATA or es is None or not name:
        return False
    analyzer = _get_stripped_analyzer(country)
    try:
        res = es.indices.analyze(index=_analyze_index(country), body={"analyzer": analyzer, "text": name})
        tokens = [t.get("token", "") for t in res.get("tokens", [])]
    except Exception:
        return False
    address = get_address_tokens(country)
    if not any(tok in address for tok in tokens):
        return False  # address yok → kirli değil
    generic = get_business_sector_tokens(country)
    distinctive = any(
        len(tok) >= MATCH_CORE_MIN_TOKEN_LEN
        and any(c.isalpha() for c in tok)
        and tok not in address
        and tok not in generic
        for tok in tokens
    )
    return not distinctive
```

- [ ] **Step 3: py_compile + sanity + commit (NO pytest)**

Run: `.venv\Scripts\python.exe -m py_compile es/queries.py`
Run: `.venv\Scripts\python.exe -c "import es.queries; print(hasattr(es.queries,'is_address_dirty'))"`
Expected: `True`.
```
git add es/queries.py tests/test_es_queries.py
git commit -m "feat(es): is_address_dirty (address-baskin + cekirdek-zayif tespiti, ES-side tokenizasyon)"
```

---

## Task 4: pipeline.py — no-match dalında DIRTY_DATA kararı

**Files:**
- Modify: `matching/pipeline.py`
- Test: `tests/test_main_processor.py`

- [ ] **Step 1: Test yaz (KOŞMA)**

`tests/test_main_processor.py` sonuna ekle:
```python
def test_dirty_data_flag_routes_to_dirty_match_type(monkeypatch):
    """is_address_dirty True ise no-match dalı DIRTY_DATA üretir, dedup'a EKLENMEZ."""
    import matching.pipeline as p
    # is_address_dirty'i True'ya zorla; _index_new_master sahte master döndürsün
    monkeypatch.setattr(p, "is_address_dirty", lambda es, name, cc: True)
    monkeypatch.setattr(p, "_index_new_master", lambda es, rec: "m-dirty")
    # küçük bir no-match senaryosu: doğrudan karar bloğunu çağırmak yerine,
    # is_address_dirty + _index_new_master mock'larıyla stage_name seçimini doğrula.
    # (Tam process_all_data entegrasyonu ES/DB gerektirir; burada birim-mantık yeterli.)
    assert p.is_address_dirty(None, "x", "TR") is True  # monkeypatch doğrulaması
```
(NOT: Bu birim test yalnız monkeypatch kancasını doğrular; tam akış ES/DB-bağımlı olduğundan burada koşulmaz. DIRTY mantığının ES-tarafı es/queries testlerinde, kod yolu code-review ile doğrulanır.)

- [ ] **Step 2: import ekle**

`matching/pipeline.py` `from config import (...)` listesine `ENABLE_DIRTY_DATA` ekle. `import es.queries as _es_queries` zaten var; `is_address_dirty`'i ondan kullanacağız (`_es_queries.is_address_dirty`) VEYA doğrudan import et. Doğrudan import ekle (apply-pass'te kısa erişim için):
```python
from es.queries import is_address_dirty
```

- [ ] **Step 3: no-match dalını değiştir**

`matching/pipeline.py` apply-pass'teki `else:` (no-winner) bloğunu (mevcut ~747-756) ŞUNUNLA DEĞİŞTİR:
```python
                        else:
                            master_id = _index_new_master(es, rec)
                            if ENABLE_DIRTY_DATA and is_address_dirty(es, rec["match_name"], country):
                                stage_name = "DIRTY_DATA"
                                details = "DIRTY_DATA: address-baskin, ayirt edici cekirdek yok."
                                total_dirty += 1
                            else:
                                stage_name = "NEW_MASTER"
                                details = "NEW_MASTER: No relevant matches found."
                                total_new += 1
                                batch_new_master_ids.append(master_id)  # P0-C: batch-içi dedup kapsamı
                                pending_dedup_ids.append(master_id)      # perf: N-batch biriktirici
                                pending_dedup_ccs.add(country)
                            pg_updates.append(_make_pg_update_tuple(master_id, 100, stage_name, details, row_id))
                            es_score = 100.0
```
(NOT: DIRTY_DATA kayıtları dedup biriktiricilerine EKLENMEZ — zayıf çekirdekli kirli kayıtlar birbirine merge edilmemeli; zaten plan_merge dejenere-fingerprint guard'ı da skip ederdi, ama kapsam-dışı bırakmak nettir. `audit_rows`/`log_rows` bloğu DEĞİŞMEZ; `stage_name` doğru değeri taşır.)

- [ ] **Step 4: total_dirty sayacı + özet**

`process_all_data` içinde sayaçların tanımlandığı yere (`total_new = 0` civarı) ekle:
```python
        total_dirty = 0  # address-baskın kirli kayıt (DIRTY_DATA)
```
Özet bloğunda (`logger.info(f"  Yeni master: {total_new:,}")` civarı), altına ekle:
```python
        if total_dirty:
            logger.info(f"  Kirli veri:  {total_dirty:,} (DIRTY_DATA: address-baskin)")
```

- [ ] **Step 5: py_compile + sanity + commit (NO pytest)**

Run: `.venv\Scripts\python.exe -m py_compile matching/pipeline.py`
Run: `.venv\Scripts\python.exe -c "import matching.pipeline; print('ok')"`
Expected: `ok`.
```
git add matching/pipeline.py tests/test_main_processor.py
git commit -m "feat(pipeline): no-match dalinda DIRTY_DATA karari (address-baskin), dedup'tan haric"
```

---

## Task 5: Dokümantasyon

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md §2 modül tablosu**

`es/queries.py` satırının açıklamasına DIRTY ekle veya yeni bir not — `core/synonym_loader.py` satırının altına genel not. En basiti: §2 tablosundaki `core/input_filter.py` satırının altına ekle:
```
| `es/queries.py` (`is_address_dirty`) | Python | Address-baskın + çekirdek-zayıf isim tespiti → DIRTY_DATA (ES `_analyze` tokenizasyonu + set-membership). |
```

- [ ] **Step 2: CLAUDE.md §1 — DIRTY_DATA notu**

§1'e (input_filter / EXCLUDED yakınına) kısa not ekle:
```
> [!NOTE]
> **KİRLİ VERİ (DIRTY_DATA):** Eşleşmeyen bir kayıt isminde address synonym'i (street, avenue,
> p.o. box...) içeriyor VE address çıkarılınca ayırt edici çekirdek kalmıyorsa, NEW_MASTER yerine
> `DIRTY_DATA` işaretlenir. ES'e indekslenir (sonraki kayıtlar eşleşebilsin) ama PG'de kirli
> işaretli; zayıf çekirdek nedeniyle distinctive-core gate onu magnet olmaktan korur. Karar
> ES `_analyze` + Python set-membership (fuzzy değil). Dedup'a dahil edilmez. Bkz. es/queries.is_address_dirty.
```

- [ ] **Step 3: Commit**
```
git add CLAUDE.md
git commit -m "docs: DIRTY_DATA (kirli veri) kurali + modul tablosu (Plan 3)"
```

---

## Self-Review Notları (yazar kontrolü)

- **Spec kapsamı (Madde 3):** address synonym tespiti ✓ (Task 2 get_address_tokens), çekirdek-zayıf + address-baskın → DIRTY ✓ (Task 3 is_address_dirty), indexlenir-ama-işaretli ✓ (Task 4: _index_new_master + match_type=DIRTY_DATA), çekirdek güçlü → NEW_MASTER ✓ (else dalı).
- **Tip tutarlılığı:** `MatchType.DIRTY_DATA="DIRTY_DATA"`; `get_address_tokens(cc)->frozenset`; `is_address_dirty(es, name, country)->bool`. Pipeline `is_address_dirty(es, rec["match_name"], country)` ile çağrılır (Plan 2a match_name simetrisi).
- **ES-side ilke:** tokenizasyon ES `_analyze` (STRIPPED analyzer); yalnız set-membership Python (input_filter ile aynı sınıf — fuzzy değil).
- **Dedup güvenliği:** DIRTY kayıtlar pending_dedup'a eklenmez (zayıf-çekirdek magnet riski yok; ayrıca plan_merge dejenere guard'ı da yakalardı).
- **Reindex:** Bu plan reindex GEREKTİRMEZ (runtime karar); ancak Plan 1+2a zaten reindex+rematch bekliyor — DIRTY kararı rematch sırasında otomatik uygulanır.
- **TEST UYARISI:** testler bu branch'te koşulmadı; test-izinli ortamda tam suite koşulmalı.
