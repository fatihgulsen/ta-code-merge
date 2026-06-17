# Plan 2a — Synonym-İçi Fonetik Typo-Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Çekirdeğe sızan bozuk-yazımlı synonym token'larını (örn. `limmtd`→`ltd.`, `internacaonal`→`international`) fonetik olarak tespitle kanonik forma çevirip, aynı-firma kayıtlarının çekirdek-exact eşleşmesini sağlamak; markaya/çekirdeğe ASLA dokunmadan.

**Architecture:** Saf-Python `core/synonym_phonetic.py` modülü, synonym sözlüğünün (legal+sector+address) double-metaphone kodlarından bir `{metaphone_code → kanonik}` haritası kurar. `canonicalize_phonetic(name, cc)` her token için: zaten tam-synonym ise dokunmaz; değilse ve metaphone'u TAM eşleşiyorsa (uzunluk + ambiguity guard'larıyla) kanonik forma çevirir; aksi halde korur (marka çekirdeği). Hem index (variations[].name kanonik saklanır) hem query (`rec["match_name"]`) tarafında simetrik uygulanır. `es/queries.py` DEĞİŞMEZ.

**Tech Stack:** Python 3.12, `metaphone` (doublemetaphone, saf-Python), elasticsearch-py, pytest.

---

## KISITLAR (bu branch'e özel)
- **HİÇBİR TEST KOŞULMAZ** (kullanıcı talebi — ES-test takılması geçmişi). Doğrulama: kod-okuma + `.venv\Scripts\python.exe -m py_compile <dosya>` (sözdizimi) + plain `python -c "import ..."` (import/bağımlılık kontrolü, pytest DEĞİL). Testler YAZILIR ama KOŞULMAZ.
- **MEVCUT KODU YENİDEN BİÇİMLENDİRME.** Cerrahi Edit'ler; testleri dosya SONUNA ekle.
- Reindex gerektirir (variations[].name içeriği değişir). Bu plan reindex YAPMAZ — kod + dökümandan ibaret; reindex+rematch ayrı operasyon adımıdır (Plan 2 reindex penceresi).

