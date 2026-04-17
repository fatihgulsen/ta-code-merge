# Firma Eşleştirme Sistemi — AI Development Guide (CLAUDE.md)

This project is an advanced, self-learning entity resolution engine backed by Elasticsearch & PostgreSQL. It deduplicates and merges messy company names globally under a single "Master Record".

**Sprint 2 Architecture Update:** The project has heavily migrated logic *from Python to Elasticsearch Ingest Pipelines and Queries*. The `RapidFuzz` logic was replaced by strict ES-based `match`, `match_phrase`, and strict python post-validation logic (`symmetric_token_coverage` etc.) to guarantee accuracy.

## Mimari (Architecture Workflow)

```mermaid
graph LR
    PG[PostgreSQL (raw)] --> Python[main_processor.py: Batched Read & Dedup]
    Python --> Msearch[es_queries.py: msearch by Stage]
    Msearch --> ES_Query[Elasticsearch]
    ES_Query --> Validate[main_processor.py: Post-Validation]
    Validate --> UpdateES[main_processor.update_es_variations]
    UpdateES --> UpdatePG[PG match_stages_log & p7_firms_v2]
```

## Aşamalı Eşleştirme (Row-by-Row & Msearch)

Sistem karmaşayı ve veri tekrarını önlemek için (aynı batch içinde gelen aynı firmaların ayrı UUID'ler almasını engellemek için) **TEK TEK (Row-by-Row)** çalışır.
Her bir kayıt için tüm stage (aşama) sorguları tek bir ES `msearch` paketi olarak gönderilir. İlk başarılı olan stage'den (min_score geçen) sonuç alınır.

| Aşama Puanı | Stage Ismi | Karakteristik (ES Sorgusu & Doğrulama) |
|---|---|---|
| 1 | TAX_EXACT | Deterministik. `tax_number` uyuşuyorsa 100 verilir, Post-verify yapılmaz. |
| 2 | CANONICAL_EXACT | ES `match_phrase`. İki metin tamamen aynı sırada eşleşmeli. |
| 3 | STRIPPED_EXACT | Suffix'ler temizlenmiş (*stripped*) modelde `match_phrase`. |
| 4 | TOKEN_COVERAGE | Sadece `match`. Kelime sırasında serbestlik vardır. Eşleşme `post_verify()`'da **Symmetric Token Coverage**'dan geçer. |
| >4 | NEW_MASTER | Hiçbir aşamada threshold'u geçemiyorsa yeni Unique ID üretilip ES'e kaydedilir. |

*Fuzzy sorguları (`SUFFİX_FUZZY` vb.) var ancak Python post-verify `strict_name_match` fonksiyonunu çağırarak ana ismin BİREBİR aynı olup olmadığını kanıtlamanızı ister.*

## Önemli Geliştirme Kuralları (Sprint 2 Mantrası)

> [!WARNING]
> Python tarafında (artık silinen `matcher_logic.py`'deki gibi) Levenshtein veya RapidFuzz çalıştırmak **YASAKTIR.** Fuzzy yeteneğini kısıtladık. 

1. **COUNTRY CODE IS A HARD FILTER**: Arama, indexleme, doğrulama dahil her şey `country_code` bazlı `_routing` yeteneğiyle yapılır. ASLA farklı ülke kodlu veriler cross-match olamaz.
2. **First Meaningful Token Limit**: Şirket isminin ilk anlamlı kelimesi EŞİT olmak ZORUNDADIR. (`_first_meaningful_token`). Örneğin: `Kay Bee` ile `Bee Kay` benzer görünse de post-verify'da reddedilir!
3. **Ingest Pipelines (`es_ingest.py`)**: Elasticsearch, veriyi kaydetmeden hemen önce Painless script çalıştırır. `variations_unidecode`, `variations_stripped` oluşturulması gibi operasyonları Python üzerinde döngüyle yapmak yerine Ingest pipeline sağlar.
4. **Synonym JSONs Are Immutable**: `synonyms_data/` altındaki json'lara dokunma, onlar kaynak veriler. Düzeltme eklemek gerekiyorsa `config.py` `SUFFIX_TYPO_MAP` eklenebilir.

## Geliştirici Kılavuzu: Dosya Yapısı

| Modül | Sorumluluk |
| --- | --- |
| `main_processor.py` | Ana Orkestrasyon! Batch Okuma, Dedup, ES Msearch çağrısı, Post-Verify |
| `es_queries.py` | Stagelere bağlı Query DSL JSON builder'ları burada |
| `es_ingest.py` | Elasticsearch Ingest Pipeline Scripts |
| `synonym_loader.py` | JSON country data ile suffix, article temizleme ve canonicalize etme |
| `config.py` | Limitler, pipeline isimleri, Veritabanı configleri |

## Temel Çalıştırma
```bash
python es_manager.py       # ES Pipeline ve Index Refresh.
python main_processor.py   # Eşleştirmeyi çalıştır (Tüm stage'leri döner).
```
