# Round-4 — Yanlış Eşleşmelerin Tam Listesi + Yorum + Çözüm Önerileri

**Tarih:** 2026-06-10 · **Kaynak:** qa4 rastgele-400 precision örneklemi (kısmi rematch %22,5)
**Toplam yanlış:** 40 / 400 (precision %90,0) · FUZZY_PHRASE 23 · TOKEN_COVERAGE 14 · STRIPPED_EXACT 3
**Veri:** `C:/tmp/qa4_wrong_full.json` (ham, tam isimler) · Script: `C:/tmp/qa4_show_wrong.py` / `qa4_dump_wrong.py`

> Notasyon: her grupta `[match_type sc=skor]` ham isim. `<== KÖTÜ` = LLM'in gruba ait olmadığını söylediği üye. `sc=100` = NEW_MASTER (master tohumu).

---

## Hata desenlerinin özeti (önce genel resim)

| # | Desen | Adet (yaklaşık) | Hangi stage | Kök-neden |
|---|---|---|---|---|
| D1 | **Truncation-shell** (isim cümle ortasında kesik: `…DE`, `…DEL`, `…Y`, `…S`) | ~9 | FUZZY + STRIPPED | Kesik isim, tam ismin prefix'i → fuzzy/stripped örtüşüyor |
| D2 | **Subset / kısa marka** (kısa isim uzun ismin alt-kümesi, ayırt edici kelime eksik) | ~10 | FUZZY | Kısa isim düşük skorla uzun master'a giriyor; gate ≥2-char geçiyor |
| D3 | **Jenerik-kelime farklı-marka** (paylaşılan jenerik tanım, farklı ayırt edici) | ~7 | FUZZY + TOKEN | Jenerik kelime örtüşüyor, marka farklı |
| D4 | **Kişi adları** (slash-format `SOYAD/SOYAD/AD` ↔ `AD SOYAD SOYAD`) | ~8 | TOKEN_COVERAGE | Firma değil; token-örtüşmesi yüksek skor veriyor |
| D5 | **Bozuk/çift-token veri** (`ROBERT BOSCH BOSCH`, `SAME AS`) | ~2 | TOKEN + FUZZY | Veri kalitesi |

---

## STRIPPED_EXACT — 3 yanlış

