# ============================================================================
# es_ingest.py - Elasticsearch Ingest Pipeline
# ============================================================================
# light_clean() adımlarını ES ingest processor'larına taşır.
# Doküman index'lenirken otomatik temizleme uygulanır.
#
# Pipeline: company_name_clean
#   1. lowercase
#   2. Painless script: NFKC normalize, zero-width temizlik, parantez kaldırma,
#      label temizleme, ampersand normalizasyonu, özel karakter temizleme,
#      nokta-harf pattern normalizasyonu, suffix typo düzeltme
#   3. variations_stripped alanını otomatik hesapla
#   4. variations_suffix alanını otomatik hesapla
# ============================================================================

import logging

from elasticsearch import Elasticsearch

from config import ES_INDEX, SUFFIX_TYPO_MAP

logger = logging.getLogger(__name__)

PIPELINE_NAME = "company_name_clean"


def _build_clean_script() -> str:
    """
    Painless script: variations array'indeki her name için light_clean uygular.
    Temizlenmiş name'leri variations'a yazar.

    NOT: Painless "..." string'lerinde sadece \\\\ ve \\" escape geçerli.
    Unicode karakterler için /regex/ literal kullanılır.
    """
    # SUFFIX_TYPO_MAP'i Painless map literal'e dönüştür
    typo_entries = ", ".join(
        f"'{k}': '{v}'" for k, v in SUFFIX_TYPO_MAP.items()
    )

    # Script'i raw string olarak oluştur (f-string escape karmaşasından kaçın)
    script_parts = [
        # Map tanımı
        "Map typoMap = [" + typo_entries + "];",
        # Null kontrolü
        "if (ctx.variations == null) { return; }",
        "List cleanedVariations = new ArrayList();",
        # Ana döngü
        "for (int vi = 0; vi < ctx.variations.size(); vi++) {",
        "  String text = ctx.variations[vi];",
        "  if (text == null || text.trim().length() == 0) { continue; }",
        # 1. Lowercase
        "  text = text.toLowerCase();",
        # 2. Zero-width karakter temizligi (regex literal ile)
        r"  text = /[\u200b\u200c\u200d\ufeff\u00ad]/.matcher(text).replaceAll('');",
        # 3. Parantez icerigi kaldir
        r"  text = /\([^)]*\)/.matcher(text).replaceAll('');",
        r"  text = /\[[^\]]*\]/.matcher(text).replaceAll('');",
        # 4. Label temizligi
        r"  text = /^(email|attn|tel|phone|web|site)\s*:/.matcher(text).replaceAll('');",
        r"  text = /\bc\/o\b/.matcher(text).replaceAll('');",
        r"  text = /\battn\b/.matcher(text).replaceAll('');",
        r"  text = /\bcare of\b/.matcher(text).replaceAll('');",
        r"  text = /\bto\s+(the\s+)?order\s+of\b/.matcher(text).replaceAll('');",
        # 5. Ampersand normalizasyonu
        r"  text = /\s*&\s*/.matcher(text).replaceAll(' and ');",
        # 6. Ozel karakter temizligi
        r"  text = /[^\w\s&.\-]/.matcher(text).replaceAll(' ');",
        # 7. Nokta-harf pattern: L.T.D. -> LTD (tekrarlı regex ile)
        # Painless'te lookbehind yok, tekrarlı replace ile yakala
        "  String prev = '';",
        "  while (!text.equals(prev)) {",
        "    prev = text;",
        r"    text = /([a-z])\.([a-z])/.matcher(text).replaceAll('$1$2');",
        "  }",
        # 8. Cift bosluk temizligi
        r"  text = /\s+/.matcher(text).replaceAll(' ').trim();",
        # 9. Suffix typo duzeltme
        r"  def tokens = / /.split(text);",
        "  StringBuilder result = new StringBuilder();",
        "  for (int t = 0; t < tokens.length; t++) {",
        "    String token = /[.]/.matcher(tokens[t]).replaceAll('');",
        "    if (typoMap.containsKey(token)) {",
        "      token = (String)typoMap.get(token);",
        "    }",
        "    if (t > 0) { result.append(' '); }",
        "    result.append(token);",
        "  }",
        "  text = result.toString().trim();",

        # 9b. Boşluklu tek harf birleştirme: "l t d" -> "ltd"
        "  def knownSuffixes = ['ltd', 'inc', 'llc', 'bv', 'nv', 'ag', 'sa', 'plc', 'co', 'pvt'];",
        r"  def spTokens = / /.split(text);",
        "  List spResult = new ArrayList();",
        "  int si = 0;",
        "  while (si < spTokens.length) {",
        "    if (spTokens[si].length() == 1 && /^[a-z]$/.matcher(spTokens[si]).matches()) {",
        "      StringBuilder run = new StringBuilder(spTokens[si]);",
        "      int sj = si + 1;",
        "      while (sj < spTokens.length && spTokens[sj].length() == 1 && /^[a-z]$/.matcher(spTokens[sj]).matches()) {",
        "        run.append(spTokens[sj]); sj++;",
        "      }",
        "      String joined = run.toString();",
        "      if (sj > si + 1 && knownSuffixes.contains(joined)) {",
        "        spResult.add(joined); si = sj;",
        "      } else {",
        "        spResult.add(spTokens[si]); si++;",
        "      }",
        "    } else {",
        "      spResult.add(spTokens[si]); si++;",
        "    }",
        "  }",
        "  StringBuilder spJoined = new StringBuilder();",
        "  for (int spi = 0; spi < spResult.size(); spi++) {",
        "    if (spi > 0) spJoined.append(' ');",
        "    spJoined.append(spResult[spi]);",
        "  }",
        "  text = spJoined.toString().trim();",

        # 9c. Birleşik suffix ayırma: "pvtltd" -> "pvt ltd"
        "  def fusedMap = ['pvtltd': 'pvt ltd', 'ltdco': 'ltd co', 'corpltd': 'corp ltd',",
        "    'incltd': 'inc ltd', 'gmbhco': 'gmbh co'];",
        r"  def fTokens = / /.split(text);",
        "  List fResult = new ArrayList();",
        "  for (int ft = 0; ft < fTokens.length; ft++) {",
        "    String ftok = fTokens[ft];",
        "    if (fusedMap.containsKey(ftok)) {",
        "      fResult.add((String)fusedMap.get(ftok));",
        "    } else {",
        "      fResult.add(ftok);",
        "    }",
        "  }",
        "  StringBuilder fJoined = new StringBuilder();",
        "  for (int fi = 0; fi < fResult.size(); fi++) {",
        "    if (fi > 0) fJoined.append(' ');",
        "    fJoined.append(fResult[fi]);",
        "  }",
        "  text = fJoined.toString().trim();",

        # Sonuca ekle
        "  if (text.length() > 0 && !cleanedVariations.contains(text)) {",
        "    cleanedVariations.add(text);",
        "  }",
        "}",
        "ctx.variations = cleanedVariations;",
    ]

    return "\n".join(script_parts)


