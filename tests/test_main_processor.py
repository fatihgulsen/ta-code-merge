# tests/test_main_processor.py
from unittest.mock import MagicMock


def _make_es_hit(master_id: str, score: float = 80.0, variations: list[str] | None = None) -> dict:
    return {
        "_source": {
            "master_id": master_id,
            "variations": variations if variations is not None else [],
        },
        "_score": score,
    }


def _make_msearch_response(hits_per_query: list[list[dict]]) -> dict:
    """Her sorgu için hit listesi içeren msearch yanıtı üretir."""
    return {
        "responses": [
            {"hits": {"hits": hits, "total": {"value": len(hits)}}}
            for hits in hits_per_query
        ]
    }


def test_run_stage_returns_matched_and_unmatched():
    """Eşleşen kayıtlar matched, eşleşmeyenler unmatched listesine girer."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Global Ltd", "country": "TR", "tax": "", "phone": ""},
        {"row_id": 2, "raw_name": "Beta Holdings Corp", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "CANONICAL_EXACT", "order": 2, "query_fn": "CANONICAL_EXACT",
             "min_score": 50.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=80.0, variations=["Acme Global Ltd"])],  # record 1 eşleşti
        [],                                                                          # record 2 eşleşmedi
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 1
    assert matched[0]["row_id"] == 1
    assert matched[0]["master_id"] == "master-001"
    assert matched[0]["stage_name"] == "CANONICAL_EXACT"

    assert len(unmatched) == 1
    assert unmatched[0]["row_id"] == 2


def test_run_stage_respects_min_score():
    """min_score altındaki hit'ler eşleşme sayılmaz."""
    import main_processor as mp

    records = [
        {"row_id": 1, "raw_name": "Acme Ltd", "country": "TR", "tax": "", "phone": ""},
    ]
    stage = {"name": "NGRAM_MATCH", "order": 6, "query_fn": "NGRAM_MATCH",
             "min_score": 3.0, "enabled": True}

    mock_es = MagicMock()
    mock_es.msearch.return_value = _make_msearch_response([
        [_make_es_hit("master-001", score=1.5)],  # min_score altında
    ])

    matched, unmatched = mp.run_stage(mock_es, records, stage)

    assert len(matched) == 0
    assert len(unmatched) == 1


def test_country_code_filter_uses_parametric_sql():
    """COUNTRY_CODE_FILTER değeri SQL string'ine gömülmemeli; parametre olarak geçilmeli (CLAUDE.md §1.1)."""
    from unittest.mock import patch, call as mcall
    import main_processor as mp
    import config

    original_filter = config.COUNTRY_CODE_FILTER
    original_mp_filter = mp.COUNTRY_CODE_FILTER

    try:
        # Force COUNTRY_CODE_FILTER to a non-None value so the branch executes
        config.COUNTRY_CODE_FILTER = "TR"
        mp.COUNTRY_CODE_FILTER = "TR"

        # One shared cursor mock for all cursor() calls on both connections
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = [0]   # COUNT(*) returns 0 → skips while loop
        mock_cur.fetchall.return_value = []     # batch fetch returns empty → loop exits

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(mp, "get_db_connection", return_value=mock_conn), \
             patch.object(mp, "get_es_client", MagicMock()), \
             patch.object(mp, "create_index", MagicMock()), \
             patch.object(mp, "register_all_pipelines", MagicMock()), \
             patch.object(mp, "validate_db_schema", MagicMock()), \
             patch.object(mp, "ensure_stage_log_table", MagicMock()), \
             patch.object(mp, "STAGES", []):

            try:
                mp.process_all_data()
            except Exception:
                pass  # Interested only in what SQL was executed

        # Collect all execute() calls across all cursors
        assert mock_cur.execute.called, "cursor.execute was never called at all"

        all_calls = mock_cur.execute.call_args_list

        # Find the COUNT(*) call — it's the first execute on count_cur
        count_call = all_calls[0]
        sql_arg = count_call.args[0] if count_call.args else str(count_call)
        sql_text = str(sql_arg)

        # ASSERT 1: the literal "'TR'" string must NOT be embedded in the SQL text
        assert "'TR'" not in sql_text, (
            f"SQL injection vector detected: value 'TR' is hardcoded in SQL: {sql_text!r}"
        )

        # ASSERT 2: "TR" must appear in the params passed to at least one execute call
        tr_in_params = False
        for c in all_calls:
            params = c.args[1] if len(c.args) > 1 else None
            if params and "TR" in (str(p) for p in params):
                tr_in_params = True
                break
        assert tr_in_params, (
            "COUNTRY_CODE_FILTER='TR' was never passed as a SQL parameter. "
            "It must be passed via the params argument to cur.execute(sql, params)."
        )

    finally:
        config.COUNTRY_CODE_FILTER = original_filter
        mp.COUNTRY_CODE_FILTER = original_mp_filter


