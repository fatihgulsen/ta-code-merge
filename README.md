# Firma Eslestirme ve Tekillestirme Sistemi

Buyuk olcekli firma verilerini analiz ederek "Master" kayitlarla eslestiren, kendi kendini egiten (yeni varyasyonlari ogrenen) ve Elasticsearch gucunu kullanan akilli bir eslestirme motorudur.

## Ozellikler

- **Ulke Izolasyonu (Hard Filter):** Farkli ulkelerdeki ayni isimli firmalar asla eslestirilmez.
- **Synonym Destegi:** "Co Ltd", "Inc", "A.S." gibi firma tipleri otomatik taninir.
- **Ogrenen Sistem:** Her yeni yazim sekli, varyasyon havuzuna eklenir.
- **Hibrit Skorlama:** Isim benzerligi + Vergi No + Telefon ile guclendirmis eslestirme.
- **Cross-Script:** Korece, Japonca gibi alfabeleri Latin karsiliklariyla eslestirir.
- **msearch Batch:** Toplu ES sorgusu ile yuksek performansli eslestirme.
- **ES-Side Scoring:** Post-verification mantigi ES Painless script ile ES tarafinda calisir.
- **Ingest Pipeline:** Firma ismi temizleme ES tarafinda otomatik uygulanir.
- **Duplicate Detection:** ES Transform ile surekli duplicate tespiti.

## Kurulum

### 1. Python Bagimliliklari

```bash
pip install -r requirements.txt
```

### 2. Elasticsearch Plugin'leri (Opsiyonel ama Onerilen)

```bash
# ICU plugin: Unicode normalizasyon ve Latin folding (latinize() yerine)
elasticsearch-plugin install analysis-icu

# Phonetic plugin: Fonetik benzerlik (transliterasyon varyantlari)
elasticsearch-plugin install analysis-phonetic

# Plugin kurulumu sonrasi ES restart gerekir
```

> Plugin'ler kurulu degilse sistem graceful fallback yapar:
> - ICU yoksa → `standard` analyzer kullanilir (variations.unidecode subfield)
> - Phonetic yoksa → phonetic tier sorgudan cikarilir

### 3. PostgreSQL Tablo

```bash
# Tablo olustur (gerekirse)
psql -d market_calculus -f schema.sql
```

`config.py` dosyasindaki `DB_CONFIG`, `RAW_TABLE_NAME`, `COLUMN_MAPPING` degerlerini kendi ortaminiza gore duzenleyin.

## Calistirma

### Hizli Baslangic (Sifirdan)

```bash
# 1. ES index olustur (routing + fingerprint + ngram + ICU + phonetic)
python es_manager.py

# 2. Ingest pipeline kaydet (firma ismi temizleme)
python es_ingest.py

# 3. Eslestirme islemini baslat
python main_processor.py
```

### Bastan Eslestirme (Sifirlama)

```bash
# PG + ES tamamen sifirla (master_code, match_score, match_type = NULL + index sil/olustur)
python reset_matching.py

# Sadece PG sifirla (ES index korunur)
python reset_matching.py --pg

# Sadece ES sifirla (PG korunur)
python reset_matching.py --es

# Ingest pipeline kaydet
python es_ingest.py

# Yeniden eslestir
python main_processor.py
```

### Mevcut Index'i Yeniden Olusturma

```bash
# Synonym degisikligi veya mapping guncellemesi sonrasi
python es_manager.py --force

# Ingest pipeline guncelle
python es_ingest.py

# Eslestirme (mevcut eslesmeler korunur, sadece NULL olanlar islenir)
python main_processor.py
```

### Duplicate Tespiti

```bash
# ES Transform olustur ve baslat (surekli calisan arka plan gorevi)
python es_transform.py

# Potansiyel duplicate'lari incele (interaktif)
python dedup_reviewer.py

# Minimum 3 master iceren gruplari goster
python dedup_reviewer.py 3
```

### Test ve Analiz

```bash
# Synonym normalizer test
python synonym_normalizer.py

# Eslesmeme analizi
python analyze_mismatches.py
```

## Mimari (v3)

```
PostgreSQL (ham veri)
    |
    v
[main_processor.py] --- batch okuma (5000 kayit)
    |
    +---> [matcher_logic.py: prepare_match_request()]
    |         Python pre-processing: light_clean + canonical_form
    |         Sorgu hazirlama: 7-tier bool query + rescore script
    |
    +---> [es_batch_search.py: batch_find_best_match()]
    |         msearch API ile toplu ES sorgusu (500'luk chunk)
    |         Country routing ile shard izolasyonu
    |
    +---> ES Index (living_companies_v1)
    |         Ingest Pipeline: otomatik temizleme
    |         7 Tier Scoring + Rescore (Painless script_score)
    |         Analyzer'lar: synonym, fingerprint, ngram, ICU, phonetic
    |
    +---> [matcher_logic.py: interpret_match_result()]
    |         ES _score tier'indan match_type belirleme
    |         >= 1000: CANONICAL_EXACT
    |         >= 500:  STRIPPED_EXACT
    |         >= 100:  TOKEN_COVERAGE
    |         < 100:   NEW_MASTER
    |
    v
PostgreSQL (master_code, match_score, match_type)
```

