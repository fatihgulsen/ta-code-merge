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

from config import SUFFIX_TYPO_MAP
from synonym_loader import get_company_type_tokens, get_all_country_codes

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
    """
    Painless script: variations array'indeki her name için light_clean uygular.
    Temizlenmiş name'leri variations'a yazar.

    NOT: Painless "..." string'lerinde sadece \\\\ ve \\" escape geçerli.
    Unicode karakterler için /regex/ literal kullanılır.
    """
    tokens = get_company_type_tokens(country_code)
    known = sorted(t for t in tokens if t.isalpha() and " " not in t and len(t) <= 6)
    known_literal = ", ".join(_pl_str(t) for t in known)

    # SUFFIX_TYPO_MAP'i Painless map literal'e dönüştür
    typo_entries = ", ".join(
        f"{_pl_str(k)}: {_pl_str(v)}" for k, v in SUFFIX_TYPO_MAP.items()
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
        f"  def knownSuffixes = [{known_literal}];",
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


def _build_stripped_script(country_code: str) -> str:
    """
    Painless script: variations'tan generic token'ları kaldırarak
    variations_stripped array'ini oluşturur.
    """
    # Generic token'ları Painless list literal olarak oluştur
    # Boşluk içeren çok-kelimeli token'lar split sonrası hiç eşleşmez — filtrele
    tokens = [t for t in get_company_type_tokens(country_code) if " " not in t]
    tokens_literal = ", ".join(_pl_str(t) for t in tokens)

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
    # Boşluk içeren çok-kelimeli token'lar split sonrası eşleşmez — filtrele ve escape et
    tokens_literal = ", ".join(_pl_str(t) for t in generic_tokens if " " not in t)

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


def build_pipeline_body(country_code: str) -> dict:
    """Ingest pipeline tanımını oluşturur."""
    company_type_tokens = list(get_company_type_tokens(country_code))
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
                    "source": _build_suffix_script(company_type_tokens),
                }
            },
        ],
    }


def register_pipeline(es: Elasticsearch, country_code: str) -> None:
    """Tek ülke için ingest pipeline oluşturur/günceller."""
    name = pipeline_name(country_code)
    body = build_pipeline_body(country_code)
    es.ingest.put_pipeline(id=name, body=body)
    logger.info(f"Ingest pipeline '{name}' kaydedildi.")


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
        logger.info(f"Ingest pipeline '{name}' silindi.")
    except Exception:
        logger.warning(f"Pipeline '{name}' silinemedi (muhtemelen mevcut değil).")


def delete_all_pipelines(es: Elasticsearch) -> None:
    """Tüm ülke pipeline'larını siler."""
    for cc in get_all_country_codes():
        delete_pipeline(es, cc)


# ============================================================================
if __name__ == "__main__":
    from es_manager import get_es_client

    es = get_es_client()
    register_all_pipelines(es)
    print("Tüm ülke pipeline'ları başarıyla kaydedildi.")
