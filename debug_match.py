# ============================================================================
# debug_match.py - Firma Eslestirme Debug & Analiz Araci
# ============================================================================
# Iki firma ismini verip hangi asamada eslesip eslesmedigini gormenizi saglar.
#
# Kullanim:
#   python debug_match.py "FIRMA A" "FIRMA B" --country IN
#   python debug_match.py "ARVIND LTD" "ARVIND LIMITED" -c IN
#   python debug_match.py "C & C OVERSEAS" "C OVERSEAS" -c IN
#
# ES baglantisi olmadan (sadece Python tarafli kontrol):
#   python debug_match.py "FIRMA A" "FIRMA B" -c IN --offline
#
# ES'te bir firma aramak:
#   python debug_match.py "ARVIND" -c IN --search
#
# Toplu kalite raporu:
#   python debug_match.py --report
# ============================================================================

import argparse
import json
import sys

from main_processor import (
    _clean_labels,
    _tokenize,
    _symmetric_token_coverage,
    _post_verify,
    _SUFFIX_NORMALIZE,
    _ARTICLE_STOPWORDS,
    _COUNTRY_NAME_TOKENS,
)
from config import STAGES, ES_INDEX


def analyze_pair(name_a: str, name_b: str, country: str) -> dict:
    """Iki firma ismini tum asamalardan gecirip detayli rapor uretir."""

    result = {
        "input_a": name_a,
        "input_b": name_b,
        "country": country,
        "steps": {},
    }

    # 1. Label temizleme
    clean_a = _clean_labels(name_a)
    clean_b = _clean_labels(name_b)
    result["steps"]["1_clean_labels"] = {
        "a": clean_a,
        "b": clean_b,
        "changed_a": clean_a != name_a,
        "changed_b": clean_b != name_b,
    }

    # 2. Tokenize
    tokens_a = _tokenize(name_a, country)
    tokens_b = _tokenize(name_b, country)
    result["steps"]["2_tokenize"] = {
        "a": sorted(tokens_a),
        "b": sorted(tokens_b),
        "same": tokens_a == tokens_b,
    }

    # 3. Suffix / meaningful analizi
    suffix_tokens = set(_SUFFIX_NORMALIZE.values())
    meaningful_a = tokens_a - suffix_tokens
    meaningful_b = tokens_b - suffix_tokens
    result["steps"]["3_meaningful"] = {
        "a_suffix": sorted(tokens_a & suffix_tokens),
        "a_meaningful": sorted(meaningful_a),
        "b_suffix": sorted(tokens_b & suffix_tokens),
        "b_meaningful": sorted(meaningful_b),
        "min_meaningful": min(len(meaningful_a), len(meaningful_b)),
    }

    # 4. Coverage hesaplari
    coverage = _symmetric_token_coverage(tokens_a, tokens_b)
    meaningful_cov = _symmetric_token_coverage(meaningful_a, meaningful_b)

    # Word count
    from synonym_loader import get_company_type_tokens as _get_ctt
    _wc_stopwords = _ARTICLE_STOPWORDS | _get_ctt(country)

    def _word_count(name: str) -> int:
        return len([
            t for t in _clean_labels(name).lower().split()
            if t.rstrip('.,') not in _wc_stopwords
            and t.rstrip('.,')
            and t.rstrip('.,').isalnum()
        ])

    wc_a = _word_count(name_a)
    wc_b = _word_count(name_b)
    wc_ratio = min(wc_a, wc_b) / max(wc_a, wc_b) if max(wc_a, wc_b) > 0 else 0

    len_a = len(clean_a)
    len_b = len(clean_b)
    len_ratio = min(len_a, len_b) / max(len_a, len_b) if max(len_a, len_b) > 0 else 0

    result["steps"]["4_coverage"] = {
        "token_coverage": round(coverage, 4),
        "meaningful_coverage": round(meaningful_cov, 4),
        "word_count_a": wc_a,
        "word_count_b": wc_b,
        "word_count_ratio": round(wc_ratio, 4),
        "len_a": len_a,
        "len_b": len_b,
        "len_ratio": round(len_ratio, 4),
    }

    # 5. Dedup key (ayni master olur mu?)
    # Sirali tuple — tekrarlari korur (C & C ≠ C)
    def _dedup_key(name: str, cc: str) -> tuple:
        raw_tokens = _clean_labels(name).lower().split()
        country_toks = _COUNTRY_NAME_TOKENS.get(cc.upper(), frozenset())
        norm_list = []
        for t in raw_tokens:
            tc = t.rstrip('.,')
            if not tc or (len(tc) <= 1 and not tc.isalnum()):
                continue
            if tc in _ARTICLE_STOPWORDS or tc in country_toks:
                continue
            norm = _SUFFIX_NORMALIZE.get(tc, _SUFFIX_NORMALIZE.get(t, tc))
            norm_list.append(norm)
        return tuple(sorted(norm_list))

    dk_a = _dedup_key(name_a, country)
    dk_b = _dedup_key(name_b, country)
    result["steps"]["5_dedup"] = {
        "key_a": list(dk_a),
        "key_b": list(dk_b),
        "same_master": dk_a == dk_b,
    }

    # 6. Her stage icin post-verify
    # SUFFIX_FUZZY icin variations_stripped da gerekli
    suffix_set = set(_SUFFIX_NORMALIZE.values())

    def _stripped_form(name: str) -> str:
        tokens = _clean_labels(name).lower().split()
        return " ".join(
            t.rstrip('.,') for t in tokens
            if t.rstrip('.,') and t.rstrip('.,') not in suffix_set
            and t.rstrip('.,') not in _STOPWORDS
        )

    stripped_b = _stripped_form(name_b)
    stripped_a = _stripped_form(name_a)

    master_source_b = {"variations": [name_b.lower()], "variations_stripped": [stripped_b]}
    master_source_a = {"variations": [name_a.lower()], "variations_stripped": [stripped_a]}

    stage_results = {}
    for stage_name in ["CANONICAL_EXACT", "STRIPPED_EXACT", "SUFFIX_FUZZY", "TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"]:
        pass_ab = _post_verify(name_a, master_source_b, stage_name, country)
        pass_ba = _post_verify(name_b, master_source_a, stage_name, country)
        stage_results[stage_name] = {
            "a_to_b": pass_ab,
            "b_to_a": pass_ba,
        }
    result["steps"]["6_stage_verify"] = stage_results

    return result


