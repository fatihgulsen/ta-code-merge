# Tests for input_filter.classify_input — boundary NON-FIRM detection (P0-B, narrowed).
# Philosophy: we CANNOT judge if a firm is "correct". A name made of codes/numbers/
# initials, or a very long name, MAY be a legitimate (new) firm → it must NOT be excluded.
# We exclude ONLY completely meaningless inputs: empty, punctuation-only, n/a/null
# markers, and explicit "no business name" placeholders. Everything else → NEW_MASTER.
import pytest

import input_filter as inf


@pytest.mark.parametrize("name,reason", [
    ("Sin Razon Social", "placeholder"),
    ("SIN RAZON SOCIAL", "placeholder"),
    ("Razon Social no determinada", "placeholder"),
    ("Razón Social no determinada", "placeholder"),   # aksanlı → aynı
    ("#N/A", "na_marker"),
    ("N/A", "na_marker"),
    ("NA", "na_marker"),
    ("null", "na_marker"),
    ("NULL", "na_marker"),
    ("None", "na_marker"),
    ("nan", "na_marker"),
])
def test_meaningless_inputs_flagged(name, reason):
    assert inf.classify_input(name, "MX") == reason


def test_empty_and_whitespace():
    assert inf.classify_input("", "MX") == "empty"
    assert inf.classify_input("   ", "MX") == "empty"


def test_only_punctuation_is_no_alnum():
    assert inf.classify_input("...,-/", "MX") == "no_alnum"


@pytest.mark.parametrize("name", [
    # Real firms
    "AUDI MEXICO",
    "SIEMENS S.A. DE C.V.",
    "VIBRACOUSTIC DE MEXICO S.A. DE C.V.",
    "H&M HENNES & MAURITZ SERVICIOS",
    "3M MEXICO",
    "3M",
    "ACME, S.A. DE C.V.",
    "INDUSTRIAS JOHN DEERE",
    # NOT excluded anymore (may be a legitimate new firm — code/number/initials/long):
    "RQMT-00170/2017",
    "DDI051109783",
    "AIL-1264",
    "CFR-0289",
    "1234",
    "101840",
    "C R M",
    "P. D. X",
    "B.V.G",
    "A.S",
    "QHE LOGISTICS MEXICO S DE RL DE MEXICO Manzanillo EGM 1 incoterm FOB ref 99887766",
])
def test_codes_numbers_initials_long_are_kept_as_new_firm(name):
    assert inf.classify_input(name, "MX") is None


def test_placeholder_is_country_scoped():
    assert inf.classify_input("sin razon social", "DE") is None
    assert inf.classify_input("sin razon social", "MX") == "placeholder"
