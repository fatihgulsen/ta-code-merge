# es_queries.py Audit Bulguları

**Tarih:** 2026-05-25
**Dosya:** es_queries.py (316 satır)
**Audit eden:** Claude (subagent, sonnet)
**Baseline (bu modülle ilgili):** 5 failing tests in tests/test_es_queries.py; 1 collection error (tests/test_address_anchoring.py — _strip_address_python missing)

---

## Özet
- CRITICAL: 0
- HIGH: 1
- MEDIUM: 3
- LOW: 1

---

## Kapsam Notu

- **`_routing` enforcement** CLAUDE.md §1.1 hem `bool.filter.country_code` hem de `_routing=country_code.upper()` ister. `es_queries.py` sadece query body DSL üretir — `_routing` parametresi `client.msearch()` / `client.search()` çağrısında verilir. Bu audit kapsamında **es_queries.py içindeki `country_code` filter** doğrulanmıştır (✅). `_routing` paramının fiilen geçirilip geçirilmediği `main_processor.py` audit'inin kapsamındadır ve orada doğrulanmıştır (main_processor.py:262 `msearch(... routing=...)` çağrıları, ayrıca `es.index` çağrılarında `routing=cc` kullanımı — Task 2 quality review notu).
- **`PHONETIC_MATCH` (satır 289-316)** Bu stage fonksiyonu okunmuş, `country_code` filter mevcut, görünür defekt bulunmamıştır. Bulgu çıkarılmadığı için raporda zikredilmemiştir.

---

## Checklist Durumu

### CLAUDE.md kuralları
- country_code in every query function (filter + caller routing): ✅ — Tüm 6 public fonksiyon `bool.filter` içinde `{"term": {"country_code": country.upper()}}` kullanıyor.
- Python fuzzy/Levenshtein imports: ✅ — `rapidfuzz`, `Levenshtein`, `difflib` import yok.
- synonyms_data writes: ✅ — Dosyaya yazma yok.

### es_queries.py-özgü
- Stage names match config.py STAGES: ✅ — `CANONICAL_EXACT`, `STRIPPED_EXACT`, `SUFFIX_FUZZY`, `FUZZY_PHRASE`, `TOKEN_COVERAGE`, `PHONETIC_MATCH`, `NGRAM_MATCH` — hepsi config.STAGES ile birebir eşleşiyor.
- fuzziness usage consistent (AUTO): ⚠️ — Sadece `SUFFIX_FUZZY` fuzziness kullanıyor ve `"AUTO:4,7"` ile sınırlandırılmış. Diğer stageler fuzziness kullanmıyor (match_phrase/match). Bu bilinçli tasarım; sorun yok.
- Nested paths / inner_hits consistent: ❌ — `CANONICAL_EXACT` içindeki token_count field path yanlış: `variations.name.token_count` yerine `variations.token_count` olmalı. Bkz. HIGH bulgu #1.
- Country-specific analyzer usage: ✅ — `_get_analyzer` ve `_get_stripped_analyzer` yardımcı fonksiyonları ülkeye özel ve fallback analyzer döndürüyor.
- Painless thresholds in code vs config: ✅ — Painless script yok. `min_score` değerleri config.py'de STAGES içinde tanımlı.
- DRY (duplicate stage builders): ⚠️ — `CANONICAL_EXACT` ve `STRIPPED_EXACT` neredeyse özdeş bir şablonu paylaşıyor (yalnızca alan adları farklı). MEDIUM düzey şişirilme; kritik değil.
- Missing helper patterns (e.g., _strip_address_python): ❌ — `_strip_address_python` es_queries.py'de tanımlı değil. `tests/test_address_anchoring.py` ve `scratch/test_address_strip.py` bu fonksiyonu import etmeye çalışıyor ve `ImportError` ile çöküyor. Bkz. MEDIUM bulgu #3.

### Failing tests (test_es_queries.py) — verdict per test

- **test_canonical_exact_structure**: **Real bug in es_queries.py.** Test `variations.token_count` field path'ini bekliyor, kaynak kod ise `variations.name.token_count` kullanıyor. ES mapping'de token_count sub-field'ı `variations.name` altında değil, `variations` altında tanımlanmış olması kuvvetle muhtemel. Kaynak kodu düzeltilmeli.