def test_validate_db_schema_uses_safe_identifiers():
    """ALTER TABLE DDL in validate_db_schema must use psycopg2.sql objects, not raw f-strings (CLAUDE.md §1.1)."""
    from unittest.mock import patch, MagicMock, call as mcall
    import psycopg2.sql
    import main_processor as mp

    # Simulate: table exists, mandatory read columns present, one update column missing
    # so the ALTER TABLE branch executes.
    mock_cur = MagicMock()

    # fetchone()[0] -> True (table exists)
    # fetchall() -> existing_columns (all MANDATORY_READ_COLUMNS present, update columns absent)
    mandatory_read_cols = {mp.COLUMN_MAPPING.get(n) for n in mp.MANDATORY_READ_COLUMNS if mp.COLUMN_MAPPING.get(n)}
    mock_cur.fetchone.return_value = (True,)
    mock_cur.fetchall.return_value = [(col,) for col in mandatory_read_cols]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch.object(mp, "AUTO_CREATE_UPDATE_COLUMNS", True):
        mp.validate_db_schema(mock_conn)

    # Find ALTER TABLE calls among all execute() calls
    alter_calls = [
        c for c in mock_cur.execute.call_args_list
        if "ALTER" in str(c.args[0]).upper()
    ]

    assert alter_calls, "Expected at least one ALTER TABLE execute() call — none found."

    for c in alter_calls:
        sql_arg = c.args[0]
        assert not isinstance(sql_arg, str), (
            f"ALTER TABLE SQL must NOT be a raw str (f-string injection risk). "
            f"Got: {sql_arg!r}"
        )
        assert isinstance(sql_arg, (psycopg2.sql.Composed, psycopg2.sql.SQL)), (
            f"ALTER TABLE SQL must be psycopg2.sql.Composed or psycopg2.sql.SQL. "
            f"Got type {type(sql_arg)}: {sql_arg!r}"
        )


# ---------------------------------------------------------------------------
# C3 + C4: pg_updates tuple shape consistency
# ---------------------------------------------------------------------------

def test_create_new_masters_produces_5_element_tuple():
    """C3: create_new_masters must append 5-element tuples to pg_updates (not 4-element).
    The missing field is 'details'. This test will FAIL before the fix at line 594."""
    from unittest.mock import patch, MagicMock, call as mcall
    import main_processor as mp

    records = [
        {"row_id": 10, "raw_name": "Alpha Corp", "country": "TR", "tax": "", "phone": "", "address": ""},
        {"row_id": 11, "raw_name": "Beta Ltd", "country": "DE", "tax": "", "phone": "", "address": ""},
    ]

    mock_es = MagicMock()
    # helpers.bulk should succeed silently
    mock_write_cursor = MagicMock()
    mock_write_conn = MagicMock()

    captured_updates: list[tuple] = []

    original_execute_values = None

    def fake_execute_values(cur, sql, argslist, *args, **kwargs):
        # Capture pg_updates passed to the UPDATE execute_values call
        if "UPDATE" in str(sql):
            captured_updates.extend(argslist)

    with patch.object(mp, "execute_values", side_effect=fake_execute_values), \
         patch("main_processor.helpers.bulk", return_value=(2, [])), \
         patch.object(mp, "NEW_MASTER_SUBBATCH_SIZE", 10), \
         patch.object(mp, "ES_INDEX", "test_index"):
        mp.create_new_masters(mock_es, mock_write_cursor, mock_write_conn, records)

    assert captured_updates, "No pg_updates were flushed — create_new_masters must call execute_values."
    for tup in captured_updates:
        assert len(tup) == 5, (
            f"Each pg_updates tuple must have 5 elements "
            f"(master_id, score, stage_name, details, row_id) but got {len(tup)}: {tup!r}"
        )


