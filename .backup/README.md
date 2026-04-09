# Firma Eşleştirme ve Tekilleştirme Sistemi

Büyük ölçekli firma verilerini analiz ederek "Master" kayıtlarla eşleştiren, kendi kendini eğiten (yeni varyasyonları öğrenen) ve Elasticsearch gücünü kullanan akıllı bir eşleştirme motorudur.

## Özellikler

- **Ülke İzolasyonu (Hard Filter):** Farklı ülkelerdeki aynı isimli firmalar asla eşleştirilmez.
- **Synonym Desteği:** "Co Ltd", "Inc", "A.Ş." gibi firma tipleri otomatik tanınır.
- **Öğrenen Sistem:** Her yeni yazım şekli, varyasyon havuzuna eklenir.
- **Hibrit Skorlama:** İsim benzerliği + Vergi No + Telefon ile güçlendirilmiş eşleştirme.
- **Cross-Script:** Korece, Japonca gibi alfabeleri Latin karşılıklarıyla eşleştirir.

## Kurulum

```bash
pip install -r requirements.txt
```

## Kullanım

```bash
# 1. Elasticsearch index oluştur
python es_manager.py

# 2. Eşleştirme işlemini başlat
python main_processor.py
```

## Mimari

```
PostgreSQL (raw_data)  →  Python (matcher_logic)  →  Elasticsearch (variations)
         ↑                         ↓
         └─── Sonuçlar (master_code, match_score) ───┘
```

## Dosya Yapısı

| Dosya | Açıklama |
|---|---|
| `config.py` | Bağlantı ayarları, eşik değerleri, synonym kuralları |
| `es_manager.py` | Elasticsearch index oluşturma ve yönetimi |
| `matcher_logic.py` | Eşleştirme mantığı ve puanlama motoru |
| `main_processor.py` | Batch veri işleme ve öğrenme döngüsü |
| `schema.sql` | PostgreSQL tablo şeması ve indeksler |
| `requirements.txt` | Python bağımlılıkları |