def print_analysis(result: dict) -> None:
    """Analiz sonucunu okunakli formatta yazdir."""
    a = result["input_a"]
    b = result["input_b"]
    cc = result["country"]

    print()
    print("=" * 80)
    print(f"  FIRMA ESLESTIRME ANALIZI")
    print(f"  A: {a}")
    print(f"  B: {b}")
    print(f"  Ulke: {cc}")
    print("=" * 80)

    # 1. Label temizleme
    s = result["steps"]["1_clean_labels"]
    if s["changed_a"] or s["changed_b"]:
        print(f"\n[1] Label Temizleme:")
        if s["changed_a"]:
            print(f"  A: '{a}' -> '{s['a']}'")
        if s["changed_b"]:
            print(f"  B: '{b}' -> '{s['b']}'")
    else:
        print(f"\n[1] Label Temizleme: degisiklik yok")

    # 2. Tokenize
    s = result["steps"]["2_tokenize"]
    print(f"\n[2] Tokenize (suffix norm + country filter + stopword filter):")
    print(f"  A: {s['a']}")
    print(f"  B: {s['b']}")
    print(f"  Ayni set mi? {'EVET' if s['same'] else 'HAYIR'}")

    # 3. Meaningful
    s = result["steps"]["3_meaningful"]
    print(f"\n[3] Anlamli / Suffix Ayirimi:")
    print(f"  A anlamli: {s['a_meaningful']}  suffix: {s['a_suffix']}")
    print(f"  B anlamli: {s['b_meaningful']}  suffix: {s['b_suffix']}")
    print(f"  Min anlamli token: {s['min_meaningful']}")
    if s["min_meaningful"] < 2:
        print(f"  !! TEK ANLAMLI TOKEN — sadece CANONICAL/STRIPPED tam eslesmede gecerli")

    # 4. Coverage
    s = result["steps"]["4_coverage"]
    print(f"\n[4] Coverage Metrikleri:")
    print(f"  Token coverage:      {s['token_coverage']:.2%}")
    print(f"  Meaningful coverage: {s['meaningful_coverage']:.2%}")
    print(f"  Word count:          A={s['word_count_a']} B={s['word_count_b']}  ratio={s['word_count_ratio']:.2%}")
    print(f"  Karakter uzunlugu:   A={s['len_a']} B={s['len_b']}  ratio={s['len_ratio']:.2%}")

    # 5. Dedup
    s = result["steps"]["5_dedup"]
    print(f"\n[5] Dedup Key (NEW_MASTER icinde):")
    print(f"  A: {s['key_a']}")
    print(f"  B: {s['key_b']}")
    print(f"  Ayni master olur mu? {'EVET — ayni dedup key' if s['same_master'] else 'HAYIR — farkli master'}")

    # 6. Stage sonuclari
    s = result["steps"]["6_stage_verify"]
    print(f"\n[6] Stage Post-Verify Sonuclari:")
    print(f"  {'Stage':<20s} {'A->B':>8s} {'B->A':>8s}  Sonuc")
    print(f"  {'-'*55}")
    for stage_name in ["CANONICAL_EXACT", "STRIPPED_EXACT", "SUFFIX_FUZZY", "TOKEN_COVERAGE", "FUZZY_PHRASE", "NGRAM_MATCH"]:
        sr = s[stage_name]
        ab = "GECTI" if sr["a_to_b"] else "RED"
        ba = "GECTI" if sr["b_to_a"] else "RED"
        if sr["a_to_b"] or sr["b_to_a"]:
            sonuc = "ESLESIR"
        else:
            sonuc = "eslesmez"
        print(f"  {stage_name:<20s} {ab:>8s} {ba:>8s}  {sonuc}")

    # Genel sonuc
    any_match = any(
        s[stage]["a_to_b"] or s[stage]["b_to_a"]
        for stage in s
    )
    print(f"\n{'='*80}")
    if any_match:
        matching_stages = [st for st in s if s[st]["a_to_b"] or s[st]["b_to_a"]]
        print(f"  SONUC: ESLESIR (ilk eslesen stage: {matching_stages[0]})")
    else:
        print(f"  SONUC: ESLESMEZ (hicbir stage'den gecemedi)")
    print(f"{'='*80}")
    print()


