# Tests for dedup_auto_merge — ES-side canonical-fingerprint master merge (Option-2).
# Pure planning logic is unit-tested; ES/PG I/O validated live (needs running ES).


def test_choose_primary_is_deterministic():
    import dedup.auto_merge as dam
    ids = ["c-3", "a-1", "b-2"]
    assert dam.choose_primary(ids) == dam.choose_primary(list(reversed(ids)))
    # deterministic = sorted first
    assert dam.choose_primary(ids) == "a-1"


def test_plan_merge_skips_single_master():
    import dedup.auto_merge as dam
    assert dam.plan_merge({"fingerprint": "acme", "country_code": "MX", "master_ids": ["m1"]}) is None


def test_plan_merge_skips_empty_fingerprint():
    """Boş fingerprint (yalnız yasal-ek/geo/çöp) → BİRLEŞTİRME (garbage magnet önlenir)."""
    import dedup.auto_merge as dam
    assert dam.plan_merge({"fingerprint": "", "country_code": "MX", "master_ids": ["m1", "m2"]}) is None
    assert dam.plan_merge({"fingerprint": "   ", "country_code": "MX", "master_ids": ["m1", "m2"]}) is None


def test_is_distinctive_fingerprint_respects_threshold():
    """Saf fonksiyon: eşik (min_token_len) parametrik. P-R2-1."""
    import dedup.auto_merge as dam
    # min=1 (config default şu an) → her boş-olmayan token ayırt edici sayılır (guard kapalı)
    assert dam._is_distinctive_fingerprint("m", min_token_len=1) is True
    assert dam._is_distinctive_fingerprint("g m", min_token_len=1) is True
    assert dam._is_distinctive_fingerprint("", min_token_len=1) is False  # boş yine reddedilir
    # min=2 → akronim-çökmesi ('m','g m') dejenere; gerçek kısa markalar (vf,3m) korunur
    assert dam._is_distinctive_fingerprint("m", min_token_len=2) is False
    assert dam._is_distinctive_fingerprint("g m", min_token_len=2) is False
    assert dam._is_distinctive_fingerprint("vf", min_token_len=2) is True
    assert dam._is_distinctive_fingerprint("3m", min_token_len=2) is True
    assert dam._is_distinctive_fingerprint("a bc", min_token_len=2) is True  # karışık → ayırt edici


def test_plan_merge_degenerate_guard_is_config_driven(monkeypatch):
    """plan_merge config.DEDUP_MIN_FINGERPRINT_TOKEN_LEN eşiğini kullanır.
    Default 1'de 'm' birleşir (guard kapalı); 2'ye çekilince magnet skip edilir."""
    import dedup.auto_merge as dam
    grp = {"fingerprint": "m", "country_code": "MX", "master_ids": ["m1", "m2"]}
    # Eşik 1 (default) → birleştir
    monkeypatch.setattr(dam, "DEDUP_MIN_FINGERPRINT_TOKEN_LEN", 1)
    assert dam.plan_merge(grp) is not None
    # Eşik 2 → dejenere magnet skip
    monkeypatch.setattr(dam, "DEDUP_MIN_FINGERPRINT_TOKEN_LEN", 2)
    assert dam.plan_merge(grp) is None
    # Gerçek kısa marka eşik 2'de bile korunur
    assert dam.plan_merge({"fingerprint": "vf", "country_code": "MX", "master_ids": ["m1", "m2"]}) is not None


def test_plan_merge_keeps_distinctive_fingerprint():
    """Ayırt edici (boş-olmayan) fingerprint → birleştir (default eşik 1)."""
    import dedup.auto_merge as dam
    assert dam.plan_merge({"fingerprint": "outdoor vf", "country_code": "MX", "master_ids": ["m1", "m2"]}) is not None
    assert dam.plan_merge({"fingerprint": "acme", "country_code": "MX", "master_ids": ["m1", "m2"]}) is not None