### 1. ENVASES UNIVERSALES (master `95891357`) — Desen D1+D3
```
[NEW_MASTER     sc=100] Envases Universales De Mexico, S.A.
[NEW_MASTER     sc=100] ENVASES UNIVERSALES DE MEXICO S.A.P.I. D
[NEW_MASTER     sc=100] Envases Universales S.A.P.I. DE C.V.
[STRIPPED_EXACT sc= 18] ENVASES UNIVERSALES MEXICO SA
[FUZZY_PHRASE   sc= 18] ENVASES UNIVERSALES DE MEXICO S.A.
[FUZZY_PHRASE   sc= 18] ENVASES UNIVERSALES DE MEXICO, S.A.
[STRIPPED_EXACT sc= 17] ENVASES UNIVERSALES SAPI DE CV
[STRIPPED_EXACT sc= 17] ENVASES UNIVERSALES DE              <== KÖTÜ
[STRIPPED_EXACT sc= 17] ENVASES UNIVERSALES S.A. DE C.V.
[STRIPPED_EXACT sc= 17] ENVASES UNIVERSALES S.A.P.I. DE C.V.
[STRIPPED_EXACT sc= 16] ENVASES UNIVERSALES
```
**Yorum:** "ENVASES UNIVERSALES" = jenerik tanım ("evrensel ambalaj"). Hem kesik `ENVASES UNIVERSALES DE` hem de çıplak `ENVASES UNIVERSALES` aynı stripped-key'e çöküyor; bu jenerik çekirdek farklı firmaları toplama riskli. (Bu özel grupta çoğu muhtemelen aynı firma ama jenerik-çekirdek + truncation kombinasyonu kırılgan.)
**Çözüm:** Stripped-key sadece jenerik/legal/geo token'lardan oluşuyorsa **auto-merge etme → dedup_reviewer'a düşür**. (Jenerik-çekirdek tespiti: STRIPPED token'ların tamamı generic_stopwords listesinde mi?)

### 2. MANTENIMIENTO INDUSTRIAL AVANZADO (master `ac8cbb19`) — Desen D1
```
[NEW_MASTER     sc=100] MANTENIMIENTO INDUSTRIAL AVANZADO, S.A. DE C.V.
[STRIPPED_EXACT sc= 20] MANTENIMIENTO INDUSTRIAL AVANZADO S    <== KÖTÜ
```
**Yorum:** Sondaki çıplak `S` (muhtemelen `S.A.` kesilmiş) stripleniyor → tam isimle aynı key. Aslında **muhtemelen aynı firma** (LLM "truncated garbage" dedi ama AVANZADO çekirdeği örtüşüyor); bu sınırda bir vaka.
**Çözüm:** Düşük öncelik — sondaki tek-harf `S` artığı zaten aynı firmaya işaret ediyor; gerçek over-merge değil, isim-temizliği sorunu.

### 3. SPORT CYCLE / SPORT CYCLE CENTER (master `c88df942`) — Desen D2
```
[NEW_MASTER     sc=100] SPORT CYCLE CENTER, S.A. DE C.V.
[STRIPPED_EXACT sc= 23] SPORT CYCLE CENTER S.A. DE C.V.       <== KÖTÜ
[FUZZY_PHRASE   sc= 12] SPORT CYCLE, S.A. DE C.V.
```
**Yorum:** `SPORT CYCLE` ile `SPORT CYCLE CENTER` farklı firma olabilir (CENTER ayırt edici). Master "CENTER" içeriyor ama "SPORT CYCLE" (CENTER'sız) de gruba alınmış.
**Çözüm:** Core-coverage gate — `CENTER` master'da ayırt edici fazladan token; kısa isim onu kapsamıyor → ayır/incele.

---

## FUZZY_PHRASE — 23 yanlış

### Desen D2 — Kısa marka / subset (ayırt edici kelime EKSİK)

**SPM (master `9f45ef42`)**
```
[NEW_MASTER   sc=100] SPM FLOW CONTROL DE MEXICO S. DE R.L. DE C.V.
[FUZZY_PHRASE sc= 23] SPM FLOW CONTROL DE MEXICO, S. DE R.L. DE C.V.
[FUZZY_PHRASE sc=  6] SPM                                    <== KÖTÜ
```
**Yorum:** Çıplak `SPM` (skor 6) → `SPM FLOW CONTROL` master'ına girmiş. SPM tek başına firma kimliği değil.

**AMCOR (master `782dc05d`)**
```
[NEW_MASTER     sc=100] AMCOR TOBACCO PACKAGING MEXICO S
[STRIPPED_EXACT sc= 23] AMCOR TOBACCO PACKAGING MEXICO S DE
[STRIPPED_EXACT sc= 23] AMCOR TOBACCO PACKAGING MEXICO
[FUZZY_PHRASE   sc=  9] AMCOR                                <== KÖTÜ
```
**VALEO (master `b2a8827c`)**
```
[NEW_MASTER   sc=100] VALEO NORTH AMERICA INC. DBA VALEO SYSTEMS
[FUZZY_PHRASE sc=  9] VALEO                                  <== KÖTÜ
```
**SWISSMEX (master `d2e791e0`)**
```
[NEW_MASTER     sc=100] SWISSMEX-RAPID, S.A. DE C.V.
[STRIPPED_EXACT sc= 22] SWISSMEX-RAPID S.A. DE
[FUZZY_PHRASE   sc= 11] SWISSMEX                             <== KÖTÜ
```
**SURVEY (master `fd68a2e2`)**
```
[NEW_MASTER   sc=100] FUJISAN SURVEY S.A. DE C.V.
[FUZZY_PHRASE sc= 13] SURVEY, S.A. DE C.V.                   <== KÖTÜ
```
**IND SUPPLY (master `da362639`)**
```
[NEW_MASTER   sc=100] ATLAS INDUSTRIAL SUPPLY, S.A. DE C.V.
[FUZZY_PHRASE sc= 17] IND SUPPLY S.A. DE C.V.                <== KÖTÜ
```
**WORLDWIDE LOGISTICS (master `469ccfcd`)**
```
[NEW_MASTER   sc=100] MENLO WORLDWIDE LOGISTICS
[FUZZY_PHRASE sc= 11] WORLDWIDE LOGISTICS                    <== KÖTÜ
```
**MEDICAL & SUPPLIES (master `adda10e2`)**
```
[NEW_MASTER   sc=100] MEDICAL ADVANCED SUPPLIES, S.A. DE C.V.
[FUZZY_PHRASE sc=  9] MEDICAL & SUPPLIES S.A.                <== KÖTÜ
```
**NUTRITION BIOSCIENCES (master `2cdb3428`)**
```
[NEW_MASTER   sc=100] NUTRITION & BIOSCIENCES MEXICO S. DE R.L. DE C.V.
[FUZZY_PHRASE sc=  9] NUTRITION BIOSCIENCES                  <== KÖTÜ
```
**F8 INSUMOS (master `6f1d6f85`)**
```
[NEW_MASTER   sc=100] F8 INSUMOS PUBLICITARIOS, S.A. DE C.V.
[FUZZY_PHRASE sc= 12] F8 INSUMOS, S.A. DE C.V.               <== KÖTÜ
```
**COMERICALIZADORA (master `9cd40777`)**
```
[NEW_MASTER   sc=100] ROVILA COMERICALIZADORA, S.A. DE C.V.
[FUZZY_PHRASE sc= 13] COMERICALIZADORA S.A. DE C.V.          <== KÖTÜ
```
**TRACTORES Y MAQUINARIA (master `63deb38e`)**
```
[NEW_MASTER   sc=100] TRACTORES Y MAQUINARIA REAL S.A. DE
[FUZZY_PHRASE sc= 23] TRACTORES Y MAQUINARIA REAL S.A.
[FUZZY_PHRASE sc= 16] TRACTORES Y MAQUINARIA                 <== KÖTÜ
```
**DISTRIBUIDORA DE EXPLOSIVOS (master `ba8d8473`)**
```
[NEW_MASTER   sc=100] DISTRIBUIDORA DE EXPLOSIVOS OVIEDO
[FUZZY_PHRASE sc= 16] DISTRIBUIDORA DE EXPLOSIVOS            <== KÖTÜ
```
**Ortak yorum (D2):** Hepsinde aday isim, master isminin **gerçek alt-kümesi** ve ayırt edici markayı (FLOW CONTROL, OVIEDO, MENLO, ATLAS, FUJISAN, -RAPID, PUBLICITARIOS, ROVILA, REAL, ADVANCED) **içermiyor**. Skorlar 6–17 arası (düşük). Gate geçiyor çünkü ≥2-char alfabetik token var.
**Çözüm (D2 için en etkili):**
1. **Core-coverage gate (ASIL ÇÖZÜM):** Master'ın STRIPPED ayırt-edici token kümesi, adayın token kümesini **kapsamıyorsa ve aday master'ın ayırt edici bir token'ını eksik bırakıyorsa → MATCH_NONE**. Yani "uzun isimde fazladan ayırt-edici kelime var, kısa isim onu kapsamıyor" → birleştirme. (geo/legal/jenerik fazlalıklar sayılmaz; HALLIBURTON ⊂ HALLIBURTON DE MEXICO korunur çünkü DE/MEXICO geo.)
2. **Yardımcı:** FUZZY_PHRASE `min_score 5→9` skor 6–8 olanları keser (SPM@6 gibi) — küçük katkı.

### Desen D1 — Truncation-shell (cümle ortasında kesik)
**INTER MEX MATERIALES DE (`042fc8ad`)**
```
[NEW_MASTER   sc=100] INTER MEX MATERIALES DE CONSTRUCCION, S.A. DE C.V.
[FUZZY_PHRASE sc= 17] INTER MEX MATERIALES DE CONSTRUCCION S.A. DE C.V.
[FUZZY_PHRASE sc= 10] INTER MEX MATERIALES DE                <== KÖTÜ
```
**GALERIA PRODUCTORA DE (`18ecf308`)**
```
[NEW_MASTER   sc=100] GALERIA PRODUCTORA DE COSMETICOS
[FUZZY_PHRASE sc= 16] GALERIA PRODUCTORA DE                  <== KÖTÜ
```
**TUBERIAS Y VALVULAS DEL (`35050fd7`)**
```
[NEW_MASTER   sc=100] TUBERIAS Y VALVULAS DEL NOROES
[FUZZY_PHRASE sc= 23] TUBERIAS Y VALVULAS DEL                <== KÖTÜ
```
**CRISTALES ESPEJOS Y (`46ef5e85`)**
```
[NEW_MASTER   sc=100] CRISTALES ESPEJOS Y VIDRIO
[FUZZY_PHRASE sc= 24] CRISTALES ESPEJOS Y                    <== KÖTÜ
```
**Ortak yorum (D1):** İsim bir **edatla/bağlaçla** (`DE`, `DEL`, `Y`) bitiyor — açıkça kesik. Tamamlayıcı kelime (CONSTRUCCION, COSMETICOS, NOROES, VIDRIO) eksik. Bunlar **muhtemelen aynı firma** olabilir AMA isim eksik olduğu için kesin değil; LLM "incomplete/garbage" diyor.
**Çözüm (D1):**
1. **Trailing-konektör tespiti:** İsim `DE/DEL/Y/LA/EL/S` ile bitiyorsa → "kesik isim" işareti; bu durumda **core-coverage gate'i sıkı uygula** (eksik tamamlayıcı kelime varsa birleştirme veya review'a düşür).
2. Alternatif: kesik-isim adayı master'ı oluşturan tam-isimle aynı master'a **review onayıyla** gir.

### Desen D3 — Jenerik-kelime farklı-marka
**HI TECH vs TECHNOLOGY ALIMENTICIA (`c48a8eb7`)**
```
[NEW_MASTER   sc=100] HI TECH TECNOLOGIA ALIMENTICIA S.A. DE C.V.   <== KÖTÜ (LLM: farklı marka)
[FUZZY_PHRASE sc= 15] TECNOLOGIA ALIMENTICIA, S.A. DE C.V.
[FUZZY_PHRASE sc= 15] TECNOLOGIA ALIMENTICIA S.A. DE C.V.
[FUZZY_PHRASE sc= 14] TECNOLOGIA ALIMENTICIA S.A.
[FUZZY_PHRASE sc=  9] TECHNOLOGY ALIMENTICIA S.A. DE C.V.            <== KÖTÜ
```
**Yorum:** `TECNOLOGIA ALIMENTICIA` (jenerik: "gıda teknolojisi") ortak; `HI TECH` prefix'i ayırt edici ama jenerik çekirdek hepsini topluyor. `TECHNOLOGY` (İngilizce) vs `TECNOLOGIA` ayrı.
**Çözüm:** Core-coverage + jenerik-çekirdek-review: çekirdek tamamen jenerik kelimelerse auto-merge etme.

### Desen D5 — Bozuk veri / garbage
**SAME AS / SAME AS CNEE (`a3ad8561`)** — gümrük/placeholder işareti, firma değil
```
[NEW_MASTER   sc=100] SAME AS CNEE                           <== KÖTÜ
[FUZZY_PHRASE sc= 20] SAME AS                                <== KÖTÜ
```
**MAGNETI MARELLI ... ELEC (`19a5d7dd`)** — ikisi de kesik
```
[NEW_MASTER   sc=100] MAGNETI MARELLI SISTEMAS ELEC DE M     <== KÖTÜ
[FUZZY_PHRASE sc= 30] MAGNETI MARELLI SISTEMAS ELEC          <== KÖTÜ
```
**ANA DIS / EUROGOURMET (`2de49799`)**
```
[NEW_MASTER    sc=100] ANA-DIS S A DE C V EUROGOURMET        <== KÖTÜ
[TOKEN_COVERAGE sc= 15] EUROGOURMET ANA
[FUZZY_PHRASE   sc= 12] ANA DIS                              <== KÖTÜ
```
**TO CASA HOMS (`b0ab8ea4`)** — adres karışmış kayıtlar
```
[NEW_MASTER   sc=100] TO CASA HOMS S.C. AV, 5 DE MAYO
[FUZZY_PHRASE sc= 45] TO CASA HOMS SC AV 5 DE MAYO
[FUZZY_PHRASE sc= 39] CASA HOMS, S.C AV. 5 DE MAYO
[FUZZY_PHRASE sc= 26] CASA HOMS, S.C. AV
[FUZZY_PHRASE sc= 26] CASA HOMS S.C. AV
[FUZZY_PHRASE sc= 26] CASA HOMS SC. AV
[FUZZY_PHRASE sc= 18] TO CASA HOMS                           <== KÖTÜ
```
**Yorum:** `SAME AS`/`SAME AS CNEE` = gümrük placeholder'ı (B-sınıfı garbage; gerçekte EXCLUDED olmalıydı ama tam-string olmadığı için kaçtı). `TO CASA HOMS` içinde isim+adres karışmış (`AV 5 DE MAYO` = sokak).
**Çözüm:** Placeholder listesine `SAME AS`, `SAME AS CNEE` ekle (config NON_FIRM_PLACEHOLDERS). Adres-içeren isimler için ayrı temizlik (ingest pipeline).

---

## TOKEN_COVERAGE — 14 yanlış

### Desen D4 — Kişi adları (slash-format vs normal sıra) — EN NET DESEN
```
[GARBAGE a867aef7]  COSS/LUNA/JOSE CARLOS              ↔ JOSE CARLOS COSS LUNA (sc 31)
[GARBAGE a3e582b4]  GRACIA/MARQUEZ/FRANCISCO LUIS      ↔ FRANCISCO LUIS GRACIA MARQUEZ (sc 28)
[GARBAGE ec28c945]  LEONARDO MENDEZ VAZQUEZ            ↔ MENDEZ/VAZQUEZ/LEONARDO (sc 26)
[GARBAGE bbfd78f0]  SANCHEZ/RUVALCABA/ABEL FRANCISCO   ↔ ABEL FRANCISCO SANCHEZ RUVALCABA (sc 34) ↔ ABEL SANCHEZ (sc 15)
[GARBAGE 88826f75]  BARRERA/HERNANDEZ/BARBARA          ↔ BARBARA BARRERA HERNANDEZ (sc 28)
[GARBAGE d6fbeeff]  GONZALEZ/MEDINA/JORGE ARTURO       ↔ JORGE ARTURO GONZALEZ MEDINA (sc 28)
[GARBAGE ebf32036]  NOE TORRES DOMINGUEZ               ↔ TORRES/DOMINGUEZ/NOE (sc 27)
```
**Yorum:** Bunlar **firma değil, şahıs adları**. Veride iki format var: `SOYAD/SOYAD/AD` (slash'lı) ve `AD SOYAD SOYAD` (normal). Aynı kişinin iki formatı token-örtüşmesiyle yüksek skor (26–34) alıp birleşiyor. **min_score bunları KESEMEZ** (skor yüksek).
**Çözüm (D4 — yüksek etki, kolay):**
1. **Slash-format kişi-adı tespiti (veri-konvansiyonu):** `A/B/C` formatındaki (2+ slash, legal-suffix yok, firma-anahtar kelimesi yok) isimler bu veride şahıs kaydı → bunları **eşleştirmeye sokma** (kendi master'ı olur, başkası katılamaz / TOKEN_COVERAGE adayı olamaz). Hardcode ülke-token'ı değil, **format kuralı**.
2. **İsteğe bağlı:** Meksika yaygın-ad sözlüğü (veri-driven dosya) ile "tüm token'lar kişi-adı" → non-firm. Ama slash-format kuralı tek başına bu 7 vakanın çoğunu kapatır.

### Desen D3 — Jenerik/teknik kelime farklı-marka
**ENERGIA ELECTRICA vs ENERGIA CHIHUAHUA (`cd4ff0f7`)**
```
[NEW_MASTER    sc=100] ENERGIA ELECTRICA DE CHIHUAHUA, S.A. DE C.V.
[TOKEN_COVERAGE sc= 14] ENERGIA ELECTRICA, S.A. DE C.V.
[TOKEN_COVERAGE sc= 14] ENERGIA CHIHUAHUA S.A. DE C.V.        <== KÖTÜ
[TOKEN_COVERAGE sc= 14] ENERGIA ELECTRICA S.A. DE C.V.
```
**INGENIERIA HIDRAULICA reorder (`7dbd83b5`)**
```
[NEW_MASTER    sc=100] INGENIERIA HIDRAULICA Y SISTEMAS CONTRA INCENDIO S.A. DE C.V.
[TOKEN_COVERAGE sc= 17] SISTEMAS DE INGENIERIA HIDRAULICA, S.A. DE C.V.   <== KÖTÜ (farklı firma)
[FUZZY_PHRASE   sc= 16] INGENIERIA Y SISTEMAS CONTRA INCENDIO, S.A. DE C.V.
```
**EL NORTE vs EL BUEN TELAR DEL NORTE (`ff6d6a76`)**
```
[NEW_MASTER    sc=100] EL BUEN TELAR DEL NORTE S.A. DE C.V.
[TOKEN_COVERAGE sc= 10] EL NORTE, S.A.                        <== KÖTÜ
```
**RCI MEXICO vs RCI ENERGIES (`4ed7b8eb`)**
```
[NEW_MASTER    sc=100] RCI ENERGIES DE MEXICO, S.A. DE C.V.
[TOKEN_COVERAGE sc= 11] RCI MEXICO                            <== KÖTÜ
```
**MATTEL INC (ABD parent) vs MATTEL DE MEXICO (`44f0d8f9`)**
```
[NEW_MASTER    sc=100] MATTEL DE MEXICO S.A. DE C.V., MIGUEL DE CERVANTES
[FUZZY_PHRASE   sc= 11] MATTEL DE MEXICO, S.A. DE C.V.
[TOKEN_COVERAGE sc=  9] MATTEL, INC.                          <== KÖTÜ (global parent ≠ MX iştirak)
```
**CL P&CO vs ATOZ LOGISTICS (`beea57bf`)**
```
[NEW_MASTER    sc=100] ATOZ LOGISTICS S.A. DE S.V CALLE RIO DANUBIO 80 PISO 1 COL
[TOKEN_COVERAGE sc= 10] CL P&CO                               <== KÖTÜ (tamamen farklı)
```
**Yorum:** Token örtüşmesi sıra-bağımsız olduğu için `SISTEMAS DE INGENIERIA HIDRAULICA` ≈ `INGENIERIA HIDRAULICA Y SISTEMAS...` (aynı kelimeler, farklı firma). `EL NORTE` ⊂ `EL BUEN TELAR DEL NORTE` (NORTE ortak ama TELAR markası yok). `MATTEL INC` = global parent, `RCI MEXICO` ≠ `RCI ENERGIES`.
**Çözüm:** Core-coverage gate (D2/D3 ile aynı): ayırt edici kelime eksik/farklıysa birleştirme. MATTEL gibi parent/subsidiary vakaları **review** kararı (otomatik çözülemez).

### Desen D5 — Çift-token / bozuk
**ROBERT BOSCH BOSCH (`2378c8af`)**
```
[NEW_MASTER    sc=100] ROBERT BOSCH MEXICO SISTEMAS AUTOMOTRICES, S.A. DE C.V.
[TOKEN_COVERAGE sc= 25] ROBERT BOSCH BOSCH MEXICO SISTEMAS              <== KÖTÜ (BOSCH çift)
[STRIPPED_EXACT sc= 24] ROBERT BOSCH MEXICO SISTEMAS AUTOMOTRICES S.A. DE
... (10 üye, çoğu gerçek BOSCH varyantı)
[TOKEN_COVERAGE sc= 14] SISTEMAS AUTOMOTRICES DE MEXICO S A DE C V      <== KÖTÜ (ROBERT BOSCH yok)
```
**Yorum:** Çoğu üye gerçek ROBERT BOSCH; iki üye sorunlu — biri `BOSCH` çift yazılmış (veri hatası), biri `ROBERT BOSCH` prefix'i olmayan jenerik `SISTEMAS AUTOMOTRICES DE MEXICO`. Master geneli doğru, kenar üyeler kirli.
**Çözüm:** Düşük öncelik; core-coverage `SISTEMAS AUTOMOTRICES DE MEXICO`yu (BOSCH markası yok) ayırır.

---

## ÖNERİLEN ÇÖZÜM TASARIMI (öncelik sırasıyla)

### Çözüm A — Ayırt-edici-çekirdek COVERAGE gate (EN YÜKSEK ETKİ) ★
**Hedef:** D1 (truncation-shell) + D2 (subset) + D3 (jenerik farklı-marka) = **~26/40 yanlış (%65)**.
**Mantık (ES-side, STRIPPED analyzer, Python fuzzy YOK):**
- Aday ve master'ın STRIPPED token kümelerini al (zaten ES'de var).
- "Ayırt edici token" = generic_stopwords + legal_fragment + geo_stopwords listelerinde OLMAYAN token (hepsi JSON/config-driven, hardcode yok).
- **Kural:** İki taraftan birinin diğerinde OLMAYAN bir **ayırt edici** token'ı varsa → `MATCH_NONE` (NEW_MASTER). Yani `MENLO`/`OVIEDO`/`ATLAS`/`-RAPID`/`PUBLICITARIOS`/`CONSTRUCCION`/`VIDRIO` master'da var, adayda yok → birleşme.
- HALLIBURTON ⊂ HALLIBURTON DE MEXICO **korunur** (fazlalık DE/MEXICO geo → ayırt edici değil).
- **DİKKAT:** Bu, Round-3'te geri alınan `clean_analyzer token_count` DEĞİL (synonym genişlemesi recall'ı kırmıştı). Token-SET kapsama + STRIPPED analyzer (synonym yok) kullanılmalı.
- **Risk:** Gerçekten kesik-ama-aynı firma (D1) bazıları NEW_MASTER olur (recall maliyeti). Hafifletme: tek-yönlü kapsama (aday ⊂ master ve eksik token sayısı=1 ve master'ın geri kalanı örtüşüyorsa) review'a düşür, sert ayırma yerine.

### Çözüm B — Kişi-adı / slash-format filtresi (KOLAY, YÜKSEK ETKİ) ★
**Hedef:** D4 = **~7-8/40 yanlış (%18-20)**, hepsi TOKEN_COVERAGE.
**Mantık:** `input_filter.py`'ye kural: 2+ `/` içeren, legal-suffix ve firma-anahtar kelimesi (S.A., GRUPO, COMERCIAL… JSON-driven) olmayan isim = **şahıs kaydı** → kendi master'ı, eşleştirmeye girmez (ne aday ne hedef). Format kuralı, ülke-token değil.
**Bonus:** TOKEN_COVERAGE'ın en kötü precision'ını (%53→muhtemelen %75+) düzeltir.

### Çözüm C — Placeholder genişletme (KÜÇÜK)
`SAME AS`, `SAME AS CNEE`, salt-adres isimleri → config NON_FIRM_PLACEHOLDERS / ingest temizliği.

### Çözüm D — min_score (DÜŞÜK ETKİ, tamamlayıcı)
FUZZY_PHRASE 5→9: sadece SPM@6, MEDICAL&SUPPLIES@9 gibi en düşükleri keser (~3-4 vaka). TOKEN_COVERAGE 3→11: birkaç vaka. **Tek başına yetersiz** çünkü hataların çoğu (kişi-adı, jenerik) yüksek skorlu.

---

## Etki tahmini (40 yanlış üzerinden)

| Çözüm | Kapatması beklenen | Yan-etki riski |
|---|---|---|
| A (core-coverage) | ~26 (D1+D2+D3) | recall: gerçek-kesik firmalar NEW_MASTER (review ile hafifletilir) |
| B (kişi-adı/slash) | ~8 (D4) | düşük — slash-format net konvansiyon |
| C (placeholder) | ~2 (D5 garbage) | yok |
| D (min_score) | ~3-4 (örtüşür A ile) | recall: düşük-skorlu gerçek eşleşmeler |
| **A+B+C birlikte** | **~34/40 (%85)** → precision ~%90 → **~%96-97** | recall maliyeti A'da yoğun, ölçülmeli |

> ⚠️ Tüm tahminler **kısmi %22,5 rematch** örneklemine göre; kesin kalibrasyon tam rematch + yeni qa4 turu gerektirir. Recall maliyeti (Çözüm A) ayrıca `live_probe.py` + qa3 nm-recall ile ölçülmeli.