## ⚠️ REINDEX ÖNCESİ ZORUNLU (bu branch dışında, test izni olan ortamda)
`pytest tests/test_synonym_phonetic.py -v` MUTLAKA koşulmalı — marka over-rescue (gerçek markanın yanlışlıkla synonym'e çevrilmesi) yalnız altın-küme testiyle yakalanır. Testler bu planda yazılır; canlıya/rematch'e geçmeden önce koşulması ŞART.

## Kapsam Dışı (bilinçli)
- **Geo + article sınıfları fonetik rescue'ya DAHİL DEĞİL.** Geo: countries.json kanoniği ISO kod (`argentina=>ar`) → typo'yu "ar"a çevirmek geo-stop setinde olmadığından kırılır. Article: çok kısa (de/la/the) → MIN_TOKEN_LEN guard'ı zaten eler, collision riski yüksek. Yalnız legal_suffixes + business_sectors + address_abbreviations. (Spec "tüm sınıflar" demişti; bu teknik istisna belgelenir.)
- Token sınıflandırma genişletme, address detection, synonym-yenileme → ayrı planlar.

---

## File Structure

| Dosya | Sorumluluk | Değişim |
| :--- | :--- | :--- |
| `requirements.txt` | Bağımlılık | `metaphone>=0.6` eklenir |
| `core/synonym_loader.py` | Synonym parse | `get_synonym_canonical_map(cc, categories)` genel kanonik eşlem |
| `core/synonym_phonetic.py` | **YENİ** — fonetik rescue | metaphone haritası + `canonicalize_phonetic(name, cc)` |
| `matching/pipeline.py` | Orkestrasyon | parse-pass `rec["match_name"]`; 2 query çağrısı match_name; create_new_masters kanonik |
| `matching/es_writer.py` | ES yazımı | variations[].name kanonik saklanır (inline canonicalize) |
| `CLAUDE.md` | Dok. | fonetik-on-synonyms kuralı + Python-metaphone istisnası |
| `tests/test_synonym_phonetic.py` | **YENİ** test | altın-küme (typo→kanonik, marka→değişmez) — YAZILIR, KOŞULMAZ |
| `tests/test_synonym_loader.py` | test | get_synonym_canonical_map testi |

---

## Task 1: metaphone bağımlılığı + genel kanonik eşlem

**Files:**
- Modify: `requirements.txt`
- Modify: `core/synonym_loader.py`
- Test: `tests/test_synonym_loader.py`

- [ ] **Step 1: requirements.txt'e ekle**

`requirements.txt` sonuna ekle:
```
metaphone>=0.6
```

- [ ] **Step 2: Bağımlılığı kur + import doğrula (TEST DEĞİL)**

Run: `.venv\Scripts\python.exe -m pip install "metaphone>=0.6"`
Then: `.venv\Scripts\python.exe -c "from metaphone import doublemetaphone; print(doublemetaphone('limited'))"`
Expected: bir tuple yazdırır (örn. `('LMTT', '')`). Hata verirse kurulum başarısız — düzelt.

- [ ] **Step 3: Test yaz (KOŞMA)**

`tests/test_synonym_loader.py` sonuna ekle:
```python
def test_get_synonym_canonical_map_maps_source_to_target():
    from core.synonym_loader import get_synonym_canonical_map
    # common.json legal_suffixes: "...,incorporated,inc,inc.=>corp." vb.
    m = get_synonym_canonical_map("TR", ("legal_suffixes",))
    # her kaynak token kanonik hedefe gitmeli; hedef kendine idempotent
    assert m.get("inc") == "corp." or m.get("inc") == "inc."  # gruba göre
    # business_sectors: trading ailesi
    ms = get_synonym_canonical_map("TR", ("business_sectors",))
    assert ms.get("traders") == "trading"
    assert ms.get("trading") == "trading"  # idempotent hedef
    # address: avenue ailesi
    ma = get_synonym_canonical_map("TR", ("address_abbreviations",))
    assert ma.get("ave") == "ave."
    assert ma.get("avenue") == "ave."
```

- [ ] **Step 4: get_synonym_canonical_map ekle**

`core/synonym_loader.py` içine, `get_business_sector_canonical_map` fonksiyonunun ALTINA ekle:
```python
@lru_cache(maxsize=None)
def get_synonym_canonical_map(country_code: str, categories: tuple) -> dict:
    """Verilen kategorilerdeki tüm 'src,src=>target' kurallarından {kaynak: hedef} eşlem döner.

    categories: ör. ("legal_suffixes", "business_sectors", "address_abbreviations").
    Çok-kelimeli (boşluklu) kaynak token'lar atlanır (tek-token rescue için).
    Hedef kendisiyle de eşlenir (idempotent). Tamamen JSON'dan türetilir.
    """
    country_code = country_code.upper()
    paths = [SYNONYMS_DIR / f for f in COMMON_FILES]
    country_file = SYNONYMS_DIR / f"{country_code.lower()}.json"
    if country_file.exists():
        paths.append(country_file)

    mapping: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for category in categories:
            rules = data.get(category, [])
            if not isinstance(rules, list):
                continue
            for rule in rules:
                rule_norm = normalize_text(rule)
                if "=>" not in rule_norm:
                    continue
                left, right = rule_norm.split("=>", 1)
                target = right.strip().lower().replace(".", "").strip()
                if not target or " " in right.strip():
                    # not: hedef tek kelime değilse (ör. 'import export') yine de
                    # kaynakları hedefe eşle; target string'i olduğu gibi kullan
                    target = right.strip().lower()
                for src in left.split(","):
                    src_token = src.strip().lower().replace(".", "").strip()
                    if src_token and " " not in src_token:
                        mapping[src_token] = right.strip().lower()
                # hedef kendisiyle idempotent
                t_self = right.strip().lower()
                if " " not in t_self.replace(".", ""):
                    mapping[t_self.replace(".", "")] = t_self
    return mapping
```

NOT: Bu fonksiyon mevcut `get_business_sector_canonical_map`'i bozmaz (o ayrı kalır). `lru_cache` için `categories` bir tuple olmalı (çağıran tuple geçer).

- [ ] **Step 5: py_compile + commit (TEST KOŞMA)**

Run: `.venv\Scripts\python.exe -m py_compile core/synonym_loader.py`
Expected: çıktı yok (başarı).
```
git add requirements.txt core/synonym_loader.py tests/test_synonym_loader.py
git commit -m "feat(synonym): genel kanonik eslem (get_synonym_canonical_map) + metaphone bagimliligi"
```

---

## Task 2: core/synonym_phonetic.py — fonetik harita + canonicalize

**Files:**
- Create: `core/synonym_phonetic.py`
- Test: `tests/test_synonym_phonetic.py`

- [ ] **Step 1: Altın-küme testi yaz (KOŞMA — reindex öncesi koşulacak)**

`tests/test_synonym_phonetic.py` oluştur:
```python
"""Fonetik typo-rescue altın-küme testleri.

NOT: Bu testler bu branch'te KOŞULMAZ (kullanıcı talebi). Reindex/rematch ÖNCESİ
test izni olan ortamda MUTLAKA koşulmalı — marka over-rescue'yi yakalamanın tek yolu.
"""
from core.synonym_phonetic import canonicalize_phonetic, build_synonym_phonetic_map


def test_typod_legal_suffix_rescued_to_canonical():
    # 'limmtd' listede yok ama metaphone'u 'limited'e yakın → kanonik 'ltd.'
    out = canonicalize_phonetic("acme limmtd", "TR")
    assert "acme" in out
    assert "ltd" in out  # 'ltd.' veya 'ltd' kanonik
    assert "limmtd" not in out


def test_typod_sector_rescued():
    out = canonicalize_phonetic("apex internacaonal", "TR")
    assert "apex" in out
    assert "international" in out


def test_real_brand_not_rescued():
    # Gerçek markalar synonym'e ÇEVRİLMEMELİ
    for brand in ["santander", "halliburton", "siemens", "flextronics", "vibracoustic"]:
        out = canonicalize_phonetic(brand, "TR")
        assert out == brand, f"marka degismemeli: {brand} -> {out}"


def test_exact_synonym_token_untouched_passthrough():
    # zaten tam synonym olan token aynen kalır (downstream synonym_graph/strip işler)
    out = canonicalize_phonetic("acme ltd", "TR")
    assert "acme" in out and "ltd" in out


def test_short_tokens_not_rescued():
    # MIN_TOKEN_LEN altı token'lar (kısa marka/akronim) dokunulmaz
    out = canonicalize_phonetic("vf sa", "TR")
    assert "vf" in out


def test_ambiguous_metaphone_excluded_from_map():
    # Aynı metaphone kodu birden çok kanonike işaret ediyorsa haritadan çıkar
    m = build_synonym_phonetic_map("TR")
    # değerler kanonik string; aynı kod -> tek kanonik (ambiguity guard)
    assert all(isinstance(v, str) for v in m.values())


def test_digits_token_not_rescued():
    out = canonicalize_phonetic("3m mexico", "MX")
    assert "3m" in out
```

- [ ] **Step 2: core/synonym_phonetic.py yaz**

`core/synonym_phonetic.py` oluştur:
```python
"""Synonym-içi fonetik typo-rescue.

Çekirdeğe sızan bozuk-yazımlı synonym token'larını (suffix/sector/address) double-metaphone
ile tespitleyip kanonik forma çevirir. MARKAYA/ÇEKİRDEĞE ASLA dokunmaz: yalnız synonym
sözlüğüyle TAM metaphone eşleşen, yeterince uzun, ambiguity-içermeyen token'lar çevrilir.

Geo + article sınıfları KAPSAM DIŞI (bkz. plan: geo ISO-kanonik mekaniği / article çok kısa).
"""
from functools import lru_cache

from metaphone import doublemetaphone

from core.synonym_loader import (
    get_legal_suffix_tokens,
    get_business_sector_tokens,
    get_synonym_canonical_map,
)

# Rescue YALNIZ bu sınıflarda (kanoniği normal token olanlar):
_RESCUE_CATEGORIES = ("legal_suffixes", "business_sectors", "address_abbreviations")

# Brand-güvenlik guard'ları:
MIN_TOKEN_LEN = 5          # sorgu token'ı bu uzunlukta olmalı (kısa marka/akronim korunur)
MIN_SYNONYM_SRC_LEN = 4    # synonym kaynak token'ı bu uzunlukta olmalı (kısa kodlar collision yapar)


def _primary_code(token: str) -> str:
    """Token'ın birincil double-metaphone kodu (boşsa '')."""
    code, _ = doublemetaphone(token)
    return code or ""


@lru_cache(maxsize=None)
def _exact_synonym_sources(country_code: str) -> frozenset:
    """Rescue kategorilerindeki TÜM tam synonym kaynak token'ları (dokunulmayacaklar)."""
    cc = country_code.upper()
    m = get_synonym_canonical_map(cc, _RESCUE_CATEGORIES)
    return frozenset(m.keys())


@lru_cache(maxsize=None)
def build_synonym_phonetic_map(country_code: str) -> dict:
    """{metaphone_code: kanonik_form} — ambiguous kodlar ve kısa kaynaklar hariç.

    Aynı metaphone koduna FARKLI kanonikler düşerse o kod ATILIR (yanlış-çevirme önlenir).
    """
    cc = country_code.upper()
    canon_map = get_synonym_canonical_map(cc, _RESCUE_CATEGORIES)  # {src: canonical}
    code_to_canon: dict[str, str] = {}
    ambiguous: set[str] = set()
    for src, canon in canon_map.items():
        if len(src) < MIN_SYNONYM_SRC_LEN or not src.isalpha():
            continue
        code = _primary_code(src)
        if not code:
            continue
        existing = code_to_canon.get(code)
        if existing is not None and existing != canon:
            ambiguous.add(code)  # aynı kod -> farklı kanonik => güvenilmez
        else:
            code_to_canon[code] = canon
    for code in ambiguous:
        code_to_canon.pop(code, None)
    return code_to_canon


@lru_cache(maxsize=100_000)
def canonicalize_phonetic(name: str, country_code: str) -> str:
    """İsimdeki bozuk-yazımlı synonym token'larını kanonik forma çevirir.

    Her token için: zaten tam-synonym ise / kısa ise / alfabetik değilse → dokunma.
    Aksi halde metaphone'u haritada TAM eşleşiyorsa → kanonik forma çevir; yoksa → koru.
    MARKAYA dokunmaz (markaların metaphone'u synonym sözlüğünde TAM eşleşmez).
    """
    if not name:
        return name
    cc = country_code.upper()
    exact_sources = _exact_synonym_sources(cc)
    phon_map = build_synonym_phonetic_map(cc)
    out_tokens = []
    for tok in name.split():
        low = tok.lower()
        bare = low.replace(".", "")
        if (
            bare in exact_sources                     # zaten bilinen synonym → dokunma
            or len(bare) < MIN_TOKEN_LEN              # kısa → koru (marka/akronim)
            or not bare.isalpha()                     # rakam/karışık → koru
        ):
            out_tokens.append(tok)
            continue
        canon = phon_map.get(_primary_code(bare))
        out_tokens.append(canon if canon is not None else tok)
    return " ".join(out_tokens)


# get_legal_suffix_tokens / get_business_sector_tokens import edildi: gelecekte sınıf-bazlı
# genişletme/teşhis için; şu an map get_synonym_canonical_map üzerinden kuruluyor.
```

NOT: `get_legal_suffix_tokens`/`get_business_sector_tokens` import'ları ileride teşhis için; kullanılmıyorsa import'u silebilirsin (lint). Güvenli taraf: kullanılmayan iki import'u KALDIR — yalnız `get_synonym_canonical_map` kalsın.

- [ ] **Step 3: py_compile + import sanity (TEST DEĞİL)**

Run: `.venv\Scripts\python.exe -m py_compile core/synonym_phonetic.py`
Run: `.venv\Scripts\python.exe -c "from core.synonym_phonetic import canonicalize_phonetic; print(canonicalize_phonetic('acme limmtd','TR'))"`
Expected: bir string yazdırır (çökme yok). NOT: Bu bir import/sanity kontrolü; pytest DEĞİL.

- [ ] **Step 4: Commit (TEST KOŞMA)**

```
git add core/synonym_phonetic.py tests/test_synonym_phonetic.py
git commit -m "feat(phonetic): synonym-ici fonetik typo-rescue (canonicalize_phonetic, marka-korumali)"
```

---

## Task 3: Query tarafı wiring (pipeline match_name)

**Files:**
- Modify: `matching/pipeline.py`

`rec` parse-pass'te `match_name` (kanonikleştirilmiş) hesaplanır; iki query çağrısı `match_name` kullanır. `raw_name` audit/log için ORİJİNAL kalır.

- [ ] **Step 1: Import ekle**

`matching/pipeline.py` import bloğuna ekle (diğer `from core...` importlarının yanına):
```python
from core.synonym_phonetic import canonicalize_phonetic
```

- [ ] **Step 2: parse-pass'te match_name ekle**

`rec = {` sözlüğünün (parse-pass, ~709-716 civarı) içine `"match_name"` ekle:
```python
                        rec = {
                            "row_id": row_id,
                            "raw_name": raw_name,
                            "match_name": canonicalize_phonetic(raw_name, country),
                            "country": country,
                            "tax": row.get(col_tax) or "" if col_tax else "",
                            "phone": row.get(col_phone) or "" if col_phone else "",
                            "address": row.get(col_address) or "" if col_address else "",
                        }
```

- [ ] **Step 3: query çağrılarını match_name'e çevir**

`run_stage` içindeki query (satır ~113-116):
```python
        q = query_fn(
            name=rec["match_name"],
            country=rec["country"],
            tax_number=rec.get("tax", ""),
        )
```
`_build_stage_body` içindeki query (satır ~222):
```python
        q = query_fn(name=rec["match_name"], country=rec["country"], es=es)
```

- [ ] **Step 4: create_new_masters — kanonik variations + dedup key**

`create_new_masters` içinde, dedup key (satır ~298) ORİJİNAL yerine match_name kullanmalı (kanonik tutarlılık). `rec` burada match_name taşıyor:
```python
        norm_name = rec["match_name"].lower().strip()
```
Ve NEW_MASTER doc'unun variations name'i (satır ~346):
```python
                    "variations": [{"name": rec["match_name"]}],
```
NOT: create_new_masters duplicate_logs/log_rows'a yazılan isim (input_name) ORİJİNAL `rec["raw_name"]` KALSIN (audit). Yalnız ES'e giden variations + dedup-key match_name olur.

- [ ] **Step 5: py_compile + commit (TEST KOŞMA)**

Run: `.venv\Scripts\python.exe -m py_compile matching/pipeline.py`
```
git add matching/pipeline.py
git commit -m "feat(pipeline): query+index match_name (fonetik kanonik), audit raw_name korunur"
```

---

## Task 4: Index tarafı wiring (es_writer kanonik saklar)

**Files:**
- Modify: `matching/es_writer.py`

ES'e yazılan TÜM variation isimleri kanonikleştirilir (çekirdek simetrisi). Her fonksiyon kendi aldığı ismi canonicalize eder (rec'e bağımlı değil → self-contained).

