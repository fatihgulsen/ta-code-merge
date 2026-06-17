# ============================================================================
# analysis/es_verify.py — Hibrit doğrulama: bir ismi ES'e stage query'siyle sorgular
# ============================================================================
# Kullanım:
#   python -m analysis.es_verify "WITTE, S.A. DE C.V." MX PHONETIC_MATCH
# ============================================================================

import sys

import es.queries as _eq
from es.manager import get_es_client
from config import alias_for_country


def verify_pair(es, name: str, country: str, stage_name: str) -> list[dict]:
    """İsmi ilgili stage query'siyle ES'e sorgular, hit'leri (master_id, score, variation) döner."""
    query_fn = getattr(_eq, stage_name)
    body = query_fn(name=name, country=country, es=es)
    resp = es.search(index=alias_for_country(country), body=body)
    out = []
    for h in resp["hits"]["hits"]:
        src = h.get("_source", {})
        out.append({
            "master_id": src.get("master_id"),
            "score": h["_score"],
            "variations": [v.get("name") for v in src.get("variations", []) if isinstance(v, dict)][:5],
        })
    return out


def main() -> None:
    if len(sys.argv) < 4:
        print("Kullanım: python -m analysis.es_verify '<isim>' <ülke> <STAGE_NAME>")
        sys.exit(1)
    name, country, stage = sys.argv[1], sys.argv[2], sys.argv[3]
    es = get_es_client()
    hits = verify_pair(es, name, country, stage)
    print(f"'{name}' [{country}] {stage} → {len(hits)} hit")
    for h in hits:
        print(f"  master={h['master_id']} score={h['score']:.2f} variations={h['variations']}")


if __name__ == "__main__":
    main()
