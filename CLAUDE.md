# Firma Eslestirme Sistemi — Gelistirme Kilavuzu

## Proje Amaci

Elasticsearch tabanli firma isim eslestirme sistemi. Farkli kaynaklardan gelen firma isimlerini (yazim hatalari, farkli uzantilar, farkli diller) tek bir master kayit altinda birlestirir.

## Mimari

```
PostgreSQL (ham veri) → Python (temizlik + normalizasyon) → Elasticsearch (eslestirme) → Python (dogrulama) → PostgreSQL (sonuc)
```

### Katmanlar

1. **Pre-Processing (Python):** `light_clean()` — label temizligi, suffix typo duzeltme, birlesmis suffix ayirma, nokta pattern normalizasyonu
2. **Normalizasyon (Python):** `canonical_form()` — synonym kurallari ile standart forma donusturme
3. **Eslestirme (ES):** `build_search_query()` — match_phrase + fuzzy match + function_score
4. **Dogrulama (Python):** Post-ES verification — CANONICAL_EXACT, STRIPPED_EXACT, TOKEN_COVERAGE
5. **Ogrenme:** Yeni varyasyonlar ES'e otomatik ogretilir

### Match Tipleri (Oncelik Sirasi)

| Tip | Skor | Aciklama |
|-----|------|----------|
| TAX_MATCH | 100 | Vergi numarasi kesin eslesmesi (deterministic) |
| CANONICAL_EXACT | 100 | Synonym-aware canonical form tam eslesmesi |
| STRIPPED_EXACT | 100 | Suffix'ler temizlendikten sonra tam eslesmesi |
| TOKEN_COVERAGE | 90 | Anlamli tokenlarin simetrik ortusme esigi |
| NEW_MASTER | 100 | Eslesmedi — yeni firma kaydi olusturulur |

## Dosya Yapisi

| Dosya | Sorumluluk |
|-------|------------|
| `config.py` | Tum konfigurasyonlar, sabitler, esikler |
| `matcher_logic.py` | Cekirdek eslestirme mantigi: temizlik, ES sorgusu, karar motoru |
| `synonym_normalizer.py` | Canonical form ve stripped form hesaplama |
| `synonym_loader.py` | Synonym JSON dosyalarini yukleme |
| `es_manager.py` | ES index olusturma, mapping, analyzer tanimlama |
| `main_processor.py` | Batch isleme dongusu (PG → ES → PG) |
| `synonyms_data/` | Ulke bazli synonym kurallari (JSON) |

## Gelistirme Kurallari

### Degistirilmemesi Gerekenler
- `synonyms_data/*.json` dosyalari **SABIT** — iceriklerine dokunulmaz
- ES index mapping yapisi (`es_manager.py`) — alan tipleri degismez
- `MatchType` sinifindan mevcut tiplerin isimleri degismez

### Temel Ilkeler
- **Firma isminde 1 harf bile farkliysa → yeni firma.** Fuzzy matching sadece suffix/uzanti icin gecerli, firma ismi icin ASLA
- **Country code HARD FILTER** — farkli ulke eslesmesi ASLA yapilmaz
- **ES tarafli eslestirme** — Python tarafinda fuzzy karsilastirma yapilmaz, tum fuzzy/scoring ES'te olur
- **Post-ES verification zorunlu** — ES sonuclari her zaman Python'da dogrulanir (CANONICAL_EXACT, STRIPPED_EXACT, TOKEN_COVERAGE)

### Suffix Typo Handling Stratejisi
Suffix yazim hatalari 3 katmanda yakalanir:
1. `light_clean()` → Python pre-processing (deterministik duzeltmeler)
2. ES query → `fuzziness: "AUTO"` ile ES tarafli fuzzy matching
3. `stripped_form()` → SUFFIX_TYPO_MAP + son-harf-fazlaligi kontrolu

### Yeni Suffix Typo Ekleme
`config.py` dosyasindaki `SUFFIX_TYPO_MAP` dictionary'sine ekle:
```python
SUFFIX_TYPO_MAP = {
    "yanlisyazim": "dogruyazim",
}
```

## Calistirma

```bash
# ES index olustur (ilk seferde)
python es_manager.py

# Zorla yeniden olustur (synonym degisikligi sonrasi)
python es_manager.py --force

# Eslestirme islemi
python main_processor.py

# Synonym normalizer testi
python synonym_normalizer.py

# Guvenlik testleri
python test_safety.py
python test_stripped_exact.py
```

## ES Sorgu Hiyerarsisi

| # | Sorgu Tipi | Boost | Aciklama |
|---|-----------|-------|----------|
| 1 | match_phrase variations | 2.0 | Canonical exact phrase |
| 2 | match_phrase variations_stripped | 1.5 | Suffix-free exact phrase |
| 3 | match variations (operator:and) | 1.2 | Tum tokenlar mevcut, sirasiz |
| 4 | match_phrase variations.unidecode | 1.0 | Latinize exact phrase |
| 5 | match variations (fuzziness:AUTO) | 0.8 | Fuzzy token eslesmesi |
| 6 | match variations_stripped (fuzziness:AUTO) | 0.6 | Fuzzy stripped eslesmesi |
