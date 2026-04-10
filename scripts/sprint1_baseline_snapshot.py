"""Sprint 1 baseline metrics — captures pre-change state for before/after diff."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_CONFIG, RAW_TABLE_NAME  # noqa: E402


def snapshot() -> dict:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {RAW_TABLE_NAME}")
    total = cur.fetchone()[0]

    cur.execute(
        f"SELECT COUNT(*) FROM {RAW_TABLE_NAME} WHERE master_code IS NULL"
    )
    unmatched = cur.fetchone()[0]

    cur.execute(
        f"SELECT COUNT(DISTINCT master_code) FROM {RAW_TABLE_NAME} "
        f"WHERE master_code IS NOT NULL"
    )
    unique_masters = cur.fetchone()[0]

    cur.execute(
        f"SELECT match_type, COUNT(*) FROM {RAW_TABLE_NAME} "
        f"WHERE master_code IS NOT NULL GROUP BY match_type ORDER BY 2 DESC"
    )
    by_type = {row[0]: row[1] for row in cur.fetchall()}

    conn.close()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_rows": total,
        "unmatched": unmatched,
        "unique_masters": unique_masters,
        "matches_by_type": by_type,
    }


def main() -> None:
    data = snapshot()
    out_dir = Path(__file__).resolve().parent.parent / "baselines"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"baseline_{stamp}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Baseline written to {out_file}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
