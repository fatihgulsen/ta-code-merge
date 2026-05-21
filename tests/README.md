# Test Suite Guide (Test Kılavuzu)

Bu dizin, Firma Eşleştirme ve Tekilleştirme Sistemi'nin kararlılığını garanti altına alan birim testlerini (`unit tests`) içerir.

---

## 1. Test Stratejisi & Mimarisi

Sistem birim testleri yaparken veritabanı veya canlı Elasticsearch cluster bağlantısına ihtiyaç duymaz. Test kalitesini yüksek tutmak ve hız kazanmak için mocking stratejisi uygulanmıştır:

1.  **Elasticsearch Mocking**:
    *   `tests/test_main_processor.py` içerisinde `MagicMock` kullanılarak ES `msearch` çıktıları simüle edilir. 
    *   Gelen sorguların min_score eşiklerini aşıp aşmadığı, stage kararlarının doğru verilip verilmediği mock hit listeleri ile doğrulanır.
2.  **Query DSL Doğrulama**:
    *   `tests/test_es_queries.py` dosyası, `es_queries.py` içindeki sorguların geçerli birer dict döndürdüğünü, `operator: "and"` kullanımını ve ngram/phrase ayarlarının doğruluğunu canlı sunucu olmadan test eder.
3.  **Config ve Stage Testleri**:
    *   `tests/test_config.py` stage sıralamalarının (`order`) doğru kurgulandığını denetler (örneğin: `STRIPPED_EXACT`'in `CANONICAL_EXACT`'ten sonra gelmesi).

---

## 2. Testleri Çalıştırma Komutları

Test suite `pytest` kütüphanesini kullanır. Bağımlılıkları kurduktan sonra aşağıdaki komutlarla testleri çalıştırabilirsiniz:

```bash
# Tüm testleri ayrıntılı çalıştır
pytest -v

# Sadece main_processor testlerini çalıştır
pytest tests/test_main_processor.py -v

# Sadece es_queries testlerini çalıştır
pytest tests/test_es_queries.py -v

# Test coverage raporu al (pytest-cov kurulu ise)
pytest --cov=. --cov-report=term-missing
```

---

## 3. Yeni Test Ekleme Kuralları

Yeni bir eşleştirme stage'i (`STAGES`) veya sorgu türü eklendiğinde:
1.  `tests/test_es_queries.py` dosyasına ilgili stage sorgusunun parametreleri ürettiğini doğrulayan bir test eklenmelidir.
2.  `tests/test_main_processor.py` dosyasına mock ES çıktısı üreten bir test eklenerek orkestrasyonun (matched / unmatched listeleri) doğru ayrıştığı test edilmelidir.
