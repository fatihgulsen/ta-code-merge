# ru.json Kanonik Şema Migrasyonu — Design

**Tarih:** 2026-06-30
**Branch:** `feat/ru-synonym-canonical-migration`
**Durum:** Onaylandı

## Problem

`synonyms_data/ru.json` legacy şema kullanıyor: kategori adları `company_types` ve
`address_terms` ve sektör/article/placeholder kategorileri tamamen eksik. mx/br/ar
dosyaları ise kanonik şemada (`legal_suffixes`, `business_sectors`,
`address_abbreviations`, `articles`, `non_firm_placeholders`).

Sonuç: ru.json'daki legal+address token'ları `synonym_graph`'a girip eşleşmede çalışıyor
**ama** sınıf-bazlı loader'lar (`get_legal_suffix_tokens`, `get_address_tokens`,
`get_business_sector_tokens`, `get_article_stopwords`, `get_non_firm_placeholders`) yanlış
key adları yüzünden RU token'larını sınıflandıramıyor. Bu da:
- generic-core gate'in ayırt-edicilik hesabını (legal ∪ article ∪ geo ∪ sector) eksik bırakır
- DIRTY_DATA tespitini (address) devre dışı bırakır
- input_filter placeholder EXCLUDED'ını çalıştırmaz

Bu, bilinen "Synonym category-name inconsistency" sorununun RU örneğidir
(40/44 cc dosyası legacy key kullanıyor).

## Hedef

ru.json'u mx/br/ar ile birebir kanonik şemaya taşımak (tam zenginleştirme — ar/br
migrasyonunun aynısı).

## Hedef Şema

```
legal_suffixes          ← company_types (yeniden adlandır + Latin source genişletme)
business_sectors        ← YENİ
address_abbreviations   ← address_terms (yeniden adlandır)
articles                ← YENİ (bağlaç/edat stopword)
cities                  ← olduğu gibi korunur
non_firm_placeholders   ← YENİ
```

## Alfabe Stratejisi (karışık veri)

RU firma verisi Kiril + Latin transliterasyon karışık geliyor. Strateji:
- Her kuralın **source** (sol) tarafında hem Kiril hem Latin transliterasyon varyantları.
- **Kanonik hedef (sağ) Kiril** kalır (yerel norm; mevcut ru.json yaklaşımı korunur).
- İki alfabe de tek kanonik'e map edildiği için RU içinde tutarlılık garanti, recall maksimum.

Örnek:
```
"общество с ограниченной ответственностью,obshchestvo s ogranichennoy otvetstvennostyu,ооо,о.о.о,ooo,o.o.o=>ооо"
```

## Kategori İçerikleri

### legal_suffixes (containment kontrollü)
Mevcut 9 Rus legal formu korunur. Rus legal rejimleri **farklı regülasyon rejimleri**
olduğu için **ayrı kanonik** kalır (over-merge önlemi):
- ООО (ograničennoj — limited liability)
- АО (akcionernoe — joint stock)
- ПАО (publichnoe AO — public joint stock)
- ЗАО (zakrytoe AO — closed joint stock)
- ОАО (otkrytoe AO — open joint stock; tarihsel)
- ИП (individualnoe predpriyatie — sole proprietor)
- ГП / КП (gosudarstvennoe / kollektivnoe)
- товарищество / КТ (partnership)

Sadece yazım varyantları (dotted `о.о.о`, undotted `ооо`, spaced, + Latin `ooo`/`o.o.o`)
genişletilir. Aktivite-tanımlayıcı birleştirme YOK (Rusça'da SACIF-tarzı kompozit yok).

### business_sectors (YENİ, ~12)
Her biri Kiril full + Latin transliterasyon + kısaltma → Kiril kanonik:
торговая (trade), промышленная (industrial), строительная (construction),
транспортная (transport), производственная (manufacturing), нефтяная (oil),
металлургическая (metallurgy), продуктовая/пищевая (food), технологическая (tech),
логистическая (logistics), страховая (insurance), инвестиционная (investment).

### articles (YENİ — bağlaç/edat stopword)
Şirket adlarında geçen ayırt-edici-olmayan bağlaç/edatlar:
и, i, по, на, с, s, для + Latin amp, and.
(Plain liste; `=>` yok.)

### address_abbreviations (yeniden adlandır)
Mevcut 20 adres terimi (улица/ул, проспект/пр, дом/д, корпус/корп...) — sadece key adı
`address_terms` → `address_abbreviations`. Latin source'lar zaten mevcut.

### non_firm_placeholders (YENİ — plain phrase listesi)
Rusça firma-olmayan placeholder'lar + Latin transliterasyon:
«не указано / ne ukazano», «нет данных», «физическое лицо / fizicheskoe litso»,
«частное лицо», «конечный потребитель», «без названия», «не определено», «прочие».

### cities
Mevcut 17 şehir kuralı olduğu gibi korunur (henüz standart loader okumuyor; mx/br/ar de
aynı şekilde tutuyor).

## Disjointness & Kurallar

- Class disjointness: her token tek kategoride. Öncelik address → legal → sector → geo → article.
- Rule format (Solr): `variant1,variant2,canonical=>canonical`; kanonik source'a da dahil (idempotent).
- articles / non_firm_placeholders plain liste (no `=>`).
- Surgical edit: ASCII-anchor ile, Kiril/aksan bozulmadan.

## Doğrulama

```bash
.venv\Scripts\python.exe -c "import json; json.load(open('synonyms_data/ru.json',encoding='utf-8')); print('json ok')"
.venv\Scripts\python.exe -c "from core.synonym_loader import get_legal_suffix_tokens as g; print(sorted(g('RU'))[:30])"
.venv\Scripts\python.exe -c "from core.synonym_loader import get_business_sector_tokens as g; print(sorted(g('RU'))[:30])"
.venv\Scripts\python.exe -c "from core.synonym_loader import get_non_firm_placeholders as g; print(sorted(g('RU')))"
.venv\Scripts\python.exe -c "from core.synonym_loader import get_address_tokens as g; print(sorted(g('RU'))[:30])"
```
Beklenti: hepsi non-empty ve RU'ya özgü token'lar görünür.

`tests/test_synonym_loader.py`'a RU sınıflandırma assertion'ları eklenir (legal/sector/
placeholder/address non-empty + örnek token üyeliği).

## Bilinen Riskler

1. **ES analyzer Kiril desteği:** Kanonik hedef Kiril olduğu için `es/manager.py`
   `clean_analyzer`'ının Kiril'i doğru lowercase/tokenize ettiği doğrulanmalı (ICU
   gerekebilir). Implementation'da kontrol edilecek; gerekirse risk olarak raporlanacak.
2. **Reindex zorunlu:** Synonym değişiklikleri `python -m es.manager --force --country ru`
   + rematch sonrası etkili. Bu PR canlı etki iddia ETMEZ; kod + test teslimi.
3. **Çift-token precedence:** common.json ile RU arasında aynı source token varsa
   `load_synonyms_for_country` precedence'ı (ülke > common) tek-token garantisini korur;
   yeni RU kuralları common ile çakışmamalı (örn. Latin `ooo` gibi RU-özgü token'lar common'da yok).

## Kapsam Dışı (YAGNI)

- `cities` için yeni loader yazımı (açık tasarım boşluğu, ayrı iş).
- Diğer 39 legacy cc dosyasının migrasyonu (bu iş yalnızca RU).
- Phonetic typo enumerasyonu (synonym_phonetic.py long-tail'i otomatik yakalar).