- **test_token_coverage_uses_and_operator**: **Test outdated (test hatası).** Test `nested["query"]["bool"]["must"]` path'ini bekliyor, fakat `TOKEN_COVERAGE` fonksiyonundaki nested query yapısı `{"match": {...}}` — yani `bool` wrapper'ı yok. `KeyError 'bool'` bu yüzden oluşuyor. Kaynak kodun yapısı doğru; test yanlış path varsayımı yapıyor.

- **test_fuzzy_phrase_has_slop**: **Test outdated (test hatası).** `FUZZY_PHRASE` fonksiyonundaki nested query `{"match_phrase": {...}}` şeklinde — `bool` wrapper'ı yok. Test `nested["query"]["bool"]["must"]` path'ini bekliyor. Kaynak kodun yapısı doğru; test path'i güncellenmelidir.

- **test_ngram_match_queries_ngram_field**: **Test outdated (test hatası) + field path assertion yanlış.** İki sorun: (1) `nested["query"]["bool"]["must"]` path hatası — nested query `bool` wrapper içermiyor. (2) Test `variations_stripped.ngram` alanını arıyor, kaynak kod ise `variations_stripped.name.ngram` kullanıyor. Test path hem structürel hem semantic olarak yanlış.

- **test_suffix_fuzzy_must_queries_variations_stripped**: **Test outdated (test hatası).** `SUFFIX_FUZZY` fonksiyonundaki nested query `{"match_phrase": {...}}` şeklinde — `bool` wrapper yok. Test `nested["query"]["bool"]["must"]` bekliyor. Kaynak yapısı mantıklı; test güncellenmeli.

---

## Bulgular

---

## [HIGH] es_queries.py:93 — CANONICAL_EXACT token_count field path yanlış

**Kanıt:**
```python
"filter": (
    [{"term": {"variations.name.token_count": expected_count}}]
    if expected_count > 0 else []
)
```

**Neden problem:** ES mapping'de token_count sub-field `variations.name` altında değil, `variations` object altında ayrı bir keyword field olarak tanımlanması beklenir (örn. `variations.token_count`). `variations.name.token_count` path'i çalışmaz; ES bu terimi tanımaz ve filtre sessizce sıfır sonuç döndürür veya query tamamen başarısız olur. Bu, CANONICAL_EXACT stage'in token eşitliği garantisini fiilen devre dışı bırakır ve yanlış eşleşmelere kapı açar.

**Önerilen düzeltme:** ES index mapping'i kontrol et ve token_count field path'ini doğru değerle güncelle. Muhtemelen `{"term": {"variations.token_count": expected_count}}` olmalı. `test_canonical_exact_structure` testini de aynı şekilde güncelle.

**CLAUDE.md ihlali:** —

**Test edilebilir mi?** Evet — `test_canonical_exact_structure` zaten bu senaryoyu test ediyor ve field path düzeltildikten sonra geçmesi beklenir.

---

## [MEDIUM] es_queries.py:152-192 — `SUFFIX_FUZZY` should clause `minimum_should_match` eksik

**Kanıt:**
```python
"should": [
    {
        "match": {
            "variations_suffix": {
                "query": name,
                "fuzziness": "AUTO:4,7",
                "operator": "or",
            }
        }
    }
],
```

**Neden problem:** ES'de bir `bool` query içinde `should` clauseları, `must` mevcutken varsayılan olarak isteğe bağlıdır (minimum_should_match=0). Bu, suffix fuzzy clause'unun yalnızca bir skor booster olarak çalıştığı anlamına gelir — suffix hiç eşleşmese bile bir belge döndürülebilir. Stage'in tasarım amacına göre suffix fuzzy eşleşmesinin en az kısmi bir katkısı olması gerekiyorsa, `minimum_should_match: 1` eklenmesi gerekir.

**Önerilen düzeltme:** Query body'e `"minimum_should_match": 1` ekle; böylece should clause en az bir kez eşleşmek zorunda kalır. Alternatif olarak suffix'i de `must` clauseuna taşı.

**CLAUDE.md ihlali:** —

**Test edilebilir mi?** Evet — mevcut `test_suffix_fuzzy_structure` testi should clause'un varlığını kontrol ediyor fakat minimum_should_match'i kontrol etmiyor; yeni bir assertion eklenebilir.

---

## [MEDIUM] es_queries.py:64-149 — CANONICAL_EXACT ve STRIPPED_EXACT arasında copy-paste tekrarı

