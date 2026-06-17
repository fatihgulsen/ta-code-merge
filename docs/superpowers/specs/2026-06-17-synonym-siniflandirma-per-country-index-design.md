# Tasarım: Synonym Sınıflandırma + Per-Country Index + Kirli Veri + Synonym-İçi Fonetik

**Tarih:** 2026-06-17
**Durum:** Onaylandı (tasarım) — uygulama planı bekliyor
**Kapsam:** 4 bağlı mimari değişiklik. Hepsi synonym yapısı etrafında döner.

---

## 1. Amaç & Bağlam

Mevcut sistem tek ortak ES index'i (`living_companies_v2`, `_routing=country_code`) ve
"strip-then-compare" (synonym token'larını silip kalan çekirdeği karşılaştırma) yaklaşımı
kullanıyor. Bu tasarım 4 değişikliği getirir:

1. **Per-country index** — her ülke kendi fiziksel index'i + alias.
2. **Token sınıflandırma** — silme yerine her token'ı synonym tablosundan sınıflandırma.
3. **Kirli veri işareti** — address synonym'i baskın + eşleşme yok ise `DIRTY_DATA`.
4. **Synonym-içi fonetik** — fonetik typo-rescue, yalnızca synonym sözlüğüne uygulanır.

### Onaylanan mimari kararlar

- **Karar A1:** Çekirdek çıkarma/sınıflandırma **ES ingest Painless**'te kalır (ES-side kuralı).
- **Karar B1:** Fonetik typo-rescue, sınırlı bir **Python adımı** (metaphone sözlük-araması,
  Levenshtein/RapidFuzz değil). Hem ingest-öncesi hem sorgu-öncesi çalışır (simetri).

---

## 2. Madde 1 — Per-Country Index

### Mevcut
Tek `living_companies_v2`; 65 ülke analyzer'ı tek index içinde; `_routing=country_code`;
sorgularda `{"term": {"country_code": cc}}` filtresi.

### Hedef
- Fiziksel index: `living_companies_<cc>_v3`; üstünde alias `living_companies_<cc>`.
- Tüm okuma/yazma **alias** üzerinden. İleride `_v4` + alias-swap ile sıfır-kesintili reindex.
- Her index **yalnızca o ülkenin** analyzer'larını taşır. Analyzer adları sabit
  (`clean_analyzer`, `stripped_search_analyzer`, `phonetic_analyzer`) — `_cc` soneki YOK.
- `number_of_shards`: per-country index için düşürülür (öneri: 1; ölçüp ayarlanır).
- Geçersiz/2-harf-olmayan ülke kodu → `EXCLUDED` (sebep `invalid_country`); `DEFAULT`
  index'i **yok**, kayıt index'lenmez.

### Etkilenen dosyalar
| Dosya | Değişiklik |
| :--- | :--- |
| `config.py` | `ES_INDEX` kaldırılır → `INDEX_PREFIX` + `index_for_country(cc)` / `alias_for_country(cc)` |
| `es/manager.py` | `create_index` ülke döngüsü; index başına sade analyzer; alias kurulumu; `acronym_glue_active` per-index |
| `es/queries.py` | `country_code` term filtresi ve `_get_analyzer` ülke-dallanması kaldırılır; analyzer adları sabit |
| `matching/pipeline.py` | `msearch` header `{"index": alias_for_country(cc)}`, `routing` kalkar; `_analyze` per-index |
| `es/ingest.py` | Pipeline kayıtları aynı (zaten per-country); index hedefleri alias |
| `es/transform.py` | Ülke index'leri üzerinde döngü |
| `dedup/auto_merge.py` | Ülke index'leri üzerinde döngü; fingerprint aggregation per-index |
| `tools/reset_matching.py` | Tüm ülke index'lerini sıfırlama |

### Kazanımlar / Riskler
- (+) Query DSL ve analyzer tanımı 65 kat sadeleşir; tek ülke reindex'i izole.
- (−) Daha çok index/shard → shard sayısı düşürülmeli.
- (−) Cross-country raporlama artık alias / multi-index okuma gerektirir.

---

## 3. Madde 2 — Token Sınıflandırma

### Mevcut
Ingest, `legal_suffixes + articles + kendi-ülke-geo` token'larını siler → `variations_stripped`.

### Hedef
Ingest Painless her token'ı **sınıflandırır** (öncelik sırası, ilk eşleşen kazanır):

```
address  → legal  → sector  → geo(kendi ülke)  → article  → core
```

- Synonym token'ları **kanonik forma** çevrilir (`A,B=>C` ⇒ `C`).
- `core` = hiçbir synonym sınıfına girmeyen token (marka/ayırt edici çekirdek).

### Yeni ES doküman alan düzeni
| Alan | İçerik | Kullanım |
| :--- | :--- | :--- |
| `variations[].name` | Tam form (synonym_graph analyzer) | CANONICAL_EXACT, FUZZY_PHRASE, TOKEN_COVERAGE |
| `variations_core[].name` | Yalnız çekirdek token'lar | **Birincil eşleştirme** (eski `variations_stripped` yerine) |
| `variations_core[].name.token_count` | Çekirdek kelime sayısı | 1-1 identity + coverage gate |
| `variations_core[].name.fingerprint` | Sıralı+tekil çekirdek parmak izi | dedup/auto_merge, transform |
| `address_token_count` | İsimdeki address-sınıfı token sayısı | 3. madde kirli tespiti |

> **NOT (YAGNI):** ES'te ayrı `variations_synonym[]` / `.phonetic` alanı **kurulmaz**. Fonetik
> typo-rescue (Madde 4) tamamen sorgu/ingest öncesi Python normalize adımında çözülür; ES
> tarafında synonym-fonetik alanı eşleştirmede kullanılmaz.

### Eşleştirme stage'leri
- Tüm `variations_stripped` referansları → `variations_core`.
- Çekirdek-exact, distinctive-core gate, coverage gate mantığı **aynı kalır** (yalnız alan adı
  ve analyzer adı değişir).

---

## 4. Madde 4 — Synonym-İçi Fonetik (Typo-Rescue)

### Amaç
Bir synonym token'ı o kadar bozuk yazılmış ki synonym listesinde **yok** ve çekirdeğe sızıyor
(`limmtd`, `internacaonal`). Bu, aynı-firma kayıtlarının çekirdeğini farklılaştırıp under-merge
üretiyor. Fonetik bunu kurtarır; **markaya/çekirdeğe asla dokunmaz.**

### Katı kural (kullanıcı talebi)
Fonetik YALNIZCA synonym dosyasındaki girişlere uygulanır; firma/marka ismine **asla**.
Karşılaştırma hedefi her zaman bir synonym girişidir: bir name-token fonetik olarak bir synonym
girişine eşleşirse o synonym'in kanonik formuna çevrilir; eşleşmezse **çekirdek olarak korunur**.
Hiçbir koşulda iki marka token'ı birbirine fonetik kıyaslanmaz.

### Tasarım
- Yeni modül: `core/synonym_phonetic.py`.
- Build-time: synonym sözlüğünün (legal+sector+geo+article+address) metaphone kodları
  `synonyms_data/`'dan türetilip `metaphone_code → kanonik_form` haritası kurulur (per-country).
- Çalışma-zamanı: `canonicalize_phonetic(name, cc)` →
  her token için: listede **tam** varsa dokunma; tam yoksa ama metaphone'u bir synonym
  girişiyle eşleşiyorsa → token **kanonik synonym formuna** çevrilir; aksi halde aynen bırakılır
  (çekirdek korunur).
- **Hem** ingest-öncesi (ES'e yazmadan) **hem** sorgu-öncesi (eşleştirmeden önce) çağrılır →
  index/sorgu simetrisi.
- Metaphone hesaplama: hafif fonetik kodlama (Levenshtein/RapidFuzz değil). Kullanıcı tarafından
  açıkça talep edildi; CLAUDE.md "Python fuzzy yasak" kuralının dışında değerlendirilir
  (sözlük-araması, string-distance değil).

### Kaldırılanlar
- `config.SUFFIX_TYPO_MAP` referansları (varsa) — fonetik typo-rescue yerini alır.
- Kapalı `PHONETIC_MATCH` ve `NGRAM_MATCH` stage'leri (artık işlevsiz) ve ilgili
  analyzer/alan tanımları.

---

## 5. Madde 3 — Kirli Veri

### Tasarım
- Yeni `MatchType.DIRTY_DATA`.
- `matching/pipeline.py` apply-pass'te, kazanan **yoksa** (NEW_MASTER yoluna girmeden önce):
  ES `_analyze` ile sorgu isminin (a) address-token sayısı, (b) çekirdek ayırt-ediciliği ölçülür.
- **Karar:**
  - `address_token_count > 0` **VE** çekirdek zayıf/yok (distinctive-core yok) → `DIRTY_DATA`.
  - Çekirdek güçlü → normal `NEW_MASTER` (isimde address geçse bile, örn. "Main Street Pharma").
- **Davranış:** `DIRTY_DATA` kaydı ES'e **index'lenir** (sonraki kayıtlar eşleşebilsin) ama
  PG'de `match_type=DIRTY_DATA` işaretli. Çekirdek zayıf olduğundan distinctive-core gate onu
  magnet olmaktan zaten korur.

### Etkilenen dosyalar
| Dosya | Değişiklik |
| :--- | :--- |
| `config.py` | `MatchType.DIRTY_DATA` eklenir |
| `core/synonym_loader.py` | `get_address_tokens(cc)` (address_abbreviations sınıfı) |
| `matching/pipeline.py` | No-match dalında kirli kontrolü + `DIRTY_DATA` yazımı |

---

## 6. Madde 5 — Synonym Dosya Yenileme

İçerik **yine sabittir** (yeni keyfi token eklenmez, Python'da hardcode yok). Yenileme =
**yasal-ek (legal_suffix) ailelerinin birleştirilmesi**:

- Biri diğerini **kapsayan** / aynı uzantının daha **uzun hali** olan ekler tek synonym grubuna
  alınır ve aynı kanonik forma indirgenir.
  - Örnek (AR): `sa` ile `sacif` aynı aile → `sa,sacif=>...` (SACIF, SA'nın uzun hali).
  - Karşı-örnek: `gmbh` ile `sa` farklı tüzel form → **ayrı** gruplar, birleştirilmez.
- Bu, JSON'daki `A,B=>C` gruplamasının **per-country küratörlüğüdür** (data, ES synonym_graph
  ile uygulanır). Prefix/containment kararı insan-küratörlüdür; otomatik prefix-eşleme **yok**.
- `address_abbreviations` sınıfı eşleştirmeye **dahil edilir** (bugün atıl); ülke dosyalarında
  bütünlüğü gözden geçirilir.
- JSON tutarlılığı: kanonik hedef tek, sınıflar çakışmasız (bir token birden çok sınıfa girerse
  §3 öncelik sırası uygulanır).
- **CLAUDE.md etkisi:** §1.4 "JSON sabit" kuralı, legal-suffix aile gruplaması için bilinçli
  istisna alır; eski `SUFFIX_TYPO_MAP` (config) kalkar (typo işi fonetik-rescue'ye taşınır).
  CLAUDE.md uygulama sırasında güncellenir.

---

## 7. Test, Migrasyon, Riskler

### Test (TDD)
- Her değişiklik için önce test (RED → GREEN → refactor).
- Mevcut ~192 test güncellenir: `ES_INDEX` → per-country alias; `variations_stripped` →
  `variations_core`.
- Yeni testler: `index_for_country`/alias; token sınıflandırma (her sınıf + öncelik);
  `canonicalize_phonetic` (typo-rescue + marka-korunur); `DIRTY_DATA` karar tablosu;
  DEFAULT reddi.

### Migrasyon
- Eski tek index düşürülür; tüm ülke index'leri sıfırdan kurulur.
- Tam reindex + rematch (roadmap'te zaten bekliyordu).
- Alias kurulumu ilk create'te yapılır.

### Riskler
- (R1) 65 index ⇒ shard patlaması → `number_of_shards=1` ile başla, ölç.
- (R2) Cross-country raporlama kırılır → alias/multi-index okuma ile telafi.
- (R3) Python metaphone yeni bağımlılık → hafif, saf-Python kütüphane tercih edilir.
- (R4) Fonetik over-rescue (meşru marka token'ını yanlışlıkla synonym'e çevirme) → en yüksek
  öncelikli risk. Korumalar: (a) yalnız "listede tam yok ama metaphone TAM eşleşiyor"; prefix
  eşleme yok; (b) çok kısa synonym token'ları (örn. tek-harf/iki-harf metaphone kodları) marka
  fragmanlarıyla çakışabilir → minimum kod uzunluğu eşiği; (c) altın-küme testiyle (gerçek
  markalar synonym'e çevrilmemeli) doğrulanır.

---

## 8. Önerilen Uygulama Sırası

1. **Synonym sınıflandırma temeli** (Madde 2) — keystone; diğerleri buna dayanır.
2. **Per-country index** (Madde 1) — altyapı; sınıflandırma ile birlikte reindex.
3. **Fonetik typo-rescue** (Madde 4) — sınıflandırma üstüne.
4. **Kirli veri** (Madde 3) — sınıflandırma + address sınıfı üstüne.
5. **Synonym dosya yenileme** (Madde 5) — yatay; sınıflandırmayla doğrulanır.

Detaylı adımlar `writing-plans` ile çıkarılacak.