def search_es(name: str, country: str) -> None:
    """ES'te firma ara ve sonuclari goster."""
    from elasticsearch import Elasticsearch
    import es_queries

    es = Elasticsearch("http://localhost:9200")

    stages = [
        ("CANONICAL_EXACT", es_queries.CANONICAL_EXACT),
        ("STRIPPED_EXACT", es_queries.STRIPPED_EXACT),
        ("SUFFIX_FUZZY", es_queries.SUFFIX_FUZZY),
        ("TOKEN_COVERAGE", es_queries.TOKEN_COVERAGE),
        ("FUZZY_PHRASE", es_queries.FUZZY_PHRASE),
        ("NGRAM_MATCH", es_queries.NGRAM_MATCH),
    ]

    print(f"\n{'='*80}")
    print(f"  ES ARAMA: '{name}' (ulke: {country})")
    print(f"{'='*80}")

    for stage_name, query_fn in stages:
        q = query_fn(name=name, country=country)
        try:
            result = es.search(index=ES_INDEX, body=q, routing=country)
        except Exception as e:
            print(f"\n  [{stage_name}] HATA: {e}")
            continue

        hits = result["hits"]["hits"]
        total = result["hits"]["total"]["value"]
        print(f"\n  [{stage_name}] {total} hit")
        for h in hits[:3]:
            score = h["_score"]
            src = h["_source"]
            vars_list = src.get("variations", [])
            stripped = src.get("variations_stripped", [])
            mid = h["_id"][:12]
            print(f"    score={score:.1f}  master={mid}...")
            print(f"      variations: {vars_list[:3]}")
            if stripped:
                print(f"      stripped:   {stripped[:3]}")

    print()


