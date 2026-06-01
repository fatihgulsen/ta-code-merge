# PG ↔ ES Eşleştirme Doğruluğu — Denetim ve İyileştirme Tasarımı

**Tarih:** 2026-04-10
**Durum:** Taslak — kullanıcı onayı bekleniyor
**Kapsam:** Üretim tablosundaki (`p7_firms_v2`) eşleştirme sonuçlarının denetlenmesi, false positive kök sebeplerinin tespiti, iki sprintlik iyileştirme yol haritası
**Kalibrasyon tercihi:** Temkinli — şüpheli durumlarda ayrı firma (NEW_MASTER) açmak, yanlış birleştirmekten tercih edilir

---

## 1. Yönetici Özeti

Bugünkü üretim durumu (`p7_firms_v2`):

| Metrik | Değer |
|--------|------:|
| Toplam kayıt | 18.452.901 |
| Henüz eşleşmemiş | 18.430.850 |
| Ham eşleşme (NEW_MASTER hariç) | 3.172 |
| Benzersiz master | 17.066 |

Eşleşme dağılımı:

| match_type | Adet |
|-----------:|-----:|
| NEW_MASTER | 18.879 |
| CANONICAL_EXACT | 2.012 |
| STRIPPED_EXACT | 913 |
| SUFFIX_FUZZY | 243 |
| FUZZY_PHRASE | 2 |
| NGRAM_MATCH | 2 |

Rastgele örneklemede (Hindistan — en yoğun ülke): **false positive oranı ≥ %40**. En kritik stage'ler **STRIPPED_EXACT** ve **SUFFIX_FUZZY**, ancak **CANONICAL_EXACT** bile kirlenmiş durumda. Kök sebep tek bir kelime ile özetlenebilir: *aşırı stripping* — sektör/ayırt edici kelimeler, tüzel kişi eklerinin yanı sıra "generic token" sayılıp siliniyor.

---

## 2. Kanıt: Gerçek False Positive Örnekleri

Aşağıdaki örneklerin tamamı `p7_firms_v2` tablosundan rastgele örneklemeyle alınmıştır. Her satır, master firmanın ismini (NEW_MASTER) ve ona yanlışlıkla bağlanmış child firmayı gösterir.

### 2.1 CANONICAL_EXACT — yanlış eşleşmeler

```
master="JAY & CO."                    | child="JAY CHEMICAL INDUSTRIES PRIVATE LIMITED"
master="HOTEL IMPERIAL"               | child="IMPERIAL AUTO INDUSTRIES LIMITED"
master="AJANTA INDUSTRIES,"           | child="AJANTA PHARMA LIMITED"
master="ATUL COMMODITIES PVT. LTD."   | child="ATUL LIMITED"
master="AGRI LIFE"                    | child="LIFE."
master="AG ELECTRO SERVICES"          | child="ELECTRO"
```

**Not:** Bu stage'in "kesin eşleşme" olarak tasarlanmasına rağmen cascade yoluyla kirli `variations` listesi üzerinden yanlış eşleşebildiği görülüyor (ayrıntı: §3.4).

### 2.2 STRIPPED_EXACT — yanlış eşleşmeler

```
master="GOEL ENTERPRISES.."            | child="GOEL STEEL COMPANY"
master="ANAND ENTERPRISES,,_"          | child="ANAND TECHNOLOGIES,"
master="CARE ENTERPRISES"              | child="GLOBAL CARE"
master="AUTO DYNAMIC CORPORATION"      | child="DYNAMIC TRADERS."
master="APEX AUTO LIMITED,"            | child="APEX INDUSTRIES,."
master="A.H. INTERNATIONAL"            | child="AH CHEMICALS PVT. LTD."
master="ARIHANT ENTERPRISE.."          | child="ARIHANT TRADERS.."
master="AKSHAYA CORP,"                 | child="AKSHAYA TEXTILE,"
master="KAMAL INTERNATIONAL."          | child="KAMAL INDUSTRIES,"
master="HARSH AGENCIES."               | child="HARSH INTERNATIONAL.."
master="AMAN TRADING CO."              | child="AMAN INTERNATIONAL,,"
master="LAKSHMI AGENCIES."             | child="LAKSHMI METALS"
master="LAXMI AGRO INDUSTRIAL CONS…"   | child="LAXMI ELECTRONICS."
```

