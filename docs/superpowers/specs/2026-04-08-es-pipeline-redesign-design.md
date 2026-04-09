# ES Pipeline Redesign — Design Spec
**Date:** 2026-04-08  
**Project:** ta-code-merge (Firma Eşleştirme Sistemi)

---

## Amaç

Mevcut sistemde firma ismi normalizasyonu (temizlik, canonical form, stripped form) Python tarafında yapılmaktadır. Bu tasarım:

1. Tüm normalizasyonu ES Ingest Pipeline + Analyzer'a taşır — Python firma ismine dokunmaz.
2. Tek geçişli eşleştirme yerine **aşama-bazlı waterfall** modeli getirir.
3. Her aşamanın sonucunu `match_stages_log` tablosuna yazarak debug/audit kolaylığı sağlar.
4. Yeni stage eklemeyi/çıkarmayı/sıralamayı tek bir config listesi üzerinden mümkün kılar.

---

## Mimari Özet

```
PostgreSQL (ham veri)
    |
    v
[main_processor.py] — Stage-by-Stage Batch Orchestrator
    |
    |— Stage 1: TAX_EXACT        ← tüm batch msearch
    |     ↓ eşleşenler → PG yaz + match_stages_log
    |     ↓ unmatched → match_stages_log (matched=False)
    |     ↓ ES refresh
    |
    |— Stage 2: CANONICAL_EXACT  ← kalan kayıtlar msearch
    |     ↓ aynı pattern
    |
    |— Stage 3..6: aynı pattern
    |
    |— Stage 7: NEW_MASTER       ← hiç eşleşmeyen
          ↓ ES'e yeni doc yaz + PG yaz + match_stages_log

[es_queries.py]  — Tüm stage sorguları, fonksiyon adı = stage adı
[es_ingest.py]   — Ingest pipeline: normalizasyon ES tarafında
[config.py]      — STAGES listesi: tek kaynaktan stage yönetimi
```

**Python'un rolü:** Sadece orkestrasyon. Ham `name` değeri doğrudan ES'e gönderilir.

---

## Eşleştirme Modeli

**Waterfall (Huni):** Her kayıt sadece bir stage'de eşleşir. İlk eşleşmede durur, sonraki stage'ler denenmez.

**Stage geçişinde ES refresh:** Her stage sonunda NEW_MASTER'lar ES'e yazılır ve refresh yapılır. Böylece bir stage'de oluşan yeni master kayıtlar bir sonraki stage'de bulunabilir (within-batch duplicate sorunu minimize edilir).

---

## Stage Tanımları

| Sıra | Stage Adı | Açıklama | Güven |
|------|-----------|----------|-------|
| 1 | `TAX_EXACT` | Vergi no birebir eşleşme — deterministik | En yüksek |
| 2 | `CANONICAL_EXACT` | Synonym-aware canonical form tam phrase | Yüksek |
| 3 | `STRIPPED_EXACT` | Suffix temizlenmiş tam phrase | Yüksek |
| 4 | `TOKEN_COVERAGE` | Anlamlı token'ların ≥%80 örtüşmesi | Orta |
| 5 | `FUZZY_PHRASE` | match_phrase slop:3 (kelime sırası toleranslı) | Orta-düşük |
| 6 | `NGRAM_MATCH` | Trigram index-time fuzzy — en geniş ağ | Düşük |
| 7 | `NEW_MASTER` | Hiç eşleşmedi — yeni master oluşturulur | — |

---

## Dosya Yapısı

### Silinen Dosyalar
| Dosya | Neden |
|-------|-------|
| `matcher_logic.py` | light_clean, canonical_form ES'e taşındı; interpret_match_result yerini stage döngüsü aldı |
| `synonym_normalizer.py` | stripped_form, canonical_form ES analyzer'a taşındı |
| `es_batch_search.py` | Mantığı main_processor'a taşındı |

### Korunan Dosyalar
| Dosya | Değişim |
|-------|---------|
| `config.py` | `STAGES` listesi ve `STAGE_MIN_SCORES` eklenir |
| `es_manager.py` | Mevcut mapping korunur |
| `synonym_loader.py` | Korunur — ES analyzer synonym source olarak kullanılır |

### Yeni / Yeniden Yazılan Dosyalar
| Dosya | Açıklama |
|-------|----------|
| `es_queries.py` | Tüm stage sorguları — fonksiyon adı = stage adı |
| `es_ingest.py` | Ingest pipeline: Painless ile normalizasyon, typo fix, synonym |
| `main_processor.py` | Stage döngüsü orkestratörü — tam yeniden yazılır |

---

## config.py — STAGES Listesi

```python
STAGES = [
    {
        "name": "TAX_EXACT",
        "order": 1,
        "query_fn": "TAX_EXACT",
        "min_score": 1.0,
        "enabled": True,
    },
    {
        "name": "CANONICAL_EXACT",
        "order": 2,
        "query_fn": "CANONICAL_EXACT",
        "min_score": 50.0,
        "enabled": True,
    },
    {
        "name": "STRIPPED_EXACT",
        "order": 3,
        "query_fn": "STRIPPED_EXACT",
        "min_score": 30.0,
        "enabled": True,
    },
    {
        "name": "TOKEN_COVERAGE",
        "order": 4,
        "query_fn": "TOKEN_COVERAGE",
        "min_score": 10.0,
        "enabled": True,
    },
    {
        "name": "FUZZY_PHRASE",
        "order": 5,
        "query_fn": "FUZZY_PHRASE",
        "min_score": 5.0,
        "enabled": True,
    },
    {
        "name": "NGRAM_MATCH",
        "order": 6,
        "query_fn": "NGRAM_MATCH",
        "min_score": 3.0,
        "enabled": True,
    },
]
```

