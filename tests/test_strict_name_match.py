"""Sprint 2 — regression tests for strict_name_match.

Each false positive from session 2026-04-10 is encoded as a test case that
must return False from main_processor.strict_name_match after Sprint 2.

Positive controls guard against recall collapse: same-brand name variations
that differ only in legal suffix or typo must still return True.
"""
from __future__ import annotations

import pytest


# ---- False positives from session 2026-04-10 ---------------------------------
# These are real records from p7_firms_v2 that matched via SUFFIX_FUZZY pre-Sprint-2.

FP_PAIRS: list[tuple[str, str, str]] = [
    # (country, name_a, name_b) — must NOT match
    ("IN", "ATLAS CHEMICALS(PROP. KIRTI GOVERDHANDAS THAKKAR)", "ATLAS FINE CHEMICALS PVT LTD"),
    ("IN", "AB WOOD PRODUCTS PVT.LTD.", "BABA WOOD PRODUCTS PVT LTD"),
    ("IN", "A.S. ENGINEERING WORKS", "BABA ENGINEERING WORKS"),
]


@pytest.mark.parametrize("country,name_a,name_b", FP_PAIRS)
def test_sprint2_fp_rejected_forward(country, name_a, name_b):
    """strict_name_match must return False in the A→B direction."""
    import main_processor as mp
    assert mp.strict_name_match(name_a, name_b, country) is False


@pytest.mark.parametrize("country,name_a,name_b", FP_PAIRS)
def test_sprint2_fp_rejected_reverse(country, name_a, name_b):
    """strict_name_match must return False in the B→A direction (symmetry)."""
    import main_processor as mp
    assert mp.strict_name_match(name_b, name_a, country) is False


# ---- Positive controls — same-brand variations that MUST match ----------------

TP_PAIRS: list[tuple[str, str, str]] = [
    # (country, name_a, name_b) — must match (after legal suffix strip + canonicalisation)
    ("IN", "ATLAS FINE CHEMICALS PVT LTD", "ATLAS FINE CHEMICALS PRIVATE LIMITED"),
    ("IN", "ATLAS FINE CHEMICALS PVT LTD", "atlas fine chemicals pvt. ltd."),
    ("IN", "BABA WOOD PRODUCTS PVT LTD", "BABA WOOD PRODUCTS PRIVATE LIMITED"),
    ("IN", "AB WOOD PRODUCTS PVT.LTD.", "AB WOOD PRODUCTS LIMITED"),
    ("IN", "ISHA ENTERPRISES", "ISHA ENTERPRISE"),   # plural normalisation
    ("IN", "JAY CHEMICAL INDUSTRIES PVT LTD", "JAY CHEMICAL INDUSTRIES LIMITED"),
]


@pytest.mark.parametrize("country,name_a,name_b", TP_PAIRS)
def test_sprint2_tp_match_forward(country, name_a, name_b):
    """strict_name_match must return True in the A→B direction."""
    import main_processor as mp
    assert mp.strict_name_match(name_a, name_b, country) is True


@pytest.mark.parametrize("country,name_a,name_b", TP_PAIRS)
def test_sprint2_tp_match_reverse(country, name_a, name_b):
    """strict_name_match must return True in the B→A direction (symmetry)."""
    import main_processor as mp
    assert mp.strict_name_match(name_b, name_a, country) is True


# ---- Single-token-brand rejection ---------------------------------------------

def test_sprint2_rejects_single_token_brand():
    """When stripping reduces either side to <2 meaningful tokens, reject."""
    import main_processor as mp
    # "Apex Ltd" → [apex], too short to trust
    assert mp.strict_name_match("Apex Ltd", "Apex Inc", "IN") is False


def test_sprint2_rejects_empty_after_strip():
    """All-stopword input rejected."""
    import main_processor as mp
    assert mp.strict_name_match("Ltd Pvt", "Inc Corp", "IN") is False
