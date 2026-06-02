# ============================================================================
# analysis/live_probe.py — Canlı eşleştirme regresyon probe'u (prod'a yazmaz)
# ============================================================================
# Amaç: es_queries / config STAGES / es_manager analyzer'ları DÜZENLENDİKÇE,
# tam reindex+rematch beklemeden gerçek isimler üzerinde "over-merge / under-merge"
# davranışını canlı ölçmek.
#
# Nasıl çalışır:
#   1. Geçici bir index açar (build_index_settings → güncel analyzer'lar).
#   2. Golden set isimlerini GERÇEK ingest pipeline'ından geçirerek index'ler
#      (variations_stripped/phonetic/ngram güncel mapping ile hesaplanır).
#   3. Her isim için config.STAGES sırasını izleyerek es_queries sorgularını
#      çalıştırır; ilk min_score'u geçen stage = "kazanan eşleşme".
#   4. Golden ground-truth'a göre precision (farklı firmalar eşleşmemeli) ve
#      recall (aynı firma eşleşmeli) raporlar. Geçici index'i siler.
#
# Kullanım:
#   python -m analysis.live_probe
#   python -m analysis.live_probe --keep   # geçici index'i silme (inceleme için)
# ============================================================================

import argparse
import copy
import uuid

import config
import es_queries
from core_name import best_core_coverage
from es_ingest import build_pipeline_body, pipeline_name
from es_manager import build_index_settings, get_es_client

PROBE_INDEX = "living_companies_probe"

# ── Golden set: denetimden (docs/audit/2026-06-02) çıkan GERÇEK vakalar ──
# Her grup AYNI firmadır (positives → eşleşmeli). Farklı gruplar FARKLI
# firmalardır (negatives → birbirleriyle eşleşmemeli). country = MX.
GOLDEN_GROUPS: dict[str, list[str]] = {
    # --- PHONETIC over-merge kurbanları: hepsi FARKLI firma ---
    "audi": ["AUDI MEXICO S.A. DE C.V."],
    "kohler": ["KOHLER DE MEXICO S.A. DE C.V."],
    "igsa": ["IGSA S.A. DE C.V."],
    "diga": ["DIGA, S.A. DE C.V."],
    "witte_firm": ["WITTE, S.A. DE C.V.", "WITTE. S.A. DE C.V."],  # ikisi AYNI (nokta tipo)
    # --- NGRAM over-merge kurbanları: 'USA INC' paylaşan FARKLI firmalar ---
    "alpi": ["ALPI USA, INC."],
    "cordialsa": ["CORDIALSA USA, INC."],
    "hascor": ["HASCOR USA, INC."],
    # --- Subset over-merge (Faz 2 coverage gate testi): FARKLI firmalar ---
    # ALCATEL ⊂ ALCATEL-LUCENT: fonetik subset eşleşir; coverage gate ayırmalı.
    "alcatel": ["ALCATEL S.A. DE C.V."],
    "alcatel_lucent": ["ALCATEL LUCENT S.A. DE C.V."],
    # --- SHOULD_MERGE (under-merge): her grup AYNI firma, eşleşmeli ---
    "vibracoustic": [
        "VIBRACOUSTIC DE MEXICO S.A. DE C.V.",
        "VIBRACOUSTIC DE MEXICO S.A. DE CA",
        "VIBRACOUSTIC DE MEXICO, S.A. DE C.V.",
    ],
    "ceva_freight_mgmt": [
        "CEVA FREIGHT MANAGEMENT MEXICO SA",
        "CEVA FREIGHT MANAGEMENT MEXICO",
        "CEVA FREIGHT MANAGMENT MEXICO",
    ],
    "dhl_global_fwd": [
        "DHL GLOBAL FORWARDING MEXICO",
        "DHL GLOBAL FORWARDING (MEXICO)",
    ],
}
COUNTRY = "MX"


def _build_probe_index(es) -> list[dict]:
    """Geçici index'i kurar, golden isimleri pipeline'dan geçirip index'ler.
    Dönüş: [{doc_id, name, firm}] indexlenen kayıtlar."""
    if es.indices.exists(index=PROBE_INDEX):
        es.indices.delete(index=PROBE_INDEX, ignore=[404])
    es.options(request_timeout=120).indices.create(
        index=PROBE_INDEX, body=build_index_settings(es)
    )
    # MX ingest pipeline (güncel es_ingest kodundan) — geçici isimle kaydet
    pname = pipeline_name(COUNTRY)
    es.ingest.put_pipeline(id=pname, body=build_pipeline_body(COUNTRY))

    indexed: list[dict] = []
    for firm, names in GOLDEN_GROUPS.items():
        for name in names:
            doc_id = str(uuid.uuid4())
            es.index(
                index=PROBE_INDEX,
                id=doc_id,
                routing=COUNTRY,
                pipeline=pname,
                document={
                    "master_id": doc_id,
                    "firm": firm,  # ground-truth etiketi (probe dışı alan)
                    "variations": [{"name": name}],
                    "variations_stripped": [],
                    "country_code": COUNTRY,
                },
            )
            indexed.append({"doc_id": doc_id, "name": name, "firm": firm})
    es.indices.refresh(index=PROBE_INDEX)
    return indexed


