# Modül-bazlı Audit + TDD Düzeltme Döngüsü — Tasarım

**Tarih:** 2026-05-25
**Durum:** Onaylandı
**Kapsam (ilk iterasyon):** `main_processor.py` + `es_queries.py`

## Amaç

Firma eşleştirme sisteminde önceden bilinen somut bir bug listesi yok. Kod inceleyerek ve mevcut test suite'ini koşturarak şüpheli yerleri bulup, her bulgu için kullanıcı onayıyla TDD döngüsünde düzelteceğiz.

## Kapsam Dışı

- `debug_match.py` (CLAUDE.md §4'te kırık olarak işaretli, dokunulmayacak)
- `synonyms_data/*.json` (CLAUDE.md §1.4 — dokunulmaz)
- `.venv/`, üçüncü taraf paketler

## Audit + Düzeltme Döngüsü

Her hedef modül için aşağıdaki adımlar sırayla uygulanır:

### 1. Baseline
- `pytest -v` koş, sonucu kaydet (yeşil/kırmızı sayısı, hangi testler kırmızı).
- Kırmızı testler bulgu olarak otomatik kaydedilir (severity: HIGH veya üzeri).

### 2. Statik Audit
Modül baştan sona okunur. Her şüpheli yer için aşağıdaki formatta bulgu çıkarılır:

```
[SEVERITY] dosya:satır — kısa başlık
  Kanıt: <kod alıntısı / neden problem>
  Öneri: <kısa düzeltme yolu>
  CLAUDE.md ihlali (varsa): <hangi kural>
```

Severity tanımları (`~/.claude/rules/common/code-review.md` ile uyumlu):
- **CRITICAL** — güvenlik / veri kaybı / üretim down
- **HIGH** — bug, yanlış sonuç, performans regression
- **MEDIUM** — bakım problemi, code smell
- **LOW** — stil, küçük öneri

CLAUDE.md kurallarına özel dikkat:
- `country_code` katı filtre — herhangi bir kaçak yer var mı?
- Python'da fuzzy/Levenshtein kullanımı yasak
- Parametrik SQL (`%s`), raw string interpolation yok
- Batch hata yönetimi: tek satır hatası tüm batch'i durdurmamalı
- Synonym JSON dosyaları dokunulmaz

### 3. Onay Kapısı
Bulgu listesi kullanıcıya sunulur. Kullanıcı hangilerini düzelteceğimizi seçer (cherry-pick). Reddedilen bulgular bu iterasyonda ele alınmaz.

### 4. TDD Düzeltme (seçilen her bulgu için)
1. **RED:** Bug'ı yakalayan test yaz. `pytest` ile fail ettiğini doğrula.
2. **GREEN:** Minimum kodla testi geçir.
3. **REFACTOR:** Gerekirse temizle, tüm suite hâlâ yeşil olmalı.
4. **Doğrulama:** `pytest -v` tamamı yeşil.

### 5. Commit
- Conventional commit formatı: `fix:`, `refactor:`, `test:`.
- Bulgu başına bir commit, ya da yakın bulguları mantıklı şekilde grupla.
- Test commit'i fix commit'inden önce gelebilir (RED commit) ya da fix ile birlikte.

### 6. Sonraki Adım
- Aynı modülde kalan onaylanmış bulgulara dön, ya da bir sonraki modüle geç.
- Modül bitince kısa retro: "şu kadar bulgu, şu kadar düzeltildi, şunlar açık kaldı".

## Çıktılar

- **Bulgu raporları:** Chat içinde. Modül büyükse `docs/superpowers/audits/YYYY-MM-DD-<modul>.md` olarak da kaydedilebilir.
- **Yeni testler:** `tests/test_<modul>.py` içine (mevcut dosya yapısına uyumlu).
- **Düzeltme commit'leri:** `main` branch üzerinde küçük adımlarla.

## Test Stratejisi

- Mevcut `tests/test_main_processor.py` ve `tests/test_es_queries.py` örneklerinin pattern'ini izle.
- ES/PG dış bağımlılıkları için mock kullanımı tercih edilir; mevcut testler bunu nasıl yapıyorsa aynı yolu izle.
- Yeni testler hızlı (saniye altı) ve deterministik olmalı.

## Kurallar / Sınırlar

- **Onaysız refactor yok.** Bulduğum her şey rapor; kararı kullanıcı verir.
- **Synonym JSON dosyalarına dokunulmaz.** Düzeltme `config.py` (`SUFFIX_TYPO_MAP`) veya kod kuralı olarak yapılır.
- **Python'da fuzzy/Levenshtein eklenmez.** Çözüm ES tarafında (Query DSL fuzziness, painless rescore).
- **Coverage hedefi:** Yeni eklenen kod için %80+. Mevcut kodda zorlama yok.

## Riskler / Belirsizlikler

- pytest çalışırken canlı ES/PG bağımlılığı varsa baseline farklı çıkabilir. Mock yoksa testler skip edilebilir veya fixture eklemek gerekebilir — bu durumda kullanıcıya danışılacak.
- `debug_match.py` deki "kayıp helper" pattern'i (CLAUDE.md §4) başka modüllerde de olabilir; rastlanırsa bulgu olarak raporlanır.

## Tamamlanma Kriteri (ilk iterasyon)

- `main_processor.py` ve `es_queries.py` için audit raporları üretildi.
- Kullanıcı tarafından onaylanan her bulgu için RED test → GREEN fix → commit yapıldı.
- `pytest -v` sonucu, başlangıçtaki yeşillerin tamamı hâlâ yeşil + yeni eklenen testler yeşil.
- Kullanıcı bir sonraki modüle geçmeye ya da durmaya karar verdi.
