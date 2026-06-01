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


from analysis.detectors import detect_over_merge, MatchedRow


def _row(rid, master, name, country="MX", mtype="PHONETIC_MATCH"):
    return MatchedRow(id=rid, master_code=master, name=name, country=country, match_type=mtype)


def test_over_merge_flags_dissimilar_cluster():
    rows = [
        _row(1, "M1", "WITTE, S.A. DE C.V."),
        _row(2, "M1", "AUDI MEXICO S.A. DE C.V."),
        _row(3, "M1", "KOHLER DE MEXICO S.A. DE C.V."),
    ]
    findings = detect_over_merge(rows, threshold=0.3)
    assert len(findings) == 1
    f = findings[0]
    assert f.master_code == "M1"
    assert f.member_count == 3
    assert f.mean_overlap < 0.3
    assert f.dominant_match_type == "PHONETIC_MATCH"


def test_over_merge_ignores_consistent_cluster():
    rows = [
        _row(1, "M2", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M2", "AUDI MEXICO SA DE CV"),
    ]
    assert detect_over_merge(rows, threshold=0.3) == []


def test_over_merge_ignores_singletons():
    rows = [_row(1, "M3", "WITTE, S.A. DE C.V.")]
    assert detect_over_merge(rows, threshold=0.3) == []


from analysis.detectors import detect_splits


def test_split_flags_same_core_different_master():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M11", "AUDI MEXICO SA DE CV"),  # aynı çekirdek, farklı master
    ]
    findings = detect_splits(rows)
    assert len(findings) == 1
    f = findings[0]
    assert f.core_signature == ("audi", "mexico")
    assert set(f.master_codes) == {"M10", "M11"}
    assert f.affected_rows == 2


def test_split_ignores_same_master():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V."),
        _row(2, "M10", "AUDI MEXICO SA DE CV"),
    ]
    assert detect_splits(rows) == []


def test_split_respects_country_boundary():
    rows = [
        _row(1, "M10", "AUDI MEXICO S.A. DE C.V.", country="MX"),
        _row(2, "M11", "AUDI MEXICO", country="US"),
    ]
    # Farklı ülke → split sayılmaz (country hard-filter)
    assert detect_splits(rows) == []