def test_plan_merge_builds_primary_and_secondaries():
    import dedup.auto_merge as dam
    plan = dam.plan_merge({"fingerprint": "acme", "country_code": "MX", "master_ids": ["m3", "m1", "m2"]})
    assert plan is not None
    assert plan["primary"] == "m1"
    assert sorted(plan["secondaries"]) == ["m2", "m3"]
    assert plan["country_code"] == "MX"


def test_plan_merge_requires_country():
    """country_code yoksa (hard-filter güvenliği) birleştirme yapma."""
    import dedup.auto_merge as dam
    assert dam.plan_merge({"fingerprint": "acme", "country_code": None, "master_ids": ["m1", "m2"]}) is None
    assert dam.plan_merge({"fingerprint": "acme", "country_code": "", "master_ids": ["m1", "m2"]}) is None


def test_apply_merge_repoints_pg_with_country_hard_filter_and_merges_es():
    """apply_merge: PG master_code repoint (country HARD FILTER param) + ES merge/delete
    + commit. ES get/update/delete routing=country ile çağrılmalı."""
    from unittest.mock import MagicMock
    import dedup.auto_merge as dam

    es = MagicMock()
    es.get.return_value = {"_source": {"variations": [{"name": "X"}], "variations_stripped": []}}
    cur = MagicMock(); cur.rowcount = 7
    conn = MagicMock()

    plan = {"primary": "m1", "secondaries": ["m2", "m3"], "country_code": "MX", "fingerprint": "acme"}
    res = dam.apply_merge(es, cur, conn, plan)

    assert res["ok"] and res["merged"] == 2 and res["repointed"] == 7
    # PG UPDATE: country_code hard-filter + ANY(secondaries) parametric
    sql_str = str(cur.execute.call_args[0][0])
    params = cur.execute.call_args[0][1]
    assert "UPDATE" in sql_str and "ANY(%s)" in sql_str and "country_code" in sql_str
    # A3: aynı UPDATE ikincil NEW_MASTER anchor'larını AUTO_DEDUP'a demote etmeli
    assert "match_type" in sql_str and "CASE" in sql_str.upper()
    assert params == ("m1", "NEW_MASTER", "AUTO_DEDUP", ["m2", "m3"], "MX")
    # ES merge+delete per secondary, with routing
    assert es.update.call_count == 2 and es.delete.call_count == 2
    for c in es.delete.call_args_list:
        assert c.kwargs.get("routing") is None
        assert c.kwargs.get("index") == "living_companies_mx"
    conn.commit.assert_called_once()


def test_apply_merge_rolls_back_on_error_without_commit():
    from unittest.mock import MagicMock
    import dedup.auto_merge as dam

    es = MagicMock()
    es.get.side_effect = RuntimeError("ES down")
    cur = MagicMock(); cur.rowcount = 3
    conn = MagicMock()

    plan = {"primary": "m1", "secondaries": ["m2"], "country_code": "MX", "fingerprint": "acme"}
    res = dam.apply_merge(es, cur, conn, plan)

    assert res["ok"] is False
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def _agg_page(buckets, after_key=None):
    page = {"buckets": buckets}
    if after_key is not None:
        page["after_key"] = after_key
    return {"aggregations": {"v": {"by_fp": page}}}


def _fp_bucket(fp, master_ids):
    return {"key": {"fp": fp}, "back": {"mids": {"buckets": [{"key": m} for m in master_ids]}}}


def test_iter_duplicate_groups_per_country_pagination_and_min_count():
    """iter_duplicate_groups: ülke-başına döngü, nested-agg parse, after_key sayfalama,
    <2 master atlama."""
    from unittest.mock import MagicMock
    import dedup.auto_merge as dam

    countries_resp = {"aggregations": {"cc": {"buckets": [{"key": "MX"}]}}}
    page1 = _agg_page(
        [_fp_bucket("acme", ["m1", "m2"]), _fp_bucket("solo", ["m9"])],  # solo: 1 master → atla
        after_key={"fp": "acme"},
    )
    page2 = _agg_page([_fp_bucket("globex", ["a", "b", "c"])], after_key=None)  # son sayfa

    es = MagicMock()
    es.search.side_effect = [countries_resp, page1, page2]

    groups = list(dam.iter_duplicate_groups(es))
    assert [g["fingerprint"] for g in groups] == ["acme", "globex"]
    assert groups[0] == {"fingerprint": "acme", "country_code": "MX", "master_ids": ["m1", "m2"]}
    assert groups[1]["master_ids"] == ["a", "b", "c"]
    # 1 ülke agg + 2 sayfa = 3 arama
    assert es.search.call_count == 3
    # her sayfa query'si country_code term filtresi içermeli (hard filter)
    page_call = es.search.call_args_list[1]
    assert page_call.kwargs["body"]["query"] == {"term": {"country_code": "MX"}}