def test_batch_end_flush_sql_binds_all_5_columns():
    """C4: The batch-end flush SQL (lines ~1149-1155) must bind all 5 columns including
    match_details (d.md). Currently it only binds 4 — this test will FAIL before the fix."""
    from unittest.mock import patch, MagicMock
    import main_processor as mp

    # We inspect the SQL passed to execute_values in the batch-end flush path.
    # The batch-end flush fires when pg_updates is non-empty at end of a chunk.
    # We feed exactly one row so the periodic flush (ES_REFRESH_INTERVAL) never fires.

    captured_sqls: list[str] = []

    def fake_execute_values(cur, sql, argslist, *args, **kwargs):
        captured_sqls.append(str(sql))

    # Minimal row dict that satisfies process_all_data's inner loop.
    # Keys must match COLUMN_MAPPING values: id="id", company_name="name",
    # country_code="country_code", tax_number="tax_number", phone_number="tel", address="address".
    import config as cfg
    fake_row = {
        cfg.COLUMN_MAPPING["id"]: 99,
        cfg.COLUMN_MAPPING["company_name"]: "Gamma GmbH",
        cfg.COLUMN_MAPPING["country_code"]: "DE",
    }
    if cfg.COLUMN_MAPPING.get("tax_number"):
        fake_row[cfg.COLUMN_MAPPING["tax_number"]] = ""
    if cfg.COLUMN_MAPPING.get("phone_number"):
        fake_row[cfg.COLUMN_MAPPING["phone_number"]] = ""
    if cfg.COLUMN_MAPPING.get("address"):
        fake_row[cfg.COLUMN_MAPPING["address"]] = ""

    # match_single_record returns a winner so no _index_new_master needed
    fake_winner = {
        "master_doc_id": "master-xyz",
        "es_score": 85.0,
        "stage_name": "CANONICAL_EXACT",
        "index_variation": False,
    }

    mock_es = MagicMock()
    mock_read_conn = MagicMock()
    mock_write_conn = MagicMock()
    mock_read_cur = MagicMock()
    mock_write_cur = MagicMock()

    mock_read_conn.cursor.return_value = mock_read_cur
    mock_write_conn.cursor.return_value = mock_write_cur

    # First fetchall returns our one row, second returns [] to break the while loop
    mock_read_cur.fetchall.side_effect = [[fake_row], []]
    mock_read_cur.fetchone.return_value = (1,)  # count query

    with patch.object(mp, "get_db_connection", side_effect=[mock_read_conn, mock_write_conn]), \
         patch.object(mp, "match_single_record", return_value={"winner": fake_winner, "trace": []}), \
         patch.object(mp, "execute_values", side_effect=fake_execute_values), \
         patch.object(mp, "validate_db_schema"), \
         patch.object(mp, "ensure_stage_log_table"), \
         patch.object(mp, "ES_REFRESH_INTERVAL", 1000), \
         patch.object(mp, "BATCH_SIZE", 10), \
         patch.object(mp, "ES_INDEX", "test_index"), \
         patch.object(mp, "RAW_TABLE_NAME", "raw_firms"), \
         patch("main_processor.get_es_client", return_value=mock_es), \
         patch("main_processor.create_index"), \
         patch("main_processor.register_all_pipelines"):
        mp.process_all_data()

    # Find the UPDATE SQL calls — the batch-end flush should be among them
    update_sqls = [s for s in captured_sqls if "UPDATE" in s.upper()]
    assert update_sqls, "No UPDATE execute_values call captured — check test setup."

    for sql in update_sqls:
        assert "d.md" in sql, (
            f"Batch-end flush SQL must bind match_details via 'd.md' column alias, "
            f"but it was absent. SQL: {sql!r}"
        )
        # Normalise whitespace to check for the 5-bind column alias list
        sql_compact = " ".join(sql.split())
        assert "d(mc, ms, mt, md, id)" in sql_compact, (
            f"Batch-end flush SQL must include 'd(mc, ms, mt, md, id)' (5 binds), "
            f"but got: {sql!r}"
        )


# ---------------------------------------------------------------------------
# HIGH-1: Per-row exception must not halt the batch loop (CLAUDE.md §1.3)
# ---------------------------------------------------------------------------

