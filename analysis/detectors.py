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


from collections import Counter
from itertools import combinations


@dataclass(frozen=True)
class MatchedRow:
    id: object
    master_code: str
    name: str
    country: str
    match_type: str | None


@dataclass(frozen=True)
class OverMergeFinding:
    master_code: str
    member_count: int
    mean_overlap: float
    dominant_match_type: str | None
    sample_names: tuple[str, ...]


def detect_over_merge(rows: list[MatchedRow], threshold: float = 0.3) -> list[OverMergeFinding]:
    """Üyeleri birbirinden farklı (düşük token örtüşmeli) master kümelerini işaretler.

    Her master için üye çiftlerinin ortalama token örtüşmesini hesaplar;
    ortalama < threshold ise over-merge adayı. Tekil master'lar atlanır.
    Sonuç: (boyut × düşük-örtüşme) ağırlığına göre azalan sıralı.
    """
    by_master: dict[str, list[MatchedRow]] = {}
    for r in rows:
        if r.master_code:
            by_master.setdefault(r.master_code, []).append(r)

    findings: list[OverMergeFinding] = []
    for master, members in by_master.items():
        if len(members) < 2:
            continue
        cores = [normalize_core(m.name, m.country) for m in members]
        pairs = list(combinations(cores, 2))
        mean_overlap = sum(token_overlap(a, b) for a, b in pairs) / len(pairs)
        if mean_overlap < threshold:
            dom = Counter(m.match_type for m in members if m.match_type).most_common(1)
            findings.append(
                OverMergeFinding(
                    master_code=master,
                    member_count=len(members),
                    mean_overlap=mean_overlap,
                    dominant_match_type=dom[0][0] if dom else None,
                    sample_names=tuple(m.name for m in members[:5]),
                )
            )

    findings.sort(key=lambda f: f.member_count * (1.0 - f.mean_overlap), reverse=True)
    return findings


@dataclass(frozen=True)
class SplitFinding:
    country: str
    core_signature: tuple[str, ...]
    master_codes: tuple[str, ...]
    affected_rows: int
    sample_names: tuple[str, ...]


def detect_splits(rows: list[MatchedRow]) -> list[SplitFinding]:
    """Aynı ülkede özdeş çekirdek-imzaya sahip ama farklı master'a düşmüş kayıtları bulur.

    Çekirdek imza = normalize_core token'larının sıralı tuple'ı (sıra-bağımsız eşitlik).
    Bir (country, signature) altında >=2 farklı master_code varsa under-merge adayı.
    """
    groups: dict[tuple[str, tuple[str, ...]], list[MatchedRow]] = {}
    for r in rows:
        if not r.master_code:
            continue
        sig = tuple(sorted(normalize_core(r.name, r.country)))
        if not sig:
            continue
        groups.setdefault((r.country.upper(), sig), []).append(r)

    findings: list[SplitFinding] = []
    for (country, sig), members in groups.items():
        masters = {m.master_code for m in members}
        if len(masters) < 2:
            continue
        findings.append(
            SplitFinding(
                country=country,
                core_signature=sig,
                master_codes=tuple(sorted(masters)),
                affected_rows=len(members),
                sample_names=tuple(dict.fromkeys(m.name for m in members))[:5],
            )
        )

    findings.sort(key=lambda f: f.affected_rows, reverse=True)
    return findings
