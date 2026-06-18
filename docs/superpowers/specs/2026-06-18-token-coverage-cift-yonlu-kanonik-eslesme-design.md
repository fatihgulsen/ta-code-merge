# TOKEN_COVERAGE — Çift Yönlü Tam-Kanonik Token Eşleşmesi (Design)

**Tarih:** 2026-06-18
**Branch:** feat/synonym-classification-per-country
**Durum:** Tasarım onaylandı → writing-plans

---

## 1. Problem

TOKEN_COVERAGE stage'i farklı firmaları birleştiriyor. Kullanıcının bildirdiği 3 vaka (MX):

| Master | Variant (girdi) | Detay |
| :-- | :-- | :-- |
| ELEKTROKONTAKT SRL DE C.V. | S. S. DE R.L. DE C.V. | TOKEN_COVERAGE 12.38 |
| AGRO Y ACOLCHADOS S.A. DE C.V. | VIOTTI S.A. DE C.V. | TOKEN_COVERAGE 16.73 |
| DELARUB MEXICO S.A. DE C.V. | DELEITES DE MEXICO S.A. DE C.V. | TOKEN_COVERAGE 18.90 |

Kullanıcı beklentisi: **iki taraftaki token'lar %100 birbirini kapsamalı** — yani iki ismin
token'ları (legal/geo dahil) birebir aynı olmalı, sadece kelime sırası serbest.

### Canlı tanı (güncel kod + MX index, `_analyze` ile doğrulandı)

- **Case 1 GERÇEK ve güncel hata, üretilebiliyor:**
  ```
  S. S. DE R.L. DE C.V.       → tokens [s, s, de, rl, de, cv]   (count 6)
  ELEKTROKONTAKT SRL DE C.V.  → tokens [elektrokontakt, s, de, rl, de, cv]  (count 6)
  ```
  `SRL` synonym ile `s de rl`'e açılıyor; TOKEN_COVERAGE bu girdiyi elektrokontakt'a +
  maharmex/containerland/tonelarteq/sumical gibi onlarca "… S. de R.L. de C.V." firmasına eşliyor.
- **Case 2 & 3: güncel TOKEN_COVERAGE'da 0 hit** → mevcut kodla üretilemiyor (stripping dönemi
  eski eşleşmeler ya da artımlı rematch artığı). Tasarım yine de bu vaka sınıfını kapsar.

### Kök neden

TOKEN_COVERAGE çift yönlü kapsamayı iki **dolaylı** mekanizmayla yaklaşıklıyor:

1. `match` + `operator:and` → sorgu token'ları **alt-küme** (query ⊆ master); token çokluğunu
   yok sayar, master'daki fazla token'ı (elektrokontakt) engellemez.
2. `_core_coverage_filter` → master varyantı `token_count`'u sorgununkine **eşit** olmalı; bu bir
   **sayı proxy'si**, küme eşitliği değil (6 == 6 çakışması case 1'i geçiriyor).

Ek olarak `_has_distinctive_core` gate'i **sızdırıyor**: `get_generic_tokens(MX)`, MX synonym
dosyasının legacy kategori adları yüzünden legal token'ları (srl/de/cv) kapsamıyor → "S.S." için
True dönüyor (oysa ayırt edici çekirdeği yok).

---

## 2. Hedef davranış (kararlar)

- **Eşleşme kuralı:** TOKEN_COVERAGE iki ismi ancak **tam-kanonik token multiset**'leri birebir
  aynıysa eşler. Sıra serbest; çokluk + legal/geo dahil. (Birleşmesi gerekenleri synonym zaten
  birleştirir; bu stage onun ötesinde token silmez/gevşetmez.)
- **Boş çekirdek:** Ayırt edici çekirdeği olmayan isimler (örn. `S. S. DE R.L. DE C.V.`, saf-legal
  `S.A. DE C.V.`) TOKEN_COVERAGE'da **hiç eşleşmez (MATCH_NONE)**. Pipeline'dan dışlanmaz —
  CANONICAL_EXACT ile birebir aynı form yakalanabilir, yoksa NEW_MASTER olur.
- **CANONICAL_EXACT'tan farkı:** TOKEN_COVERAGE kelime-sırası bağımsızdır (örn. `ACME GIDA` ≡
  `GIDA ACME`); değeri budur.

---

## 3. Çözüm — A′ (saf-ES, pratikte multiset)

Mimari deseni korur: `variations: [{"name": ...}]` ham kanonik saklanır, alt-alanlar **ES mapping +
ingest pipeline** ile otomatik türetilir. **Hiçbir yazma yolu (es_writer/pipeline) değişmez.**

İki ES alt-alanı birlikte multiset eşitliğini verir:

