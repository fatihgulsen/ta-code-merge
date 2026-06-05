# Round-2 Ön-Denetim — phonetic/ngram-off + fingerprint-dedup + garbage-filter

**Tarih:** 2026-06-03
**Branch:** `feat/phonetic-overmerge-guard`
**Commit'ler:** `84f069e` (phonetic/ngram off + fingerprint + dedup), `f70cfb0` (garbage filter), `ddcd716` (input filter daraltma + per-batch dedup)
**Durum:** ⚠️ **ÖN-DENETİM — rematch yalnızca %2,9 tamamlandı (15.4k / 530.9k).** Bu rapor *oran-bazlı before/after KARŞILAŞTIRMASI DEĞİLDİR*; yalnızca "yeni kod doğru davranıyor mu" yapısal teyidi + zamanlamadan bağımsız bulgulardır.

---

## 0. Rematch durumu — QA prematüre

| Metrik | Değer |
| :--- | :--- |
| İşlenmiş (`match_type IS NOT NULL`) | **15.400 / 530.876 (%2,9)** |
| Hız | ~5 kayıt/s (~18.000/saat) |
| **ETA (tamamlanma)** | **~28,6 saat** |
| İşlenen dilim niteliği | id-sıralı ilk %2,9 → **yanlı** (rastgele değil) |
| İşlenen dilim grup dağılımı | 14.514 / 15.257 grup **singleton (%95)**, max grup **9** |
| İşlenen dilim NEW_MASTER oranı | **%96** |

> **Neden karşılaştırılamaz:** Rematch başında index neredeyse boştur → her kayıt yeni master olur (dilimde %96 NEW_MASTER). Over-merge / dedup / recall / max-magnet metrikleri bu evrede yapısal olarak anlamsızdır ve 06-02 (68.6k) / 06-03 (278.2k) temelleriyle kıyaslanamaz. Bölünmüş hedef firmalar (FLEXTRONICS 19 master, SIEMENS 11) hâlâ ayrı görünüyor — ama bu **dedup başarısızlığı değil**: per-batch dedup yalnızca batch-içi birleştirir; bu kayıtların büyük kısmı henüz işlenmedi.

---

## 1. ✅ Düzeltmeler GERÇEKTEN devrede (yeni kod koşuyor)

| Kontrol | Beklenti | Gözlem | Sonuç |
| :--- | :--- | :--- | :--- |
| `match_type` dağılımı | PHONETIC_MATCH ≈ 0 | **0** | ✅ |
| | NGRAM_MATCH ≈ 0 | **0** | ✅ |
| EXCLUDED görünür mü | evet | **11** (işlenen dilim) | ✅ |
| placeholder magnet yakalama | "sin razon social" vb. izole | tüm tablo dry-run: **1.364 placeholder** + 7 na_marker | ✅ |
| dedup boş-fingerprint guard | boş fp birleştirilmez | `plan_merge` `not fp` guard mevcut, `L.MEXICO→[]` birleşmedi | ✅ |

**İşlenen dilimde match_type dağılımı:**
```
NEW_MASTER      14.788
STRIPPED_EXACT     333
FUZZY_PHRASE       138
TOKEN_COVERAGE     120
EXCLUDED            11
SUFFIX_FUZZY        10
PHONETIC_MATCH       0   ✅ (stage kapalı)
NGRAM_MATCH          0   ✅ (stage kapalı)
```

---

## 2. Gerçekleşen merge'lerin kalitesi (en büyük 6 grup)

Çok-üyeli grupları üreten stage'ler (PHONETIC/NGRAM kapalı olduğundan kalan kaynaklar):
`STRIPPED_EXACT 449 · TOKEN_COVERAGE 196 · FUZZY_PHRASE 142 · SUFFIX_FUZZY 12`.

### ✅ DOĞRU merge'ler (rematch'in hedeflediği recall — çalışıyor)
- **size 7 — H&M HENNES & MAURITZ SERVICIOS** (7 yasal-ek/yazım varyantı, hepsi aynı firma)
- **size 6 — VF OUTDOOR MEXICO** (S.R.L. / S. DE R.L. DE C.V. varyantları) *(bir kirli üye, aşağıda)*
- **size 6 — CENTRO ABARROTERO DEL BAJIO** (5 yasal-ek varyantı)
- **size 5 — RIDE CONTROL MEXICANA** (S. DE R.L. varyantları)

STRIPPED_EXACT/FUZZY_PHRASE gerçek yasal-ek varyantlarını doğru topluyor → **recall kazanımı görünür**.

