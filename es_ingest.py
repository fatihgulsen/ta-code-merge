"""Elasticsearch ingest pipeline yönetimi.

İndeksleme anında firma isimlerini temizler ve türev alanları hesaplar
(variations_stripped, variations_suffix). Temizlik mantığı Painless
script'lerine devredilmiştir — Python tarafında fuzzy/string-işlem yoktur.
"""

import logging

from elasticsearch import Elasticsearch

from synonym_loader import (
    get_all_country_codes,
    get_article_stopwords,
    get_geo_stopword_tokens,
    get_legal_suffix_tokens,
)

logger = logging.getLogger(__name__)


def _pl(token: str) -> str:
    """Token'ı Painless tek-tırnaklı string literal için escape eder.

    Painless'te tek-tırnak string içinde:
      - '  →  \'
      - \\  →  \\\\
    Boşluk içeren (çok-kelimeli) token'lar eşleşmeye katkı sağlamaz —
    güvenle bırakılabilir, ancak escape yine gerekli.
    """
    return token.replace("\\", "\\\\").replace("'", "\\'")


def _pl_str(token: str) -> str:
    """Escape edilmiş token'ı tek-tırnaklı Painless literal olarak döner: 'value'"""
    return f"'{_pl(token)}'"


def pipeline_name(country_code: str) -> str:
    """Ülkeye özgü ingest pipeline ismini döner."""
    return f"company_name_{country_code.lower()}"


def _build_clean_script(country_code: str) -> str:
    """Painless script: variations array'indeki her name için light_clean uygular.

    Temizlenmiş name'leri variations'a yazar.
    Painless'te /regex/ literal kullanılır; f-string yerine raw string tercih edilir.
    """
    script_parts = [
        # Null kontrolü
        "if (ctx.variations == null) { return; }",
        "List cleanedVariations = new ArrayList();",
        # Ana döngü
        "for (int vi = 0; vi < ctx.variations.size(); vi++) {",
        "  def varItem = ctx.variations[vi];",
        "  String text = varItem instanceof Map ? varItem.name : varItem;",
        "  if (text == null || text.trim().length() == 0) { continue; }",
        # 1. Lowercase
        "  text = text.toLowerCase();",
        # 2. Zero-width karakter temizligi (regex literal ile)
        r"  text = /[\u200b\u200c\u200d\ufeff\u00ad]/.matcher(text).replaceAll('');",
        # 3. Label temizligi
        r"  text = /^(email|attn|tel|phone|web|site)\s*:/.matcher(text).replaceAll('');",
        r"  text = /\bc\/o\b/.matcher(text).replaceAll('');",
        r"  text = /\battn\b/.matcher(text).replaceAll('');",
        r"  text = /\bcare of\b/.matcher(text).replaceAll('');",
        r"  text = /\bto\s+(the\s+)?order\s+of\b/.matcher(text).replaceAll('');",
        # 4. Ampersand normalizasyonu
        r"  text = /\s*&\s*/.matcher(text).replaceAll(' and ');",
        # 5. Ozel karakter temizligi
        r"  text = /[^\w\s&.\-]/.matcher(text).replaceAll(' ');",
        # 6. Cift bosluk temizligi
        r"  text = /\s+/.matcher(text).replaceAll(' ').trim();",
        # 7. Ardisik-tekrar token dedup: 'RICARD RICARD' -> 'RICARD'.
        #    Kaynak-veri tekrarı coverage/skoru şişirip over-merge üretiyor; yalnızca ardışık tekrar elenir.
        r"  def dedupToks = / /.split(text);",
        "  StringBuilder dsb = new StringBuilder();",
        "  String prevTok = null;",
        "  for (int di = 0; di < dedupToks.length; di++) {",
        "    String dt = dedupToks[di];",
        "    if (dt.length() == 0) { continue; }",
        "    if (prevTok == null || !prevTok.equals(dt)) {",
        "      if (dsb.length() > 0) { dsb.append(' '); }",
        "      dsb.append(dt);",
        "      prevTok = dt;",
        "    }",
        "  }",
        "  text = dsb.toString().trim();",
        # Sonuca ekle
        "  if (text.length() > 0) {",
        "    boolean exists = false;",
        "    for (v in cleanedVariations) { if (v.name == text) { exists = true; break; } }",
        "    if (!exists) { cleanedVariations.add(['name': text]); }",
        "  }",
        "}",
        "ctx.variations = cleanedVariations;",
    ]

    return "\n".join(script_parts)