1. **`variations.name.canonical_full`** (YENİ) — analyzer = clean zinciri (synonym_graph +
   normalizer'lar, **legal-strip YOK, article-strip YOK** — her token önemli) + `flatten_graph`
   + `fingerprint_token_filter` (sort + dedup). Sonuç: tam kanonik token **kümesinin** sıralı-tekil
   tek-token temsili. Mevcut `clean_analyzer_*`/`fingerprint_analyzer` zincirleri DEĞİŞMEZ.
2. **`variations.name.token_count`** (MEVCUT) — toplam token sayısı (çokluk).

**Eşleşme = `canonical_full` term-eşitliği (aynı küme) VE `token_count` eşitliği (aynı toplam).**
Küme aynı + toplam aynı → gerçek hayattaki tüm firma adlarında multiset aynı.

- Çakışma yalnızca "aynı küme + aynı sayı + farklı çokluk" (örn. {a,a,b} vs {a,b,b}) gerektirir;
  firma adlarında pratikte gerçekleşmez ve çekirdek-gate'le elenir.

### Gate — fingerprint-boş kontrolü

`_has_distinctive_core` yeniden tanımlanır: **`fingerprint_analyzer(name)` boş token üretiyorsa
çekirdek yok → MATCH_NONE.** Bu, sızdıran `get_generic_tokens` bağımlılığını **bypass eder**
(saf-ES, legal_fragment_stop tabanlı). Doğrulandı:

```
S. S. DE R.L. DE C.V.       → fingerprint []            (boş → MATCH_NONE)
ELEKTROKONTAKT SRL DE C.V.  → fingerprint [elektrokontakt]
DELEITES DE MEXICO …        → fingerprint [deleites mexico]
```

> Not: gate yalnızca TOKEN_COVERAGE/FUZZY_PHRASE gibi loose stage'lerde uygulanır; CANONICAL_EXACT
> kendi `require_alpha=False` davranışını korur (salt-sayı exact dedup).

---

## 4. Sorgu yapısı (TOKEN_COVERAGE, yeni)

```
if fingerprint_analyzer(name) boş → MATCH_NONE
qf  = canonical_full(name)        # query'nin sıralı-tekil kanonik kümesi (_analyze, cache'li)
qtc = token_count(name)           # query toplam token sayısı (_analyze, cache'li)

bool.must:
  nested(variations):
    bool.filter:
      term  variations.name.canonical_full = qf
      term  variations.name.token_count   = qtc
bool.filter:
  term country_code = CC
```

- Eski `match operator:and` ve `_core_coverage_filter` bu stage'den **kaldırılır**.
- `qf` / `qtc` ES `_analyze` ile üretilir (Python fuzzy DEĞİL; mevcut `_get_token_count` cache deseni
  genişletilir, ör. `_get_canonical_full`).

---

## 5. Etkilenen modüller

| Modül | Değişiklik |
| :-- | :-- |
| `es/manager.py` | `fingerprint_token_filter`'lı yeni `canonical_full_analyzer_<cc>` (legal-strip'siz); `variations.name` altına `canonical_full` multi-field. Reindex (`--force`). |
| `es/queries.py` | `TOKEN_COVERAGE` yeniden yazılır (canonical_full + token_count term-eşitliği). `_has_distinctive_core` → fingerprint-boş kontrolü. `_get_canonical_full` helper (cache'li `_analyze`). `_core_coverage_filter` TOKEN_COVERAGE'dan çıkar (FUZZY_PHRASE'deki kullanımı korunur/ayrı değerlendirilir). |
| `config.py` | Gerekirse `ENABLE_CORE_COVERAGE_GATE` revize; gate flag adları korunur. |
| `tests/` | `_has_distinctive_core` fingerprint-boş; TOKEN_COVERAGE canonical_full+token_count yapısı; 3 vaka negatif + reorder/typo pozitif golden. |
| `analysis/live_probe.py` | Golden sete 3 vaka (negatif) eklenir; reindex sonrası precision/recall ölçümü. |
| `CLAUDE.md` / `README.md` | TOKEN_COVERAGE açıklaması güncellenir. |

---

## 6. Doğrulama planı

1. **Birim:** `pytest tests/test_es_queries.py` — yeni sorgu yapısı + gate.
2. **Canlı reindex:** `python -m es.manager --force` (MX en az).
3. **Probe:** `python -m analysis.live_probe` — 3 vaka eşleşmemeli; vibracoustic/ceva/dhl recall korunmalı.
4. **Doğrudan tanı:** 3 girdi için TOKEN_COVERAGE 0/yanlış-firma hit; gerçek dup → eşleşir.
5. **Rematch (opsiyonel, tam):** wipe + rematch sonrası MX precision (match-auditor Mode B).

---

## 7. Riskler & kapsam dışı

- **Recall daralması:** TOKEN_COVERAGE artık tam-küme istiyor → eski gevşek eşleşmeler düşebilir.
  Çoğu meşru varyasyon (typo/nokta/sıra) synonym + reorder ile korunur; probe recall'ı izler.
- **Çakışma sınıfı** (aynı küme+sayı, farklı çokluk): kabul edilen teorik artık; gate'le örtüşür.
- **Kapsam dışı:** synonym-kategori-adı tutarsızlığının genel düzeltimi (authoring-synonyms ayrı iş);
  burada gate fingerprint-boş ile bu bağımlılıktan kurtulduğu için bloklamaz.
- **Multi-country:** `canonical_full_analyzer` per-country üretilir (clean_analyzer deseniyle aynı).
