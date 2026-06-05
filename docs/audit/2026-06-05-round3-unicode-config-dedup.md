# Round-3 Eşleştirme Kalite Denetimi — Unicode-Filter + Config'lenebilir Dedup Guard Sonrası

**Tarih:** 2026-06-05
**Branch:** `feat/phonetic-overmerge-guard`
**Bu oturum fix'leri:** `input_filter.py` (Unicode-aware `_norm`), `dedup_auto_merge.py` (`_is_distinctive_fingerprint` + config), `config.py` (`DEDUP_MIN_FINGERPRINT_TOKEN_LEN=1`) — 188 test geçti, commit bekliyor.
**Yargı:** 172 Haiku alt-ajan, 1.718 verdict (0 eksik / 0 bozuk), MX naming kuralları prompt'ta.

> [!WARNING]
> **REMATCH %31 TAMAMLANDI — 166.450 / 530.876.** Bu bir *ön-denetimdir*. Snapshot okuma anında **statik** (iki ardışık okuma aynı: 166.450 → durmuş/duraklatılmış). Tüm karşılaştırmalar **ORAN-bazlı** (mutlak sayılar kalan %69 işlendikçe büyür). id-sıralı dilim → hafif yanlı.

---

## ADIM 0 — Her iki fix CANLI rematch'te devrede mi? ✅ EVET

| Kontrol | Beklenti | Gözlem | Sonuç |
| :--- | :--- | :--- | :--- |
| `match_type` PHONETIC_MATCH | ≈ 0 | **0** (dağılımda yok) | ✅ stage kapalı |
| `match_type` NGRAM_MATCH | ≈ 0 | **0** (dağılımda yok) | ✅ stage kapalı |
| **★ P-R2-2** Latin-dışı EXCLUDED (`ord>0x400`) | **0** | **0** | ✅ Unicode fix canlı |
| EXCLUDED içeriği | salt placeholder | `Sin Razon Social`×1187, `Razon Social no determinada`×153, `.`, `NULL` | ✅ |
| **★ P-R2-1** `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` | 1 (park) | **1** | ✅ guard kapalı → akronim magnet BEKLENİR |

**İşlenen 166.450 kaydın `match_type` dağılımı:**
```
NEW_MASTER     134.526   STRIPPED_EXACT 22.049   FUZZY_PHRASE 5.784
TOKEN_COVERAGE  2.219    EXCLUDED        1.342   SUFFIX_FUZZY   530
PHONETIC_MATCH      0 ✅   NGRAM_MATCH        0 ✅
```

**★ P-R2-2 KANITI (Unicode fix işe yaradı):** EXCLUDED kayıtlarında Latin-dışı (Kiril/CJK/Yunan) firma **YOK** (0 / 1342). Eski `[^a-z0-9]` regex'iyle Kiril firmalar `no_alnum` sayılıp dışlanıyordu; yeni `[\W_]` ile bunlar artık NEW_MASTER oluyor. Tüm EXCLUDED 4 ayrı yapısal placeholder'dan ibaret. Rematch **yeni input_filter ile koştu** — DUR koşulu tetiklenmedi.

