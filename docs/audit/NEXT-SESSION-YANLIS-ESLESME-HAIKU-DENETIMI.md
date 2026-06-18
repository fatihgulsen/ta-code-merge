# GÖREV PROMPT'U — Yanlış Eşleşme Denetimi (Haiku) + ES-Tarafı Kök Neden & Revizyon

> Bu dosya **ayrı bir session'a yapıştırılmak** üzere yazılmış, kendi kendine yeten bir görev
> prompt'udur. Aşağıdaki talimatların **HİÇBİRİ atlanmayacaktır**. Bir adımı yapamıyorsan
> dur, nedenini raporla, uydurma. Kapsam: **over-merge** (yanlış birleşmiş = eşleşmemesi
> gerekenler). **Under-merge (eşleşmesi gerekip eşleşmeyen) bu görevin DIŞINDADIR — ayrı,
> sonraki bir görevdir; bu session'da ona dokunma.**

---

## 0. Rol ve Mutlak Kurallar (ihlal edilemez)

Sen bu firma-eşleştirme sisteminin QA orkestratörüsün. Görev iki ayağa sahip:
1. **Doğruluk denetimi** — DB'deki tüm eşleşmeleri Haiku alt-ajanlarına böldür, **tek satır
   atlamadan** doğru/yanlış işaretlet.
2. **Kök neden + ES-tarafı revizyon** — yanlış işaretlenenlerin NEDEN oluştuğunu araştır,
   sonra ayrı bir alt-ajana **Elasticsearch tarafında** hangi sorgu/analyzer revizyonunun bu
   hataları keseceğini test ettir.

**MUTLAK KURALLAR (CLAUDE.md ve proje hafızasından — asla çiğneme):**
- **COUNTRY CODE HARD FILTER**: Farklı ülke firmaları ASLA eşleşemez. `country_count > 1` olan
  her grup otomatik şüphelidir (country-leak) ve mutlaka işaretlenir.
- **PYTHON'DA FUZZY/LEVENSHTEIN YASAK**: Önerilecek hiçbir düzeltme Python tarafında RapidFuzz/
  Levenshtein/string-benzerliği kullanamaz. Tüm benzerlik/eşik/coverage mantığı **ES Query DSL
  + Painless + analyzer** ile çözülür (`fuzziness:"AUTO"`, `token_count`, `match_phrase`).
- **DOĞRULAMA ES-TARAFINDA**: Eşleşme doğrulaması/coverage Python post-verify ile değil, ES
  token_count / query DSL ile yapılır. Bu, önerilecek revizyonların da kuralıdır.
- **ÜLKE TOKEN'LARI HARDCODE EDİLMEZ**: Ülkeye özgü kelimeler (jenerik sektör sözcükleri, geo
  terimleri, yasal ekler) `synonyms_data/` JSON'larından türetilir; koda gömülmez.
- **SYNONYM JSON'LARI SABİT**: `synonyms_data/` altındaki 65 ülke dosyası içeriği elle
  düzeltilmez. İstisna yalnızca `non_firm_placeholders` kategorisi (eklemeye açık). Diğer her
  şey `config.py`/analyzer/query üzerinden çözülür.
- **Hiçbir satır örneklenip geçilmez (no sampling)**: Sorgudan dönen N satırın TAMAMI
  incelenir. Her batch'in işlendiği kanıtlanır (satır sayısı toplamı = N).

---

## 1. Sistem Arka Planı (alt-ajanlara bağlam ver)

- **Tablo**: `p7_firms_v2_ar_pe` (PostgreSQL `market_calculus` DB; AR + PE kayıtları).
  Bağlantı: `config.py` → `DB_CONFIG` (localhost:5432, db=market_calculus, user=postgres).
  Bağlantı için `dbhub` MCP'si veya `psycopg2` (proje zaten kullanıyor) tercih edilir.
- **Eşleşme modeli**: Her grup bir `master_code` ile anchor'lanır. `match_type='NEW_MASTER'`
  olan satır anchor (master). Diğer satırlar o master'a bağlanmış varyantlardır.
  `match_details` örn. `[STRIPPED_EXACT] score: 5.24` — hangi stage'in eşleştirdiğini ve
  ES skorunu verir.