## Dosya Yapisi

### Cekirdek Dosyalar

| Dosya | Sorumluluk |
| --- | --- |
| `config.py` | Tum konfigurasyonlar, sabitler, esikler, MatchType |
| `matcher_logic.py` | Veri temizligi, ES sorgu olusturma, karar motoru |
| `main_processor.py` | Batch isleme dongusu (PG -> ES -> PG) |
| `es_manager.py` | ES index olusturma, mapping, analyzer tanimlama |

### ES-Side Modulleri

| Dosya | Sorumluluk |
| --- | --- |
| `es_batch_search.py` | msearch API ile toplu sorgu (5000 kayit/batch) |
| `es_ingest.py` | Ingest pipeline: light_clean ES tarafinda |
| `es_scripts.py` | Painless rescore script: post-verification ES tarafinda |
| `es_transform.py` | Continuous duplicate detection (ES Transform) |
| `dedup_reviewer.py` | Duplicate inceleme ve birlestirme araci |

### Veri ve Destek Dosyalari

| Dosya | Sorumluluk |
| --- | --- |
| `synonym_normalizer.py` | Canonical form ve stripped form hesaplama |
| `synonym_loader.py` | Synonym JSON dosyalarini yukleme |
| `synonyms_data/` | Ulke bazli synonym kurallari (65 JSON dosya) |
| `schema.sql` | PostgreSQL tablo semasi ve indeksler |
| `analyze_mismatches.py` | Eslesmeme analiz araci |

## ES Sorgu Hiyerarsisi (7 Tier)

| Tier | Sorgu Tipi | Boost | Aciklama |
| --- | --- | --- | --- |
| 1 | match_phrase variations | 100 | Canonical exact phrase |
| 2 | match_phrase variations_stripped | 50 | Suffix-free exact phrase |
| 3 | match variations (operator:and) | 10 | Tum tokenlar mevcut, sirasiz |
| 4 | match_phrase variations.fingerprint | 8 | Token sort+dedup, sirasiz |
| 5 | match_phrase variations.unidecode | 5 | ICU/Latinize exact phrase |
| 6 | match variations.ngram | 1 | Index-time fuzzy (trigram) |
| 7 | match variations.phonetic | 0.5 | Fonetik backstop |

+ **Rescore Phase:** Top 20 aday uzerinde Painless script_score ile CANONICAL_EXACT / STRIPPED_EXACT / TOKEN_COVERAGE kontrolu.

## Match Tipleri

| Tip | Skor | Aciklama |
| --- | --- | --- |
| TAX_MATCH | 100 | Vergi numarasi kesin eslesmesi (deterministic) |
| CANONICAL_EXACT | 100 | Synonym-aware canonical form tam eslesmesi |
| STRIPPED_EXACT | 100 | Suffix'ler temizlendikten sonra tam eslesmesi |
| TOKEN_COVERAGE | 90 | Anlamli tokenlarin simetrik ortusme esigi (>=%80) |
| NEW_MASTER | 100 | Eslesmedi - yeni firma kaydi olusturulur |

## ES Index Ozellikleri (v3)

- **Routing:** `country_code` bazli shard izolasyonu (HARD FILTER)
- **Fingerprint subfield:** Token sort + dedup (sirasiz eslestirme)
- **N-gram subfield:** Trigram tokenization (index-time fuzzy, 3-4 gram)
- **ICU subfield:** Unicode normalizasyon + Latin folding (plugin gerekir)
- **Phonetic subfield:** Double Metaphone (plugin gerekir)
- **Ingest Pipeline:** Index'leme sirasinda otomatik isim temizleme

## Konfigurasyonlar (config.py)

| Parametre | Deger | Aciklama |
| --- | --- | --- | --- |
| BATCH_SIZE | 5000 | Batch basina kayit sayisi |
| ES_MIN_SCORE | 3.0 | ES minimum relevance esigi |
| ES_TAX_WEIGHT | 100 | Tax eslesmesi boost agirlik |
| ES_PHONE_WEIGHT | 20 | Phone eslesmesi boost agirlik |
| TOKEN_COVERAGE_THRESHOLD | 0.8 | Token ortusme esigi (%80) |
| RESCORE_WINDOW_SIZE | 20 | Rescore top N aday sayisi |
| MSEARCH_CHUNK_SIZE | 500 | msearch basina max sorgu |

## Gelistirme Kurallari

- `synonyms_data/*.json` dosyalari **SABIT** - iceriklerine dokunulmaz
- ES index mapping yapisi degisirse `python es_manager.py --force` ile yeniden olustur
- Country code HARD FILTER - farkli ulke eslesmesi ASLA yapilmaz
- Firma isminde 1 harf bile farkliysa yeni firma (fuzzy sadece suffix icin)
- Post-ES verification ES rescore script tarafindan yapilir
