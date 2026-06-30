"""Synonym double-token (collision) scanner.

Bir kaynak token, birleşik synonym_graph setinde (common + {cc}) >1 FARKLI kanonik
hedefe giderse, ES aynı pozisyonda birden çok token üretir (çiftleme). Bu, token_count
invariant'ını ve canonical_full'u bozar. Bu script tüm çakışmaları ülke başına listeler.
"""
import io
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.synonym_loader import (
    load_synonyms_for_country,
    _extract_rules_from_file,
    SYNONYMS_DIR,
)


def parse_rule(rule: str):
    """'src1,src2=>target' -> (sources:list, target). '=>' yoksa son token target sayılır."""
    if "=>" in rule:
        left, right = rule.split("=>", 1)
        sources = [s.strip() for s in left.split(",") if s.strip()]
        target = right.strip()
    else:
        parts = [s.strip() for s in rule.split(",") if s.strip()]
        sources, target = parts[:-1], parts[-1] if parts else ""
    return sources, target


def origin_map():
    """token-rule -> hangi dosyadan geldiği (attribution için)."""
    m = {}
    for f in ("common.json",):
        for r in _extract_rules_from_file(SYNONYMS_DIR / f):
            m[r] = "common"
    return m


def scan(cc: str):
    rules = load_synonyms_for_country(cc)
    common_rules = set(_extract_rules_from_file(SYNONYMS_DIR / "common.json"))
    cc_rules = set(_extract_rules_from_file(SYNONYMS_DIR / f"{cc.lower()}.json"))

    # source token -> {target -> set(origins)}
    src_targets = defaultdict(lambda: defaultdict(set))
    for rule in rules:
        origin = "common" if rule in common_rules else (cc.lower() if rule in cc_rules else "?")
        sources, target = parse_rule(rule)
        # SADECE sol-taraf (source) token'ları ES'te eşleşir → çiftleme yalnızca bunlardan.
        for s in sources:
            src_targets[s][target].add(origin)

    collisions = {s: t for s, t in src_targets.items() if len(t) > 1}
    return collisions


for cc in ("AR", "BR", "MX"):
    cols = scan(cc)
    print(f"\n{'='*70}\n{cc}: {len(cols)} çakışan kaynak token (>1 kanonik hedef)\n{'='*70}")
    for src in sorted(cols, key=lambda s: (-len(cols[s]), s)):
        tgts = cols[src]
        parts = []
        for tgt, origins in sorted(tgts.items()):
            parts.append(f"{tgt!r}({'+'.join(sorted(origins))})")
        print(f"  {src!r:22} -> {' , '.join(parts)}")