def _probe(es, name: str, self_id: str) -> dict | None:
    """config.STAGES sırasını izleyerek ilk eşleşen stage'i döner (kendisi hariç).
    Dönüş: {stage, matched_name, matched_firm, score} ya da None (eşleşme yok)."""
    for stage in config.STAGES:
        if not stage.get("enabled", True):
            continue
        fn = getattr(es_queries, stage["query_fn"], None)
        if fn is None:
            continue
        # deepcopy: es_queries MATCH_NONE gibi MODÜL-DÜZEYİ sabit döndürebilir;
        # body'yi yerinde değiştirmek o sabiti kalıcı bozar (review HIGH).
        body = copy.deepcopy(fn(name, COUNTRY, es=es))
        # Kendini hariç tut (aynı dokümanı yakalamasın)
        q = body.setdefault("query", {}).setdefault("bool", {})
        q.setdefault("must_not", []).append({"ids": {"values": [self_id]}})
        body["size"] = 3
        res = es.search(index=PROBE_INDEX, body=body, routing=COUNTRY)
        hits = res["hits"]["hits"]
        if hits and hits[0]["_score"] >= stage["min_score"]:
            top = hits[0]
            # Faz 2 — coverage post-verify (main_processor._variation_names ile aynı
            # çıkarım: variation hem dict hem düz string olabilir):
            names = [
                (v.get("name") if isinstance(v, dict) else v)
                for v in top["_source"].get("variations", [])
            ]
            names = [n for n in names if n]
            if config.CORE_COVERAGE_THRESHOLD > 0 and names:
                cov = best_core_coverage(name, names, COUNTRY)
                if cov < config.CORE_COVERAGE_THRESHOLD:
                    continue  # reddet → sonraki stage'e düş
            return {
                "stage": stage["name"],
                "matched_name": top["_source"]["variations"][0]["name"],
                "matched_firm": top["_source"]["firm"],
                "score": round(top["_score"], 2),
            }
    return None


def run(keep: bool = False) -> None:
    es = get_es_client()
    indexed = _build_probe_index(es)
    print(f"Probe index '{PROBE_INDEX}': {len(indexed)} kayıt indexlendi.\n")

    over_merge_viol = []  # farklı firma eşleşti (precision ihlali)
    recall_ok = 0
    recall_total = 0
    # recall: çok-üyeli firmalar için en az bir sibling eşleşmeli
    firm_counts = {firm: sum(1 for r in indexed if r["firm"] == firm) for firm in GOLDEN_GROUPS}

    for rec in indexed:
        m = _probe(es, rec["name"], rec["doc_id"])
        same_firm_siblings = firm_counts[rec["firm"]] > 1
        if same_firm_siblings:
            recall_total += 1
        if m is None:
            tag = "NEW_MASTER (eşleşme yok)"
        else:
            same = m["matched_firm"] == rec["firm"]
            tag = f"{m['stage']} -> '{m['matched_name']}' [{m['score']}] {'✓same' if same else '✗DIFF-FIRM'}"
            if not same:
                over_merge_viol.append((rec["name"], m))
            elif same_firm_siblings:
                recall_ok += 1
        print(f"  {rec['name']:<42} → {tag}")

    print("\n=== SONUÇ ===")
    print(f"Over-merge ihlali (farklı firma eşleşti): {len(over_merge_viol)}")
    for nm, m in over_merge_viol:
        print(f"   ✗ '{nm}' == '{m['matched_name']}' via {m['stage']} ({m['score']})")
    print(f"Under-merge recall (aynı firma sibling yakalandı): {recall_ok}/{recall_total}")

    if not keep:
        es.indices.delete(index=PROBE_INDEX, ignore=[404])
        print(f"\nGeçici index '{PROBE_INDEX}' silindi.")
    else:
        print(f"\nGeçici index '{PROBE_INDEX}' korundu (--keep).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Canlı eşleştirme regresyon probe'u")
    ap.add_argument("--keep", action="store_true", help="Geçici index'i silme")
    run(**vars(ap.parse_args()))
