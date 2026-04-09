# ============================================================================
# dedup_reviewer.py - Duplicate İnceleme ve Birleştirme Aracı
# ============================================================================
# ES Transform tarafından tespit edilen potansiyel duplicate'ları
# listeler ve insan onayı ile birleştirme yapar.
# ============================================================================

import logging
import sys

from elasticsearch import Elasticsearch

from config import ES_INDEX
from es_manager import get_es_client
from es_transform import get_potential_duplicates

logger = logging.getLogger(__name__)


def review_duplicates(es: Elasticsearch, min_count: int = 2) -> None:
    """
    Potansiyel duplicate'ları interaktif olarak inceler.
    Her grup için kullanıcıdan onay ister.
    """
    duplicates = get_potential_duplicates(es, min_count=min_count)

    if not duplicates:
        print("Potansiyel duplicate bulunamadi.")
        return

    print(f"\n{'='*70}")
    print(f"  {len(duplicates)} potansiyel duplicate grubu bulundu")
    print(f"{'='*70}\n")

    for i, dup in enumerate(duplicates):
        print(f"--- Grup {i+1}/{len(duplicates)} ---")
        print(f"  Fingerprint : {dup['fingerprint']}")
        print(f"  Country     : {dup['country_code']}")
        print(f"  Master Count: {dup['master_count']}")
        print(f"  Sample Names: {dup['sample_names']}")
        print()

        # Her master_id için detay göster
        master_ids = dup.get("master_ids", [])
        if isinstance(master_ids, list) and len(master_ids) > 0:
            # master_ids bir terms agg sonucu olabilir
            for mid_info in master_ids:
                mid = mid_info if isinstance(mid_info, str) else mid_info.get("key", "?")
                # ES'ten detay çek
                try:
                    doc = es.get(index=ES_INDEX, id=mid)
                    src = doc["_source"]
                    print(f"  [{mid}]")
                    print(f"    Variations: {src.get('variations', [])[:5]}")
                    print(f"    Tax: {src.get('tax_number', '-')}")
                    print(f"    Phone: {src.get('phone_number', '-')}")
                except Exception:
                    print(f"  [{mid}] - Dokuman bulunamadi")
                print()

        # İnsan onayı
        action = input("  Birlestir? (y=birlestir / n=atla / q=cik): ").strip().lower()
        if action == "q":
            print("Cikiliyor.")
            return
        elif action == "y":
            if len(master_ids) >= 2:
                primary = master_ids[0] if isinstance(master_ids[0], str) else master_ids[0].get("key")
                secondaries = []
                for m in master_ids[1:]:
                    secondaries.append(m if isinstance(m, str) else m.get("key"))
                _merge_masters(es, primary, secondaries)
                print(f"  -> {len(secondaries)} kayit {primary}'e birlestirildi.\n")
            else:
                print("  -> Yeterli master yok, atlaniyor.\n")
        else:
            print("  -> Atlandi.\n")


def _merge_masters(es: Elasticsearch, primary_id: str, secondary_ids: list[str]) -> None:
    """
    Secondary master'ları primary'e birleştirir.
    - Secondary'lerin variation'larını primary'e ekler
    - Secondary dokümanları siler
    """
    for sec_id in secondary_ids:
        try:
            sec_doc = es.get(index=ES_INDEX, id=sec_id)
            sec_variations = sec_doc["_source"].get("variations", [])
            sec_stripped = sec_doc["_source"].get("variations_stripped", [])

            # Primary'e variation ekle
            es.update(
                index=ES_INDEX,
                id=primary_id,
                body={
                    "script": {
                        "source": """
                            for (v in params.new_vars) {
                                if (!ctx._source.variations.contains(v)) {
                                    ctx._source.variations.add(v);
                                }
                            }
                            for (s in params.new_stripped) {
                                if (!ctx._source.variations_stripped.contains(s)) {
                                    ctx._source.variations_stripped.add(s);
                                }
                            }
                        """,
                        "params": {
                            "new_vars": sec_variations,
                            "new_stripped": sec_stripped,
                        },
                    }
                },
            )

            # Secondary'i sil
            es.delete(index=ES_INDEX, id=sec_id)
            logger.info(f"Master {sec_id} -> {primary_id} birlestirildi.")

        except Exception as e:
            logger.error(f"Birlestirme hatasi ({sec_id} -> {primary_id}): {e}")


# ============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    es = get_es_client()
    min_count = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    review_duplicates(es, min_count=min_count)