- [ ] **Step 1: Import ekle**

`matching/es_writer.py` import'a ekle:
```python
from core.synonym_phonetic import canonicalize_phonetic
```

- [ ] **Step 2: _index_new_master — kanonik variation**

`_index_new_master` içinde doc kurulurken `rec["raw_name"]` yerine kanonik kullan:
```python
    cc = rec["country"]
    canon = canonicalize_phonetic(rec["raw_name"], cc)
    doc = {
        "master_id": master_id,
        "variations": [{"name": canon}],
        "variations_stripped": [],
        "country_code": cc.upper(),
    }
```
(Geri kalan phone/address/index çağrıları aynı kalır.)

- [ ] **Step 3: _add_variation_to_master — kanonik variation**

`_add_variation_to_master` başında, `variation` parametresini kanonikleştir:
```python
def _add_variation_to_master(
    es, master_doc_id: str, variation: str, country: str, rec: dict | None = None
) -> None:
    """Eşleşen kaydın varyasyonunu ve meta bilgilerini master doc'a ekler."""
    cc = country.upper()
    variation = canonicalize_phonetic(variation, country)
    v_lower = variation.lower().strip().rstrip(".,")
```
(Fonksiyonun geri kalanı aynı; `cc` zaten tanımlıydıysa tekrarı kaldır — mevcut `cc = country.upper()` satırıyla çakışmasın, tek tanım bırak.)