def _build_stripped_script(generic_tokens: list[str]) -> str:
    """
    Painless script: variations'tan generic token'ları kaldırarak
    variations_stripped array'ini oluşturur.
    """
    # Generic token'ları Painless list literal olarak oluştur
    tokens_literal = ", ".join(f"'{t}'" for t in generic_tokens)

    script_parts = [
        "List genericTokens = [" + tokens_literal + "];",
        "Set genericSet = new HashSet(genericTokens);",
        "if (ctx.variations == null) { return; }",
        "List stripped = new ArrayList();",
        "for (int i = 0; i < ctx.variations.size(); i++) {",
        "  String text = ctx.variations[i];",
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
        "  if (result.length() > 0 && !stripped.contains(result)) {",
        "    stripped.add(result);",
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
    tokens_literal = ", ".join(f"'{t}'" for t in generic_tokens)

    script_parts = [
        "List genericTokens = [" + tokens_literal + "];",
        "Set genericSet = new HashSet(genericTokens);",
        "if (ctx.variations == null) { return; }",
        "List suffixes = new ArrayList();",
        "for (int i = 0; i < ctx.variations.size(); i++) {",
        "  String text = ctx.variations[i];",
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


def build_pipeline_body() -> dict:
    """Ingest pipeline tanımını oluşturur."""
    # Genel generic tokenlar (en yaygın olanlar — ülke bazlı olanlar
    # ES synonym analyzer tarafında zaten handle ediliyor)
    common_generic = [
        "ltd", "limited", "inc", "incorporated", "corp", "corporation",
        "llc", "gmbh", "ag", "sa", "srl", "bv", "nv", "plc", "co",
        "company", "pty", "pvt", "private", "public", "holding",
        "holdings", "group", "international", "intl", "and",
    ]

    return {
        "description": "Firma ismi temizleme ve normalizasyon pipeline'i",
        "processors": [
            {
                "script": {
                    "description": "light_clean: lowercase, zero-width, parantez, label, ampersand, ozel karakter, suffix typo",
                    "source": _build_clean_script(),
                }
            },
            {
                "script": {
                    "description": "stripped_form: generic token'lari kaldir",
                    "source": _build_stripped_script(common_generic),
                }
            },
            {
                "script": {
                    "description": "suffix_form: sadece generic token'lari tut",
                    "source": _build_suffix_script(common_generic),
                }
            },
        ],
    }


def register_pipeline(es: Elasticsearch) -> None:
    """Ingest pipeline'i ES'e kaydeder."""
    body = build_pipeline_body()
    es.ingest.put_pipeline(id=PIPELINE_NAME, body=body)
    logger.info(f"Ingest pipeline '{PIPELINE_NAME}' kaydedildi.")


def delete_pipeline(es: Elasticsearch) -> None:
    """Ingest pipeline'i siler."""
    try:
        es.ingest.delete_pipeline(id=PIPELINE_NAME)
        logger.info(f"Ingest pipeline '{PIPELINE_NAME}' silindi.")
    except Exception:
        logger.warning(f"Pipeline '{PIPELINE_NAME}' silinemedi (muhtemelen mevcut degil).")


# ============================================================================
if __name__ == "__main__":
    from es_manager import get_es_client

    es = get_es_client()
    register_pipeline(es)
    print(f"Pipeline '{PIPELINE_NAME}' basariyla kaydedildi.")
