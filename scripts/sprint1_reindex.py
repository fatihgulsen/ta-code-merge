"""Sprint 1 — re-register ingest pipelines and recompute variations_stripped.

After Tasks 2-3 widen BUSINESS_DESCRIPTORS and apply the guard, the Painless
scripts embedded in each per-country ingest pipeline need to be re-generated,
and every existing document in living_companies_v1 must run through the
updated pipeline so that `variations_stripped` and `variations_suffix` reflect
the new token set.

Strategy: update_by_query with explicit pipeline routing per country shard.

Usage:
    python scripts/sprint1_reindex.py           # full reindex (all countries)
    python scripts/sprint1_reindex.py --only NZ # dry-run: only NZ shard
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ES_INDEX  # noqa: E402
from es_ingest import register_all_pipelines, pipeline_name  # noqa: E402
from es_manager import get_es_client  # noqa: E402
from synonym_loader import get_all_country_codes  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def reindex_country(es, country_code: str) -> dict:
    """Run update_by_query for a single country's shard, forcing the new pipeline."""
    cc = country_code.upper()
    pipe = pipeline_name(cc)
    body = {
        "query": {"term": {"country_code": cc}},
    }
    logger.info("Reindexing %s via pipeline %s ...", cc, pipe)
    start = time.time()
    result = es.update_by_query(
        index=ES_INDEX,
        body=body,
        pipeline=pipe,
        routing=cc,
        wait_for_completion=True,
        conflicts="proceed",
        refresh=True,
        request_timeout=3600,
    )
    elapsed = time.time() - start
    logger.info(
        "  %s: updated=%s, version_conflicts=%s, elapsed=%.1fs",
        cc,
        result.get("updated", 0),
        result.get("version_conflicts", 0),
        elapsed,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprint 1 reindex helper")
    parser.add_argument(
        "--only",
        metavar="CC",
        help="Reindex only this country code (e.g. NZ). If omitted, reindex all.",
    )
    args = parser.parse_args()

    es = get_es_client()

    logger.info("Step 1/2 — re-registering all ingest pipelines")
    register_all_pipelines(es)

    if args.only:
        codes = [args.only.upper()]
        logger.info("Step 2/2 — dry-run: update_by_query for ONLY %s", codes[0])
    else:
        codes = get_all_country_codes()
        logger.info("Step 2/2 — update_by_query for %d countries", len(codes))

    total_updated = 0
    failures: list[str] = []
    for cc in codes:
        try:
            res = reindex_country(es, cc)
            total_updated += res.get("updated", 0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Reindex failed for %s", cc)
            failures.append(f"{cc}: {exc}")

    logger.info("Total docs updated: %d", total_updated)
    if failures:
        logger.error("Failures (%d):", len(failures))
        for f in failures:
            logger.error("  %s", f)
        sys.exit(1)
    logger.info("Sprint 1 reindex complete.")


if __name__ == "__main__":
    main()
