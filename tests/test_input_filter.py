# Tests for input_filter.classify_input — boundary garbage/non-firm detection (P0-B).
# Pure function; no ES/PG. Identity decision is NOT made here — only "is this a firm name?".
import pytest

import input_filter as inf


@pytest.mark.parametrize("name,reason", [
    ("Sin Razon Social", "placeholder"),
    ("SIN RAZON SOCIAL", "placeholder"),
    ("Razon Social no determinada", "placeholder"),
    ("Razón Social no determinada", "placeholder"),   # aksanlı → aynı
    ("#N/A", "na_marker"),
    ("N/A", "na_marker"),
    ("NA", "placeholder"),                              # __common__ placeholder
    ("1234", "numeric"),
    ("101840", "numeric"),
    ("RQMT-00170/2017", "code"),
    ("DDI051109783", "code"),
    ("AIL-1264", "code"),
    ("CFR-0289", "code"),
    ("ONE150407DKA", "code"),
    ("C R M", "initials"),
    ("P. D. X", "initials"),
    ("B.V.G", "initials"),
    ("M.R.V.L", "initials"),
])
def test_garbage_inputs_flagged(name, reason):
    assert inf.classify_input(name, "MX") == reason


@pytest.mark.parametrize("name", [
    "AUDI MEXICO",
    "SIEMENS S.A. DE C.V.",
    "VIBRACOUSTIC DE MEXICO S.A. DE C.V.",
    "H&M HENNES & MAURITZ SERVICIOS",
    "3M MEXICO",
    "3M",                       # kısa marka — kod sanılmamalı
    "ACME, S.A. DE C.V.",
    "KUEHNE + NAGEL",
    "A.S",                      # 2 baş-harf — korunur (yalnız >=3 dışlanır)
    "INDUSTRIAS JOHN DEERE",
])
def test_valid_firm_names_pass(name):
    assert inf.classify_input(name, "MX") is None


def test_empty_and_whitespace():
    assert inf.classify_input("", "MX") == "empty"
    assert inf.classify_input("   ", "MX") == "empty"


def test_too_long_customs_string():
    long_customs = "QHE LOGISTICS MEXICO S DE RL DE MEXICO Manzanillo EGM 1 incoterm FOB ref 99887766"
    assert inf.classify_input(long_customs, "MX") == "too_long"


def test_only_punctuation_is_no_alnum():
    assert inf.classify_input("...,-/", "MX") == "no_alnum"


def test_placeholder_is_country_scoped():
    """MX placeholder başka ülkede placeholder sayılmamalı (yapısal değilse)."""
    # 'sin razon social' MX'e özel; DE'de placeholder listesi yok → None (yapısal da değil)
    assert inf.classify_input("sin razon social", "DE") is None
    assert inf.classify_input("sin razon social", "MX") == "placeholder"


def test_classify_input_reason_only_no_identity_decision():
    """classify_input bir firma adının GEÇERLİ olup olmadığını söyler; iki firmayı
    karşılaştırmaz (kimlik kararı vermez) — None ya da sebep stringi döner."""
    r = inf.classify_input("AUDI MEXICO", "MX")
    assert r is None or isinstance(r, str)