- [ ] **Step 4: update_es_variations — kanonik variation**

`update_es_variations` içinde, master_updates kurulurken `r["raw_name"]` variations'a eklenmeden kanonikleştir. `master_updates[mid]["variations"].add(r["raw_name"])` satırını:
```python
        master_updates[mid]["variations"].add(canonicalize_phonetic(r["raw_name"], r["country"]))
```

- [ ] **Step 5: build_new_master_doc — kanonik (kullanılıyorsa)**

`build_new_master_doc(name, country, ...)` içinde variations name'i kanonikleştir:
```python
    doc = {
        "_index": alias_for_country(country),
        "_id": master_id,
        "_source": {
            "master_id": master_id,
            "variations": [{"name": canonicalize_phonetic(name, country)}],
            "variations_stripped": [],
            "country_code": country.upper(),
        },
    }
```

- [ ] **Step 6: py_compile + commit (TEST KOŞMA)**

Run: `.venv\Scripts\python.exe -m py_compile matching/es_writer.py`
Run: `.venv\Scripts\python.exe -c "import matching.es_writer, matching.pipeline, core.synonym_phonetic; print('ok')"`
Expected: `ok`.
```
git add matching/es_writer.py
git commit -m "feat(es-writer): variations[].name fonetik kanonik saklanir (cekirdek simetrisi)"
```

