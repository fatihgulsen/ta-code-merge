# Firma Eşleştirme Sistemi — AI Development Guide (CLAUDE.md)

This guide acts as the strict operational runbook and instruction filter for AI agents (Claude, Gemini) developing on this codebase.

---

## 1. Geliştirici Aforizmaları & Katı Kurallar (Strict AI Guidelines)

> [!IMPORTANT]
> **COUNTRY CODE IS A HARD FILTER**:
> Eşleştirme, indeksleme, arama ve doğrulama süreçlerinin tamamında `country_code` baz alınır. Farklı ülkelerdeki firmalar **ASLA** eşleşemez. `_routing` parametresi her zaman büyük harfli `country_code` olmalıdır.

> [!WARNING]
> **PYTHON ÜZERİNDE FUZZY/LEVENSHTEIN YASAKTIR**:
> Python kodu içerisinde `RapidFuzz`, `Levenshtein` vb. ağır kütüphanelerle string benzerliği aramak **KATI BİR ŞEKİLDE YASAKTIR.** Fuzzy yetenekleri Elasticsearch Query DSL (`fuzziness: "AUTO"`) ve Painless script rescore adımları ile ES tarafında çözülür.

1.  **PostgreSQL Güvenliği**: raw string interpolation (`f"SELECT ... '{val}'"`) kullanılmamalıdır. Her zaman parametrik sorgular (`%s`) tercih edilmeli, toplu güncellemelerde `psycopg2.extras.execute_values` kullanılmalıdır.
2.  **Index Yönetimi**: Elasticsearch index şeması, mapping'leri ve özel analyzer'lar sadece `es_manager.py` üzerinden yönetilmelidir. Ad-hoc veya geçici indeks oluşturmak yasaktır.
3.  **Hata Yönetimi (Exception Handling)**: Toplu batch eşleştirmeleri sırasında tek bir satırda veya kayıtta hata alınırsa tüm batch işlemi durdurulmamalıdır. Hata loglanmalı, veritabanı rollback edilerek diğer kayıtlar için işlem devam etmelidir.
4.  **Synonym JSON Dosyalarının Dokunulmazlığı**: `synonyms_data/` altındaki 65 ülke JSON dosyası **SABİTTİR.** İçeriklerindeki hataları düzeltmek veya yeni ekleme yapmak gerekirse `config.py` içerisindeki `SUFFIX_TYPO_MAP` veya kod içi eşleşme kuralları güncellenmelidir.
    *   **İSTİSNA — `non_firm_placeholders` kategorisi**: Firma-OLMAYAN placeholder'lar ("ticari unvan yok" / "alıcı=gönderici": `sin razon social`, `same as cnee` vb.) **hardcode edilmez**, bu kategori altında JSON'da tutulur ve **eklemeye AÇIKTIR** (ortaklar `common.json`, ülkeye-özgü olanlar `<cc>.json`). `synonym_loader.get_non_firm_placeholders(cc)` okur, `input_filter` TAM eşleşmeyle EXCLUDED yapar. Bu kategori bir Solr synonym kuralı (`A,B=>C`) DEĞİLDİR, ES analyzer'a girmez — düz ifade listesidir.

---

## 2. Geliştirici Kılavuzu: Dosya Yapısı & Sorumlulukları

| Modül | Dil | Rolü & Sorumluluğu |
| :--- | :---: | :--- |
| `config.py` | Python | Eşik değerleri (`TOKEN_COVERAGE_THRESHOLD`), DB/ES bağlantıları, MatchType listesi ve aktif `STAGES` konfigürasyonları. |
| `main_processor.py` | Python | **Orkestrasyon**: PG'den veri okuma, her kayıt için `msearch` tetikleme, kazanan eşleşmeyi belirleme, variations/meta update etme ve DB'ye yazma. |
| `es_queries.py` | Python | Her stage için Elasticsearch Query DSL generator fonksiyonları. |
| `es_manager.py` | Python | Custom analyzer'ları (fingerprint, ngram, phonetic) ve index mapping'lerini ayağa kaldıran ES yönetimi. |
| `es_ingest.py` | Python | Doküman indekslenirken Painless scriptler ile veri temizliği yapan ingest pipeline'ları. |
| `synonym_loader.py` | Python | `synonyms_data/` klasöründeki JSON dosyalarını parse eden ve kelimeleri gruplayan yükleyici. |
| `es_transform.py` | Python | Arka planda sürekli çalışan ve duplicate adayları bulan ES Transform yönetimi. |
| `dedup_reviewer.py` | Python | ES Transform çıktılarını insan denetiminde birleştiren interaktif konsol aracı. |

---

## 3. Geliştirme ve Test Komutları

### Eşleştirme Sürecini Çalıştırma
```bash
# Ingest pipeline kur
python es_ingest.py

# Index kur ve mapping güncelle (synonym değişirse --force kullanın)
python es_manager.py

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
    Bir ismin hangi aşamada eşleştiğini görmek veya offline benzerlik analizi yapmak için `analysis/live_probe.py` kullanılır. Temizleme mantığı tamamen ES Ingest Pipeline (`es_ingest.py`) ve Painless scriptlerinde olduğundan, offline çıktı ES `_analyze` API'si ya da `synonym_loader.py` fonksiyonları üzerinden alınır. (Eski `debug_match.py` aracı, kaldırılmış helper'lara bağımlı kaldığı için kaldırıldı.)
