# debug_match.py — Firma Eslestirme Debug & Analiz Araci

Iki firma ismini verip hangi asamada eslesip eslesmedigini gormenizi saglar.

## Hizli Kullanim

### Iki firma karsilastir

```bash
python debug_match.py "FIRMA A" "FIRMA B" -c IN
```

### Ornekler

```bash
# Ayni firma, farkli suffix
python debug_match.py "ARVIND LTD" "ARVIND LIMITED" -c IN

# Farkli firmalar
python debug_match.py "C & C OVERSEAS" "C OVERSEAS" -c IN

# Inisyal farki
python debug_match.py "A B IMPEX" "A G IMPEX" -c IN

# Ulke adi icerenler
python debug_match.py "MERIL LIFE SCIENCES PVT LTD" "MERIL LIFE SCIENCES INDIA PRIVATE LIMITED" -c IN

# Numara farki
python debug_match.py "STAR ENTERPRISES" "7 STAR ENTERPRISES" -c IN

# Farkli sehir
python debug_match.py "MUMBAI DUTY FREE SERVICES PVT LTD" "DELHI DUTY FREE SERVICES PVT LTD" -c IN
```

### ES'te firma ara

```bash
python debug_match.py "ARVIND" -c IN --search
```

Her stage icin ES sorgusunu calistirir ve sonuclari gosterir.

### Kalite raporu

```bash
python debug_match.py --report
```

ES'teki tum master'larin varyasyon kalitesini kontrol eder.

### JSON cikti

```bash
python debug_match.py "FIRMA A" "FIRMA B" -c IN --json
```

## Cikti Aciklamasi

### [1] Label Temizleme
"to order of", "c/o", "attn", "care of" gibi nakliye etiketleri temizlenir.

### [2] Tokenize
Firma ismi tokenlara ayrilir:
- Kucuk harf
- Suffix normalizasyonu: `limited` -> `ltd`, `private` -> `pvt`, `company` -> `co`
- Ulke adi filtreleme: IN firmasinda "india" yok sayilir
- Stopword filtreleme: "and", "of", "the" yok sayilir
- Tek karakter: alfanumerik korunur (inisyal/rakam), sembol atilir

### [3] Anlamli / Suffix Ayirimi
Tokenlar ikiye ayrilir:
- **Anlamli**: Firma ismini tanimlayan kelimeler (arvind, impex, meril)
- **Suffix**: Generic yapisal kelimeler (ltd, pvt, inc, corp)
- **Min anlamli token < 2**: Sadece CANONICAL/STRIPPED'da tam esleme kabul edilir

### [4] Coverage Metrikleri
- **Token coverage**: Simetrik token ortusme orani (min iki yon)
- **Meaningful coverage**: Suffix haric anlamli tokenlar icin ayni hesap
- **Word count ratio**: Ham kelime sayisi orani (tekrarlari korur)
- **Len ratio**: Karakter uzunluk orani

### [5] Dedup Key
NEW_MASTER icinde ayni firma iki kez olusturulmasin diye kullanilir.
Sirali tuple — tekrarlari korur ("C & C" != "C").

### [6] Stage Post-Verify Sonuclari
Her stage icin Python tarafli dogrulama:

| Stage | Esik | Aciklama |
|-------|------|----------|
| CANONICAL_EXACT | coverage >= 0.9, meaningful >= 0.9, wc_ratio >= 0.8 | Synonym-aware tam esleme |
| STRIPPED_EXACT | coverage >= 0.9, meaningful >= 0.9, wc_ratio >= 0.8 | Suffix temizlenmis tam esleme |
| TOKEN_COVERAGE | coverage >= 0.8, meaningful >= 0.8, wc_ratio >= 0.7 | Tum tokenlar mevcut |
| FUZZY_PHRASE | coverage >= 0.8, meaningful >= 0.8, wc_ratio >= 0.7 | Kelime sirasi toleransli |
| NGRAM_MATCH | coverage >= 0.8, meaningful >= 0.8, wc_ratio >= 0.7 | Trigram fuzzy (stripped) |

Ek kontroller:
- **len_ratio < 0.4**: Reddedilir (cok farkli uzunluk)
- **min_meaningful < 2**: Sadece CANONICAL/STRIPPED'da tam esleme kabul
- **TAX_EXACT**: Bu araclat test edilmez (deterministik vergi no eslesmesi)

## Stage Sirasi (Oncelik)

```
1. TAX_EXACT        → Vergi no kesin eslesmesi (deterministik)
2. CANONICAL_EXACT  → Synonym-aware tam phrase eslesmesi
3. STRIPPED_EXACT   → Suffix temizlenmis tam phrase eslesmesi
4. TOKEN_COVERAGE   → Tum tokenlarin presence kontrolu
5. FUZZY_PHRASE     → Kelime sirasi toleransli esleme (slop=3)
6. NGRAM_MATCH      → Trigram fuzzy esleme (stripped form)
7. NEW_MASTER       → Eslesmedi — yeni firma olusturulur
```

Bir kayit ilk eslesen stage'de eslesir ve sonraki stage'lere gitmez.