### 🐛 YANLIŞ merge'ler — yeni over-merge sınıfı: **degenerate-fingerprint magnet**
- **size 9 — akronim çorbası** (master `091e588b`):
  `C.M.S.A.D.C · M.R. S.A. DE C.V. · D.D.A.Y.M.S.A.D.C.V · P.M. Y L. S.A. DE C.V. · U M S.A. DE C.V.` (5 NEW_MASTER seed) + `ADM · A.P.M. S.A. · A.D.M S.A. DE C.V. · APM S.A. DE C.V.`
- **size 5 — akronim çorbası** (master `3b6f8f0e`): `G A M S · M-S.G-S.V · G.A.M.S.A.D.C.V · I. G. M. I. S.A. D. C · G.M. S.A. DE C.V.`

---

## 3. 🔬 Kök neden — `fingerprint_analyzer` akronimleri tek harfe çökertiyor

ES `_analyze` API (ES-side, salt-okuma) çıktısı:

```
C.M.S.A.D.C          -> ['m']
M.R. S.A. DE C.V.    -> ['m']
U M S.A. DE C.V.     -> ['m']
D.D.A.Y.M.S.A.D.C.V  -> ['m']
A.P.M. S.A.          -> ['m']     ← 5 FARKLI firma → AYNI fingerprint 'm'
G A M S              -> ['g m']
G.A.M.S.A.D.C.V      -> ['g m']   ← 2 farklı firma → 'g m'
L.MEXICO             -> []        ← BOŞ fingerprint (dedup guard'ı yakaladı, güvenli)
--- karşılaştırma (sağlıklı) ---
H&M HENNES & MAURITZ -> ['hennes m mauritz servicios']   ✅ ayırt edici
VF OUTDOOR MEXICO    -> ['outdoor vf']                    ✅ ayırt edici
```

**Mekanizma:** Analyzer yasal-ek harflerini (s,a,d,e,c,v) stop'luyor; noktalı-baş-harf isimlerde geriye tek bir junk harf (`m`) kalıyor. `dedup_auto_merge.plan_merge` yalnızca **boş** fingerprint'i reddediyor (satır 48-51, `if not fp`); `'m'` truthy olduğu için geçiyor → 5 alakasız akronim firma birleşiyor.

> Bu, eski "Sin Razon Social"/phonetic magnet'iyle **aynı başarısızlık modu** (over-stripping sonrası dejenere çekirdek), farklı girdi sınıfında (akronim/baş-harf). PHONETIC/NGRAM kapatıldı ama suffix-stripping kaynaklı çökme akronimlerde yeniden üretiyor.

---

## 4. 🐛 input_filter — Latin-dışı gerçek firmalar yanlış EXCLUDED

`input_filter._norm()` (input_filter.py:22,31) `[^a-z0-9]` dışı her karakteri boşluğa indiriyor → **Kiril/Yunan/CJK/Arap** alfabesindeki gerçek firma adları boşa normalize olup `no_alnum` → **EXCLUDED**.

Tüm tablo dry-run (530.876): `placeholder 1.364` (meşru) · `na_marker 7` (meşru) · **`no_alnum 139` (çoğu yanlış-dışlama)**. Örnekler:
- `ФОЛЬКСВАГЕН АГ` = **Volkswagen AG**
- `СИБУР ИНТЕРНЭШНЛ ГМБХ` = **SIBUR International GmbH**
- `ООО УРАЛКАЛИЙ ТРЕЙДИНГ` = **Uralkali Trading**

İçerik taşıyan gerçek firmalar; filtre felsefesini ("yalnızca içerik-taşımayan girdiler elenir") ihlal → veri/recall kaybı. Mutlak küçük (%0,026) ama zamanlamadan bağımsız net bir bug. *(Düzeltme zaten EXCLUDED olmuş 11 kaydı geriye düzeltmez — rematch sonrası bunlar için hedefli yeniden-işleme gerekir.)*

---

## 5. Öneriler (ES-side; Python doğrulaması YOK)

