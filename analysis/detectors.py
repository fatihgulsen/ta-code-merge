# ============================================================================
# analysis/detectors.py — Over-merge / split QA dedektörleri (salt-okunur)
# ============================================================================
# p7_firms_v2 eşleşmiş kayıtlarını in-memory işler. Fuzzy kütüphane YOK —
# yalnızca küme (set) işlemleri. DB erişimi yalnızca SELECT.
# ============================================================================

from dataclasses import dataclass

import psycopg2
from psycopg2.extras import DictCursor

from config import DB_CONFIG, RAW_TABLE_NAME, COLUMN_MAPPING
from core_name import normalize_core


def token_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """İki token tuple'ı arasında Jaccard örtüşmesi (kesişim/birleşim)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union)
