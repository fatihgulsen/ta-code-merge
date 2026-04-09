-- ============================================================================
-- schema.sql - PostgreSQL Veritabanı Şeması
-- ============================================================================
-- 1. Ham Veri Tablosu (Raw Data)
-- Farklı kaynaklardan gelen, temizlenmemiş firma verileri burada tutulur.
CREATE TABLE
    IF NOT EXISTS raw_data (
        id SERIAL PRIMARY KEY,
        -- Temel Firma Bilgileri
        company_name VARCHAR(255) NOT NULL,
        country_code VARCHAR(2) NOT NULL, -- ISO 3166-1 alpha-2 (TR, US, DE, JP vb.)
        -- Zenginleştirilmiş Veriler (Eşleştirme Başarısını Artırır)
        tax_number VARCHAR(50), -- Vergi Numarası (Varsa +100 Puan)
        phone_number VARCHAR(50), -- Telefon Numarası (Varsa +20 Puan)
        city VARCHAR(100), -- Şehir (Opsiyonel, ileride kullanılabilir)
        address TEXT, -- Tam Adres (Opsiyonel)
        -- Eşleştirme Sonuçları (Sistem Tarafından Doldurulur)
        master_code VARCHAR(50), -- Eşleşen Tekil Kod (UUID)
        match_score INTEGER, -- Eşleşme Güveni (0-100)
        -- Metadata
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

-- 2. İndeksler (Performans İçin Kritik)
-- Henüz eşleşmemiş kayıtları hızlıca bulmak için
CREATE INDEX IF NOT EXISTS idx_raw_data_unmatched ON raw_data (id)
WHERE
    master_code IS NULL;

-- Belirli bir ülkedeki firmaları hızlıca çekmek için
CREATE INDEX IF NOT EXISTS idx_raw_data_country ON raw_data (country_code);

-- Eşleştirme yapıldıktan sonra Master ID'ye göre sorgulama yapmak için
CREATE INDEX IF NOT EXISTS idx_raw_data_master_code ON raw_data (master_code);

-- 3. Örnek Veri (Test İçin)
INSERT INTO
    raw_data (
        company_name,
        country_code,
        tax_number,
        phone_number
    )
VALUES
    (
        'Samsung Electronics Co. Ltd.',
        'KR',
        '1234567890',
        '+82-2-2255-0114'
    ),
    ('Samsung Electronics', 'KR', NULL, NULL),
    ('Samsung', 'TR', '9999999999', '+90-212-123-4567'), -- TR Samsung (Farklı MasterCode almalı)
    ('Apple Inc.', 'US', 'US-TAX-001', '+1-555-0199'),
    (
        'Apple Bilgisayar Tic. Ltd. Şti.',
        'TR',
        'TR-TAX-999',
        '+90-216-111-2233'
    );

-- 4. Eşleştirme Aşamaları Günlüğü
-- Her input kaydı için eşleştirme işleminin her aşamasını loglayan audit tablosu.
-- Hangi aşamada eşleştirme bulunduğunu, hangi master_id ile eşleştiğini,
-- ES skoru vs. gibi detayları kaydeder.
CREATE TABLE IF NOT EXISTS match_stages_log (
    id               SERIAL PRIMARY KEY,
    input_id         INTEGER,
    input_name       TEXT,
    country_code     VARCHAR(10),
    stage_name       VARCHAR(30),
    stage_order      INTEGER,
    matched          BOOLEAN,
    master_id        TEXT,
    es_score         FLOAT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_msl_input_id ON match_stages_log (input_id);
CREATE INDEX IF NOT EXISTS idx_msl_stage_name ON match_stages_log (stage_name);
CREATE INDEX IF NOT EXISTS idx_msl_matched ON match_stages_log (matched);