# Round8 — Yanlış Eşleşme (Over-merge) Kök Neden Analizi

**Tarih:** 2026-06-16
**Kapsam:** `p7_firms_v2_ar_pe` (AR + PE) tablosundaki TÜM master↔variant eşleşmeleri (over-merge).
**Kaynak index:** `living_companies_v1` (524.289 doc — denetlenen veri bu index'ten üretildi).
**Yöntem:** 70 batch × ~150 çift, 70 Haiku alt-ajanı tarafından satır-atlamadan (no-skip)
doğru/yanlış işaretlendi. Parite doğrulandı (Σ verdict = 10.352 = N).

> Bu rapor yalnızca **over-merge** (yanlış birleşme) içindir. Under-merge ayrı görevdir.

---

## 1. Özet Metrikler

| Metrik | Değer |
| :-- | :-- |
| Toplam çift (N) | **10.352** |
| CORRECT | 8.570 |
| WRONG | **1.398** |
| UNCERTAIN | 384 |
| **Precision** | **%85,98** (CORRECT / (CORRECT+WRONG)) |
| country_code sızıntısı | **0** (ülke hard-filter sağlam) |

### match_type bazında precision

| match_type | toplam | WRONG | precision |
| :-- | --: | --: | --: |
| **STRIPPED_EXACT** | 8.177 | **1.177** | **0,851** |
| AUTO_DEDUP | 608 | 91 | 0,840 |
| FUZZY_PHRASE | 928 | 84 | 0,907 |
| TOKEN_COVERAGE | 637 | 46 | 0,926 |

**STRIPPED_EXACT tüm hataların %84'ünü üretiyor** ve precision'ı en düşük olan loose stage
(AUTO_DEDUP) ile birlikte odak noktası.

### WRONG kategorileri (reason)

| reason | adet | baskın match_type |
| :-- | --: | :-- |
| `different_core` | 946 | STRIPPED_EXACT (767) |
| `generic_word_only` | 269 | STRIPPED_EXACT (249) |
| `suffix_only` | 82 | STRIPPED_EXACT (80) |
| `different_suffix` / `different_legal_*` | ~21 | STRIPPED_EXACT |
| geo-gösterge sızıntısı (`country_*`) | ~18 | STRIPPED_EXACT |
| serbest-metin uzun kuyruk | ~40 | karışık |

`different_core` + `generic_word_only` = **1.215 (%87)**; bunun **1.016'sı STRIPPED_EXACT**.

---

## 2. Kök Nedenler (belirti → kanıt → mekanizma → ES-tarafı düzeltme yönü)

### RC1 — Jenerik-kelime mıknatısı (generic_word_only, ~269 + different_core'un bir kısmı)

**Belirti:**
```
L M TRADING S.A.   ↔  A Y H TRADING S.R.L.        [STRIPPED_EXACT] 5.04
L M TRADING S.A.   ↔  CV TRADING PERU S.A.C       [STRIPPED_EXACT] 5.08
L M TRADING S.A.   ↔  U & R TRADING S.A.C.        [STRIPPED_EXACT] 5.14
ACE PARTNERS LOGISTICS S.A.C. ↔ M. R. LOGISTICS   [STRIPPED_EXACT] 4.81
```

**Kanıt (kod):** [`es/queries.py:101`](es/queries.py:101) — `_has_distinctive_core`:
```python
result = any(
    len(tok) >= MATCH_CORE_MIN_TOKEN_LEN and (not require_alpha or any(c.isalpha() for c in tok))
    for tok in tokens
)
```
`MATCH_CORE_MIN_TOKEN_LEN = 2` ([config.py:148](config.py)). Gate yalnızca **uzunluk**'a bakar.

**Mekanizma:** stripped analyzer yasal eki (SA/SRL/SAC/EIRL) + tek-harf baş harfleri (`L`, `M`,
`A`, `Y`, `H`) + `&` işaretini eler. "L M TRADING S.A." → `trading`; "A Y H TRADING S.R.L." →
`trading`. Her iki taraf da tek token (`trading`, uzunluk 7 ≥ 2) → gate "ayırt edici" sanar →
`token_count = 1` eşit + aynı `match_phrase` → STRIPPED_EXACT ateşler. Gerçek ayırt edici kısım
(baş harfler) tamamen kaybolmuştur; geriye yalnızca jenerik sektör kelimesi kalır.

**ES-tarafı düzeltme yönü:** Salt-jenerik çekirdek ayırt edici sayılmamalı. Jenerik küme
`synonyms_data/` `business_sectors` JSON'undan türetilir (hardcode YOK, ülke-bilinçli). Gate,
`tok not in generic_business_tokens(country)` koşulunu eklemeli. → **Kullanıcı bunu zaten
uyguladı**: `ENABLE_GENERIC_CORE_GATE` ([config.py](config.py), [es/queries.py](es/queries.py)).
Faz 4 bunu denetlenen veri üzerinde test ediyor (bkz. es-revizyon-testi raporu).

---

### RC2 — Geo-gösterge aşırı-sıyırması (different_core'un büyük kısmı + geo sızıntısı)

**Belirti:**
```
KIMBERLY - CLARK PERU S.R.L.       ↔ KIMBERLY CLARK DE MEXICO     [STRIPPED_EXACT] 16.95
COMPAÑIA GOODYEAR DEL PERU         ↔ GOODYEAR                     [STRIPPED_EXACT] 11.98
WEATHERFORD INTERNATIONAL DE ARG.  ↔ WEATHERFORD INTERNATIONAL    [STRIPPED_EXACT] 14.33
PRODUCTOS TISSUE DEL PERU S.A.     ↔ PRODUCTOS TISSUE DEL ECUADOR [STRIPPED_EXACT]  (PE↔PE)
DHL GLOBAL FORWARDING ARGENTINA SA ↔ DHL GLOBAL FORWARDING (BRAZIL)            (AR↔AR)
FORD MOTOR CO                      ↔ FORD MOTOR CO.BRASIL LTDA.                (AR↔AR)
```

**Mekanizma:** stripped analyzer geo terimlerini (ülke adları PERU/MEXICO/ARGENTINA/BRAZIL/
ECUADOR + bağlaç DE/DEL) ayrım gözetmeden eler. "KIMBERLY CLARK PERU" ve "KIMBERLY CLARK DE
MEXICO" ikisi de → `kimberly clark` → aynı stripped phrase + eşit token_count → STRIPPED_EXACT.
Aynı markanın **farklı ülke iştirakleri** (ayrı tüzel kişiler) tek master'a çöküyor. `country_code`
ikisinde de aynı (PE ya da AR) olduğundan ülke hard-filter'ı bunu yakalamıyor — ayırt edici bilgi
firma **adının içindeki** yabancı ülke kelimesi.

**ES-tarafı düzeltme yönü:** Geo sıyırma **ülke-bilinçli** olmalı — kaydın YALNIZCA kendi ülkesine
ait geo terimleri sıyrılmalı, yabancı ülke adları KORUNMALI. Böylece "KIMBERLY CLARK PERU" (PE)
→ `kimberly clark`, "KIMBERLY CLARK ... MEXICO" (PE) → `kimberly clark mexico` (MEXICO PE'ye ait
değil → korunur) → token_count farkı → STRIPPED_EXACT ateşlemez. → **Kullanıcı bunu zaten uyguladı**:
per-country geo stripping (`core/synonym_loader.py`, `es/manager.py`, `es/ingest.py`) + yeni index
`living_companies_v2`. Faz 4 v2 analyzer'da token_count ayrışmasını ölçüyor. **Not:** v2 reindex
gerektirir (henüz tam değil: 57k/524k doc).

---

### RC3 — Çapraz-yargı yetki yasal-form farkı (suffix_only, ~82)

**Belirti:**
```
ROBERT BOSCH LLC.        ↔ ROBERT BOSCH, GMBH       [STRIPPED_EXACT] 18.30   (US ↔ DE form)
BAYER S.A.               ↔ BAYER S.A. DE C.V.       [STRIPPED_EXACT] 10.82   (AR ↔ MX form)
NOATUM LOGISTICS PERU INC↔ NOATUM LOGISTICS PVT LTD [STRIPPED_EXACT] 14.92   (PE ↔ IN form)
NATURA COSMETICOS, S.A.  ↔ NATURA COSMETICOS LTDA   [STRIPPED_EXACT] 15.64
```

**Mekanizma:** Çekirdek (BAYER, ROBERT BOSCH) aynı; analyzer tüm yasal ekleri (LLC/GMBH/INC/PVT
LTD/LTDA/DE C.V.) eşit biçimde eler → aynı stripped phrase. Ancak farklı **yargı yetkisi yasal
formu** çoğu zaman ayrı tüzel kişiyi gösterir (Bosch US LLC ≠ Bosch GmbH). Haiki bunları WRONG
saydı; tartışmalı bir sınır kategori (bazıları gerçek dup olabilir).

**ES-tarafı düzeltme yönü:** Düşük öncelik. Yasal-form **ailesi** ayrımı (yabancı-yargı GMBH/LLC/
PVT-LTD/DE-C.V. vs yerel SA/SAC/SRL) bir sinyal olarak değerlendirilebilir; ancak risk/kazanç
oranı RC1/RC2'den düşük. Şimdilik gözlem olarak bırakılıyor (aşırı-bölme riski).

---

### RC4 — UNCERTAIN ve serbest-metin reason kuyruğu (384 + ~40)

Haiku ajanları bazı kenar vakalarda kanonik reason etiketleri yerine serbest metin yazdı
(ör. "Different entity type (foundation vs corporation)"). Bunlar küçük hacimli; çoğu RC1/RC2'nin
alt-türü. UNCERTAIN'ler (384) ayrı bir insan-denetim kuyruğuna alınabilir; bu görevin WRONG
kararını etkilemez (precision yalnızca CORRECT/WRONG üzerinden).

---

## 3. Sonuç ve Önceliklendirme

| Kök neden | Etki (WRONG) | Mevcut durum | Reindex? |
| :-- | --: | :-- | :-- |
| RC1 jenerik-mıknatıs | ~269 + different_core payı | Kod yazıldı (`ENABLE_GENERIC_CORE_GATE`) | Hayır (Python gate + JSON) |
| RC2 geo aşırı-sıyırma | different_core'un büyük kısmı + ~18 | Kod yazıldı (per-country geo, v2 index) | **Evet** (v2 reindex) |
| RC3 çapraz-form | ~82 | Açık (düşük öncelik) | — |

**En yüksek etkili 2 kök neden (RC1, RC2) için düzeltmeler kullanıcı tarafından zaten
kodlanmıştır**; round8 bu düzeltmelerin gerekçesini sayısal olarak doğrular. Faz 4 raporu
(`2026-06-16-round8-es-revizyon-testi.md`) bu düzeltmelerin denetlenen WRONG'ları ne kadar
kestiğini ve CORRECT'leri bozup bozmadığını (regresyon) ES `_analyze` ile ölçer.