Her satırda paylaşılan tek gerçek bilgi ilk kelime (marka). Sonrasındaki her şey (sektör / tüzel kişi eki) sıyrılıyor.

### 2.3 SUFFIX_FUZZY — yanlış eşleşmeler

```
master="ACE AVIATION (PROP: JOHN PENRY EVANS)"  | child="ACE INDUSTRIES-"
master="DELTA ELECTRONICS"                       | child="DELTA TEXTTILES"
master="EXCEL COMMUNICATIONS"                    | child="EXCEL METAL ENGINEERING PVT.LTD,"
master="GALAXY."                                 | child="GALAXY INDUSTRIES_"
master="INDIAN TRADING CORPORATION."             | child="INDIAN CHEMICAL CORPORATION"
master="AGGARWAL & CO."                          | child="AGGARWAL ELECTRIC CO."
master="APEX AUTO LIMITED,"                      | child="APEX TRADERS,;"
master="ANIL AGENCIES PVT.LTD"                   | child="ANIL ENTERPRISES-"
```

Bu stage'in tasarım amacı "isim kısmı exact, suffix fuzzy" idi. Ancak ismin "isim kısmı" stripping'ten sonra tek kelimeye (marka) düşüyor; bu tek kelime, tamamen farklı sektörlerdeki firmalarla çakışıyor.

### 2.4 TOKEN_COVERAGE — yanlış eşleşmeler

```
master="BEE KAY ENTERPRISES"   | child="KAY BEE TRADING CO.,"
master="DEE KAY EXPORTS"       | child="KAY DEE ENTERPRISES"
```

Token sırası ters, ama token kümesi aynı → coverage %100. `TOKEN_COVERAGE` kelime sırasını umursamadığı için "BEE KAY" ile "KAY BEE" aynı firma sanılıyor.

### 2.5 Doğru eşleşmeler (kontrol örneği)

Sistem bu tür varyasyonları doğru çözüyor — yama sonrası recall kaybı olmamalı:

```
master="ISHA ENTERPRISE."          | child="ISHA ENTERPRISES"             ✓ (suffix typo)
master="J J OVERSEAS"              | child="J. J. OVERSEAS"               ✓ (punct normalize)
master="BALAJI IMPEX."             | child="BALAJI IMPEX ,,"              ✓ (punct)
master="KRISHNA OVERSEAS,."        | child="KRISHNA OVERSEAS ."           ✓ (punct)
master="K.T. INTERNATIONAL"        | child="KT INTERNATIONAL"             ✓ (acronym)
master="ARIHANT ENTERPRISE.."      | child="ARIHANT ENTERPRISES ,,"       ✓ (pluralize)
master="J M CORPORATION."          | child="J. M. CORPORATION"            ✓ (punct)
```

---

## 3. Kök Sebep Analizi

### 3.1 Synonym şema kirliliği (birincil sebep)

`synonyms_data/in.json` dosyasının `company_types` kategorisi, iki farklı doğadaki kelimeyi tek listede topluyor:

