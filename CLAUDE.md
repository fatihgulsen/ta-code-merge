# Firma Eşleştirme Sistemi — AI Development Guide (CLAUDE.md)

This guide acts as the strict operational runbook and instruction filter for AI agents (Claude, Gemini) developing on this codebase.

---

## 1. Geliştirici Aforizmaları & Katı Kurallar (Strict AI Guidelines)

> [!IMPORTANT]
> **COUNTRY CODE IS A HARD FILTER**:
> Eşleştirme, indeksleme, arama ve doğrulama süreçlerinin tamamında `country_code` baz alınır. Farklı ülkelerdeki firmalar **ASLA** eşleşemez.

> [!IMPORTANT]
> **PER-COUNTRY INDEX**: Her ülke kendi fiziksel index'ine (`living_companies_<cc>_v3`) sahiptir,
> üstünde alias `living_companies_<cc>`. Tüm okuma/yazma alias üzerinden yapılır; `_routing`
> KULLANILMAZ (ülke izolasyonu fizikseldir). Geçersiz/bilinmeyen ülke kodu (synonyms_data'da
> JSON'u olmayan) EXCLUDED(invalid_country) olarak işaretlenir ve indekslenmez.

> [!WARNING]
> **PYTHON ÜZERİNDE FUZZY/LEVENSHTEIN YASAKTIR**:
> Python kodu içerisinde `RapidFuzz`, `Levenshtein` vb. ağır kütüphanelerle string benzerliği aramak **KATI BİR ŞEKİLDE YASAKTIR.** Fuzzy yetenekleri Elasticsearch Query DSL (`fuzziness: "AUTO"`) ve Painless script rescore adımları ile ES tarafında çözülür.

> [!NOTE]
> **İSTİSNA — synonym-içi fonetik:** `core/synonym_phonetic.py` double-metaphone (saf-Python
> `metaphone` paketi) kullanır. Bu string-distance/Levenshtein DEĞİL, fonetik kodlamadır ve
> YALNIZCA synonym sözlüğüne (legal/sector/address) uygulanır — markaya/çekirdeğe ASLA. Bozuk
> yazımlı synonym token'larını (limtd→ltd.) kanonik forma çevirip çekirdek-exact recall'ını
> artırır. Eşleşme metaphone kodunda tam/prefix/≤1-sub; marka over-rescue guard'ları (token
> len≥5, ambiguity-skip) + altın-küme testi (`tests/test_synonym_phonetic.py`) ile korunur.
> Geo + article sınıfları kapsam dışıdır.

1.  **PostgreSQL Güvenliği**: raw string interpolation (`f"SELECT ... '{val}'"`) kullanılmamalıdır. Her zaman parametrik sorgular (`%s`) tercih edilmeli, toplu güncellemelerde `psycopg2.extras.execute_values` kullanılmalıdır.
2.  **Index Yönetimi**: Elasticsearch index şeması, mapping'leri ve özel analyzer'lar sadece `es/manager.py` üzerinden yönetilmelidir. Ad-hoc veya geçici indeks oluşturmak yasaktır.
3.  **Hata Yönetimi (Exception Handling)**: Toplu batch eşleştirmeleri sırasında tek bir satırda veya kayıtta hata alınırsa tüm batch işlemi durdurulmamalıdır. Hata loglanmalı, veritabanı rollback edilerek diğer kayıtlar için işlem devam etmelidir.
4.  **Synonym JSON Dosyalarının Dokunulmazlığı**: `synonyms_data/` altındaki 65 ülke JSON dosyası **SABİTTİR.** İçeriklerindeki hataları düzeltmek veya yeni ekleme yapmak gerekirse `config.py` içerisindeki `SUFFIX_TYPO_MAP` veya kod içi eşleşme kuralları güncellenmelidir.
    *   **İSTİSNA — `non_firm_placeholders` kategorisi**: Firma-OLMAYAN placeholder'lar ("ticari unvan yok" / "alıcı=gönderici": `sin razon social`, `same as cnee` vb.) **hardcode edilmez**, bu kategori altında JSON'da tutulur ve **eklemeye AÇIKTIR** (ortaklar `common.json`, ülkeye-özgü olanlar `<cc>.json`). `synonym_loader.get_non_firm_placeholders(cc)` okur, `input_filter` TAM eşleşmeyle EXCLUDED yapar. Bu kategori bir Solr synonym kuralı (`A,B=>C`) DEĞİLDİR, ES analyzer'a girmez — düz ifade listesidir.