**P-R2-1 (yüksek) — dejenere fingerprint dedup guard'ı. [UYGULANDI + CONFIG-DRIVEN 2026-06-03]** `plan_merge`'e `_is_distinctive_fingerprint(fp, min_token_len)` eklendi: en az bir token ≥ `config.DEDUP_MIN_FINGERPRINT_TOKEN_LEN` karakter şartı. **Eşik config'e taşındı; KARAR: şimdilik `1`'de park (guard pratikte kapalı — yalnız boş fp engellenir; magnet'i kapatmak için 2 yap).** Gerekçe: ≥2 bile yetersiz (aşağıda) ve asıl çözüm analyzer-side reindex → şu an knob'u en az-müdahaleli değerde tut, rematch sonrası 530k'da ölçüp karar ver. 188 test geçti.

   **EŞİK TESTİ (2026-06-03, kullanıcı talebi — ampirik):** Magnet-yayılım yalnızca `max_token_len=1`'de yoğun (`'m'`=3 master, alakasız firmalar). 2-char'ta tek fingerprint (`'av'`, 2 master), ≥3'te yayılım hep ≤2-4 (normal duplicate). Gerçek 2-char markalar (VF→`vf`, 3M→`3m`, HM→`hm`, GM→`gm`) korunuyor → **≥2 doğru ZEMİN; ≥3 bu markaları yanlış bloklardı.**
   - **ANCAK ≥2 yeterli DEĞİL:** `'av'` (HUF MEXICO + P.AV.I) ve `'adm'` (akronim-magnet + ADM Germany GmbH) hâlâ geçip yanlış birleşiyor. KÖK NEDEN eşik değil, **analyzer aşırı-strip**: tek-karakter token atılıyor (`P. AV.I`→`av`), `HUF` yutuluyor (`HUF MEXICO ... AV`→`av`) → çakışan kısa residue. Gerçek kısa marka ile residue **uzunlukla ayrılamaz** → Python eşiğiyle çözülemez.
   - **Gerçek çözüm (analyzer-level, reindex gerektirir, rematch sonrası):** `fingerprint_analyzer`'da strip sonucu degenerate (≤1 anlamlı token / orijinalin <N'i) kalıyorsa orijinal token'ı koru; tek-karakter-token atmayı, sonuç boşalmayacaksa yap. Tam rematch sonrası 530k ölçeğinde kısa-fp dağılımını yeniden ölç, sonra reindex + live_probe golden ile doğrula. Şu an rematch koştuğundan reindex YAPILAMAZ → ≥2 guard'ı geçici-yeterli (runaway magnet'i kapatır), residual kısa-fp false-merge'leri düşük-hacimli bilinen sorun olarak işaretle.

**P-R2-2 (orta) — input_filter Unicode-aware.** `_norm`'daki `[^a-z0-9]` yerine Unicode harf/rakam sınıfı (`\w` + `re.UNICODE`, ya da `str.isalnum()` Unicode tabanlı kontrolü) kullan; Latin-dışı içerik `no_alnum` sayılmasın. Bu bir kimlik/normalize kararı değil, yalnızca "içerik var mı" sınır kontrolü.

**P-R2-3 (tamamlanma sonrası doğrula) — cross-batch dedup boşluğu.** Per-batch dedup yalnızca batch-içi; id-sıralı işlemede aynı firma farklı batch'lere düşerse birleşmez. Rematch %100 olunca: ya bir **final global dedup pass** (`auto_merge_duplicates` restrict'siz) çalıştır, ya da residual NEW_MASTER under-merge'ini qa3 ile ölç.

---

## P1-B kararı

PHONETIC/NGRAM kapalı olduğundan parent↔subsidiary / şehir over-merge'inin asıl kaynağı zaten ortadan kalktı; ancak %2,9 dilimde kontrol havuzu temsil etmiyor → **P1-B kararı rematch tamamlanana ERTELENDİ**. Tamamlanınca kontrol havuzunda gerçek kalan vakalar ölçülecek.

---

## En yüksek etki — özet

1. ✅ **Yeni kod doğrulandı**: PHONETIC=0, NGRAM=0, EXCLUDED aktif, placeholder magnetler (1.364) izole ediliyor, boş-fp dedup guard'ı çalışıyor.
2. ✅ **Recall mekaniği çalışıyor**: STRIPPED_EXACT/FUZZY_PHRASE gerçek yasal-ek varyantlarını doğru topluyor (H&M, VF OUTDOOR, CENTRO ABARROTERO, RIDE CONTROL).
3. 🐛 **Yeni over-merge magnet'i (P-R2-1)**: akronim/baş-harf isimler `fingerprint_analyzer`'da tek harfe (`'m'`) çöküyor → dedup 5 alakasız firmayı birleştiriyor. ES-side guard önerildi.
4. 🐛 **input_filter Latin-dışı bug (P-R2-2)**: 139 gerçek Kiril firma (Volkswagen AG vb.) yanlış EXCLUDED. Unicode-aware düzeltme önerildi.
5. ⏳ **Tam QA için rematch bitmeli (~28h)**: oran-bazlı before/after, NEW_MASTER recall, dedup doğrulama ve P1-B kararı yalnızca %100 tamamlanmış veri üzerinde anlamlı.

**Onay:** Tam before/after denetim rematch %100 olduğunda koşulmalı. Bu arada P-R2-1 / P-R2-2 düzeltmeleri (rematch'i durdurmadan, paralel) yapılsın mı?