---

## Task 5: Dokümantasyon

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md — fonetik kuralı + Python-metaphone istisnası**

CLAUDE.md §1'deki "PYTHON ÜZERİNDE FUZZY/LEVENSHTEIN YASAKTIR" admonition'ına bir istisna notu ekle (altına):
```
> **İSTİSNA — synonym-içi fonetik:** `core/synonym_phonetic.py` double-metaphone (saf-Python
> `metaphone` paketi) kullanır. Bu bir string-distance/Levenshtein DEĞİL, fonetik kodlamadır
> ve YALNIZCA synonym sözlüğüne (legal/sector/address) uygulanır — markaya/çekirdeğe ASLA.
> Bozuk-yazımlı synonym token'larını (limmtd→ltd.) kanonik forma çevirip çekirdek-exact
> recall'ını artırır. Kullanıcı onaylı; marka over-rescue guard'ları + altın-küme testi
> (`tests/test_synonym_phonetic.py`) ile korunur.
```

- [ ] **Step 2: CLAUDE.md §2 tablo**

§2 modül tablosuna satır ekle:
```
| `core/synonym_phonetic.py` | Python | Synonym-içi fonetik typo-rescue: bozuk synonym token'larını kanonik forma çevirir (markaya dokunmaz). |
```

- [ ] **Step 3: Commit**

