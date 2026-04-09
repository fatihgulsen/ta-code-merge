# Dinamik Sutun Mapping Tasarimi

## Ozet

`p7_firms_v2` tablosunun sutun isimlerini PostgreSQL'den otomatik okuyup `config.py`'deki `COLUMN_MAPPING` dictionary'sini olusturan tek seferlik generator script.

## Problem

Mevcut `COLUMN_MAPPING` statik olarak tanimli. Farkli ortamlarda tablo sutun isimleri degistiginde kullanici hangi sutunlarin var oldugunu bilmeden config'i elle yazmak zorunda.

## Cozum

Yeni bir `generate_config.py` scripti:

1. `config.py`'den `DB_CONFIG` ve `RAW_TABLE_NAME`'i import eder
2. PostgreSQL'e baglanir
3. `information_schema.columns` ile `p7_firms_v2`'nin tum sutunlarini ceker (isim + veri tipi)
4. `config.py` dosyasini okur, `COLUMN_MAPPING = {` ile baslayan blogu bulur
5. Yeni bir `COLUMN_MAPPING` olusturur — DB'deki her sutun hem sol hem sag tarafa yazilir (kullanici sol tarafi degistirir)
6. `config.py`'yi gunceller (sadece COLUMN_MAPPING blogu degisir, dosyanin gerisi aynen kalir)

## Akis

```
python generate_config.py
    |
    v
DB'ye baglan -> p7_firms_v2 sutunlarini oku
    |
    v
config.py'deki COLUMN_MAPPING blogunu bul
    |
    v
Yeni COLUMN_MAPPING olustur (DB sutunlari hem sol hem sag tarafa yazilir)
    |
    v
config.py'yi guncelle
    |
    v
Kullanici config.py'yi acar, None'lari internal isimlerle doldurur
    |
    v
python main_processor.py (mevcut gibi calisir)
```

## Ornek Cikti

Generator calistiktan sonra `config.py`'deki COLUMN_MAPPING:

```python
# generate_config.py tarafindan otomatik olusturuldu.
# Sol taraftaki isimleri degistirin. Sag taraf DB sutunlaridir.
# Zorunlu internal isimler: id, company_name, country_code
# Zorunlu update isimleri: master_code, match_score, match_type
COLUMN_MAPPING = {
    "id": "id",                    # integer
    "name": "name",                # character varying
    "country_code": "country_code",  # character varying
    "tax_id": "tax_id",            # character varying
    "tel": "tel",                  # character varying
    "city_state": "city_state",    # character varying
    "address": "address",          # text
}
```

Kullanici sol tarafi duzenledikten sonra:

```python
COLUMN_MAPPING = {
    "id": "id",                    # integer
    "company_name": "name",        # character varying
    "country_code": "country_code",  # character varying
    "tax_number": "tax_id",        # character varying
    "phone_number": "tel",         # character varying
    "city": "city_state",          # character varying
    "address": "address",          # text
}
```

## Degisen Dosyalar

| Dosya | Degisiklik |
|-------|-----------|
| `generate_config.py` | Yeni dosya — tek seferlik generator script |
| `config.py` | Kod degisikligi yok — sadece generator tarafindan COLUMN_MAPPING blogu guncellenir |
| `main_processor.py` | Degisiklik yok |

## Teknik Detaylar

### generate_config.py Sorumluluklari

- `config.py`'den `DB_CONFIG` ve `RAW_TABLE_NAME` import edilir
- `psycopg2` ile PostgreSQL'e baglanilir
- `information_schema.columns` sorgusu ile sutun isimleri ve veri tipleri cekilir
- `config.py` dosyasi metin olarak okunur
- Regex ile `COLUMN_MAPPING = {` ... `}` blogu bulunur
- Yeni blok olusturulur: her satir `"sutun_adi": "sutun_adi",  # veri_tipi` formatinda
- Blogun ustune yorum satirlari eklenir (zorunlu internal isimler listelenir)
- Dosya guncellenir (sadece COLUMN_MAPPING blogu degisir)

### config.py Dosya Parse Stratejisi

`config.py` bir Python dosyasi oldugundan, COLUMN_MAPPING blogunu bulmak icin:
- Dosya satirlari uzerinden iterasyon yapilir
- `COLUMN_MAPPING = {` ile baslayan satir bulunur
- Acilan/kapanan suslu parantezler sayilir
- Kapanma parantezi bulununca blok sonu belirlenir
- Bu blok yeni icerikle degistirilir

### Sutun Siralama

DB'den gelen sutunlar `ordinal_position` sirasiyla listelenir (tablodaki fiziksel sira).

### Hata Durumlari

| Durum | Davranis |
|-------|----------|
| Tablo bulunamadi | Hata mesaji: "'{RAW_TABLE_NAME}' tablosu bulunamadi" ve cikis |
| config.py bulunamadi | Hata mesaji: "config.py dosyasi bulunamadi" ve cikis |
| COLUMN_MAPPING blogu bulunamadi | Hata mesaji: "COLUMN_MAPPING blogu bulunamadi" ve cikis |
| DB baglantisi basarisiz | psycopg2 hata mesaji ve cikis |

### Kapsam Disi

- Mevcut COLUMN_MAPPING'in yedeklenmesi (tek seferlik islem, gerekli degil)
- DB sutun degisikliklerinin otomatik izlenmesi (kullanici sorumlulugu)
- Interaktif esleme modu (kullanici config.py'yi elle duzenler)
- Birden fazla tablo destegi
