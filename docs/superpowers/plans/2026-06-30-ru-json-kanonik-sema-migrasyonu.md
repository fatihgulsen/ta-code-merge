# ru.json Kanonik Şema Migrasyonu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `synonyms_data/ru.json`'u legacy şemadan mx/br/ar ile aynı kanonik şemaya taşımak (legal_suffixes / business_sectors / address_abbreviations / articles / non_firm_placeholders), böylece sınıf-bazlı loader'lar RU token'larını sınıflandırabilsin.

**Architecture:** Tek veri dosyası (`ru.json`) düzenlenir; mantık değişmez. TDD ile önce `tests/test_synonym_loader.py`'a RU sınıflandırma testleri (RED) yazılır, sonra `ru.json` kanonik şemaya çevrilir (GREEN), son olarak disjointness/no-collision invariant'ları doğrulanır. Kanonik hedef Kiril; source tarafı Kiril + Latin transliterasyon karışık.

**Tech Stack:** Python 3.12 (`.venv`), pytest, JSON (Solr synonym formatı). Loader: `core/synonym_loader.py` (değiştirilmez, yalnızca okunur).

## Global Constraints

- Kanonik hedef (`=>` sağ tarafı) **Kiril** kalır; source tarafına Kiril + Latin transliterasyon eklenir. Verbatim: `...,ooo,o.o.o=>ооо`.
- Rule format (Solr): `variant1,variant2,canonical=>canonical`; kanonik form source'a da dahil (idempotent). `articles` ve `non_firm_placeholders` plain liste (no `=>`).
- Class disjointness: her token TEK kategoride. Öncelik: address → legal → sector → geo → article.
- Rus legal rejimleri (ООО/АО/ПАО/ЗАО/ОАО/ИП/ГП/КП/КТ) **ayrı kanonik** — over-merge yasak.
- Python venv: her zaman `.venv\Scripts\python.exe` (sistem python'u değil).
- pytest **tek tek test** koşulur (`-k` veya `node-id` ile); tüm suite KOŞULMAZ (kaynak/hang riski).
- Dosya düzenlemede Kiril/aksan bozulmaz; UTF-8 korunur.
- Synonym değişiklikleri yalnızca `python -m es.manager --force --country ru` + rematch sonrası canlı; bu plan canlı etki iddia ETMEZ.

---

### Task 1: RU sınıflandırma testlerini ekle (RED)

**Files:**
- Modify: `tests/test_synonym_loader.py` (dosya sonuna ekle)

**Interfaces:**
- Consumes: `core.synonym_loader.get_legal_suffix_tokens`, `get_business_sector_tokens`, `get_article_stopwords`, `get_non_firm_placeholders`, `get_address_tokens`, `get_generic_tokens` (mevcut imzalar; hepsi `(country_code: str) -> frozenset`, placeholder hariç).
- Produces: RU şema doğrulama testleri — Task 2 bunları yeşile çevirir.

- [ ] **Step 1: Failing testleri dosya sonuna ekle**

`tests/test_synonym_loader.py` dosyasının en altına ekle:

```python


# --- RU kanonik şema migrasyonu (2026-06-30) ---


def test_ru_legal_suffixes_classified():
    """RU legal formları legal_suffixes olarak sınıflandırılmalı (legacy company_types değil)."""
    from core.synonym_loader import get_legal_suffix_tokens
    tokens = get_legal_suffix_tokens("RU")
    # Kiril kanonikler
    for expected in ("ооо", "ао", "пао", "зао", "оао", "ип"):
        assert expected in tokens, f"{expected!r} RU legal_suffixes'te yok"
    # Latin transliterasyon source'ları da sınıflanmalı
    for expected in ("ooo", "ao", "pao"):
        assert expected in tokens, f"{expected!r} (Latin) RU legal_suffixes'te yok"
    # Common İngilizce formlar hâlâ akmalı
    assert "ltd" in tokens


def test_ru_legal_regimes_stay_separate():
    """Rus legal rejimleri farklı kanonik kalmalı (over-merge yok)."""
    from core.synonym_loader import get_synonym_canonical_map
    m = get_synonym_canonical_map("RU", ("legal_suffixes",))
    assert m.get("ооо") == "ооо"
    assert m.get("ао") == "ао"
    assert m.get("зао") == "зао"
    assert m.get("оао") == "оао"
    # Latin source'lar da doğru Kiril kanonike gitmeli
    assert m.get("ooo") == "ооо"
    assert m.get("zao") == "зао"


def test_ru_business_sectors_classified():
    """RU sektör kelimeleri business_sectors olarak sınıflanmalı."""
    from core.synonym_loader import get_business_sector_tokens
    tokens = get_business_sector_tokens("RU")
    for expected in ("торговая", "промышленная", "строительная", "транспортная"):
        assert expected in tokens, f"{expected!r} RU business_sectors'te yok"
    # Latin transliterasyon
    assert "torgovaya" in tokens


def test_ru_address_abbreviations_classified():
    """RU adres terimleri address_abbreviations olarak sınıflanmalı (legacy address_terms değil)."""
    from core.synonym_loader import get_address_tokens
    toks = get_address_tokens("RU")
    for expected in ("улица", "проспект", "дом"):
        assert expected in toks, f"{expected!r} RU address'te yok"
    assert "ул." in toks or "ул" in toks


def test_ru_articles_classified():
    """RU bağlaç/edatları article stopword olarak sınıflanmalı."""
    from core.synonym_loader import get_article_stopwords
    arts = get_article_stopwords("RU")
    assert "и" in arts
    assert "по" in arts
    # Common articles hâlâ akmalı
    assert "and" in arts


def test_ru_non_firm_placeholders_classified():
    """RU firma-olmayan placeholder'lar sınıflanmalı."""
    from core.synonym_loader import get_non_firm_placeholders
    ph = get_non_firm_placeholders("RU")
    assert "не указано" in ph
    assert "физическое лицо" in ph


def test_ru_categories_disjoint():
    """RU kategorileri ayrışık olmalı (legal ∩ sector = ∅)."""
    from core.synonym_loader import (
        get_business_sector_tokens,
        get_legal_suffix_tokens,
    )
    overlap = get_business_sector_tokens("RU") & get_legal_suffix_tokens("RU")
    assert not overlap, f"RU legal/sector çakışması: {sorted(overlap)}"
```

- [ ] **Step 2: Testlerin FAIL ettiğini doğrula**

Run: `.venv\Scripts\python.exe -m pytest tests/test_synonym_loader.py -k "ru_" -v`
Expected: 7 test, çoğu FAIL (örn. `assert 'ооо' in tokens` → AssertionError; RU dosyası `company_types` legacy key kullandığı için `legal_suffixes` boş döner, sadece common token'lar gelir).

- [ ] **Step 3: Commit (RED testleri)**

```bash
git add tests/test_synonym_loader.py
git commit -m "test(synonym): ru.json kanonik şema sınıflandırma testleri (RED)"
```

---

### Task 2: ru.json'u kanonik şemaya çevir (GREEN)

**Files:**
- Modify: `synonyms_data/ru.json` (tam yeniden yaz — 6 kategori)

**Interfaces:**
- Consumes: Task 1 testleri.
- Produces: Kanonik şemalı `ru.json`. Sonraki task'lar dosyanın geçerli JSON olduğuna ve invariant'ları koruduğuna güvenir.

- [ ] **Step 1: `synonyms_data/ru.json` dosyasını aşağıdaki içerikle tamamen değiştir**

Mevcut dosya `company_types`/`address_terms`/`cities` içeriyor. Tam içerik (Write ile yaz):

```json
{
  "legal_suffixes": [
    "общество с ограниченной ответственностью,obshchestvo s ogranichennoy otvetstvennostyu,ооо,о.о.о,ooo,o.o.o=>ооо",
    "акционерное общество,aktsionernoe obshchestvo,ао,а.о,ao,a.o=>ао",
    "публичное акционерное общество,publichnoe aktsionernoe obshchestvo,пао,п.а.о,pao,p.a.o=>пао",
    "индивидуальное предприятие,индивидуальный предприниматель,individualnoe predpriyatie,individualnyy predprinimatel,ип,и.п,ip,i.p=>ип",
    "коллективное предприятие,kollektivnoe predpriyatie,кп,к.п,kp,k.p=>кп",
    "государственное предприятие,gosudarstvennoe predpriyatie,гп,г.п,gp,g.p=>гп",
    "закрытое акционерное общество,zakrytoe aktsionernoe obshchestvo,zakrytoe ao,зао,з.а.о,zao,z.a.o=>зао",
    "открытое акционерное общество,otkrytoe aktsionernoe obshchestvo,otkrytoe ao,оао,о.а.о,oao,o.a.o=>оао",
    "товарищество,коммандитное товарищество,tovarishchestvo,kommanditnoe tovarishchestvo,кт,к.т,kt,k.t=>кт"
  ],
  "business_sectors": [
    "торговая,торговый,торговое,torgovaya,torgovyy,торг,torg=>торговая",
    "промышленная,промышленный,промышленное,promyshlennaya,promyshlennyy,пром,prom=>промышленная",
    "строительная,строительный,строительное,stroitelnaya,stroitelnyy,строй,stroy=>строительная",
    "транспортная,транспортный,транспорт,transportnaya,transport,трансп,transp=>транспортная",
    "производственная,производственный,производство,proizvodstvennaya,proizvodstvo,произв,proizv=>производственная",
    "нефтяная,нефтяной,нефть,neftyanaya,neft,нефте,nefte=>нефтяная",
    "металлургическая,металлургический,металл,metallurgicheskaya,metall,метал,metal=>металлургическая",
    "пищевая,пищевой,продуктовая,продукты,pishchevaya,produktovaya,продукт,produkt=>пищевая",
    "технологическая,технологический,технологии,tekhnologicheskaya,tekhnologii,техно,tekhno=>технологическая",
    "логистическая,логистический,логистика,logisticheskaya,logistika,логист,logist=>логистическая",
    "страховая,страховой,страхование,strakhovaya,strakhovanie,страх,strakh=>страховая",
    "инвестиционная,инвестиционный,инвестиции,investitsionnaya,investitsii,инвест,invest=>инвестиционная"
  ],
  "address_abbreviations": [
    "улица,ulitsa,ул.,ul=>ул.",
    "проспект,prospekt,пр.,pr=>пр.",
    "переулок,pereulok,пер.,per=>пер.",
    "площадь,ploshchad,пл.,pl=>пл.",
    "бульвар,bulvar,б-р,бул.,bul=>бул.",
    "дом,dom,д.,d=>д.",
    "корпус,korpus,корп.,к.,korp.,k=>корп.",
    "строение,stroenie,стр.,str=>стр.",
    "квартира,kvartira,кв.,kv=>кв.",
    "офис,ofis,оф.,of=>оф.",
    "этаж,etazh,эт.,et=>эт.",
    "комната,komnata,ком.,к.,kom=>ком.",
    "подъезд,podezd,п.,под.,pod=>под.",
    "город,gorod,г.,g=>г.",
    "село,selo,с.,s=>с.",
    "деревня,derevnya,дер.,д.,der=>дер.",
    "посёлок,поселок,poselok,п.,пос.,pos=>пос.",
    "микрорайон,mikrorayon,мкр.,мкрн.,м-н,м-р,mkr=>мкр.",
    "область,oblast,обл.,obl=>обл.",
    "район,rayon,р-н,рн,rn=>р-н"
  ],
  "articles": [
    "и",
    "i",
    "по",
    "po",
    "на",
    "na",
    "для",
    "dlya",
    "amp",
    "and"
  ],
  "cities": [
    "москва,moscow,moskva,msk,mow=>москва",
    "санкт-петербург,saint petersburg,st. petersburg,sankt-peterburg,leningrad,ленинград,spb,led=>санкт-петербург",
    "новосибирск,novosibirsk,ovb=>новосибирск",
    "екатеринбург,yekaterinburg,ekaterinburg,sverdlovsk,свердловск,svx=>екатеринбург",
    "нижний новгород,nizhny novgorod,gorky,горький,goj=>нижний новгород",
    "казань,kazan,kzn=>казань",
    "челябинск,chelyabinsk,cek=>челябинск",
    "омск,omsk,oms=>омск",
    "самара,samara,kuf=>самара",
    "ростов-на-дону,rostov-on-don,rostov,ростов,rov=>ростов-на-дону",
    "уфа,ufa=>уфа",
    "красноярск,krasnoyarsk,kja=>красноярск",
    "воронеж,voronezh,voz=>воронеж",
    "пермь,perm,pee=>пермь",
    "волгоград,volgograd,stalingrad,сталинград,vog=>волгоград",
    "краснодар,krasnodar,krr=>краснодар",
    "владивосток,vladivostok,vvo=>владивосток"
  ],
  "non_firm_placeholders": [
    "не указано",
    "ne ukazano",
    "нет данных",
    "net dannykh",
    "нет наименования",
    "без названия",
    "bez nazvaniya",
    "физическое лицо",
    "fizicheskoe litso",
    "частное лицо",
    "chastnoe litso",
    "конечный потребитель",
    "konechnyy potrebitel",
    "не определено",
    "ne opredeleno",
    "прочие",
    "prochie"
  ]
}
```

Not (article tek-harf riski): `с`/`s` BİLİNÇLİ olarak `articles`'a KONULMADI — tek-harf Latin `s` legal-fragment gürültüsü yaratır ve `с`/`s` zaten `address_abbreviations`'ta (село/stroenie) var; class disjointness önceliği address > article olduğundan article'a koymak gereksiz. Brainstorming'de tartışılan "с/s" bu nedenle düşürüldü.

- [ ] **Step 2: JSON geçerliliğini doğrula**

Run: `.venv\Scripts\python.exe -c "import json; json.load(open('synonyms_data/ru.json',encoding='utf-8')); print('json ok')"`
Expected: `json ok`

- [ ] **Step 3: Task 1 testlerinin PASS ettiğini doğrula**

Run: `.venv\Scripts\python.exe -m pytest tests/test_synonym_loader.py -k "ru_" -v`
Expected: 7 test PASS.

- [ ] **Step 4: Commit**

```bash
git add synonyms_data/ru.json
git commit -m "feat(synonym): ru.json kanonik şemaya migrasyon (legal/sector/address/article/placeholder)"
```

---

### Task 3: Invariant doğrulama (disjointness + no-collision + analyzer notu)

**Files:**
- Modify: `tests/test_synonym_loader.py` (mevcut `test_load_synonyms_no_source_collision`'a RU ekle)

**Interfaces:**
- Consumes: Task 2 çıktısı (`ru.json`), mevcut `_source_target_map` helper'ı.
- Produces: RU için çift-token regresyon koruması.

- [ ] **Step 1: Mevcut no-collision testine RU ekle**

`tests/test_synonym_loader.py` içindeki `test_load_synonyms_no_source_collision` fonksiyonunda ülke tuple'ına `"RU"` ekle. Mevcut satır:

```python
    for cc in ("AR", "BR", "MX", "PE", "__COMMON__"):
```

Yeni hâli:

```python
    for cc in ("AR", "BR", "MX", "PE", "RU", "__COMMON__"):
```

- [ ] **Step 2: No-collision testini koştur**

Run: `.venv\Scripts\python.exe -m pytest tests/test_synonym_loader.py::test_load_synonyms_no_source_collision -v`
Expected: PASS. (FAIL olursa: RU bir source token'ı common ile farklı kanonike gönderiyor demektir — çıktıdaki `collisions` dict'indeki token'ı RU `legal_suffixes`/`business_sectors` source listesinden çıkar; örn. common'da çakışan bir Latin token varsa RU-özgü olanı bırak, ortak olanı kaldır.)

- [ ] **Step 3: Tüm RU testlerini + collision testini birlikte koştur**

Run: `.venv\Scripts\python.exe -m pytest tests/test_synonym_loader.py -k "ru_ or collision" -v`
Expected: tümü PASS.

- [ ] **Step 4: ES analyzer Kiril desteğini elle doğrula (kanıt topla, kod değişikliği yok)**

`es/manager.py`'ın `clean_analyzer`'ı `standard` tokenizer + ICU (`icu_normalizer`/`icu_folding`/`lowercase`) kullanır. `standard` tokenizer Unicode-aware (Kiril'i tokenize eder), ICU folding Kiril'i lowercase eder. Doğrulama (ES çalışıyorsa):

Run: `.venv\Scripts\python.exe -c "from core.synonym_loader import load_synonyms_for_country as L; rules=[r for r in L('RU') if '=>ооо' in r or '=>ао' in r]; print(rules)"`
Expected: RU Kiril kanonik kuralları görünür (synonym listesi RU için doğru üretiliyor).

Not: Kanonik Kiril'in canlı eşleşmede etkili olması `python -m es.manager --force --country ru` gerektirir. ICU plugin kurulu DEĞİLSE (`es/manager.py` uyarı verir) Kiril lowercase düşer — bu durumda reindex sırasında uyarı raporlanmalı. Bu plan reindex'i KAPSAMAZ; yalnızca kod+test teslimi.

- [ ] **Step 5: Commit**

```bash
git add tests/test_synonym_loader.py
git commit -m "test(synonym): ru çift-token no-collision invariant koruması"
```

---

## Reindex & Sonraki Adımlar (kapsam dışı — not)

Bu plan kod + test teslimidir. Canlı etki için:
```bash
python -m es.manager --force --country ru   # RU indeksini yeni synonym ile yeniden kur
python main_processor.py                     # RU rematch
```
QA precision audit için `auditing-matches` skill'i (round metodolojisi) ayrı bir iş olarak çalıştırılabilir.

## Self-Review Notları

- **Spec coverage:** legal_suffixes (Task 2) ✓, business_sectors (Task 2) ✓, address_abbreviations rename (Task 2) ✓, articles (Task 2) ✓, non_firm_placeholders (Task 2) ✓, cities korunur (Task 2) ✓, disjointness (Task 1 test + Task 3) ✓, no-collision precedence (Task 3) ✓, analyzer Kiril riski (Task 3 Step 4) ✓, reindex notu ✓.
- **Containment:** Rus rejimleri ayrı kanonik (Task 1 `test_ru_legal_regimes_stay_separate`) — spec §legal_suffixes ile uyumlu.
- **Article tek-harf riski:** `с`/`s` düşürüldü (Task 2 Step 1 notu) — disjointness önceliği ve over-strip riski gerekçesiyle; spec'teki "yaygın bağlaç/edat" kararından sapma açıkça belgelendi.