**Kanıt:**
```python
# CANONICAL_EXACT (satır 64-105) ve STRIPPED_EXACT (satır 108-149)
# Tek fark: "variations" vs "variations_stripped" ve _get_analyzer vs _get_stripped_analyzer
```

**Neden problem:** İki fonksiyon neredeyse özdeş query şablonunu paylaşıyor; yalnızca nested path, field adları ve analyzer seçimi farklı. İleride query yapısında bir değişiklik (örn. ek filtre) yapıldığında her iki fonksiyonun da aynı anda güncellenmesi gerekecek. Bu DRY ihlalidir ve tutarsızlık riskini artırır.

**Önerilen düzeltme:** Ortak mantığı `_build_exact_nested_query(name, country, path_prefix, analyzer_fn)` gibi bir private yardımcı fonksiyona çıkar; `CANONICAL_EXACT` ve `STRIPPED_EXACT` bu yardımcıyı çağırsın.

**CLAUDE.md ihlali:** —

**Test edilebilir mi?** Evet — mevcut testler yeniden yapılanma sonrasında aynı şekilde çalışmalı (davranış değişmez).

---

## [MEDIUM] es_queries.py — `_strip_address_python` fonksiyonu eksik (missing helper)

**Kanıt:**
```python
# tests/test_address_anchoring.py:9
from es_queries import _strip_address_python

# scratch/test_address_strip.py:10
from es_queries import _strip_address_python
```

**Neden problem:** `_strip_address_python` fonksiyonu `es_queries.py` içinde tanımlı değil. CLAUDE.md §4'te belirtilen "Sprint 2 kapsamında Python helper fonksiyonlar kaldırıldı" legacy pattern'ına uygun, ancak test dosyaları (hem `tests/` hem `scratch/`) hâlâ bu fonksiyonu import etmeye çalışıyor. Bu, `test_address_anchoring.py` için pytest collection hatasına yol açıyor ve adres soyma mantığını test etmeyi tamamen imkânsız kılıyor.

**Önerilen düzeltme:** Ya `_strip_address_python`'ı `es_queries.py`'e yeniden ekle (eğer adres soyma mantığı hâlâ gerekli ise), ya da `test_address_anchoring.py` ve `scratch/test_address_strip.py`'yi sil/güncelle. Eğer fonksiyon ES ingest pipeline'a taşındıysa, testleri de ES analyze API üzerinden yazılmış entegrasyon testleriyle değiştir.

**CLAUDE.md ihlali:** CLAUDE.md §4 (Bilinen Kısıtlamalar) bu pattern'ı tanımlıyor, ancak çözüm hâlâ uygulanmamış.

**Test edilebilir mi?** Evet — `pytest tests/test_address_anchoring.py` şu anda `ImportError` ile collection aşamasında çöküyor; fonksiyon eklendiğinde veya test kaldırıldığında hata gider.

---

## [LOW] es_queries.py:259-286 — NGRAM_MATCH `_get_analyzer` değil, sabit ngram field kullanıyor (analyzer parametresi yok)

**Kanıt:**
```python
def NGRAM_MATCH(name: str, country: str, **kwargs) -> dict:
    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "variations_stripped",
                            "query": {
                                "match": {
                                    "variations_stripped.name.ngram": {
                                        "query": name,
                                        "minimum_should_match": "75%",
                                    }
                                }
                            }
                        }
                    }
                ],
```

**Neden problem:** `NGRAM_MATCH` ülkeye özel analyzer kullanmıyor — bu büyük ölçüde bilinçli bir tasarım (ngram field index-time analyzer kullanıyor), ancak `country` parametresi almasına rağmen içeride hiç kullanılmıyor. Bu, gelecekte ülkeye özel ngram analyzer eklenmek istendiğinde fark edilmesi zor bir silinmiş connection oluşturuyor.

**Önerilen düzeltme:** Eğer ngram field'ın search analyzer'ı ülkeye bağımlı değilse, bu kasıtlı tasarım olduğunu açıklayan bir kod içi yorum ekle. Değilse, `_get_analyzer(country)` ile sorgu analyzer'ını parametre olarak ver.

**CLAUDE.md ihlali:** —

**Test edilebilir mi?** Evet — mevcut `test_ngram_match_queries_ngram_field` testi bu konuya değiniyor (ancak testin kendisi de güncellenmeli).
