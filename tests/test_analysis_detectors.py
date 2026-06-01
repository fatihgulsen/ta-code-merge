from analysis.detectors import token_overlap


def test_token_overlap_identical():
    assert token_overlap(("audi", "mexico"), ("audi", "mexico")) == 1.0


def test_token_overlap_disjoint():
    assert token_overlap(("witte",), ("igsa",)) == 0.0


def test_token_overlap_partial():
    # kesişim={mexico}=1, birleşim={audi,mexico,kohler}=3 → 1/3
    assert abs(token_overlap(("audi", "mexico"), ("kohler", "mexico")) - 1 / 3) < 1e-9


def test_token_overlap_empty_is_zero():
    assert token_overlap((), ("x",)) == 0.0
    assert token_overlap((), ()) == 0.0
