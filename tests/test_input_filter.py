# Tests for input_filter.classify_input — boundary NON-FIRM detection (P0-B, narrowed).
# Philosophy: we CANNOT judge if a firm is "correct". A name made of codes/numbers/
# initials, or a very long name, MAY be a legitimate (new) firm → it must NOT be excluded.
# We exclude ONLY completely meaningless inputs: empty, punctuation-only, n/a/null
# markers, and explicit "no business name" placeholders. Everything else → NEW_MASTER.
import pytest

import core.input_filter as inf


@pytest.mark.parametrize("name,reason", [
    ("Sin Razon Social", "placeholder"),
    ("SIN RAZON SOCIAL", "placeholder"),
    ("Razon Social no determinada", "placeholder"),
    ("Razón Social no determinada", "placeholder"),   # aksanlı → aynı
    ("SAME AS", "placeholder"),                        # Round-4 #C: gümrük işaretçisi
    ("Same As CNEE", "placeholder"),                   # alıcı=gönderici (firma değil)
    ("SAME AS CONSIGNEE", "placeholder"),
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
    # Round-4 #C: "same as" placeholder TAM eşleşmedir — gerçek firma adında substring
    # olarak geçerse DIŞLANMAZ.
    "SAME AS GOOD TRADING S.A. DE C.V.",
])
def test_codes_numbers_initials_long_are_kept_as_new_firm(name):
    assert inf.classify_input(name, "MX") is None


def test_placeholder_is_country_scoped():
    assert inf.classify_input("sin razon social", "DE") is None
    assert inf.classify_input("sin razon social", "MX") == "placeholder"


@pytest.mark.parametrize("name", [
    # Non-Latin scripts carry real content → must NOT be excluded (P-R2-2 regression).
    # Real firms transliterated into Cyrillic in the source data.
    "ФОЛЬКСВАГЕН АГ",                 # Volkswagen AG
    "СИБУР ИНТЕРНЭШНЛ ГМБХ",          # SIBUR International GmbH
    "ООО УРАЛКАЛИЙ ТРЕЙДИНГ",         # Uralkali Trading
    "КИМИКА ЦЕНТРАЛЬ ДЕ МЕКСИКО",     # Quimica Central de Mexico
    "三菱商事株式会社",                 # CJK
    "ΑΛΦΑ ΒΗΤΑ",                      # Greek
])
def test_non_latin_real_firms_are_kept(name):
    assert inf.classify_input(name, "MX") is None


def test_na_marker_still_detected_after_unicode_norm():
    # Unicode-aware _norm must not regress structural NA markers / punctuation-only.
    assert inf.classify_input("#N/A", "MX") == "na_marker"
    assert inf.classify_input("s/n", "MX") == "na_marker"
    assert inf.classify_input("...,-/", "MX") == "no_alnum"
    assert inf.classify_input("Sin Razón Social", "MX") == "placeholder"
