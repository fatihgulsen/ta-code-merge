"""Elasticsearch ingest pipeline yönetimi.

İndeksleme anında firma isimlerini light_clean ile temizler. Temizlik mantığı
Painless script'lerine devredilmiştir — Python tarafında fuzzy/string-işlem yoktur.
NOT: stripped/suffix SİLME processor'ları kaldırıldı (Plan 4).
"""

import logging

from elasticsearch import Elasticsearch

from core.synonym_loader import get_all_country_codes

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



def build_pipeline_body(country_code: str) -> dict:
    """Ülkeye özgü ingest pipeline tanım sözlüğünü oluşturur (yalnız light_clean).

    NOT: stripped/suffix SİLME processor'ları kaldırıldı (Plan 4). Eşleşme artık
    synonym-kanonik tam form (variations[].name) üzerinden; token silinmez.
    """
    return {
        "description": f"Firma ismi temizleme pipeline'i ({country_code.upper()})",
        "processors": [
            {
                "script": {
                    "description": f"light_clean for {country_code.upper()}",
                    "source": _build_clean_script(country_code),
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
    from es.manager import get_es_client

    es = get_es_client()
    register_all_pipelines(es)
    print("Tüm ülke pipeline'ları başarıyla kaydedildi.")