def test_per_row_exception_does_not_halt_batch():
    """HIGH-1: When a single row raises during match_single_record, the loop
    must log the error and continue processing remaining rows (CLAUDE.md §1.3).
    """
    from unittest.mock import patch, MagicMock, call as mcall
    import logging
    import main_processor as mp
    import config as cfg

    # Build three fake rows using actual column mapping keys
    def _make_row(row_id, name, country="TR"):
        row = {
            cfg.COLUMN_MAPPING["id"]: row_id,
            cfg.COLUMN_MAPPING["company_name"]: name,
            cfg.COLUMN_MAPPING["country_code"]: country,
        }
        if cfg.COLUMN_MAPPING.get("tax_number"):
            row[cfg.COLUMN_MAPPING["tax_number"]] = ""
        if cfg.COLUMN_MAPPING.get("phone_number"):
            row[cfg.COLUMN_MAPPING["phone_number"]] = ""
        if cfg.COLUMN_MAPPING.get("address"):
            row[cfg.COLUMN_MAPPING["address"]] = ""
        return row

    row1 = _make_row(101, "Alpha Ltd")
    row2 = _make_row(102, "Boom Corp")   # will raise
    row3 = _make_row(103, "Gamma GmbH")

    fake_winner = {
        "master_doc_id": "master-ok",
        "es_score": 80.0,
        "stage_name": "CANONICAL_EXACT",
        "index_variation": False,
    }

    # match_single_record: OK for row1, raises for row2, OK for row3
    call_results = [
        {"winner": fake_winner, "trace": []},   # row1
        Exception("boom — row2 explodes"),       # row2
        {"winner": fake_winner, "trace": []},   # row3
    ]

    def side_effect_match(*args, **kwargs):
        result = call_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_es = MagicMock()
    mock_read_conn = MagicMock()
    mock_write_conn = MagicMock()
    mock_read_cur = MagicMock()
    mock_write_cur = MagicMock()

    mock_read_conn.cursor.return_value = mock_read_cur
    mock_write_conn.cursor.return_value = mock_write_cur

    # First fetchall: returns 3-row batch; second: empty → exits while loop
    mock_read_cur.fetchall.side_effect = [[row1, row2, row3], []]
    mock_read_cur.fetchone.return_value = (3,)  # COUNT(*) = 3

    captured_updates: list[tuple] = []

    def fake_execute_values(cur, sql, argslist, *args, **kwargs):
        if "UPDATE" in str(sql).upper():
            captured_updates.extend(argslist)

    with patch.object(mp, "get_db_connection", side_effect=[mock_read_conn, mock_write_conn]), \
         patch.object(mp, "match_single_record", side_effect=side_effect_match), \
         patch.object(mp, "execute_values", side_effect=fake_execute_values), \
         patch.object(mp, "validate_db_schema"), \
         patch.object(mp, "ensure_stage_log_table"), \
         patch.object(mp, "ES_REFRESH_INTERVAL", 1000), \
         patch.object(mp, "BATCH_SIZE", 10), \
         patch.object(mp, "ES_INDEX", "test_index"), \
         patch.object(mp, "RAW_TABLE_NAME", "raw_firms"), \
         patch("main_processor.get_es_client", return_value=mock_es), \
         patch("main_processor.create_index"), \
         patch("main_processor.register_all_pipelines"), \
         patch("main_processor.logger") as mock_logger:
        # Must NOT raise — per-row exception should be swallowed, logged, loop continues
        mp.process_all_data()

    # Row 1 (id=101) and Row 3 (id=103) must have been added to pg_updates
    processed_row_ids = [tup[4] for tup in captured_updates]  # 5th element is row_id
    assert 101 in processed_row_ids, (
        f"Row 101 (row1) should have been processed. pg_updates row_ids: {processed_row_ids}"
    )
    assert 103 in processed_row_ids, (
        f"Row 103 (row3) should have been processed after row2 failed. "
        f"pg_updates row_ids: {processed_row_ids}"
    )

    # The failure for row 2 must have been logged
    logged = (
        mock_logger.exception.called
        or mock_logger.error.called
    )
    assert logged, (
        "Expected logger.exception() or logger.error() to be called for the failing row, "
        "but neither was called."
    )