**Master grup-boyutu dağılımı:** 134.554 grup; 112.102 singleton (%83), 22.452 çok-üyeli. Max master = **72** (06-03'te 1.181 idi; "Sin Razon Social" artık EXCLUDED olduğu için magnet düştü). Kuyruk: 72, 31, 30, 28, 26, 21×4, 19, 18, 17, 16×2, 14×4.

---

## ADIM 3 — DÖRT-TUR ÖNCE/SONRA (oran-bazlı)

| Metrik | 06-02 (açık) | 06-03 (açık rematch) | R2-prelim (%2,9 kapalı) | **Round-3 (%31, Unicode+min=1)** |
| :--- | :---: | :---: | :---: | :---: |
| İşlenen | 68.6k | 278.2k | 15.4k | **166.5k** |
| PHONETIC üye / NGRAM | %80 / %95 | %95.9 / %98.1 | 0 / 0 | **0 / 0** ✅ |
| Over-merge gerçek (düşük-örtüşme havuzu) | %76.6 | (master %95.9) | n/a | **%67.3** (404/600) |
| Kontrol FP (yüksek-örtüşme) | %18 | %27.5 | n/a | **%48.3** (58/120) ⚠️ |
| Split SHOULD_MERGE | %72 | — | n/a | **%85.8** (429/500) |
| NEW_MASTER recall kaybı (qa3 nme) | — | %81.7 | n/a | **%84.6** (252/298) |
| Max magnet boyutu | — | 1.181 | 9 | **72** |
| Akronim-magnet (size≥5) sayısı / üye | — | — | 2 görüldü | **13 / 207** |
| EXCLUDED (Latin-dışı=0?) | — | — | 11 (✓) | **1.342 (Latin-dışı=0 ✓)** |

**Hangi sorun kapandı / hangisi açıldı:**
- ✅ **KAPANDI:** Phonetic/ngram over-merge (%95→0). Garbage magnet "Sin Razon Social" (1.181→EXCLUDED). Latin-dışı yanlış-dışlama (139→0).
- ⚠️ **AÇILDI / büyüdü:** (1) **Akronim/dejenere-fp magnet** — min=1 olduğundan STRIPPED_EXACT akronimleri tek-harf master'lara akıtıyor (aşağıda). (2) **Kontrol FP %48** — gerçek-marka master'larına dejenere artık-üye (`L.MEXICO`, `JABIL MX`, `MODA JOVEN`) bulaşması + LLM'in üye-seviyesi katı yargısı. (3) **Under-merge %86** — phonetic/ngram kapalı olduğundan beklenen recall takası.

---

## ADIM 1-E + 5 — ★ AKRONİM / DEJENERE-FINGERPRINT MAGNET (bu round'un ANA bulgusu)

### Magnet popülasyonu (ES fingerprint kanıtıyla)
13 dejenere magnet (size≥5), **207 üye, 188'i tek-harf fp** (≈ işlenenin %0,12'si; küçük ama yoğun). Büyük-3 = 131 üye:

| Master | Boyut | Kanonik fp | Örnek üyeler |
| :--- | :---: | :---: | :--- |
| `032d50f8` | **72** | `m` (64/72) | `C.M.S.A.D.C`, `M S.A.`, `R S.A. M`, `H&M`, `C.P.M`, `B.A.T`→t değil m... |
| `917c32eb` | 31 | `g` (29/31) | `G.D.S`, `R & G COMPANY`, `B & G`, `D.R.G`, `G.C. S.A.` |
| `71f1d3d1` | 28 | `t` (26/28) | `B.A.T`, `T.P.Y.R.`, `S.S.& T.`, `H.T`, `T.D` |
| `492e728a` | 12 | `k` | `R.P.K. MEXICO`, `K C`, `S.K.B. CORP`, `V.D.K` |
| `2ba886c5` | 11 | `n` | `E.N.S`, `N.`, `A N`, `N.A.C` |
| `188257f9` | 10 | `j` | `J & F`, `I.S.J.`, `J.C.S.A.D.C.V` |
| +7 daha | 5-8 | `w`,`o`,`g m`,… | |

### ES `_analyze` KÖK-NEDEN KANITI (salt-okuma, `fingerprint_analyzer`)
```
C.M.S.A.D.C       -> ['m']      M S.A. -> ['m']      R S.A. M -> ['m']   (5+ FARKLI firma → 'm')
G.F. S.A. DE C.V. -> ['g']      D.R.G  -> ['g']      B.A.T    -> ['t']   (British American Tobacco → 't')
CMSADC            -> ['cmsadc'] (noktasız → BÜTÜN kalır)    3M -> ['3m']  VF -> ['vf']  (gerçek marka korunur)
```

