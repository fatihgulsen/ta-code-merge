"""Elasticsearch master-doc yazımı: varyasyon/meta ekleme, yeni master indeksleme."""
import logging
import uuid

from config import alias_for_country
from core.synonym_phonetic import canonicalize_phonetic
from es.ingest import pipeline_name

logger = logging.getLogger(__name__)


def update_es_variations(es, matched: list[dict]) -> None:
    """Eslesen kayitlarin varyasyonlarini ve meta bilgilerini master ES doc'a ekler.

    Her eslesen kaydin raw_name'i variations listesine,
    tax/phone/address degerleri ilgili listelere eklenir (zaten yoksa).
    """
    if not matched:
        return

    # Master bazında gruplayarak toplu bulk update
    master_updates: dict[str, dict] = {}
    for r in matched:
        mid = r["master_id"]
        if mid not in master_updates:
            master_updates[mid] = {
                "variations": set(),
                "tax_numbers": set(),
                "phone_numbers": set(),
                "addresses": set(),
                "country": r["country"],
            }
        master_updates[mid]["variations"].add(canonicalize_phonetic(r["raw_name"], r["country"]))
        if r.get("tax"):
            master_updates[mid]["tax_numbers"].add(r["tax"])
        if r.get("phone"):
            master_updates[mid]["phone_numbers"].add(r["phone"])
        if r.get("address"):
            master_updates[mid]["addresses"].add(r["address"])

    bulk_body = []
    for master_id, info in master_updates.items():
        # Variations listesine ekle
        for variation in info["variations"]:
            v_clean = variation.strip().rstrip(".,")
            bulk_body.append(
                {
                    "update": {
                        "_index": alias_for_country(info["country"]),
                        "_id": master_id,
                    }
                }
            )
            bulk_body.append(
                {
                    "script": {
                        "source": (
                            "String v = params.v; "
                            "if (!ctx._source.variations.contains(v)) { "
                            "  ctx._source.variations.add(v); "
                            "}"
                        ),
                        "lang": "painless",
                        "params": {"v": v_clean},
                    },
                }
            )

        # Tax/phone/address listelerine duplicate kontrollu ekleme
        _append_list_fields(bulk_body, master_id, info)

    if bulk_body:
        try:
            es.bulk(body=bulk_body, refresh=False)
        except Exception:
            logger.warning("ES variations update basarisiz, devam ediliyor", exc_info=True)


def _append_list_fields(bulk_body: list[dict], master_id: str, info: dict) -> None:
    """tax_number, phone_number, address listelerine yeni degerleri ekler."""
    field_map = {
        "tax_number": info["tax_numbers"],
        "phone_number": info["phone_numbers"],
        "address": info["addresses"],
    }
    country = info["country"]

    for field_name, values in field_map.items():
        for val in values:
            val_clean = val.strip()
            if not val_clean:
                continue
            bulk_body.append(
                {
                    "update": {
                        "_index": alias_for_country(country),
                        "_id": master_id,
                    }
                }
            )
            bulk_body.append(
                {
                    "script": {
                        "source": (
                            "String v = params.v; "
                            "String field = params.field; "
                            "if (ctx._source[field] == null) { "
                            "  ctx._source[field] = [v]; "
                            "} else if (!ctx._source[field].contains(v)) { "
                            "  ctx._source[field].add(v); "
                            "}"
                        ),
                        "lang": "painless",
                        "params": {"v": val_clean, "field": field_name},
                    },
                }
            )


def build_new_master_doc(
    name: str, country: str, tax: str, phone: str, address: str = ""
) -> tuple[dict, str]:
    master_id = str(uuid.uuid4())
    doc = {
        "_index": alias_for_country(country),
        "_id": master_id,
        "_source": {
            "master_id": master_id,
            "variations": [{"name": canonicalize_phonetic(name, country)}],
            "country_code": country.upper(),
        },
    }
    if tax:
        doc["_source"]["tax_number"] = [tax]
    if phone:
        doc["_source"]["phone_number"] = [phone]
    if address:
        doc["_source"]["address"] = [address]
    return doc, master_id


def _index_new_master(es, rec: dict) -> str:
    """Yeni master olusturur, ES'e index'ler (pipeline ile), master_id doner."""
    cc = rec["country"]
    canon = canonicalize_phonetic(rec["raw_name"], cc)
    master_id = str(uuid.uuid4())
    doc = {
        "master_id": master_id,
        "variations": [{"name": canon}],
        "country_code": cc.upper(),
    }
    if rec.get("phone"):
        doc["phone_number"] = [rec["phone"]]
    if rec.get("address"):
        doc["address"] = [rec["address"]]

    try:
        es.index(
            index=alias_for_country(rec["country"]),
            id=master_id,
            body=doc,
            pipeline=pipeline_name(rec["country"]),
        )
    except Exception as exc:
        # Pipeline hatasi — pipeline olmadan dene
        logger.warning(
            f"Pipeline ile index hatasi ({exc!r}), pipeline olmadan deneniyor: {rec['raw_name'][:50]}"
        )
        es.index(
            index=alias_for_country(rec["country"]),
            id=master_id,
            body=doc,
        )
    return master_id


def _add_variation_to_master(
    es, master_doc_id: str, variation: str, country: str, rec: dict | None = None
) -> None:
    """Eşleşen kaydın varyasyonunu ve meta bilgilerini master doc'a ekler."""
    variation = canonicalize_phonetic(variation, country)
    v_lower = variation.lower().strip().rstrip(".,")
    cc = country
    try:
        doc = es.get(index=alias_for_country(cc), id=master_doc_id)
        source = doc["_source"]
        existing_variations = source.get("variations", [])

        changed = False
        existing_names = [
            v.get("name", "").lower()
            for v in existing_variations
            if isinstance(v, dict)
        ]
        # Build a shallow-copy body so we never mutate the caller's dict
        body = dict(source)

        if v_lower not in existing_names:
            body["variations"] = list(existing_variations) + [{"name": variation}]
            changed = True

        # tax/phone/address listelerine yeni değerleri ekle
        if rec:
            for field, key in [
                ("phone_number", "phone"),
                ("address", "address"),
            ]:
                val = (rec.get(key) or "").strip()
                if val:
                    existing = body.get(field, [])
                    if not isinstance(existing, list):
                        existing = [existing] if existing else []
                    if val not in existing:
                        body[field] = existing + [val]
                        changed = True

        if not changed:
            return

        pipe = pipeline_name(cc)
        es.index(
            index=alias_for_country(cc),
            id=master_doc_id,
            body=body,
            pipeline=pipe,
        )
    except Exception:
        logger.warning(f"Varyasyon ekleme basarisiz: {v_lower[:50]}", exc_info=True)
