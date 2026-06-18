# Round8 — ES-Tarafı Revizyon Testi (Faz 4)

**Tarih:** 2026-06-16
**Amaç:** Kullanıcının halihazırda kodladığı iki düzeltmenin (RC1 jenerik-çekirdek gate,
RC2 per-country geo analyzer) denetlenen round8 verisi üzerinde **kaç over-merge'ü kestiğini**
ve **kaç doğru eşleşmeyi bozduğunu (regresyon)** ES `_analyze` ile ölçmek.

**Kural uyumu:** Hiçbir Python fuzzy/Levenshtein kullanılmadı. Tüm karar ES `_analyze`
tokenizasyonu + JSON `business_sectors`/`country_names` küme üyeliği + `token_count`
karşılaştırması ile verildi — gerçek gate kodunun birebir aynası.

**Test edilen indeksler:** `living_companies_v1` (denetlenen veri — eski analyzer),
`living_companies_v2` (yeni per-country geo analyzer; **kısmî: 57k/524k doc**).
**Kapsam:** STRIPPED_EXACT çiftleri (hataların %84'ü) — WRONG 1.177, CORRECT 6.699.

---

## 1. Sonuç Tablosu (STRIPPED_EXACT)

| Düzeltme | WRONG düzeltilen ↑ | CORRECT bozulan (regresyon) ↓ | Oran |
| :-- | --: | --: | --: |
| **RC1 jenerik-gate** (v1 analyzer) | **308** | 57 | **5,4 : 1** |
| **RC2 geo-divergence** (v2 analyzer, ham) | 181 | 91 | 2,0 : 1 |
| → geo **gerçek** (ülke-adı token'ı) | **174** | 34 | 5,1 : 1 |
| → geo **gürültü** (encoding/kısaltma) | 7 | **57** | — |
| **Birleşik (gürültü hariç)** | **~460 (%39)** | **~85–90 (%1,3)** | **~5 : 1** |

Net: 1.177 STRIPPED_EXACT over-merge'ünün **~%39'u** iki düzeltmeyle kesiliyor; bedeli 6.699
doğru STRIPPED eşleşmenin **~%1,3'ü**. Over-merge'ün under-merge'den daha zararlı sayıldığı
sistem önceliğiyle uyumlu, net pozitif.

---

## 2. RC1 — Jenerik-Çekirdek Gate (ÖNERİLİR, reindex GEREKMEZ)

**Mekanizma:** `_has_distinctive_core` artık `tok not in get_business_sector_tokens(country)`
koşulunu uyguluyor ([es/queries.py](es/queries.py)). v1 analyzer çıktısına (denetlenen
tokenizasyon) uygulandığında:

- **308 WRONG düzeltildi.** Kanıt (`_analyze` + JSON üyelik):
  ```
  L M TRADING S.A.  ↔ A Y H TRADING S.R.L.   → variant stripped = {trading} ⊂ business_sectors → çekirdeksiz → STRIPPED_EXACT ateşlemez
  L M TRADING S.A.  ↔ U & R TRADING S.A.C.    → aynı
  ACE PARTNERS LOGISTICS ↔ M. R. LOGISTICS    → {logistics} ⊂ business_sectors → çekirdeksiz
  ```
- **57 CORRECT bozuldu (kabul edilebilir).** Örnekler:
  ```
  PERU TRADING SA          ↔ PERU TRADING S.A.           ({peru→geo, trading→generic} → çekirdeksiz)
  REPRESENTACIONES A & F   ↔ REPRESENTACIONES A & F S.A.C ({representaciones}→generic, A&F→tek-harf sıyrılır)
  ```
  Bu kayıtların **tek ayırt edici öğesi** jenerik kelime (+baş harf) olduğundan, sistem bunları
  rastlantısal-aynı-adlı farklı firmalardan ayıramaz. Birleşmemek (NEW_MASTER) muhafazakâr ve
  doğru tercihtir. 57/6.699 = **%0,85** — kabul edilebilir under-merge maliyeti.

**Karar:** RC1 **hemen benimsenebilir** — Python gate + JSON, reindex gerektirmez, denetlenen
veride 5,4:1 kazanç. Doğruları "bozması" gerçek analyzer hatası değil, jenerik-only adların
doğası gereği.

---

## 3. RC2 — Per-Country Geo Analyzer (ÖNERİLİR; temiz v2 reindex + doğrulama ŞARTLI)

**Mekanizma:** v2 analyzer kaydın kendi ülkesi dışındaki ülke adlarını KORUR → master/variant
`token_count` ayrışır → STRIPPED_EXACT (eşit count şartı) ateşlemez.

- **174 gerçek-geo WRONG düzeltildi.** Kanıt (`diff ∩ country_names`):
  ```
  KIMBERLY-CLARK PERU ↔ KIMBERLY CLARK DE MEXICO   diff∩geo={mexico}
  IMPORTADORA F & V   ↔ IMPORTADORA MEXICO/JORDAN   diff∩geo={mexico|jordan}
  ACE PARTNERS LOGISTICS ↔ TAIWAN LOGISTICS         diff∩geo={taiwan}
  INVERSIONES V & M   ↔ INVERSIONES AMERICA          diff∩geo={america}
  ```
  Bunlar farklı ülke iştirakleri/firmaları — gerçek over-merge düzeltmesi.
- **34 gerçek-geo CORRECT bozuldu (tartışmalı).** Örnek:
  ```
  TETRA PAK SRL ARGENTINA ↔ TETRA PAK / TETRA PAK LTDA   diff∩geo={argentina}
  ```
  Haiku bunları CORRECT (aynı firma) saydı; geo ayrımı bunları böler → under-merge. "X ARGENTINA"
  ile "X" aynı mı sorusu politik bir karar.

### ⚠️ İki kritik uyarı (v2 reindex öncesi giderilmeli)

1. **v2 kendi-ülkesini sıyırmıyor olabilir.** `TETRA PAK SRL ARGENTINA` (AR) v2 AR analyzer'ında
   "argentina" token'ını KORUYOR (diff'te görünüyor). Tasarım niyeti "yalnızca kendi ülkeyi sıyır"
   idiyse, AR kaydından "argentina" sıyrılmalıydı. v2 (57k/524k doc) muhtemelen **nihai geo
   mantığıyla tam reindex edilmemiş**. Geo kararı vermeden önce v2 tam reindex + `_analyze`
   teyidi gerekir.
2. **Mojibake veri-kalitesi sorunu (geo-DIŞI, ayrı iş).** 57 "geo gürültü" regresyonunun çoğu
   bozuk kodlamalı master adından kaynaklanıyor:
   ```
   COMPAÐIA GOODYEAR DEL PERU   (Ñ → Ð bozulması; token 'compadia')
   COMPA╤IA / COMPA├┐IA ...     (çift-bozulma)
   ```
   Bu, geo düzeltmesinin değil, **kaynak veride/önceki ingest'te karakter kodlaması** probleminin
   belirtisi. Ayrı bir veri-temizliği görevi olarak ele alınmalı.

**Karar:** RC2 yönü doğru ve yüksek-kazançlı (174 gerçek düzeltme), ancak **(a) v2'nin nihai
per-country geo mantığıyla tam reindex edilmesi ve (b) kendi-ülke sıyırma davranışının `_analyze`
ile teyidi** sonrası, `correct.jsonl` üzerinde yeniden regresyon ölçülerek benimsenmeli.
Reindex GEREKTİRİR.

---

## 4. min_score 3.0 → 5.0 (STRIPPED_EXACT)

Config'de STRIPPED_EXACT `min_score` 3.0→5.0 yükseltilmiş. `generic_word_only` örneklerinin skoru
çoğunlukla 4,4–5,1 aralığında; 5.0 eşiği bunların bir kısmını (skor<5,0) ek olarak keser ama
5,04/5,08/5,14 gibi çiftler hâlâ geçer. Tek başına yetersiz; RC1 gate'i asıl çözüm. (min_score
ucuz bir ek emniyet — zarar vermez, küçük ek kazanç.)

---

## 5. Öneri Özeti

| Düzeltme | Kazanç | Risk | Reindex | Öncelik |
| :-- | :-- | :-- | :-- | :-- |
| **RC1 jenerik-gate** | 308 over-merge | 57 ambiguous under-merge (%0,85) | Hayır | **Hemen** |
| **RC2 per-country geo** | 174 over-merge | 34 tartışmalı + 57 mojibake (ayrı) | **Evet** | v2 tam reindex + teyit sonrası |
| min_score 5.0 | küçük ek | yok | Hayır | RC1 ile birlikte |
| Mojibake temizliği | veri kalitesi | — | (ingest) | Ayrı görev |

**Kod bu görevde DEĞİŞTİRİLMEDİ** — yalnızca kullanıcının mevcut kodu denetlenen veride test
edildi. RC1 zaten kodda (`ENABLE_GENERIC_CORE_GATE=True`); RRC2 kodda ama v2 tam reindex bekliyor.