```
git add CLAUDE.md
git commit -m "docs: synonym-ici fonetik typo-rescue kurali + modul tablosu (Plan 2a)"
```

---

## Self-Review Notları (yazar kontrolü)

- **Spec kapsamı (Madde 4):** fonetik typo-rescue ✓ (Task 2), yalnız-synonym/markaya-dokunmaz ✓ (guard'lar + Task 2 testleri), index+query simetri ✓ (Task 3+4). Geo/article istisnası belgelendi (kapsam dışı notu).
- **KRİTİK:** Testler KOŞULMADI (kullanıcı). Marka over-rescue gerçek riski → reindex öncesi `tests/test_synonym_phonetic.py` MUTLAKA koşulmalı (plan başındaki uyarı).
- **Tip tutarlılığı:** `canonicalize_phonetic(name, country) -> str` her çağrı yerinde aynı imza; `build_synonym_phonetic_map(cc) -> dict`; `get_synonym_canonical_map(cc, categories: tuple) -> dict`.
- **Wiring tamlığı:** query (run_stage 113, _build_stage_body 222) + index (es_writer _index_new_master/_add_variation_to_master/update_es_variations/build_new_master_doc + pipeline create_new_masters) — tüm ES-facing isim yolları kanonikleştirilir. `es/queries.py` DEĞİŞMEZ (match_name çağrı yerinden gelir).
- **Reindex:** variations[].name içeriği değişir → `python -m es.manager --force` + tam rematch gerekir (Plan 2 reindex penceresinde, address + synonym-yenileme ile birlikte).