- **Aktif stage'ler** (`config.py` STAGES): `CANONICAL_EXACT` (1), `STRIPPED_EXACT` (2),
  `FUZZY_PHRASE` (4), `TOKEN_COVERAGE` (5). Kapalı: `SUFFIX_FUZZY`, `PHONETIC_MATCH`,
  `NGRAM_MATCH`. (Kapalı stage'ler eski kayıtlarda `match_type` olarak hâlâ görülebilir.)
- **STRIPPED_EXACT mekaniği** (`es/queries.py:STRIPPED_EXACT`): "stripped" analyzer yasal ek
  (SRL/EIRL/SA…) + geo terimlerini atar; `variations_stripped.name`'e `match_phrase` + nested
  `token_count` eşitliği uygulanır. Bir `_has_distinctive_core` GATE'i vardır
  (`MATCH_CORE_MIN_TOKEN_LEN=2`): en az 2 karakterlik bir token kalmazsa stage çalışmaz.
- **BİLİNEN ŞÜPHELİ KÖK NEDEN (örnek vaka, doğrula/çürüt)**:
  `IMPORTADORA F & V E.I.R.L.` ↔ `IMPORTADORA C & C SRL`, `[STRIPPED_EXACT] score: 5.24`.
  Hipotez: stripped analyzer yasal eki + `&` + tek-harf token'ları (F, V, C) eler; geriye
  yalnızca **jenerik sektör kelimesi "IMPORTADORA"** kalır. `_has_distinctive_core` bunu
  uzunluk≥2 olduğu için "ayırt edici" sanır; her iki taraf da `token_count=1` + aynı phrase
  → yanlış STRIPPED_EXACT. Gerçek ayırt edici kısım (F&V vs C&C) tamamen kaybolmuştur.
  **Genel desen: jenerik sektör/sıfat kelimeleri (IMPORTADORA, COMERCIAL, DISTRIBUIDORA,
  SERVICIOS, GENERAL…) tek başına "çekirdek" sayılınca over-merge oluyor.**
- **İlgili dosyalar**: `es/queries.py` (stage Query DSL), `es/ingest.py` (Painless temizlik,
  variations_stripped üretimi), `es/manager.py` (analyzer/mapping), `config.py` (eşikler,
  gate'ler), `core/synonym_loader.py` + `synonyms_data/` (kelime grupları, geo, yasal ek,
  non_firm_placeholders), `core/core_name.py` (normalizasyon).
- **Önceki QA çıktıları** (formatı taklit et, üzerine yaz): `qa-artifacts/round6/`,
  `qa-artifacts/round7/`, `docs/audit/2026-06-*`. Bu görev **round8** olacak.

---

## 2. Kaynak Sorgu (aynen çalıştır)

Sonuç kümesi bu sorgudur. **Değiştirme** (yalnızca dışa-aktarım için gerekiyorsa `ta_code`,
`country_code`, `match_score` kolonlarını ek olarak SELECT edebilirsin — mevcut kolonları
çıkarma):

```sql
WITH master_groups AS (
    SELECT
        master_code,
        count(*) FILTER (WHERE match_type != 'NEW_MASTER') AS variant_count,
        count(DISTINCT country_code)                        AS country_count,
        array_agg(DISTINCT country_code ORDER BY country_code) AS countries
    FROM p7_firms_v2_ar_pe
    WHERE master_code IS NOT NULL
    GROUP BY master_code
)
SELECT
    m.ta_code        AS master_ta_code,
    m.name           AS master_name,
    m.country_code   AS master_country,
    v.ta_code        AS variant_ta_code,
    v.name           AS variant_name,
    v.country_code   AS variant_country,
    v.match_type     AS variant_match_type,
    v.match_score    AS variant_score,
    v.match_details  AS variant_details,
    g.variant_count,
    g.country_count,
    g.countries,
    CASE WHEN g.country_count > 1 THEN 'COUNTRY_LEAK!' ELSE 'OK' END AS leak_flag
FROM p7_firms_v2_ar_pe m
JOIN p7_firms_v2_ar_pe v  ON v.master_code = m.master_code
                          AND v.ta_code    != m.ta_code
JOIN master_groups g       ON g.master_code = m.master_code
WHERE m.match_type = 'NEW_MASTER'
ORDER BY
    g.country_count DESC,
    g.variant_count DESC,
    m.ta_code,
    v.match_type;
```

> Not: Haiku'nun kararı için yalnızca `master_name`, `variant_name`, `variant_match_type`,
> `variant_details`, `master_country`, `variant_country`, `leak_flag` yeterlidir. `ta_code`'lar
> izlenebilirlik/araştırma içindir.

---

## 3. Faz 0 — Hazırlık ve Dışa Aktarım

1. `qa-artifacts/round8/` klasörünü oluştur (`batches/`, `verdicts/` alt klasörleriyle).
2. Sorguyu çalıştır, **toplam satır sayısı N**'i raporla. Bu N, sonun kapanış kontrolüdür.
3. Sonucu satır-başına bir JSON nesnesi olacak şekilde `qa-artifacts/round8/pairs.jsonl`'e
   yaz. Her nesnede en az: `master_ta_code, master_name, master_country, variant_ta_code,
   variant_name, variant_country, variant_match_type, variant_score, variant_details,
   country_count, leak_flag`.
4. `pairs.jsonl`'i ~150 satırlık parçalara böl: `batches/overmerge_batch_01.jsonl` …
   Parça sayısını ve her parçanın satır sayısını raporla. **Σ(parça satırları) == N** olmalı;
   tutmuyorsa dur ve düzelt.

---

## 4. Faz 1 — Haiku Doğru/Yanlış İşaretleme (no-skip, paralel)

Her batch için bir **Haiku alt-ajanı** dispatch et (`model: haiku`). Bağımsız oldukları için
**paralel** (tek mesajda birden fazla Task) çalıştır; aynı anda en fazla ~6-8 ajan, kalanları
sıraya al. Her ajan kendi batch'indeki **HER satırı** değerlendirir — örnekleme yok, satır
atlama yok.

**Alt-ajana verilecek talimat (birebir kullan):**

> Sen bir firma-adı eşleştirme denetçisisin. Sana JSONL satırları verilecek; her satır bir
> `master_name` ile ona eşleştirilmiş bir `variant_name` çiftidir. Görevin: bu ikisinin
> **gerçekten AYNI firma** olup olmadığına karar vermek.
>
> KURALLAR:
> - **Ülke**: `master_country != variant_country` veya `leak_flag == 'COUNTRY_LEAK!'` ise
>   verdict daima `WRONG`, reason `country_leak`. (Farklı ülke = asla aynı firma.)
> - **YANLIŞ (WRONG)** işaretle eğer eşleşme yalnızca şunlara dayanıyorsa:
>   - jenerik sektör/sıfat kelimeleri (örn. IMPORTADORA, COMERCIAL, DISTRIBUIDORA, SERVICIOS,
>     COMPANIA, GENERAL, GLOBAL, GRUPO…) ortak ama ayırt edici öz-ad farklı
>     (örn. `IMPORTADORA F & V` vs `IMPORTADORA C & C` → WRONG),
>   - yalnızca yasal ek (SRL, EIRL, SA, SAC…) ortak,
>   - ayırt edici çekirdek (marka/öz-ad) açıkça farklı (örn. INTERAGUA vs INTERFIG),
>   - biri diğerinin alt-kümesi/kısaltması DEĞİL, tamamen farklı isim.
> - **DOĞRU (CORRECT)** işaretle eğer:
>   - aynı firmanın yazım/kısaltma/aralık/noktalama varyantı (örn. `J&K SAC` vs `J & K S.A.C.`),
>   - aynı çekirdek + farklı/eksik yasal ek (örn. `ACME PERU SAC` vs `ACME PERU`),
>   - açık typo ama aynı ayırt edici çekirdek.
> - Emin değilsen `UNCERTAIN` ver ve nedenini yaz. Tahmin etme.
>
> ÇIKTI: Sana verilen her satır için **tam olarak bir** JSON nesnesi döndür (girdi satır
> sayısı == çıktı satır sayısı, hiçbirini atlama):
> `{"master_ta_code","variant_ta_code","master_name","variant_name","verdict":"CORRECT|WRONG|UNCERTAIN","reason":"<kısa: country_leak|generic_word_only|suffix_only|different_core|variant_ok|subset_ok|typo_ok|...>","shared_tokens":[...],"distinctive_diff":"<master öz-adı> vs <variant öz-adı>"}`
> Sadece JSONL döndür, başka açıklama yok.

Her alt-ajanın çıktısını `qa-artifacts/round8/verdicts/overmerge_batch_NN.verdicts.jsonl`'e
yaz. **Kontrol**: her verdict dosyasının satır sayısı, kaynağı olan batch dosyasının satır
sayısına eşit olmalı. Eşit değilse o batch'i yeniden çalıştır. Σ(verdict satırları) == N olana
kadar kapanma.

---

## 5. Faz 2 — Toplama, Metrik, Önce-Doğru-Sonra-Hatalı

1. Tüm verdict'leri birleştir. Hesapla ve raporla:
   - toplam çift, CORRECT / WRONG / UNCERTAIN sayıları ve **precision = CORRECT / (CORRECT+WRONG)**,
   - `match_type` bazında dağılım (STRIPPED_EXACT / FUZZY_PHRASE / TOKEN_COVERAGE …),
   - country-leak sayısı.
2. **Önce doğruları sabitle**: CORRECT kümesini `qa-artifacts/round8/correct.jsonl`'e ayır
   (kanıt/regresyon temeli). Bunlara dokunulmayacak — sonraki revizyon bunları bozmamalı.
3. **Sonra hataları topla**: WRONG kümesini `qa-artifacts/round8/wrong.jsonl`'e ayır ve
   `reason` + `match_type`'a göre kategorize et. Beklenen kategoriler (gözlemle, genişlet):
   `country_leak`, `generic_word_only`, `suffix_only`, `different_core`, `subset_truncation`,
   `acronym_collapse`, `phonetic_collision`. Her kategori için sayı + 5-10 temsili örnek.

---

## 6. Faz 3 — Kök Neden Araştırması (yanlışlar için)

Her WRONG kategorisi için NEDEN oluştuğunu kodda izini sürerek araştır (gerekiyorsa kategori
başına bir araştırma alt-ajanı; bunlar `sonnet` olabilir, salt-okuma):
- İlgili stage'in Query DSL'i (`es/queries.py`) — hangi şart gevşek?
- `es/ingest.py` Painless temizliği — `variations_stripped` üretirken hangi token'lar atılıyor
  (örn. tek-harf, `&`, jenerik kelime), hangileri kalıyor?
- `_has_distinctive_core` / `MATCH_CORE_MIN_TOKEN_LEN` gate'i neden jenerik kelimeyi "çekirdek"
  sayıyor?
- `synonyms_data/` (özellikle `common.json` ve `ar.json`/`pe.json`) — jenerik sektör kelimeleri
  / geo / yasal ek listelerinde eksik var mı? (Düzeltme JSON'a elle değil; kategoriye uygun
  yere — config/analyzer/query — yapılacak. Yalnızca `non_firm_placeholders` JSON'a eklenebilir.)

Çıktı: `docs/audit/2026-06-16-round8-yanlis-eslesme-kok-neden.md` — her kategori için:
*belirti → kanıt (dosya:satır) → kök neden → önerilen ES-tarafı düzeltme yönü*.
Her örnek vaka için `master_name | variant_name | match_details | kök neden` satırı.

---

## 7. Faz 4 — ES-Tarafı Revizyon Testi (ayrı alt-ajan)

Kök neden raporu hazır olunca, **ayrı bir alt-ajan** dispatch et: görevi, önerilen düzeltmelerin
ES tarafında gerçekten işe yarayıp yaramadığını **canlı ES üzerinde test etmek**. Bu ajan:

- Yalnızca **ES Query DSL / analyzer / Painless** ile çözüm üretir (Python fuzzy YASAK).
- Her hipotez için ES `_analyze` API'si ve gerçek sorgularla kanıt toplar:
  - Örn. "IMPORTADORA tek başına çekirdek olmamalı" → jenerik-kelime stop/synonym listesini
    stripped analyzer'a ekleyince `IMPORTADORA F & V` ve `IMPORTADORA C & C` çıktıları
    `_analyze` ile nasıl değişiyor? (Hedef: jenerik kelime atılınca her iki taraf da
    çekirdeksiz kalmalı → STRIPPED_EXACT artık ateşlememeli → bu çift WRONG'tan çıkmalı.)
  - token_count eşitliği / coverage gate (`ENABLE_CORE_COVERAGE_GATE`) sıkılaştırması
    over-merge'ü keser mi?
  - Önerilen değişiklik `correct.jsonl`'deki doğru eşleşmeleri **bozuyor mu?** (regresyon).
    Doğruları bozan revizyon reddedilir.
- Her öneri için: *değişiklik → ES kanıtı (_analyze/sorgu çıktısı) → kaç WRONG düzelir →
  kaç CORRECT bozulur (sıfır olmalı) → net karar*.

Çıktı: `docs/audit/2026-06-16-round8-es-revizyon-testi.md`. **Kod değişikliğini bu görevde
UYGULAMA** (analyzer değişikliği reindex gerektirir, ayrı onaylı iş). Yalnızca test + öneri.

> ES test ajanına talimat çekirdeği: "Aşağıdaki yanlış-eşleşme kategorileri için ES tarafında
> (analyzer/Query DSL/Painless) düzeltme öner ve `_analyze` + gerçek sorgu çıktısıyla DOĞRULA.
> Python tarafı string-benzerliği KULLANMA. Her öneri `correct.jsonl`'deki doğruları bozmamalı —
> bozuyorsa reddet. Reindex GEREKTİREN değişiklikleri ayrıca işaretle."

---

## 8. Kapanış Çıktısı

Ana session sonunda tek özet ver:
- N (toplam çift), precision, WRONG kategori dağılımı,
- en yüksek-etkili 3 kök neden,
- ES tarafında doğrulanmış (regresyonsuz) revizyon önerileri ve tahmini kazanç,
- üretilen dosyalar: `qa-artifacts/round8/{pairs,correct,wrong}.jsonl`, verdict'ler,
  `docs/audit/2026-06-16-round8-*.md`.

**Hatırlatma**: Bu görev yalnızca **over-merge (yanlış birleşme)** içindir. Under-merge
(eşleşmesi gerekip eşleşmeyenler) **ayrı bir sonraki görevdir** — bu session'da başlatma.
