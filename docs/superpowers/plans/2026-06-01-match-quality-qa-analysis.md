# Eşleştirme Kalitesi QA Analizi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PostgreSQL eşleştirme sonuçlarında over-merge (yanlış birleşme) ve split (yanlış bölünme) vakalarını tespit eden salt-okunur QA araç seti kurmak, bulguları raporlamak ve PHONETIC_MATCH over-merge'ü için onaylı TDD düzeltmesi uygulamak.

**Architecture:** İzole `analysis/` paketi salt-okunur SELECT ile `p7_firms_v2` kayıtlarını çeker; çekirdek-isim normalizasyonu (pipeline'ın `synonym_loader.get_legal_suffix_tokens` ek verisiyle) ve token-örtüşme küme işlemleriyle (fuzzy kütüphane YOK — yalnızca set kesişimi) iki dedektör çalıştırır. Şüpheli kümeler ES'e geri sorgulanarak (hibrit doğrulama) sorumlu stage kanıtlanır. Onaylı kök-nedenler `es_queries.py`/`config.py`'de TDD ile düzeltilir.

**Tech Stack:** Python 3, psycopg2 (salt-okunur), pytest + unittest.mock, mevcut `synonym_loader`/`es_queries`/`es_manager` modülleri, canlı Elasticsearch (doğrulama için).

---

## Dosya Yapısı

| Dosya | Sorumluluk |
| :--- | :--- |
| `core_name.py` (kök) | `normalize_core(name, country)` → ayırt edici çekirdek token tuple'ı (yasal ek + kısa/sayısal token düşürülür). Üretim-seviyesi saf helper; hem `es_queries` hem `analysis/` buradan import eder (bağımlılık yönü: analysis → üretim). |
| `analysis/__init__.py` | Paket işareti (boş). |
| `analysis/detectors.py` | `token_overlap`, `detect_over_merge`, `detect_splits` — in-memory satır listesi üzerinde çalışır; `load_matched_rows` salt-okunur SELECT. |
| `analysis/es_verify.py` | `verify_pair(es, name, country, stage_name)` — tek bir ismi ES'e ilgili stage query'siyle sorgular, hit'leri döner (hibrit B-ayağı). |
| `analysis/run_qa.py` | CLI giriş noktası: dedektörleri çalıştırır, top-N adayı yazdırır + CSV export. |
| `tests/test_analysis_core_name.py` | `normalize_core` birim testleri. |
| `tests/test_analysis_detectors.py` | `token_overlap`/`detect_*` birim testleri (in-memory veri). |
| `es_queries.py` (modify) | Faz 3: PHONETIC_MATCH kısa-çekirdek guard'ı. |
| `config.py` (modify) | Faz 3: `PHONETIC_MIN_CORE_TOKENS` sabiti. |
| `docs/audits/2026-06-01-match-quality-qa-findings.md` (create) | Faz 2: bulgu raporu + optimizasyon önerileri. |

---

## Faz 1 — QA Analiz Araç Seti (TDD)

### Task 1: Çekirdek İsim Normalizasyonu

**Files:**
- Create: `analysis/__init__.py`
- Create: `core_name.py` (proje kökü — üretim-seviyesi paylaşılan helper)
- Test: `tests/test_core_name.py`

- [ ] **Step 1: Boş paket dosyası oluştur**

`analysis/__init__.py`:
```python
```
(boş dosya)

- [ ] **Step 2: Başarısız testi yaz**

`tests/test_core_name.py`:
```python
from core_name import normalize_core


def test_strips_mx_legal_suffix_single_token():
    assert normalize_core("WITTE, S.A. DE C.V.", "MX") == ("witte",)
    assert normalize_core("IGSA S.A. DE C.V.", "MX") == ("igsa",)


def test_keeps_distinctive_multi_token_core():
    assert normalize_core("AUDI MEXICO S.A. DE C.V.", "MX") == ("audi", "mexico")
    assert normalize_core("KOHLER DE MEXICO S.A. DE C.V.", "MX") == ("kohler", "mexico")


def test_drops_single_char_and_numeric_tokens():
    # "O-TEK" → "o" (tek harf, düşer) + "tek"
    assert normalize_core("O-TEK MEXICO, S.A. DE C.V.", "MX") == ("tek", "mexico")
    assert normalize_core("FORM 123 S.A. DE C.V.", "MX") == ("form",)


def test_empty_and_whitespace():
    assert normalize_core("", "MX") == ()
    assert normalize_core("   ", "MX") == ()
```

- [ ] **Step 3: Testi çalıştır, başarısız olduğunu doğrula**

Run: `pytest tests/test_core_name.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_name'`

- [ ] **Step 4: Minimal implementasyonu yaz**

`core_name.py` (proje kökü):
```python
# ============================================================================
# core_name.py — Çekirdek-isim normalizasyonu (paylaşılan üretim helper'ı)
# ============================================================================
# Ham firma ismini, pipeline'ın yasal-ek verisini (synonym_loader) kullanarak
# ayırt edici "çekirdek" token'lara indirger. Hem es_queries (PHONETIC guard)
# hem analysis/ QA katmanı kullanır. Fuzzy kütüphane YOK (yalnızca set/regex).
# ============================================================================

import re
from functools import lru_cache

from synonym_loader import get_legal_suffix_tokens

# Yasal ek kısaltma parçaları (çok-kelimeli ek ifadelerinin tokenları + yaygın MX kısaltmaları)
_SUFFIX_FRAGMENTS = {"s", "a", "de", "c", "v", "sa", "cv", "sab", "rl", "sc", "sapi", "del"}

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=None)
def _strip_tokens(country: str) -> frozenset:
    """Ülkeye özgü düşürülecek token kümesi: yasal-ek parçaları + kısaltmalar."""
    out = set(_SUFFIX_FRAGMENTS)
    for phrase in get_legal_suffix_tokens(country):
        for tok in _TOKEN_SPLIT.split(phrase.lower()):
            if tok:
                out.add(tok)
    return frozenset(out)


def normalize_core(name: str, country: str) -> tuple[str, ...]:
    """Ham ismi ayırt edici çekirdek token tuple'ına indirger.

    Adımlar: lower → alfanümerik token'lara böl → sayısal / tek-harf /
    yasal-ek token'larını düş. Sıra korunur.
    """
    if not name:
        return ()
    strip = _strip_tokens(country.upper())
    tokens = [t for t in _TOKEN_SPLIT.split(name.lower()) if t]
    return tuple(t for t in tokens if not t.isdigit() and len(t) > 1 and t not in strip)
```

- [ ] **Step 5: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_core_name.py -v`
Expected: PASS (4 test)

- [ ] **Step 6: Commit**

```bash
git add analysis/__init__.py core_name.py tests/test_core_name.py
git commit -m "feat: add shared core-name normalization helper"
```

---

### Task 2: Token Örtüşme Metriği

**Files:**
- Create: `analysis/detectors.py`
- Test: `tests/test_analysis_detectors.py`

- [ ] **Step 1: Başarısız testi yaz**

`tests/test_analysis_detectors.py`:
```python
from analysis.detectors import token_overlap


def test_token_overlap_identical():
    assert token_overlap(("audi", "mexico"), ("audi", "mexico")) == 1.0


def test_token_overlap_disjoint():
    assert token_overlap(("witte",), ("igsa",)) == 0.0


def test_token_overlap_partial():
    # kesişim={mexico}=1, birleşim={audi,mexico,kohler}=3 → 1/3
    assert abs(token_overlap(("audi", "mexico"), ("kohler", "mexico")) - 1 / 3) < 1e-9


def test_token_overlap_empty_is_zero():
    assert token_overlap((), ("x",)) == 0.0
    assert token_overlap((), ()) == 0.0
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `pytest tests/test_analysis_detectors.py::test_token_overlap_identical -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.detectors'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`analysis/detectors.py`:
```python
# ============================================================================
# analysis/detectors.py — Over-merge / split QA dedektörleri (salt-okunur)
# ============================================================================
# p7_firms_v2 eşleşmiş kayıtlarını in-memory işler. Fuzzy kütüphane YOK —
# yalnızca küme (set) işlemleri. DB erişimi yalnızca SELECT.
# ============================================================================

from dataclasses import dataclass

import psycopg2
from psycopg2.extras import DictCursor

from config import DB_CONFIG, RAW_TABLE_NAME, COLUMN_MAPPING
from core_name import normalize_core


def token_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """İki token tuple'ı arasında Jaccard örtüşmesi (kesişim/birleşim)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union)
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_analysis_detectors.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add analysis/detectors.py tests/test_analysis_detectors.py
git commit -m "feat(analysis): add token_overlap metric"
```

---

### Task 3: Over-merge Dedektörü

**Files:**
- Modify: `analysis/detectors.py`
- Test: `tests/test_analysis_detectors.py`

- [ ] **Step 1: Başarısız testi yaz** (`tests/test_analysis_detectors.py` sonuna ekle)

```python
from analysis.detectors import detect_over_merge, MatchedRow


def _row(rid, master, name, country="MX", mtype="PHONETIC_MATCH"):
    return MatchedRow(id=rid, master_code=master, name=name, country=country, match_type=mtype)


def test_over_merge_flags_dissimilar_cluster():
    rows = [
        _row(1, "M1", "WITTE, S.A. DE C.V."),
        _row(2, "M1", "AUDI MEXICO S.A. DE C.V."),
        _row(3, "M1", "KOHLER DE MEXICO S.A. DE C.V."),
    ]
    findings = detect_over_merge(rows, threshold=0.3)
    assert len(findings) == 1
    f = findings[0]
    assert f.master_code == "M1"
    assert f.member_count == 3
    assert f.mean_overlap < 0.3
    assert f.dominant_match_type == "PHONETIC_MATCH"


def test_over_merge_ignores_consistent_cluster():
    rows = [
        _row(1, "M2", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M2", "AUDI MEXICO SA DE CV"),
    ]
    assert detect_over_merge(rows, threshold=0.3) == []


def test_over_merge_ignores_singletons():
    rows = [_row(1, "M3", "WITTE, S.A. DE C.V.")]
    assert detect_over_merge(rows, threshold=0.3) == []
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `pytest tests/test_analysis_detectors.py::test_over_merge_flags_dissimilar_cluster -v`
Expected: FAIL — `ImportError: cannot import name 'detect_over_merge'`

- [ ] **Step 3: Implementasyonu ekle** (`analysis/detectors.py` sonuna)

```python
from collections import Counter
from itertools import combinations


@dataclass(frozen=True)
class MatchedRow:
    id: object
    master_code: str
    name: str
    country: str
    match_type: str | None


@dataclass(frozen=True)
class OverMergeFinding:
    master_code: str
    member_count: int
    mean_overlap: float
    dominant_match_type: str | None
    sample_names: tuple[str, ...]


def detect_over_merge(rows: list[MatchedRow], threshold: float = 0.3) -> list[OverMergeFinding]:
    """Üyeleri birbirinden farklı (düşük token örtüşmeli) master kümelerini işaretler.

    Her master için üye çiftlerinin ortalama token örtüşmesini hesaplar;
    ortalama < threshold ise over-merge adayı. Tekil master'lar atlanır.
    Sonuç: (boyut × düşük-örtüşme) ağırlığına göre azalan sıralı.
    """
    by_master: dict[str, list[MatchedRow]] = {}
    for r in rows:
        if r.master_code:
            by_master.setdefault(r.master_code, []).append(r)

    findings: list[OverMergeFinding] = []
    for master, members in by_master.items():
        if len(members) < 2:
            continue
        cores = [normalize_core(m.name, m.country) for m in members]
        pairs = list(combinations(cores, 2))
        mean_overlap = sum(token_overlap(a, b) for a, b in pairs) / len(pairs)
        if mean_overlap < threshold:
            dom = Counter(m.match_type for m in members if m.match_type).most_common(1)
            findings.append(
                OverMergeFinding(
                    master_code=master,
                    member_count=len(members),
                    mean_overlap=mean_overlap,
                    dominant_match_type=dom[0][0] if dom else None,
                    sample_names=tuple(m.name for m in members[:5]),
                )
            )

    findings.sort(key=lambda f: f.member_count * (1.0 - f.mean_overlap), reverse=True)
    return findings
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_analysis_detectors.py -v`
Expected: PASS (önceki 4 + yeni 3 = 7 test)

- [ ] **Step 5: Commit**

```bash
git add analysis/detectors.py tests/test_analysis_detectors.py
git commit -m "feat(analysis): add over-merge detector"
```

---

### Task 4: Split Dedektörü

**Files:**
- Modify: `analysis/detectors.py`
- Test: `tests/test_analysis_detectors.py`

- [ ] **Step 1: Başarısız testi yaz** (`tests/test_analysis_detectors.py` sonuna)

```python
from analysis.detectors import detect_splits


def test_split_flags_same_core_different_master():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M11", "AUDI MEXICO SA DE CV"),  # aynı çekirdek, farklı master
    ]
    findings = detect_splits(rows)
    assert len(findings) == 1
    f = findings[0]
    assert f.core_signature == ("audi", "mexico")
    assert set(f.master_codes) == {"M10", "M11"}
    assert f.affected_rows == 2


def test_split_ignores_same_master():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M10", "AUDI MEXICO SA DE CV"),
    ]
    assert detect_splits(rows) == []


def test_split_respects_country_boundary():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V.", country="MX"),
        _row(2, "M11", "AUDI MEXICO", country="US"),
    ]
    # Farklı ülke → split sayılmaz (country hard-filter)
    assert detect_splits(rows) == []
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `pytest tests/test_analysis_detectors.py::test_split_flags_same_core_different_master -v`
Expected: FAIL — `ImportError: cannot import name 'detect_splits'`

- [ ] **Step 3: Implementasyonu ekle** (`analysis/detectors.py` sonuna)

```python
@dataclass(frozen=True)
class SplitFinding:
    country: str
    core_signature: tuple[str, ...]
    master_codes: tuple[str, ...]
    affected_rows: int
    sample_names: tuple[str, ...]


def detect_splits(rows: list[MatchedRow]) -> list[SplitFinding]:
    """Aynı ülkede özdeş çekirdek-imzaya sahip ama farklı master'a düşmüş kayıtları bulur.

    Çekirdek imza = normalize_core token'larının sıralı tuple'ı (sıra-bağımsız eşitlik).
    Bir (country, signature) altında >=2 farklı master_code varsa under-merge adayı.
    """
    groups: dict[tuple[str, tuple[str, ...]], list[MatchedRow]] = {}
    for r in rows:
        if not r.master_code:
            continue
        sig = tuple(sorted(normalize_core(r.name, r.country)))
        if not sig:
            continue
        groups.setdefault((r.country.upper(), sig), []).append(r)

    findings: list[SplitFinding] = []
    for (country, sig), members in groups.items():
        masters = {m.master_code for m in members}
        if len(masters) < 2:
            continue
        findings.append(
            SplitFinding(
                country=country,
                core_signature=sig,
                master_codes=tuple(sorted(masters)),
                affected_rows=len(members),
                sample_names=tuple(dict.fromkeys(m.name for m in members))[:5],
            )
        )

    findings.sort(key=lambda f: f.affected_rows, reverse=True)
    return findings
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_analysis_detectors.py -v`
Expected: PASS (7 + 3 = 10 test)

- [ ] **Step 5: Commit**

```bash
git add analysis/detectors.py tests/test_analysis_detectors.py
git commit -m "feat(analysis): add split detector"
```

---

### Task 5: DB Yükleyici + CLI + ES Doğrulayıcı

**Files:**
- Modify: `analysis/detectors.py` (load_matched_rows)
- Create: `analysis/run_qa.py`
- Create: `analysis/es_verify.py`

- [ ] **Step 1: `load_matched_rows` ekle** (`analysis/detectors.py` sonuna)

```python
def load_matched_rows(country: str | None = None) -> list[MatchedRow]:
    """Eşleşmiş (master_code dolu) kayıtları salt-okunur SELECT ile yükler."""
    col_id = COLUMN_MAPPING["id"]
    col_name = COLUMN_MAPPING["company_name"]
    col_country = COLUMN_MAPPING["country_code"]
    col_master = COLUMN_MAPPING["master_code"]
    col_type = COLUMN_MAPPING["match_type"]

    sql = psycopg2.sql.SQL(
        "SELECT {id}, {master}, {name}, {country}, {mtype} FROM {table} "
        "WHERE {master} IS NOT NULL"
    ).format(
        id=psycopg2.sql.Identifier(col_id),
        master=psycopg2.sql.Identifier(col_master),
        name=psycopg2.sql.Identifier(col_name),
        country=psycopg2.sql.Identifier(col_country),
        mtype=psycopg2.sql.Identifier(col_type),
        table=psycopg2.sql.Identifier(RAW_TABLE_NAME),
    )
    params: tuple = ()
    if country:
        sql = sql + psycopg2.sql.SQL(" AND {c} = %s").format(c=psycopg2.sql.Identifier(col_country))
        params = (country,)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute(sql, params)
        rows = [
            MatchedRow(
                id=r[col_id],
                master_code=r[col_master],
                name=(r[col_name] or "").strip(),
                country=(r[col_country] or "").strip().upper() or "DEFAULT",
                match_type=r[col_type],
            )
            for r in cur.fetchall()
        ]
        cur.close()
        return rows
    finally:
        conn.close()
```

`analysis/detectors.py` üstündeki importlara `import psycopg2.sql` ekle (zaten `import psycopg2` var).

- [ ] **Step 2: CLI yaz**

`analysis/run_qa.py`:
```python
# ============================================================================
# analysis/run_qa.py — QA dedektörlerini canlı DB üzerinde çalıştırır (salt-okunur)
# ============================================================================
# Kullanım:
#   python -m analysis.run_qa --country MX --top 30
# ============================================================================

import argparse
import csv

from analysis.detectors import load_matched_rows, detect_over_merge, detect_splits


def main() -> None:
    ap = argparse.ArgumentParser(description="Eşleştirme kalitesi QA dedektörleri")
    ap.add_argument("--country", default=None, help="Ülke kodu filtresi (örn. MX)")
    ap.add_argument("--top", type=int, default=30, help="Gösterilecek aday sayısı")
    ap.add_argument("--threshold", type=float, default=0.3, help="Over-merge örtüşme eşiği")
    ap.add_argument("--csv-prefix", default=None, help="Verilirse <prefix>_overmerge.csv / _splits.csv yazar")
    args = ap.parse_args()

    rows = load_matched_rows(args.country)
    print(f"Yüklenen eşleşmiş kayıt: {len(rows):,}")

    over = detect_over_merge(rows, threshold=args.threshold)
    splits = detect_splits(rows)

    print(f"\n=== OVER-MERGE adayları: {len(over)} (top {args.top}) ===")
    for f in over[: args.top]:
        print(f"  master={f.master_code} üye={f.member_count} örtüşme={f.mean_overlap:.2f} "
              f"stage={f.dominant_match_type} örnek={list(f.sample_names)}")

    print(f"\n=== SPLIT adayları: {len(splits)} (top {args.top}) ===")
    for f in splits[: args.top]:
        print(f"  {f.country} imza={list(f.core_signature)} master_sayisi={len(f.master_codes)} "
              f"kayit={f.affected_rows} örnek={list(f.sample_names)}")

    if args.csv_prefix:
        with open(f"{args.csv_prefix}_overmerge.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["master_code", "member_count", "mean_overlap", "dominant_match_type", "sample_names"])
            for f in over:
                w.writerow([f.master_code, f.member_count, f"{f.mean_overlap:.3f}",
                            f.dominant_match_type, " | ".join(f.sample_names)])
        with open(f"{args.csv_prefix}_splits.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["country", "core_signature", "master_count", "affected_rows", "sample_names"])
            for f in splits:
                w.writerow([f.country, " ".join(f.core_signature), len(f.master_codes),
                            f.affected_rows, " | ".join(f.sample_names)])
        print(f"\nCSV yazıldı: {args.csv_prefix}_overmerge.csv / _splits.csv")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: ES doğrulayıcı yaz**

`analysis/es_verify.py`:
```python
# ============================================================================
# analysis/es_verify.py — Hibrit doğrulama: bir ismi ES'e stage query'siyle sorgular
# ============================================================================
# Bir over-merge/split adayının sorumlu stage'ini canlı ES üzerinde kanıtlar.
# Kullanım:
#   python -m analysis.es_verify "WITTE, S.A. DE C.V." MX PHONETIC_MATCH
# ============================================================================

import sys

import es_queries as _eq
from es_manager import get_es_client
from config import ES_INDEX


def verify_pair(es, name: str, country: str, stage_name: str) -> list[dict]:
    """İsmi ilgili stage query'siyle ES'e sorgular, hit'leri (master_id, score, variation) döner."""
    query_fn = getattr(_eq, stage_name)
    body = query_fn(name=name, country=country, es=es)
    resp = es.search(index=ES_INDEX, body=body, routing=country.upper())
    out = []
    for h in resp["hits"]["hits"]:
        src = h.get("_source", {})
        out.append({
            "master_id": src.get("master_id"),
            "score": h["_score"],
            "variations": [v.get("name") for v in src.get("variations", []) if isinstance(v, dict)][:5],
        })
    return out


def main() -> None:
    if len(sys.argv) < 4:
        print("Kullanım: python -m analysis.es_verify '<isim>' <ülke> <STAGE_NAME>")
        sys.exit(1)
    name, country, stage = sys.argv[1], sys.argv[2], sys.argv[3]
    es = get_es_client()
    hits = verify_pair(es, name, country, stage)
    print(f"'{name}' [{country}] {stage} → {len(hits)} hit")
    for h in hits:
        print(f"  master={h['master_id']} score={h['score']:.2f} variations={h['variations']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Birim testlerin hâlâ geçtiğini doğrula** (yeni I/O kodu canlı bağımlılık; birim test gerektirmez)

Run: `pytest tests/test_core_name.py tests/test_analysis_detectors.py -v`
Expected: PASS (10 test)

- [ ] **Step 5: Commit**

```bash
git add analysis/detectors.py analysis/run_qa.py analysis/es_verify.py
git commit -m "feat(analysis): add DB loader, QA CLI and ES verifier"
```

---

## Faz 2 — Analizi Çalıştır, Triyaj, Rapor

### Task 6: Dedektörleri Canlı DB'de Çalıştır

**Files:** (yalnızca çalıştırma; kod değişikliği yok)

- [ ] **Step 1: Over-merge + split adaylarını üret ve CSV'ye yaz**

Run: `python -m analysis.run_qa --country MX --top 30 --csv-prefix qa_mx`
Expected: "Yüklenen eşleşmiş kayıt: ~62.950", over-merge ve split aday listeleri + `qa_mx_overmerge.csv` / `qa_mx_splits.csv`.

- [ ] **Step 2: En yüksek etkili over-merge'ü doğrula (49-üyeli master beklenir)**

Konsol çıktısında top over-merge adayının `stage=PHONETIC_MATCH`, `üye≈49`, düşük örtüşme ile geldiğini gözle teyit et. CSV'yi inceleyerek ilk 30 adayı not al.

- [ ] **Step 3: (commit yok — üretilen CSV'ler geçici analiz çıktısı; .gitignore'a eklenmez, repo'ya girmez)**

CSV'leri `.gitignore`'a ekle:
```bash
echo "qa_*.csv" >> .gitignore
git add .gitignore
git commit -m "chore: ignore QA analysis CSV outputs"
```

---

### Task 7: PHONETIC Over-merge Kök-Nedenini ES'te Doğrula

**Files:** (yalnızca çalıştırma)

- [ ] **Step 1: Tekil-çekirdek bir kurbanı ES'e geri sorgula**

Run: `python -m analysis.es_verify "WITTE, S.A. DE C.V." MX PHONETIC_MATCH`
Expected: Çöp/dev master'a bağlanan bir hit (variations içinde uzun gümrük-satırı kaydı). Sorumlu stage = PHONETIC_MATCH teyit edilir.

- [ ] **Step 2: İki-token bir kurbanı sorgula (token sayısı değil, dev-master sorunu mu?)**

Run: `python -m analysis.es_verify "AUDI MEXICO S.A. DE C.V." MX PHONETIC_MATCH`
Expected: Aynı dev master'a bağlanma. Bu, kök-nedenin "kısa çekirdek + dev/çöp master içine operator:and ile sızma" olduğunu netleştirir.

- [ ] **Step 3: İyi vs kötü skor dağılımını karşılaştır (eşik kalibrasyonu için)**

`match_type='PHONETIC_MATCH'` kayıtların `match_score` dağılımını incele:
```bash
python -c "import psycopg2; from config import DB_CONFIG, RAW_TABLE_NAME; c=psycopg2.connect(**DB_CONFIG); cur=c.cursor(); cur.execute(f\"SELECT min(match_score),percentile_disc(0.5) within group (order by match_score),max(match_score),count(*) FROM {RAW_TABLE_NAME} WHERE match_type='PHONETIC_MATCH'\"); print('min,median,max,count=',cur.fetchone()); c.close()"
```
Expected: skor aralığını not al — Faz 3 fix kararını besler.

- [ ] **Step 4: (commit yok — gözlemler Task 8 raporuna girer)**

---

### Task 8: Bulgu Raporunu Yaz

**Files:**
- Create: `docs/audits/2026-06-01-match-quality-qa-findings.md`

- [ ] **Step 1: Raporu oluştur**

`docs/audits/2026-06-01-match-quality-qa-findings.md` — Task 6/7 gerçek çıktılarıyla doldurulacak bölümler:
- **Yönetici özeti:** toplam over-merge aday sayısı, split aday sayısı, en kritik vaka.
- **Metrikler:** yüklenen kayıt, match_type dağılımı, grup-boyutu dağılımı (keşiften: 49/11/9/8...).
- **Over-merge bulguları:** top-N tablo (master, üye, örtüşme, stage, örnek isimler). 49-üyeli PHONETIC_MATCH vakası ayrıntılı kök-neden (çöp master + operator:and sızması, ES doğrulama çıktısı dahil).
- **Split bulguları:** top-N tablo (imza, master sayısı, etkilenen kayıt, örnekler).
- **Optimizasyon önerileri (öncelik sırasıyla):**
  1. PHONETIC_MATCH kısa-çekirdek guard'ı (Faz 3'te uygulanıyor).
  2. Çöp/aşırı-uzun kayıtların master olmasını engelleyen ingest-seviyesi guard (takip planı).
  3. Split'ler için ilgili stage gevşetme/ekleme önerileri (her biri ES doğrulamasına tabi).
- **Legacy residue notu:** `EXACT_FUZZY`/`ADDRESS_CLEAN_MATCH`/`SUBSET_MATCH` eski sürümden; güncel stage önerileriyle karıştırılmaz.

- [ ] **Step 2: Commit**

```bash
git add docs/audits/2026-06-01-match-quality-qa-findings.md
git commit -m "docs(audit): add match-quality QA findings report"
```

---

## Faz 3 — Onaylı Over-merge Düzeltmesi: PHONETIC_MATCH Kısa-Çekirdek Guard'ı (TDD)

> **Checkpoint:** Bu faza Task 7 PHONETIC_MATCH'i sorumlu stage olarak kanıtladıktan SONRA geçilir. Guard, tekil-ayırt-edici-token isimlerin dev master'lara `operator:and` ile sızmasını engeller (en net alt-sınıf). Çok-token dev-master vakaları rapor önerisi (2) ile takip planına bırakılır.

### Task 9: PHONETIC_MATCH kısa-çekirdek guard'ı

**Files:**
- Modify: `config.py` (yeni sabit)
- Modify: `es_queries.py:292-319` (PHONETIC_MATCH)
- Test: `tests/test_es_queries.py`

- [ ] **Step 1: Başarısız testi yaz** (`tests/test_es_queries.py` sonuna)

```python
def test_phonetic_match_blocks_short_core():
    # Tek ayırt edici token (yasal ek çıkınca "witte") → guard devreye girer:
    # eşleşmeyi imkânsız kılan bir filtre döner (dev master'a sızmayı önler).
    q = es_queries.PHONETIC_MATCH("WITTE, S.A. DE C.V.", "MX")
    assert q == es_queries.MATCH_NONE


def test_phonetic_match_allows_multi_token_core():
    # İki+ ayırt edici token → normal fonetik query döner.
    q = es_queries.PHONETIC_MATCH("AUDI MEXICO S.A. DE C.V.", "MX")
    bool_q = q["query"]["bool"]
    nested = next(c["nested"] for c in bool_q["must"] if "nested" in c)
    assert nested["path"] == "variations_stripped"
    assert _get_country_filter(q) == "MX"
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `pytest tests/test_es_queries.py::test_phonetic_match_blocks_short_core -v`
Expected: FAIL — `AttributeError: module 'es_queries' has no attribute 'MATCH_NONE'`

- [ ] **Step 3: config sabitini ekle** (`config.py`, `RESCORE_WINDOW_SIZE` yakınına)

```python
# PHONETIC_MATCH guard — bu kadar az ayırt edici çekirdek token'da fonetik eşleşme
# dev/çöp master'lara operator:and ile sızdığından devre dışı bırakılır.
PHONETIC_MIN_CORE_TOKENS = 2
```

- [ ] **Step 4: PHONETIC_MATCH'i guard ile güncelle** (`es_queries.py`)

`es_queries.py` üst importlara ekle:
```python
from core_name import normalize_core
from config import PHONETIC_MIN_CORE_TOKENS
```

`PHONETIC_MATCH` fonksiyonundan hemen önce ekle:
```python
# Hiçbir dokümanla eşleşmeyen sentinel query — guard'lar tarafından kullanılır.
MATCH_NONE = {"query": {"bool": {"must_not": [{"match_all": {}}]}}, "size": 0}
```

`PHONETIC_MATCH` gövdesinin başına (docstring'den sonra) guard ekle:
```python
    core = normalize_core(name, country)
    if len(core) < PHONETIC_MIN_CORE_TOKENS:
        return MATCH_NONE
```

- [ ] **Step 5: Testi çalıştır, geçtiğini doğrula**

Run: `pytest tests/test_es_queries.py -v`
Expected: PASS (mevcut + 2 yeni test)

- [ ] **Step 6: Canlı ES'te kurbanın artık eşleşmediğini doğrula**

Run: `python -m analysis.es_verify "WITTE, S.A. DE C.V." MX PHONETIC_MATCH`
Expected: 0 hit (MATCH_NONE → boş sonuç). Önce-sonra farkını rapora not düş.

- [ ] **Step 7: Tüm test paketini çalıştır (regresyon)**

Run: `pytest -v`
Expected: Tüm testler PASS (mevcut paket kırılmamış).

- [ ] **Step 8: Commit**

```bash
git add config.py es_queries.py tests/test_es_queries.py
git commit -m "fix(es_queries): guard PHONETIC_MATCH against short-core over-merge"
```

---

## Faz 4 — Split Önerileri (rapor; uygulama ES doğrulamasına tabi)

### Task 10: Split bulgularını raporla + önerilen düzeltmeyi kayıt altına al

**Files:**
- Modify: `docs/audits/2026-06-01-match-quality-qa-findings.md`

- [ ] **Step 1: Top split adaylarını ES'te doğrula**

Her top split adayı için iki master'ın temsilci isimlerini ilgili exact/stripped stage ile sorgula:
Run: `python -m analysis.es_verify "<split örnek isim>" MX STRIPPED_EXACT`
Expected: Aynı çekirdek isimlerin neden ayrı master'a düştüğünü gözle (örn. ek/typo farkı, stripping boşluğu).

- [ ] **Step 2: Raporun split bölümünü kök-neden + öneriyle güncelle**

Her doğrulanan split deseni için: sorumlu eksiklik (örn. belirli bir ekin stripping'de yakalanmaması) + önerilen düzeltme (örn. `config`/analyzer ayarı). Düzeltme uygulaması, over-merge fix'i gibi ayrı RED→GREEN döngüsüyle ve kullanıcı onayıyla yapılır — bu plan kapsamında yalnızca önerilir.

- [ ] **Step 3: Commit**

```bash
git add docs/audits/2026-06-01-match-quality-qa-findings.md
git commit -m "docs(audit): document split findings and recommended fixes"
```

---

## Self-Review Notları

- **Spec kapsamı:** Over-merge tespiti (Task 3), split tespiti (Task 4), hibrit doğrulama (Task 5/7), uzantısız token-örtüşme (Task 2), rapor (Task 8), onaylı TDD düzeltmesi (Task 9), split önerisi (Task 10) — tüm spec bölümleri karşılandı.
- **Tip tutarlılığı:** `MatchedRow`/`OverMergeFinding`/`SplitFinding` tek yerde tanımlı; `normalize_core`/`token_overlap` imzaları testlerle birebir.
- **Placeholder yok:** Tüm kod adımları gerçek, doğrulanmış kod (Task 1-5, 9 keşif sırasında canlı veriyle doğrulandı). Faz 2 adımları somut komut + beklenen çıktı.
- **Country hard-filter:** Split dedektörü `country` sınırında kalır (Task 4 testi). CLAUDE.md ilkesine uygun.
- **Fuzzy yasağı:** Analiz katmanı yalnızca küme işlemleri kullanır; matching pipeline'ına fuzzy kütüphane sokulmaz.