def quality_report() -> None:
    """ES'teki multi-varyasyon master'larin kalite raporu."""
    from elasticsearch import Elasticsearch

    es = Elasticsearch("http://localhost:9200")

    count = es.count(index=ES_INDEX)["count"]
    print(f"\n{'='*80}")
    print(f"  KALITE RAPORU — ES: {count:,} master")
    print(f"{'='*80}")

    # Varyasyon dagilimi
    result = es.search(index=ES_INDEX, body={
        "size": 0,
        "aggs": {
            "var_count": {
                "histogram": {
                    "script": 'doc["variations.keyword"].size()',
                    "interval": 1,
                }
            }
        },
    })
    print(f"\n  Varyasyon Dagilimi:")
    for bucket in result["aggregations"]["var_count"]["buckets"][:10]:
        k = int(bucket["key"])
        c = bucket["doc_count"]
        bar = "#" * min(50, c // max(1, count // 100))
        print(f"    {k:2d} varyasyon: {c:>8,d}  {bar}")

    # Sorunlu master'lar (yeni tokenize ile kontrol)
    result2 = es.search(index=ES_INDEX, body={
        "size": 200,
        "query": {"match_all": {}},
        "sort": [{"_script": {"type": "number", "script": 'doc["variations.keyword"].size()', "order": "desc"}}],
        "_source": ["variations", "country_code"],
    })

    sorunlu = []
    dogru = []
    for h in result2["hits"]["hits"]:
        variations = h["_source"]["variations"]
        cc = h["_source"]["country_code"]
        if len(variations) < 2:
            continue

        base_tokens = _tokenize(variations[0], cc)
        problem = False
        for v in variations[1:]:
            v_tokens = _tokenize(v, cc)
            suffix_tokens = set(_SUFFIX_NORMALIZE.values())
            base_m = base_tokens - suffix_tokens
            v_m = v_tokens - suffix_tokens
            cov = _symmetric_token_coverage(base_m, v_m)
            if cov < 0.8:
                problem = True
                break

        if problem:
            sorunlu.append((cc, variations))
        else:
            dogru.append((cc, variations))

    print(f"\n  Multi-Varyasyon Kalite (ilk 200 master):")
    print(f"    Dogru:   {len(dogru)}")
    print(f"    Sorunlu: {len(sorunlu)}")

    if sorunlu:
        print(f"\n  Sorunlu Master'lar:")
        for cc, vars_list in sorunlu[:15]:
            print(f"    [{cc}] {vars_list}")

    if dogru:
        print(f"\n  Ornek Dogru Eslesmeler:")
        for cc, vars_list in dogru[:10]:
            print(f"    [{cc}] {vars_list}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Firma eslestirme debug araci",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ornekler:
  python debug_match.py "ARVIND LTD" "ARVIND LIMITED" -c IN
  python debug_match.py "C & C OVERSEAS" "C OVERSEAS" -c IN
  python debug_match.py "ARVIND" -c IN --search
  python debug_match.py --report
        """,
    )
    parser.add_argument("name_a", nargs="?", help="Birinci firma ismi")
    parser.add_argument("name_b", nargs="?", help="Ikinci firma ismi (karsilastirma icin)")
    parser.add_argument("-c", "--country", default="IN", help="Ulke kodu (varsayilan: IN)")
    parser.add_argument("--search", action="store_true", help="ES'te ara (tek firma)")
    parser.add_argument("--report", action="store_true", help="Kalite raporu")
    parser.add_argument("--json", action="store_true", help="JSON cikti")

    args = parser.parse_args()

    if args.report:
        quality_report()
    elif args.search and args.name_a:
        search_es(args.name_a, args.country)
    elif args.name_a and args.name_b:
        result = analyze_pair(args.name_a, args.name_b, args.country)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print_analysis(result)
    elif args.name_a:
        print("Ikinci firma ismi gerekli. Tek firma icin --search kullanin.")
    else:
        parser.print_help()