**Kök neden (kesin):** `es_manager.punctuation_remover` char-filter `[.,]+` → **boşluk**. `C.M.S.A.D.C` → `c m s a d c` → standard tokenizer 6 tek-harf üretir → `legal_fragment_stop` tek-harf yasal-ek parçalarını (`get_all_legal_suffix_fragments`'tan: **a b c d e f h i l p r s u v y**) düşürür → geriye yasal-olmayan tek harf kalır. Hayatta kalan harfler (set DIŞI): **g j k m n o q t w** + rakam — **gözlenen magnet fingerprint'leriyle birebir aynı.** `B.A.T`→(b,a sil)→`t`; `D.R.G`→(d,r sil)→`g`; `C.P.M`→(c sil)→`m`.

### ★ Bu magnetler dedup'tan DEĞİL, STRIPPED_EXACT'ten geliyor (karar için kritik)
| Master | STRIPPED_EXACT | NEW_MASTER | diğer |
| :--- | :---: | :---: | :---: |
| `032d50f8` (72) | **66** | 5 | 1 (TOKEN_COVERAGE) |
| `917c32eb` (31) | **29** | 2 | — |
| `71f1d3d1` (28) | **25** | 2 | 1 (FUZZY_PHRASE) |

Üyelerin **%91+'i STRIPPED_EXACT** ile eşleşme-zamanında ilgili tek-harf master'a akıyor. `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` yalnız **dedup-merge adımını** yönetir (master başına 2-9 NEW_MASTER üyesi) — STRIPPED_EXACT'i DEĞİL. **Bu yüzden config eşiği magneti pratikte kapatamaz.**

---

## ADIM 4 — ★ KARAR: `DEDUP_MIN_FINGERPRINT_TOKEN_LEN` = 1 mi 2 mi?

### Simülasyon (salt-okuma, ES fingerprint gruplarında `_is_distinctive_fingerprint`)
Index'te kalan aynı-fp ≥2-master grubu: **6.770**. fp max-token-uzunluk histogramı:

| max-token-len | 1 | 2 | 3 | 4+ |
| :--- | :---: | :---: | :---: | :---: |
| grup sayısı | **21** | 10 | 73 | 6.666 |

- **min=2'nin YENİ engelleyeceği grup: 21** — hepsi tek-harf fp: `m`(8 master), `t`(6), `o`(5), `w`(4), `m t`(7), `g m`(4), `n t`(4), `g`(2), `k`(3), `q`(3)… → **tamamı dejenere akronim artığı, GERÇEK MARKA YOK.**
- **min=2'nin KORUDUĞU len-2 gruplar (10):** `3m`(3M), `gm`(GM/General Motors), `dr`(DR MEXICO), `mt`, `kh`, `6m`, `jv`, `ho` = **gerçek 2-harfli markalar korunur** ✓. Ama `av`(←`P.AV.I`), `ag`(←`C S AG.`) = 2 dejenere len-2 artık min=2'yi **geçer** (config'in ampirik notu doğrulandı: ≥2 tam fix değil).

### Trade-off (sayıyla)
| | Kazanç | Kayıp |
| :--- | :--- | :--- |
| **min=1 → min=2** | 21 tek-harf dedup magnet grubu engellenir (master'lar arası 8'e kadar yanlış birleşme) | **0 gerçek marka** (tüm len-2 marka korunur) |
| **Sınır** | — | STRIPPED_EXACT magnetlerine (gerçek büyük magnet) **etkisiz**; len-2 artık (`av`,`ag`) hâlâ geçer |

### 🎯 KARAR: **min=2 yapılsın** — ama "asıl çözüm" DEĞİL, ücretsiz hijyen.
- **Gerekçe:** Ölçülen maliyet **sıfır** (hiçbir gerçek firmanın fingerprint'i salt tek-harf değil); 21 dejenere dedup magnetini kapatır; kalan %69 rematch için dedup'ı güvenli kılar → **kesin baskın (strictly dominant) seçim.**
- **AMA kritik uyarı:** Magnetlerin **%91'i STRIPPED_EXACT** kaynaklı; min=2 bunlara dokunmaz. Yani 1↔2 seçimi **görünen magnetleri materyal olarak küçültmez** — düşük-bahisli bir karardır. Kullanıcının "analyzer reindex'i bekle" sezgisi **asıl fix için doğru.**
- **Öneri:** min=2'yi şimdi uygula (bedava), **ama magnetin gerçek çözümünü `DEDUP_MIN`'den BEKLEME** — o, analyzer reindex'tir (ADIM 5).

---

## ADIM 5 — Kalan over-merge stage'leri + analyzer kök-neden + öneriler

### Kalan over-merge'i ÜRETEN stage'ler (yargılı örneklem)
| Stage | Master-seviyesi FP | Üye-seviyesi FP | Yorum |
| :--- | :---: | :---: | :--- |
| **TOKEN_COVERAGE** | **%91.1** (144/158) | **%75.9** (202/266) | EN YÜKSEK oran — coverage eşiği gevşek (CLARIANT+LESCHACO, `I.I.Q`+`Q.S.I`, `#N/A` parçaları) |
| NEW_MASTER (magnet seed) | %88.9 (8/9) | — | tek-harf seed master'lar |
| STRIPPED_EXACT | %68.6 (35/51) | %15.8 (91/577) | akronim magnet sürücüsü (büyük master, üye-oranı düşük) |
| FUZZY_PHRASE | %56.8 (179/315) | %35.3 (213/604) | EN YÜKSEK HACİM (315 master) |
| SUFFIX_FUZZY | %56.7 (38/67) | %39.4 (39/99) | |

> Phonetic/ngram kapandığından **over-merge'in yeni birincil kaynakları TOKEN_COVERAGE (oran) ve FUZZY_PHRASE (hacim)**; akronim magnet en *görünür* (büyük master) ama TOKEN_COVERAGE en *yüksek-oranlı* suçludur.

### Analyzer kök-neden — hedefli ES-side öneriler (KOD DEĞİŞTİRİLMEDİ; reindex gerekir)
1. **Akronim çökmesini durdur (ANA):** `punctuation_remover` tek-harfler arası noktayı boşluğa çevirmesin → `C.M.S.A.D.C`→`cmsadc` (ayırt edici, len 6) olur, `m`'ye çökmez. Dikkat: `S.A.`→`sa`, `C.V.`→`cv` olacağından `legal_fragment_stop`'a 2-harf biçimler (`sa`,`cv`,`rl`,`de`…) zaten var (✓), tek-harf set yeterli kalır.
2. **Veya dejenere artık bırak:** Bir analyzer zincirinde strip sonrası **tek-harf token'ı tamamen düş** → akronim fp'i BOŞ olur → `plan_merge` boş-fp guard'ı + STRIPPED_EXACT boş-anahtar magneti engeller; her akronim kendi NEW_MASTER'ı olur (under-merge ama magnet yok). Gerçek 2-harf marka (vf/3m/gm) len≥2 → korunur.
3. **STRIPPED_EXACT + TOKEN_COVERAGE'a ayırt-edici-çekirdek şartı:** ES-side `token_count` ile kazanan adayda ≥1 yasal-olmayan + ≥2-karakter çekirdek token zorunlu kıl (Python doğrulaması YOK; query DSL/script). TOKEN_COVERAGE eşiği (`%95`) tek-harf/akronimde no-op kalıyor.
4. **COUNTRY_LEAK yapısal olarak imkânsız:** `country_code` = %100 MX (530.876). Yargıdaki 4 LEAK verdict'i, *isimde* geçen coğrafi kelimeyi (ECUADOR/SINGAPORE) okuyan LLM yanılgısıdır — gerçek country_code sızıntısı değil.

---

## NEW_MASTER recall + dedup doğrulama + garbage

**★ Dedup doğrulama (bölünmüş hedef firmalar) — kısmen toparlandı, kuyruk dağınık (rematch %31):**
| Firma | master sayısı | işlenen satır | en büyük master |
| :--- | :---: | :---: | :---: |
| VF OUTDOOR | 31 | 63 | **29** ✓ ana toplandı |
| CUMMINS | 74 | 128 | 26 |
| FLEXTRONICS | 78 | 126 | 18 |
| JOHN DEERE | 62 | 118 | 21 |
| SIEMENS | 76 | 109 | 10 |
| HULERA TORNEL | 22 | 43 | 13 |
| HALLIBURTON | 25 | 33 | 3 (parçalı) |

Ana master'lar büyük doğru kümeyi topluyor (VF 29, CUMMINS 26) ama uzun kuyruk (size-2/1) henüz birleşmemiş — **kısmen rematch eksikliği (per-batch dedup yalnız batch-içi), kısmen analyzer-gap** (suffix-truncation farklı fingerprint üretiyor). 122 "temiz" büyük grup (size≥8) doğru dedup; yalnız 7'si akronim magnet → **dedup mekaniği esasen doğru çalışıyor.**

**★ NEW_MASTER recall (qa3 deseni):** nme (özdeş geo-çekirdek) **%84.6 SHOULD_MERGE** (252/298) — yüksek under-merge. Pattern: suffix-truncation 266, truncat 163, spacing 44, word-order 30, abbrev 28, typo 28. Örnek: GENERAL MOTORS / FORD MOTOR / SIEMENS (8 master) / KIMBERLY CLARK / JABIL CIRCUIT hepsi yalnız yasal-ek/geo varyantı yüzünden ayrı. nml (gevşek) %39.5 (gerçek-ayrı daha çok).

**★ Garbage/EXCLUDED:** `Sin Razon Social` (1187) + `Razon Social no determinada` (153) artık EXCLUDED → magnet seed'i bitti ✓. Yargıda kalan garbage (`#N/A NNN`, harf-parçaları `D.E.C`/`E.C.S.D.C`) STRIPPED_EXACT/TOKEN_COVERAGE ile gerçek-marka master'larına sızıyor → input_filter değil, **analyzer-strip kaynaklı** (kod/harf-parçası "isim yok" değildir; bilinçli olarak NEW_MASTER tutuluyor, ama akronim-collapse onları magnete sokuyor).

---

## ★ EN YÜKSEK ETKİ ÖZETİ (5 madde)

1. **Her iki bu-oturum fix'i CANLI ve DOĞRU:** Latin-dışı EXCLUDED = 0 (Unicode fix ✓); PHONETIC/NGRAM = 0; "Sin Razon Social" magneti EXCLUDED (max magnet 1.181→72).
2. **Asıl açık yara = analyzer akronim-çökmesi** (`punctuation_remover` + tek-harf `legal_fragment_stop`): farklı firmalar `m`/`g`/`t` fingerprint'ine çöküp STRIPPED_EXACT ile birleşiyor (13 magnet/207 üye). **Tek gerçek çözüm: analyzer reindex** (öneri 1 veya 2).
3. **`DEDUP_MIN_FINGERPRINT_TOKEN_LEN=2 yap** — bedava ve baskın (21 dejenere grup kapanır, 0 gerçek marka kaybı), AMA magnetin %91'i STRIPPED_EXACT olduğundan bu bir mikro-hijyen, çözüm değil.
4. **Over-merge'in yeni birincil oran-suçlusu TOKEN_COVERAGE (%91 master FP)** ve hacim-suçlusu FUZZY_PHRASE (315 master). Phonetic/ngram sonrası bunlara ES-side ayırt-edici-çekirdek şartı gerekli.
5. **Under-merge yüksek (%84.6 recall kaybı)** — phonetic/ngram takasının bedeli; suffix-truncation varyantları (GENERAL MOTORS/SIEMENS/FORD) ayrı master. Analyzer reindex aynı zamanda bunların fingerprint'ini birleştirip recall'i de kazandırır.

---

## ONAY İSTENEN KARARLAR
- [ ] **`DEDUP_MIN_FINGERPRINT_TOKEN_LEN = 2`** yapılsın mı? (bedava/baskın; önceki oturumda 1'de park edilmişti)
- [ ] **Analyzer reindex** (öneri 1: akronim glue, veya öneri 2: tek-harf token düş) planlanıp tam rematch SONRASI mı, ÖNCESİ mi uygulansın?
- [ ] **TOKEN_COVERAGE + STRIPPED_EXACT'a ES-side ayırt-edici-çekirdek (`token_count`) şartı** eklensin mi?

---

## UYGULAMA DURUMU (2026-06-05, kullanıcı onayı sonrası)

| # | Karar | Durum | Detay |
| :--- | :--- | :--- | :--- |
| 1 | `DEDUP_MIN_FINGERPRINT_TOKEN_LEN = 2` | ✅ **UYGULANDI** | `config.py`. Testler monkeypatch kullandığından kırılmadı. |
| 2 | Öneri-1 akronim-glue analyzer | ✅ **UYGULANDI + DOĞRULANDI** | `es_manager.py` yeni `acronym_glue` char-filter (`\b(\p{L})\.(?=\p{L})` → `$1`, lookbehind-SIZ → JVM-portable), tüm 9 analyzer'da `punctuation_remover`'dan önce. **REINDEX GEREKTİRİR.** |
| 3 | TOKEN_COVERAGE/STRIPPED_EXACT çekirdek-gate | 📋 **PLANLANDI** (aşağıda) | Henüz kod yok. |

**Test:** 189 passed / 1 skipped (yeni `test_acronym_glue_char_filter_precedes_punctuation_remover`).
**Temp-index uçtan-uca doğrulama** (`tmp_glue_verify_r3`, prod index'e dokunulmadı): 11/11 OK —
`C.M.S.A.D.C→cmsadc`, `B.A.T→bat`, `D.R.G→drg`, `A.P.M. S.A.→apm` (akronim ayırt edici oldu);
`S.A.P.I.→''`, `ACME S.A.P.I. DE C.V.→acme`, `ACME S.A. DE C.V.→acme` (yasal-ek REGRESYON YOK);
`VF OUTDOOR MEXICO S.A.→outdoor vf`, `SIEMENS...MEXICO→siemens` (geo strip korunur); `3M...→3m` (marka korunur).
Kalan: `M S.A.→m` (boşlukla-ayrılmış tek-harf marka — DEDUP_MIN=2 + çekirdek-gate ile kapanır).

> [!IMPORTANT]
> **AKTİVASYON:** Akronim-glue yalnız **reindex** sonrası devreye girer. Mevcut %31 rematch ESKİ
> analyzer ile koştu. Aktivasyon sırası: `python es_manager.py --force` (530k reindex) →
> `python main_processor.py` (sıfırdan tam rematch). Reindex zamanı kullanıcı kararı (uzun/destructive).

### Karar #3 PLANI — ES-side ayırt-edici-çekirdek (token_count) gate
**Amaç:** STRIPPED_EXACT ve TOKEN_COVERAGE kazananı, EN AZ bir *ayırt edici* (yasal-ek/geo DIŞI,
≥2-karakter) çekirdek token paylaşmalı. Böylece reindex sonrası kalan boşluk-ayrılmış tek-harf
artıkları (`M S.A.→m`) ve `#N/A`/harf-parçası adaylar STRIPPED_EXACT/TOKEN_COVERAGE ile **kazanan olamaz**.
**ES-side (Python doğrulaması YOK, CLAUDE.md §):**
- `es_queries.STRIPPED_EXACT` / `TOKEN_COVERAGE` sorgularına, `variations_stripped` (zaten yasal/geo-stop'lu)
  alanında **min 1 ortak ≥2-char token** zorunluluğu (`token_count` runtime/script veya `minimum_should_match`
  + uzunluk filtreli `terms`). Tek-harf veya boş çekirdekli sorgu kaydı bu stage'lerde **eşleşmez → NEW_MASTER**.
- Mevcut `TOKEN_COVERAGE_THRESHOLD=0.95` tek-harf/akronimde no-op kalıyor (1/1=%100); gate bunu kapatır.
- Reindex'le birlikte test edilmeli (`analysis/live_probe.py` golden + temp-index). Kullanıcı onayı bekliyor.

---

> Kaynak artefaktlar: `C:/tmp/qa2_summary.json`, `C:/tmp/qa2_results/*.json` (1.718 verdict), `C:/tmp/verify_glue_tempindex.py`, ES `_analyze` çıktıları (rapor içi). Salt-okuma: p7_firms_v2'ye yazılmadı.