---

## 2. Geliştirici Kılavuzu: Dosya Yapısı & Sorumlulukları

| Modül | Dil | Rolü & Sorumluluğu |
| :--- | :---: | :--- |
| `config.py` | Python | Eşik değerleri (`TOKEN_COVERAGE_THRESHOLD`), DB/ES bağlantıları, MatchType listesi ve aktif `STAGES` konfigürasyonları. |
| `main_processor.py` | Python | **Çalıştırma giriş noktası**: `matching.pipeline.process_all_data()` çağırır. Orkestrasyon mantığı `matching/pipeline.py` içindedir. |
| `matching/pipeline.py` | Python | **Orkestrasyon**: Stage çalıştırma, `msearch` tetikleme, kazanan seçimi ve ana eşleştirme döngüsü. |
| `matching/db_io.py` | Python | PostgreSQL I/O: bağlantı, şema doğrulama, eşleşme/stage-log yazımı. |
| `matching/es_writer.py` | Python | ES master-doc yazımı: varyasyon/meta ekleme, yeni master indeksleme. |
| `es/queries.py` | Python | Her stage için Elasticsearch Query DSL generator fonksiyonları. |
| `es/manager.py` | Python | Per-country index + alias konfigürasyonu: Her ülke için fiziksel `living_companies_<cc>_v3` indeksi ve alias `living_companies_<cc>` oluşturur. Custom analyzer'ları (fingerprint, ngram, phonetic) ve mapping'leri yönetir. |
| `es/ingest.py` | Python | Doküman indekslenirken Painless scriptler ile veri temizliği yapan ingest pipeline'ları. |
| `es/transform.py` | Python | Arka planda sürekli çalışan ve duplicate adayları bulan ES Transform yönetimi. |
| `core/synonym_loader.py` | Python | `synonyms_data/` klasöründeki JSON dosyalarını parse eden ve kelimeleri gruplayan yükleyici. |
| `core/core_name.py` | Python | Firma adı normalizasyonu ve `_first_meaningful_token` hesaplama. |
| `core/input_filter.py` | Python | Girdi doğrulama ve `non_firm_placeholders` bazlı EXCLUDED filtrelemesi. |
| `core/synonym_phonetic.py` | Python | Synonym-içi fonetik typo-rescue: bozuk synonym token'larını kanonik forma çevirir (double-metaphone; markaya dokunmaz). |
| `dedup/reviewer.py` | Python | ES Transform çıktılarını insan denetiminde birleştiren interaktif konsol aracı. |
| `dedup/auto_merge.py` | Python | Yüksek güvenilirlikli duplicate adayları otomatik birleştiren toplu işlem aracı. |

---

## 3. Geliştirme ve Test Komutları

### Eşleştirme Sürecini Çalıştırma
```bash
# Ingest pipeline kur
python -m es.ingest

# Per-country indeksleri kur ve mapping'leri güncelle (synonym değişirse --force kullanın)
python -m es.manager

# Eşleştirmeyi başlat
python main_processor.py
```

### Testleri Çalıştırma
```bash
# Tüm testleri çalıştır
pytest -v

# Belirli bir testi çalıştır
pytest tests/test_main_processor.py -v
```

---

## 4. Bilinen Kısıtlamalar & Legacy Notları

*   **Offline benzerlik/eşleşme analizi**:
    Bir ismin hangi aşamada eşleştiğini görmek veya offline benzerlik analizi yapmak için `analysis/live_probe.py` kullanılır. Temizleme mantığı tamamen ES Ingest Pipeline (`es/ingest.py`) ve Painless scriptlerinde olduğundan, offline çıktı ES `_analyze` API'si ya da `core/synonym_loader.py` fonksiyonları üzerinden alınır. (Eski `debug_match.py` aracı, kaldırılmış helper'lara bağımlı kaldığı için kaldırıldı.)