def test_auto_merge_dry_run_counts_without_mutating(monkeypatch):
    import dedup.auto_merge as dam
    from unittest.mock import MagicMock

    fake_groups = [
        {"fingerprint": "acme", "country_code": "MX", "master_ids": ["m1", "m2", "m3"]},
        {"fingerprint": "", "country_code": "MX", "master_ids": ["x", "y"]},   # boş fp → skip
    ]
    monkeypatch.setattr(dam, "iter_duplicate_groups", lambda es, **k: iter(fake_groups))
    es = MagicMock(); conn = MagicMock()

    stats = dam.auto_merge_duplicates(es, conn, dry_run=True)
    assert stats["groups"] == 1 and stats["merged_masters"] == 2 and stats["skipped"] == 1
    es.indices.refresh.assert_not_called()   # dry-run → refresh yok
    conn.commit.assert_not_called()


def test_auto_merge_limit_stops_early(monkeypatch):
    import dedup.auto_merge as dam
    from unittest.mock import MagicMock

    fake_groups = [
        {"fingerprint": f"fp{i}", "country_code": "MX", "master_ids": [f"a{i}", f"b{i}"]}
        for i in range(5)
    ]
    monkeypatch.setattr(dam, "iter_duplicate_groups", lambda es, **k: iter(fake_groups))
    es = MagicMock(); conn = MagicMock()
    stats = dam.auto_merge_duplicates(es, conn, dry_run=True, limit=2)
    assert stats["groups"] == 2


def test_iter_duplicate_groups_restrict_scopes_to_master_ids():
    """restrict_master_ids verilince agg query master_id terms filtresiyle batch'e ölçeklenir
    (tüm index taranmaz)."""
    from unittest.mock import MagicMock
    import dedup.auto_merge as dam

    countries_resp = {"aggregations": {"cc": {"buckets": [{"key": "MX"}]}}}
    page = _agg_page([_fp_bucket("acme", ["m1", "m2"])], after_key=None)
    es = MagicMock()
    es.search.side_effect = [countries_resp, page]

    groups = list(dam.iter_duplicate_groups(es, restrict_master_ids=["m1", "m2", "m3"]))
    assert groups[0]["master_ids"] == ["m1", "m2"]
    # query bool/filter içinde master_id terms olmalı
    q = es.search.call_args_list[1].kwargs["body"]["query"]
    assert "bool" in q
    flts = q["bool"]["filter"]
    assert {"term": {"country_code": "MX"}} in flts
    assert any("terms" in f and f["terms"].get("master_id") == ["m1", "m2", "m3"] for f in flts)


def test_auto_merge_per_batch_no_refresh(monkeypatch):
    """Batch-içi kullanım: refresh=False iken ES refresh çağrılmaz (döngü kendi refresh eder)."""
    import dedup.auto_merge as dam
    from unittest.mock import MagicMock

    monkeypatch.setattr(dam, "iter_duplicate_groups",
                        lambda es, **k: iter([{"fingerprint": "acme", "country_code": "MX", "master_ids": ["m1", "m2"]}]))
    monkeypatch.setattr(dam, "apply_merge", lambda es, cur, conn, plan: {"ok": True, "merged": 1, "repointed": 1})
    es = MagicMock(); conn = MagicMock()
    stats = dam.auto_merge_duplicates(es, conn, restrict_master_ids=["m1", "m2"], refresh=False)
    assert stats["groups"] == 1 and stats["merged_masters"] == 1
    es.indices.refresh.assert_not_called()
