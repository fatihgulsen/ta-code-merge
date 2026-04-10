"""Regression tests for matching accuracy.

Each false positive from docs/superpowers/specs/2026-04-10-pg-es-matching-accuracy-audit-design.md §2
is encoded as a test case that must return False from _post_verify after Sprint 1.

Each true positive from §2.5 must continue to return True — these guard against recall collapse.
"""
from __future__ import annotations

import pytest


def _master_source(variations: list[str], variations_stripped: list[str] | None = None) -> dict:
    """Build a minimal master doc as returned by Elasticsearch.

    For SUFFIX_FUZZY the _post_verify reads variations_stripped; caller must supply it.
    For the other stages the first element of variations is used as the canonical master name.
    """
    return {
        "variations": variations,
        "variations_stripped": variations_stripped if variations_stripped is not None else [],
    }


# ---- Positive controls (§2.5) -------------------------------------------------
# These are the benign variations the system already handles correctly. They must keep passing.

POSITIVE_CONTROLS_CANONICAL: list[tuple[str, str, str]] = [
    # (country, input_name, master_variation_as_stored_in_ES)
    # NOTE: master_variation must be the POST-ingest-cleaned form, because
    # _post_verify reads master_source["variations"][0] which ES stores after
    # running the clean_script pipeline (lowercase, dot-between-letters removed,
    # punctuation normalised).
    ("IN", "ISHA ENTERPRISES", "isha enterprise."),
    ("IN", "J. J. OVERSEAS", "j j overseas"),
    ("IN", "BALAJI IMPEX ,,", "balaji impex."),
    ("IN", "KRISHNA OVERSEAS .", "krishna overseas,."),
    ("IN", "KT INTERNATIONAL", "kt international"),  # k.t. → kt via ingest
    ("IN", "ARIHANT ENTERPRISES ,,", "arihant enterprise.."),
    ("IN", "J. M. CORPORATION", "j m corporation."),
]


@pytest.mark.parametrize("country,input_name,master_variation", POSITIVE_CONTROLS_CANONICAL)
def test_canonical_exact_positive_controls_still_match(country, input_name, master_variation):
    """True positives from spec §2.5 must continue to return True."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "CANONICAL_EXACT", country) is True


# ---- False positives — CANONICAL_EXACT (§2.1) --------------------------------

FP_CANONICAL: list[tuple[str, str, str]] = [
    ("IN", "JAY CHEMICAL INDUSTRIES PRIVATE LIMITED", "jay & co."),
    ("IN", "IMPERIAL AUTO INDUSTRIES LIMITED", "hotel imperial"),
    ("IN", "AJANTA PHARMA LIMITED", "ajanta industries,"),
    ("IN", "ATUL LIMITED", "atul commodities pvt. ltd."),
    ("IN", "LIFE.", "agri life"),
    ("IN", "ELECTRO", "ag electro services"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_CANONICAL)
def test_canonical_exact_false_positives_rejected(country, input_name, master_variation):
    """False positives from spec §2.1 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "CANONICAL_EXACT", country) is False


# ---- False positives — STRIPPED_EXACT (§2.2) ---------------------------------

FP_STRIPPED: list[tuple[str, str, str]] = [
    ("IN", "GOEL STEEL COMPANY", "goel enterprises.."),
    ("IN", "ANAND TECHNOLOGIES,", "anand enterprises,,_"),
    ("IN", "GLOBAL CARE", "care enterprises"),
    ("IN", "DYNAMIC TRADERS.", "auto dynamic corporation"),
    ("IN", "APEX INDUSTRIES,.", "apex auto limited,"),
    ("IN", "AH CHEMICALS PVT. LTD.", "a.h. international"),
    ("IN", "ARIHANT TRADERS..", "arihant enterprise.."),
    ("IN", "AKSHAYA TEXTILE,", "akshaya corp,"),
    ("IN", "KAMAL INDUSTRIES,", "kamal international."),
    ("IN", "HARSH INTERNATIONAL..", "harsh agencies."),
    ("IN", "AMAN INTERNATIONAL,,", "aman trading co."),
    ("IN", "LAKSHMI METALS", "lakshmi agencies."),
    ("IN", "LAXMI ELECTRONICS.", "laxmi agro industrial consultants and"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_STRIPPED)
def test_stripped_exact_false_positives_rejected(country, input_name, master_variation):
    """False positives from spec §2.2 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "STRIPPED_EXACT", country) is False


# ---- False positives — SUFFIX_FUZZY (§2.3) -----------------------------------
# SUFFIX_FUZZY reads variations_stripped; supply a realistic stripped form.

FP_SUFFIX_FUZZY: list[tuple[str, str, str, list[str]]] = [
    # (country, input_name, master_variation, master_variations_stripped)
    ("IN", "ACE INDUSTRIES-", "ace aviation (prop: john penry evans)", ["ace aviation"]),
    ("IN", "DELTA TEXTTILES", "delta electronics", ["delta electronics"]),
    ("IN", "EXCEL METAL ENGINEERING PVT.LTD,", "excel communications", ["excel communications"]),
    ("IN", "GALAXY INDUSTRIES_", "galaxy.", ["galaxy"]),
    ("IN", "INDIAN CHEMICAL CORPORATION", "indian trading corporation.", ["indian trading"]),
    ("IN", "AGGARWAL ELECTRIC CO.", "aggarwal & co.", ["aggarwal and"]),
    ("IN", "APEX TRADERS,;", "apex auto limited,", ["apex auto"]),
    ("IN", "ANIL ENTERPRISES-", "anil agencies pvt.ltd", ["anil agencies"]),
]


@pytest.mark.parametrize("country,input_name,master_variation,master_stripped", FP_SUFFIX_FUZZY)
def test_suffix_fuzzy_false_positives_rejected(country, input_name, master_variation, master_stripped):
    """False positives from spec §2.3 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation], master_stripped)
    assert mp._post_verify(input_name, master, "SUFFIX_FUZZY", country) is False


# ---- False positives — TOKEN_COVERAGE (§2.4) ---------------------------------

FP_TOKEN_COVERAGE: list[tuple[str, str, str]] = [
    ("IN", "KAY BEE TRADING CO.,", "bee kay enterprises"),
    ("IN", "KAY DEE ENTERPRISES", "dee kay exports"),
]


@pytest.mark.parametrize("country,input_name,master_variation", FP_TOKEN_COVERAGE)
def test_token_coverage_false_positives_rejected(country, input_name, master_variation):
    """Order-swap false positives from spec §2.4 must return False after Sprint 1 hardening."""
    import main_processor as mp

    master = _master_source([master_variation])
    assert mp._post_verify(input_name, master, "TOKEN_COVERAGE", country) is False