**Stage ekleme:** Listeye yeni dict ekle + `es_queries.py`'e aynı isimde fonksiyon yaz.  
**Stage çıkarma:** `"enabled": False` yap veya listeden sil.  
**Sıralama:** Listenin sırasını veya `order` değerini değiştir.

---

## es_queries.py — Stage Sorgu Fonksiyonları

Her fonksiyon sadece ES query body döner. `main_processor.py` bunu msearch'e paketler.

```python
def TAX_EXACT(name, country, tax_number=None, **kwargs) -> dict:
    """Vergi no birebir eşleşme — deterministik"""

def CANONICAL_EXACT(name, country, **kwargs) -> dict:
    """Synonym-aware canonical form tam phrase match"""

def STRIPPED_EXACT(name, country, **kwargs) -> dict:
    """Suffix temizlenmiş tam phrase match"""

def TOKEN_COVERAGE(name, country, **kwargs) -> dict:
    """Tüm anlamlı token'lar operator:and ile"""

def FUZZY_PHRASE(name, country, **kwargs) -> dict:
    """match_phrase slop:3 — kelime sırası toleranslı"""

def NGRAM_MATCH(name, country, **kwargs) -> dict:
    """Trigram subfield match — en geniş fuzzy ağ"""
```

**Kural:** Fonksiyon adı `config.STAGES`'deki `query_fn` değeri ile birebir aynı olmalı.

---

## es_ingest.py — Ingest Pipeline

Pipeline işlem sırası (index zamanında otomatik çalışır):

1. `lowercase` processor
2. Painless char filter: parantez içi temizle
3. Painless char filter: c/o, attn, to the order of temizle
4. Painless char filter: `&` → `"and"`
5. Painless char filter: `L.T.D.` → `LTD` (nokta-harf pattern)
6. Painless script: `PVTLTD` → `PVT LTD` (birleşik suffix ayırma)
7. Painless script: `INCC` → `INC` (çift-harf typo)
8. Painless script: `SUFFIX_TYPO_MAP` uygulaması (LIMTED → LIMITED vb.)

**Arama zamanında:** `search_analyzer` aynı normalizasyonu uygular — index ve sorgu aynı forma gelir.

**Synonym normalizasyonu:** `canonical_form` mantığı ES analyzer'daki `synonym` token filter'a taşınır. Ülke bazlı analyzer'lar korunur (`clean_analyzer_TR`, `clean_analyzer_DE` vb.).

---

## match_stages_log Tablosu

```sql
CREATE TABLE match_stages_log (
    id               SERIAL PRIMARY KEY,
    input_id         INTEGER,        -- p7_firms_v2.id
    input_name       TEXT,           -- ham firma adı
    country_code     VARCHAR(10),
    stage_name       VARCHAR(30),    -- TAX_EXACT, CANONICAL_EXACT, ...
    stage_order      INTEGER,        -- 1, 2, 3, ...
    matched          BOOLEAN,        -- bu aşamada eşleşti mi?
    master_id        TEXT,           -- eşleşen master (matched=true ise)
    es_score         FLOAT,          -- ES'ten dönen _score
    created_at       TIMESTAMP DEFAULT NOW()
);
```

**Okuma senaryosu:**
```sql
-- Bir kaydın hangi aşamalardan geçtiğini gör:
SELECT stage_name, stage_order, matched, es_score
FROM match_stages_log
WHERE input_id = 12345
ORDER BY stage_order;

-- Hangi stage en çok eşleşme yapıyor:
SELECT stage_name, COUNT(*) as match_count
FROM match_stages_log
WHERE matched = TRUE
GROUP BY stage_name ORDER BY match_count DESC;
```

---

## main_processor.py Yeni Akışı

```
1. PG'den master_code IS NULL kayıtları batch oku (BATCH_SIZE)
2. config.STAGES'den aktif (enabled=True) stage'leri sıralı al
3. unmatched_records = tüm batch kayıtları

4. Her stage için:
   a. unmatched_records'u msearch ile stage sorgusuna gönder (MSEARCH_CHUNK_SIZE'lık parçalar)
   b. min_score kontrolü → eşleşenleri ve eşleşmeyenleri ayır
   c. Eşleşenler:
      - p7_firms_v2: master_code, match_type, match_score güncelle
      - match_stages_log: matched=True, es_score yaz
      - unmatched_records'dan çıkar
   d. Eşleşmeyenler:
      - match_stages_log: matched=False yaz
   e. ES refresh (yeni master'lar varsa)
   f. unmatched_records ile sonraki stage'e geç

5. Tüm stage'ler bitti, hala unmatched varsa → NEW_MASTER:
   - ES'e yeni doc index'le
   - p7_firms_v2 güncelle
   - match_stages_log'a yaz (stage_name="NEW_MASTER", matched=True)
```

---

## Kısıtlar ve Değişmeyen Kurallar

- `synonyms_data/*.json` dosyaları **SABIT** — içeriklerine dokunulmaz
- **Country code HARD FILTER** — tüm ES sorgularında `filter: term country_code` zorunlu
- **Firma isminde 1 harf bile farklıysa yeni firma** — fuzzy sadece suffix/typo için
- ES mapping yapısı değişirse `python es_manager.py --force` ile yeniden oluştur