def _build_stripped_script(country_code: str) -> str:
    """Painless script: variations'tan generic token'ları kaldırarak variations_stripped'ı oluşturur.

    legal_suffixes + articles + geo token'ları (global liste) çıkarılır;
    business_sectors korunur. Geo token'ları global listeden alınır — search
    analyzer'daki geo_stopwords_global ile simetri için (bkz. docs/audit/).
    """
    suffix_tokens = [t for t in get_legal_suffix_tokens(country_code) if " " not in t]
    article_tokens = [t for t in get_article_stopwords(country_code) if " " not in t]
    geo_tokens = [t for t in get_geo_stopword_tokens() if " " not in t]
    all_tokens = list(
        dict.fromkeys(suffix_tokens + article_tokens + geo_tokens)
    )  # dedup, order preserved
    tokens_literal = ", ".join(_pl_str(t) for t in all_tokens)

    script_parts = [
        "List genericTokens = [" + tokens_literal + "];",
        "Set genericSet = new HashSet(genericTokens);",
        "if (ctx.variations == null) { return; }",
        "List stripped = new ArrayList();",
        "for (int i = 0; i < ctx.variations.size(); i++) {",
        "  def varItem = ctx.variations[i];",
        "  String text = varItem instanceof Map ? varItem.name : varItem;",
        r"  def tokens = / /.split(text);",
        "  StringBuilder sb = new StringBuilder();",
        "  for (int t = 0; t < tokens.length; t++) {",
        "    String token = /[.]/.matcher(tokens[t]).replaceAll('').trim();",
        "    if (token.length() > 0 && !genericSet.contains(token)) {",
        "      if (sb.length() > 0) { sb.append(' '); }",
        "      sb.append(token);",
        "    }",
        "  }",
        "  String result = sb.toString().trim();",
        "  if (result.length() > 0) {",
        "    boolean exists = false;",
        "    for (v in stripped) { if (v.name == result) { exists = true; break; } }",
        "    if (!exists) { stripped.add(['name': result]); }",
        "  }",
        "}",
        "ctx.variations_stripped = stripped;",
    ]

    return "\n".join(script_parts)


def _build_suffix_script(generic_tokens: list[str]) -> str:
    """
    Painless script: variations'tan sadece generic (suffix) token'ları toplayarak
    variations_suffix array'ini oluşturur. _build_stripped_script() tersine —
    generic SET'te OLAN token'ları tutar, position-independent (sorted, deduped).
    """
    # Boşluk içeren çok-kelimeli token'lar split sonrası eşleşmez — filtrele ve escape et
    tokens_literal = ", ".join(_pl_str(t) for t in generic_tokens if " " not in t)

    script_parts = [
        "List genericTokens = [" + tokens_literal + "];",
        "Set genericSet = new HashSet(genericTokens);",
        "if (ctx.variations == null) { return; }",
        "List suffixes = new ArrayList();",
        "for (int i = 0; i < ctx.variations.size(); i++) {",
        "  def varItem = ctx.variations[i];",
        "  String text = varItem instanceof Map ? varItem.name : varItem;",
        r"  def tokens = / /.split(text);",
        "  List suffixTokens = new ArrayList();",
        "  for (int t = 0; t < tokens.length; t++) {",
        "    String token = /[.]/.matcher(tokens[t]).replaceAll('').trim();",
        "    if (token.length() > 0 && genericSet.contains(token)) {",
        "      suffixTokens.add(token);",
        "    }",
        "  }",
        "  Collections.sort(suffixTokens);",
        "  StringBuilder sb = new StringBuilder();",
        "  for (int s = 0; s < suffixTokens.size(); s++) {",
        "    if (s > 0) { sb.append(' '); }",
        "    sb.append(suffixTokens[s]);",
        "  }",
        "  String result = sb.toString().trim();",
        "  if (result.length() > 0 && !suffixes.contains(result)) {",
        "    suffixes.add(result);",
        "  }",
        "}",
        "ctx.variations_suffix = suffixes;",
    ]

    return "\n".join(script_parts)


def build_pipeline_body(country_code: str) -> dict:
    """Ülkeye özgü ingest pipeline tanım sözlüğünü oluşturur."""
    legal_suffix_tokens = list(get_legal_suffix_tokens(country_code))
    return {
        "description": f"Firma ismi temizleme ve normalizasyon pipeline'i ({country_code.upper()})",
        "processors": [
            {
                "script": {
                    "description": f"light_clean for {country_code.upper()}",
                    "source": _build_clean_script(country_code),
                }
            },
            {
                "script": {
                    "description": f"stripped_form for {country_code.upper()}",
                    "source": _build_stripped_script(country_code),
                }
            },
            {
                "script": {
                    "description": f"suffix_form for {country_code.upper()}",
                    "source": _build_suffix_script(legal_suffix_tokens),
                }
            },
        ],
    }


def register_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke için ingest pipeline oluşturur/günceller."""
    name = pipeline_name(country_code)
    body = build_pipeline_body(country_code)
    es.ingest.put_pipeline(id=name, body=body)
    logger.debug(f"Ingest pipeline '{name}' kaydedildi.")


def register_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülkeler için ingest pipeline'ları oluşturur/günceller."""
    codes = get_all_country_codes()
    for cc in codes:
        register_pipeline(es, cc)
    logger.info(f"Toplam {len(codes)} ülke pipeline'ı kaydedildi.")


def delete_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke pipeline'ını siler."""
    name = pipeline_name(country_code)
    try:
        es.ingest.delete_pipeline(id=name)
        logger.debug(f"Ingest pipeline '{name}' silindi.")
    except Exception:
        logger.warning(f"Pipeline '{name}' silinemedi (muhtemelen mevcut değil).")


def delete_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülke pipeline'larını siler."""
    for cc in get_all_country_codes():
        delete_pipeline(es, cc)


if __name__ == "__main__":
    from es_manager import get_es_client

    es = get_es_client()
    register_all_pipelines(es)
    print("Tüm ülke pipeline'ları başarıyla kaydedildi.")