**Doğru içerik (legal suffix — stripping'e tabi tutulmalı):**
`pvt. ltd.`, `ltd.`, `inc.`, `llp`, `opc`, `huf`, `trust`, `society`, `proprietorship`

**Yanlış içerik (business sector — ayırt edici, asla stripping'e tabi tutulmamalı):**
```
enterprises, industries, trading, traders, exports, imports, solutions,
services, technologies, systems, consultants, international, global,
group, corporation, holdings, ventures, associates, agency, agencies,
dealers, distributors, suppliers, manufacturers, construction, infra,
realty, developers, logistics, transport, engineering, pharma, chemicals,
textiles, garments, foods, agro, steel, metals, plastics, packaging,
media, healthcare, education, finance, capital, investments, securities,
insurance, leasing, commodities, power, petroleum, auto, automobile,
electronics, software, hardware, retail, hotel, resort, hospitality,
aviation, shipping, marine
```

`get_company_type_tokens()` bu listenin tamamını döndürüyor → `_build_stripped_script` tamamını siliyor → `variations_stripped` alanında sadece marka kalıyor → "APEX AUTO" ve "APEX INDUSTRIES" her ikisi de `apex` oluyor.

### 3.2 `BUSINESS_DESCRIPTORS` guard pratikte devre dışı

`config.py` içindeki `BUSINESS_DESCRIPTORS` frozenset'i bu problemi çözmek için eklenmiş görünüyor:

```python
BUSINESS_DESCRIPTORS = frozenset({
    "enterprises", "group", "holding", "industrial", "industries",
    "internacional", "international", "manufacturing", "prod", "sanayi",
    "services", "solutions", "technologies", "ticaret", "trading",
    "comercial", "koncern",
})
```

Ancak bu set yalnızca `synonym_loader.get_generic_tokens_for_country()` fonksiyonunun sonunda çıkarılıyor (satır 140). Üretim akışında kullanılan `get_company_type_tokens()` (`_parse_company_type_tokens` üzerinden) bu guard'ı uygulamıyor. ES ingest pipeline'larını ve search analyzer'larını besleyen yol, guard'ı hiç görmüyor.

### 3.3 `BUSINESS_DESCRIPTORS` listesi eksik

Guard aktifleştirilse bile mevcut 17 kelimelik liste, gerçek sektör kelime havuzunun yalnızca küçük bir alt kümesini kapsıyor. Denetimde tespit edilen ve listeye eklenmesi gereken asgari 50+ kelime §4.1'de listelendi.

### 3.4 Cascade kirliliği (variations snowball)

`main_processor.update_es_variations()` eşleşen child kayıtlarının ham ismini master'ın `variations` listesine ekliyor. Stage sırası:

1. `CANONICAL_EXACT` başlangıçta "JAY & CO." master'ını kuruyor
2. Başka bir stage (muhtemelen `STRIPPED_EXACT` veya önceki iterasyonlar) `JAY CHEMICAL INDUSTRIES PVT LTD`'i yanlışlıkla "JAY & CO."'ya eşleştiriyor
3. Artık master'ın `variations` listesinde `"jay chemical industries pvt ltd"` var
4. Sonraki sorgular `CANONICAL_EXACT` (match_phrase) olarak o dokümana düşüyor — teknik olarak "kesin eşleşme" ama semantik olarak yanlış

Son commit'lerde (`8f92a01`) en zayıf stage'ler için `index_variation=False` eklenmiş (STRIPPED_EXACT, FUZZY_PHRASE, NGRAM_MATCH). Fakat `CANONICAL_EXACT`, `SUFFIX_FUZZY` ve `TOKEN_COVERAGE` hâlâ `True` ile variations'a yazıyor — kirli master'ın kirliliği yayılmaya devam ediyor.

### 3.5 İkincil zayıflıklar

- **`_post_verify` kısa-isim loophole'ı** (`main_processor.py` satır 449-453): `min_tokens < 2` durumunda `CANONICAL_EXACT` / `STRIPPED_EXACT` için `input_tokens == master_tokens` kontrolü yapılıyor. Her iki taraf stripping sonrası 1 token'a inerse bu trivially karşılanır.
- **`TOKEN_COVERAGE` sıra duyarsız:** `_symmetric_token_coverage` yalnızca set işlemi yapar; `BEE KAY` vs `KAY BEE` farkı görülmez.
- **`SUFFIX_FUZZY` kısa-isim zaafı:** `_post_verify` içindeki `doc_multi_char` kontrolü tek-karakterli doc token'ları reddediyor ama tek-anlamlı-token (brand) durumu yakalamıyor.
- **Ülke hard-filter dışında kaynak güveni yok:** Aynı ülkede farklı sektörde iki firma için ek bir "sektör benzerliği zayıfsa reddet" kuralı yok.

---

## 4. Sprint 1 — Hızlı Yamalar (Düşük Risk)

**Amaç:** synonym JSON dosyalarına dokunmadan, Python + ES pipeline seviyesinde guardrailler kurarak bilinen false positive ailelerini bloke etmek. Tüm değişiklikler geri alınabilir; yeni bir ES re-index gerektirir ancak schema migration içermez.

### 4.1 `BUSINESS_DESCRIPTORS` listesini genişlet

`config.py` içindeki frozenset'i aşağıdaki sektör kelimeleriyle güncelle. Liste küratördür — her kelime için "bu firma ismini ayırt ediyor mu?" testi uygulandı.

```python
BUSINESS_DESCRIPTORS = frozenset({
    # Mevcut
    "comercial", "enterprises", "group", "holding", "industrial", "industries",
    "internacional", "international", "koncern", "manufacturing", "prod",
    "sanayi", "services", "solutions", "technologies", "ticaret", "trading",

    # Yeni: tekil/çoğul çeşitleri
    "enterprise", "holdings", "service", "solution", "technology",

    # Yeni: ticari/rol kelimeleri
    "traders", "exports", "imports", "export", "import",
    "dealers", "dealer", "distributors", "distributor",
    "suppliers", "supplier", "agency", "agencies",
    "consultants", "consultant", "consulting",
    "associates", "associate", "ventures", "venture",
    "systems", "system", "overseas",

    # Yeni: sektör kelimeleri
    "pharma", "pharmaceuticals", "pharmaceutical",
    "chemicals", "chemical", "textiles", "textile",
    "steel", "steels", "metals", "metal",
    "plastics", "plastic", "packaging",
    "foods", "food", "agro", "agriculture",
    "auto", "automobile", "automobiles", "automotive",
    "electronics", "electronic", "electric", "electrical",
    "software", "hardware", "media", "communications",
    "healthcare", "health", "education", "educational",
    "finance", "financial", "capital", "investments", "investment",
    "securities", "insurance", "leasing", "commodities", "commodity",
    "power", "energy", "petroleum", "petro",
    "hotel", "hotels", "hospitality", "resort", "resorts",
    "aviation", "shipping", "marine", "maritime",
    "logistics", "transport", "transportation",
    "engineering", "engineers", "construction", "constructions",
    "infra", "infrastructure", "realty", "developers", "developer",
    "retail", "retails", "global",
})
```

**Kabul kriteri:** Liste PR içinde inline doğrulama — her kelimeye "ayırt edici mi?" yorum satırı. Ülkeye özel istisnalar (ör. Brezilya'da "global") için §5'teki refactor aşamasına ertelendi; bu aşamada global/tek liste kullanılır.

### 4.2 `get_company_type_tokens()` içine guard ekle

`synonym_loader._parse_company_type_tokens` fonksiyonunun sonuna `BUSINESS_DESCRIPTORS` çıkarma adımı ekle. Aynı modülün üstünde zaten `from config import BUSINESS_DESCRIPTORS` var, import tekrar edilmeye gerek yok.

```python
# _parse_company_type_tokens sonu
return frozenset(tokens) - BUSINESS_DESCRIPTORS
```

`get_company_type_tokens` ve `get_all_company_type_tokens` bu fonksiyonu çağırdığı için iki yol da korunmuş olur. `get_generic_tokens_for_country` mevcut eksik davranışını korur (kullanılmıyor olsa da sızma olmaz).

**Yan etki:** `_post_verify._tokenize` ve `_is_fuzzy_suffix` artık sektör kelimelerini "suffix değil" olarak görecek; bu istenen davranış.

### 4.3 ES ingest pipeline re-register + re-index

`es_ingest._build_stripped_script` dolaylı olarak `get_company_type_tokens` kullanıyor. §4.2 uygulandıktan sonra:

```bash
python es_manager.py --force
python main_processor.py   # sadece pipeline verify kısmı çalışır; tam run sonradan
```

**Re-index zorunluluğu:** `variations_stripped` alanı ingest pipeline'ında hesaplanıyor. Pipeline değişince mevcut dokümanlar otomatik güncellenmez. İki seçenek:

1. `update_by_query` (ES 7+): `?pipeline=company_name_<cc>` ile in-place yeniden hesaplama
2. Tam re-index: index'i sil → yeniden oluştur → NEW_MASTER dokümanlarını bulk index'le

Öneri: Seçenek 1 önce denenir (hızlı). Başarısız olursa seçenek 2.

### 4.4 `_post_verify` sertleştirme

Aşağıdaki değişiklikler `main_processor.py` içinde yapılır. Her biri izole; ayrı commit olarak atılabilir.

**(a) `min_tokens < 2` loophole'unu kapat**

```python
# Mevcut:
if min_tokens < 2:
    if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
        if input_tokens == master_tokens:
            return True
    return False
```

Değişiklik — temkinli modda tüm stage'ler için reddet:

```python
if min_tokens < 2:
    return False
```

**Gerekçe:** Stripping sonrası tek token'a inmiş isimler (marka) zaten yüksek çakışma riskli; ayrı firma açılması tercih edilir.

**(b) `CANONICAL_EXACT` / `STRIPPED_EXACT` eşiklerini yükselt**

```python
if stage_name in ("CANONICAL_EXACT", "STRIPPED_EXACT"):
    if coverage < 0.9:
        return False
    if word_count_ratio < 0.9:   # was 0.8
        return False
```

**(c) `TOKEN_COVERAGE` brand-anchor kontrolü**

Yeni yardımcı fonksiyon:

```python
def _first_meaningful_token(name: str, country: str) -> str | None:
    cleaned = _clean_labels(name).lower()
    suffix_tokens = get_company_type_tokens(country)
    article_tokens = get_article_stopwords(country)
    for t in cleaned.split():
        tc = t.rstrip('.,')
        if not tc or (len(tc) <= 1 and not tc.isalnum()):
            continue
        if tc in article_tokens or tc in suffix_tokens:
            continue
        return tc
    return None
```

`_post_verify` içinde `TOKEN_COVERAGE/FUZZY_PHRASE/NGRAM_MATCH` dalı sonuna:

```python
if stage_name in ("TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"):
    ...
    # Brand anchor: ilk anlamlı token her iki tarafta da aynı olmalı
    input_first = _first_meaningful_token(input_name, country)
    master_first = _first_meaningful_token(master_name, country)
    if input_first is None or master_first is None:
        return False
    if input_first != master_first:
        return False
```

Bu, `BEE KAY` vs `KAY BEE` vakasını keser. `APEX ...` ve `APEX ...` gibi gerçek kardeşlerde etki yok.

**(d) `SUFFIX_FUZZY` minimum meaningful-token sayısı**

`SUFFIX_FUZZY` dalının başına:

```python
if stage_name == "SUFFIX_FUZZY":
    ...
    # Stripping sonrası en az 2 anlamlı token olmalı — tek-brand eşleşmesi yasak
    if len(doc_multi_char) < 2:
        return False
    if len(input_stripped_ordered) < 2:
        return False
```

**Gerekçe:** `ACE AVIATION` vs `ACE INDUSTRIES` stripping sonrası `ace` + (silinmiş) → her iki tarafta tek token. Yeni kural bunu reddeder.

### 4.5 Cascade kirliliğini tüm belirsiz stage'lerde durdur

Temkinli mod gereği, Sprint 1 boyunca **yalnızca** `TAX_EXACT` (deterministik) variations listesini beslemeye devam eder. Diğer tüm stage'ler PG-only moduna alınır. `config.STAGES` güncellemesi:

| Stage | Mevcut `index_variation` | Sprint 1 sonrası |
|-------|:------------------------:|:----------------:|
| TAX_EXACT | True | **True** (değişmez) |
| CANONICAL_EXACT | True | **False** |
| SUFFIX_FUZZY | True | **False** |
| TOKEN_COVERAGE | True | **False** |
| FUZZY_PHRASE | False | False (değişmez) |
| NGRAM_MATCH | False | False (değişmez) |
| STRIPPED_EXACT | False | False (değişmez) |

**Gerekçe:** Variations listesinin kirlenmesi tüm stage'ler için kartopu riski yaratıyor (§3.4). Temkinli modda sadece vergi numarası üzerinden yapılan deterministik eşleşmenin variations beslemesine güvenilir. Bu, Sprint 1 boyunca master başına variations çeşitliliğini dondurur — recall açısından küçük bir kayıp yaratabilir ama cascade FP'leri tamamen keser. Sprint 2'de schema düzeldikten sonra CANONICAL_EXACT gibi güvenilir stage'ler dikkatli şekilde tekrar True'ya alınır.

**Kabul kriteri:** Yama sonrası 500 rastgele kayıtlık smoke test'te CANONICAL_EXACT ve SUFFIX_FUZZY false positive'i bulunamamalı; sonraki iterasyonlarda master'ların variations listesi yalnızca TAX_EXACT üzerinden büyümeli.

### 4.6 Smoke test script'i

`tests/test_matching_accuracy_smoke.py` oluştur. Tablodan rastgele 500 çift (master + child) çeker, bilinen FP desenlerini ve regression seti olarak §2'deki tüm ismi içerir. `pytest -m smoke` ile çalışır.

**Regression fixture:** §2'deki tüm false positive çiftleri, düzeltme sonrası "eşleşmemeli" testiyle kontrol edilir. §2.5'teki doğru eşleşmeler ise "eşleşmeli" testiyle kontrol edilir.

### 4.7 Sprint 1 kabul kriterleri

| # | Kontrol | Hedef |
|---|---------|------:|
| S1-K1 | §2'deki 30+ FP çifti, yeni kod ile `_post_verify` False dönsün | %100 |
| S1-K2 | §2.5'teki doğru çiftler hâlâ True dönsün (recall) | ≥ %95 |
| S1-K3 | Smoke test'te 500 örneklemde FP oranı | < %5 |
| S1-K4 | ES re-index sonrası pipeline warning yok | 0 |
| S1-K5 | Mevcut unit test'ler hâlâ geçsin (`pytest tests/`) | 100% |

---

## 5. Sprint 2 — Yapısal Refactor

**Amaç:** Sprint 1 bant yapıştırma iken, Sprint 2 synonym şemasını kökten onarır. `BUSINESS_DESCRIPTORS` guard'ı artık gereksizdir çünkü ayrım JSON seviyesinde yapılır.

### 5.1 Yeni synonym şeması

Her ülke dosyası ve `common.json` üç kategoriye ayrılır:

```jsonc
{
  "legal_suffixes": [
    // STRIPPING'E GİRER — tüzel kişi ekleri
    "private limited,private limited company,pvt. ltd.,...=>pvt. ltd.",
    "public limited,ltd.,limited,...=>ltd.",
    "limited liability partnership,llp,l.l.p.=>llp",
    ...
  ],
  "business_sectors": [
    // STRIPPING'E GİRMEZ — ayırt edici; synonym expand edilir
    "pharma,pharmaceuticals,pharmaceutical,pharm.=>pharma",
    "chemicals,chemical,chem.=>chemicals",
    "auto,automobile,automobiles,automotive=>auto",
    ...
  ],
  "articles": ["and", "of", "the", ...],
  "address_terms": [ ... ]
}
```

**Temel kural:** `legal_suffixes` stripping'e girer ve `variations_stripped` alanında silinir. `business_sectors` stripping'e GİRMEZ, ama `clean_analyzer` synonym filter'ında expansion için kullanılır (`pharma` ↔ `pharmaceuticals` hâlâ eşanlamlı).

### 5.2 Migration stratejisi

Manuel değil, insan onayı gerekli:

1. **Otomatik öneri üretici script** (`scripts/migrate_synonyms.py`): mevcut `company_types` listesindeki her kuralı kategorize eder. Heuristic:
   - Kural hedefi Sprint 1'deki genişletilmiş `BUSINESS_DESCRIPTORS` içindeyse → `business_sectors`
   - Değilse → `legal_suffixes`
   - İkisi arasında kalanlar → `ambiguous` (manuel karar)
2. Çıktı: ülke başına diff dosyası (`{cc}.migration.diff`)
3. İnsan reviewer diff'leri onaylar, `ambiguous` olanları karara bağlar
4. Script onaylı diff'leri uygular

**Öncelik ülkeleri (ilk parti):** IN, US, TR, DE, CN, GB, IT, FR, BR, RU, JP, KR

**İkinci parti:** Kalan tüm ülke dosyaları

### 5.3 Python API değişiklikleri

`synonym_loader` modülüne yeni fonksiyonlar:

```python
@lru_cache(maxsize=None)
def get_legal_suffix_tokens(country_code: str) -> frozenset:
    """Yalnızca legal_suffixes kategorisindeki tokenlar — stripping'e girer."""
    ...

@lru_cache(maxsize=None)
def get_business_sector_tokens(country_code: str) -> frozenset:
    """business_sectors — stripping'e girmez, ayırt edici."""
    ...
```

`get_company_type_tokens` geriye uyumluluk için kalır ama artık sadece `legal_suffixes` döner. `BUSINESS_DESCRIPTORS` frozenset'i kaldırılır.

### 5.4 ES pipeline ve analyzer değişiklikleri

- `_build_stripped_script` yalnızca `get_legal_suffix_tokens(country_code)` ile besleniyor
- `clean_analyzer_<cc>` synonym filter'ı her iki kategoriyi de synonym expansion için kullanır (böylece `pharma ≈ pharmaceutical` hâlâ eşleşir — sadece silinmez)
- `stripped_search_analyzer_<cc>` stop filter'ı yalnızca legal suffix + articles içerir

### 5.5 Sprint 2 kabul kriterleri

| # | Kontrol | Hedef |
|---|---------|------:|
| S2-K1 | Öncelik ülkeleri migration'ı tamamlanmış, diff onaylanmış | 12/12 |
| S2-K2 | `BUSINESS_DESCRIPTORS` referansı codebase'den tamamen kalkmış | 0 occurrence |
| S2-K3 | Sprint 1 regression fixture'ı hâlâ %100 geçiyor | 100% |
| S2-K4 | Sprint 2'ye özel yeni regression: "sektör synonym expansion" doğru çalışıyor (ör. `pharma` ↔ `pharmaceutical`) | Tüm örnek çiftler |
| S2-K5 | Tam re-index tamamlanmış | ✓ |

### 5.6 Sprint 2 riskleri

- **Ülke başına istisnalar:** Meksika için `mexicana` hem yer adı ekidir hem markadır; Brezilya için `global` bazı durumlarda marka parçası olabilir. Her ülke dosyasının insan review'u kritik.
- **Migration script hataları:** Heuristic %100 doğru olmayabilir; `ambiguous` kategorisi geniş olursa manuel iş yükü artar.
- **Re-index süresi:** 18M kayıtlık tam re-index birkaç saat sürebilir. Mavi/yeşil index strategy önerilir (yeni index'e bulk load + alias swap).

---

## 6. Ölçüm ve Doğrulama

### 6.1 Önce/sonra testi

Her iki sprint için aynı test seti:

1. **FP regression fixture** (§2'deki 30+ çift, manuel küratörlenen)
2. **TP regression fixture** (§2.5'teki doğru çiftler + 50 ek örnek)
3. **Rastgele smoke sample** (500 kayıt, manuel review notu)

### 6.2 Stage bazlı delta

Sprint sonrası `match_stages_log` tablosundan her stage için:
- Eşleşme adedi (delta %)
- Post-verify'dan geçme oranı (delta %)

Beklenen yönler:
- STRIPPED_EXACT eşleşme sayısı düşer (çünkü aşırı stripping azalır) — **istenen davranış**
- CANONICAL_EXACT eşleşme sayısı hafif düşer — cascade kesildiği için
- TAX_MATCH, SUFFIX_FUZZY hafif düşer veya sabit kalır
- NEW_MASTER sayısı artar — temkinli mod beklentisiyle uyumlu

### 6.3 Üretim izleme

`match_stages_log` tablosunda stage başına günlük aggregate; Sprint 1 sonrası 7 gün boyunca:
- Toplam eşleşme < önceki 7 gün * 0.8 olursa alarm (aşırı recall kaybı riski)
- Manuel review için haftalık 50 random eşleşme örneklenir

---

## 7. Kirli Veri Durumu (Raporlama)

**Karar:** Kullanıcı isteğine göre kirli verinin temizlenme stratejisi bu dökümanın kapsamı dışında; sadece mevcut durum raporlanır ve opsiyonel araçlar belgelenir.

### 7.1 Etkilenen kayıt sayısı

```sql
SELECT match_type, COUNT(*) FROM p7_firms_v2
WHERE master_code IS NOT NULL AND match_type != 'NEW_MASTER'
GROUP BY match_type ORDER BY 2 DESC;
```

Bugünkü sonuç: 3.172 kayıt (CANONICAL 2.012 + STRIPPED 913 + SUFFIX_FUZZY 243 + FUZZY_PHRASE 2 + NGRAM 2).

### 7.2 İki temizleme seçeneği

**Seçenek A — Tam reset + yeniden çalıştır**

```sql
UPDATE p7_firms_v2
SET master_code = NULL, match_type = NULL, match_score = NULL
WHERE match_type IS NOT NULL;
```

Sonra `python main_processor.py`. Temiz çıktı; 18M kayıt tekrar işlenir, saatler/günler alabilir.

**Seçenek B — Selektif rollback (önerilir)**

```sql
UPDATE p7_firms_v2
SET master_code = NULL, match_type = NULL, match_score = NULL
WHERE match_type IN ('STRIPPED_EXACT', 'SUFFIX_FUZZY',
                     'TOKEN_COVERAGE', 'FUZZY_PHRASE', 'NGRAM_MATCH');
```

TAX_MATCH ve CANONICAL_EXACT korunur (CANONICAL_EXACT'in az da olsa FP'si var — risk kabul edilir). Ardından yeniden çalıştır: yalnızca ~3.200 kirli + unmatched kayıtlar işlenir. Hızlı.

**Seçenek C — Hiçbir şey yapma**

Sprint 1 sonrası sadece yeni işlemeler doğru olur; mevcut kirli master'lar üretim raporlarında yaşamaya devam eder. En az risk, en kötü kalite.

Kararın kullanıcı tarafından Sprint 1 tamamlanınca verilmesi önerilir.

---

## 8. Açık Riskler ve Bilinmeyenler

| Risk | Olasılık | Etki | Azaltma |
|------|----------|------|---------|
| Genişletilmiş `BUSINESS_DESCRIPTORS` gerçek suffix'leri yanlışlıkla korur | Orta | Orta | Liste manuel küratör, PR review, regression test |
| Re-index süreci 18M kayıtta saatler sürer | Yüksek | Orta | Mavi/yeşil strategy, update_by_query önce |
| Recall aşırı düşer (recall collapse) | Düşük | Yüksek | Smoke test §4.6, stage log delta izleme §6.3 |
| Ülkeye özel istisnalar (mexicana, global) güvenle yakalanmaz | Orta | Düşük-Orta | Sprint 2'ye ertelendi; ülke bazlı override mekanizması |
| Sprint 2 migration script heuristic'i %100 doğru değil | Yüksek | Düşük | İnsan review gate'i + `ambiguous` kategorisi |
| CANONICAL / SUFFIX_FUZZY / TOKEN_COVERAGE `index_variation=False` yapılınca legitimate varyasyonlar da index'e düşmez | Orta | Orta | Sprint 2'de dikkatli şekilde geri aç; o zamana kadar §6.3 recall izleme + weekly random review |

---

## 9. Özet Dosya Etkisi

### Sprint 1 (değişen dosyalar)

| Dosya | Değişiklik türü | Boyut |
|-------|-----------------|-------|
| `config.py` | `BUSINESS_DESCRIPTORS` genişletme + 3 stage için `index_variation=False` | +60 satır |
| `synonym_loader.py` | `_parse_company_type_tokens` guard ekleme | +2 satır |
| `main_processor.py` | `_post_verify` sertleştirme + `_first_meaningful_token` helper | +30 satır |
| `tests/test_matching_accuracy_smoke.py` | Yeni smoke + regression fixture | +200 satır |
| ES pipeline | Re-register + re-index | runtime |

### Sprint 2 (değişen/yeni dosyalar)

| Dosya | Değişiklik türü |
|-------|-----------------|
| `synonyms_data/*.json` (50+ dosya) | Schema split: `company_types` → `legal_suffixes` + `business_sectors` |
| `synonym_loader.py` | Yeni API fonksiyonları + eski API geriye uyumluluk |
| `config.py` | `BUSINESS_DESCRIPTORS` kaldırılır |
| `es_ingest.py` | `_build_stripped_script` yeni API kullanır |
| `es_manager.py` | Analyzer synonym filter güncellenir |
| `scripts/migrate_synonyms.py` | Yeni migration aracı |

---

## 10. Sonraki Adım

Bu döküman onaylandıktan sonra `writing-plans` skill'i ile Sprint 1 için adım adım implementasyon planı yazılır. Plan:
- Her değişikliğin test-first yaklaşımla yazılması
- Her commit için yeşil testler
- ES re-index öncesinde/sonrasında metric snapshot'ları
- Rollback prosedürleri

Sprint 2 için ayrı bir plan dokümanı, Sprint 1 başarılı şekilde üretime çıktıktan sonra hazırlanır.
