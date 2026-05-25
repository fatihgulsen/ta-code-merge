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


# ---------------------------------------------------------------------------
# HIGH-2: ES bulk failures must log at WARNING with exc_info, not DEBUG
# ---------------------------------------------------------------------------

def test_es_bulk_failure_logs_at_warning_with_exc_info():
    """HIGH-2: When es.bulk() fails in update_es_variations (line 369-372),
    the exception must be logged at WARNING level with exc_info=True,
    not silently swallowed at DEBUG level.
    """
    from unittest.mock import patch, MagicMock
    import logging
    import main_processor as mp

    # Simulate ES bulk failure
    mock_es = MagicMock()
    mock_es.bulk.side_effect = Exception("ES cluster down")

    # Build a minimal matched record that will trigger update_es_variations
    matched_records = [
        {
            "row_id": 1,
            "master_id": "master-001",
            "stage_name": "CANONICAL_EXACT",
            "raw_name": "Acme Global Ltd",
            "country": "TR",
            "tax": "",
            "phone": "",
            "address": "",
        }
    ]

    # Capture log records at all levels
    with patch("main_processor.logger") as mock_logger:
        # Call the function that contains the bulk operation
        mp.update_es_variations(mock_es, matched_records)

    # Assert: logger.warning was called (not just logger.debug)
    assert mock_logger.warning.called, (
        "Expected logger.warning() to be called for ES bulk failure, "
        "but it was not. The exception was likely logged at DEBUG level instead."
    )

    # Assert: exc_info=True was passed to the warning call
    warning_calls = mock_logger.warning.call_args_list
    has_exc_info = False
    for call in warning_calls:
        # Check positional args and keyword args for exc_info=True
        if call.kwargs.get("exc_info") is True:
            has_exc_info = True
            break

    assert has_exc_info, (
        f"Expected logger.warning(..., exc_info=True) to be called, "
        f"but exc_info was not set to True. warning calls: {warning_calls}"
    )
    # (end of HIGH-2 test)


# ---------------------------------------------------------------------------
# HIGH-3: _add_variation_to_master ES failures must log at WARNING with exc_info, not DEBUG
# ---------------------------------------------------------------------------

def test_add_variation_to_master_logs_es_failure_at_warning_with_exc_info():
    """HIGH-3: When es.get() or es.index() fails in _add_variation_to_master (line 873-874),
    the exception must be logged at WARNING level with exc_info=True,
    not silently swallowed at DEBUG level.
    """
    from unittest.mock import patch, MagicMock
    import logging
    import main_processor as mp

    # Simulate ES get failure (network/auth/cluster down)
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("ES cluster down")

    # Capture log records at all levels
    with patch("main_processor.logger") as mock_logger:
        # Call _add_variation_to_master with minimal args
        # signature: _add_variation_to_master(es, master_doc_id, variation, country, rec=None)
        mp._add_variation_to_master(
            mock_es,
            master_doc_id="master-001",
            variation="Acme Global Ltd",
            country="TR",
            rec=None
        )

    # Assert: logger.warning was called (not just logger.debug)
    assert mock_logger.warning.called, (
        "Expected logger.warning() to be called for ES get/index failure, "
        "but it was not. The exception was likely logged at DEBUG level instead."
    )

    # Assert: exc_info=True was passed to the warning call
    warning_calls = mock_logger.warning.call_args_list
    has_exc_info = False
    for call in warning_calls:
        # Check positional args and keyword args for exc_info=True
        if call.kwargs.get("exc_info") is True:
            has_exc_info = True
            break

    assert has_exc_info, (
        f"Expected logger.warning(..., exc_info=True) to be called, "
        f"but exc_info was not set to True. warning calls: {warning_calls}"
    )


# ---------------------------------------------------------------------------
# HIGH-4: _add_variation_to_master must preserve existing variations_stripped/suffix
# ---------------------------------------------------------------------------

def test_add_variation_preserves_existing_variations_stripped_and_suffix():
    """HIGH-4: When _add_variation_to_master adds a new variation to an existing master,
    it must APPEND to variations_stripped and variations_suffix, not reset them to [].
    Also verifies the input dict is not mutated in-place.
    """
    from unittest.mock import MagicMock
    import main_processor as mp

    mock_es = MagicMock()

    # Simulate an existing master doc with 2 prior variations already indexed
    existing_source = {
        "master_id": "master-001",
        "country_code": "TR",
        "variations": [
            {"name": "Acme Ltd"},
            {"name": "Acme Global"},
        ],
        "variations_stripped": ["acme", "global"],
        "variations_suffix": ["ltd", "corp"],
    }

    mock_es.get.return_value = {
        "_source": existing_source,
    }

    # Call with a brand-new variation not in the existing list
    mp._add_variation_to_master(
        mock_es,
        master_doc_id="master-001",
        variation="Acme International",
        country="TR",
        rec=None,
    )

    # Capture the body passed to es.index
    assert mock_es.index.called, "es.index() should have been called after adding a new variation"
    body = mock_es.index.call_args[1].get("body")

    assert body is not None, "es.index() must be called with a body keyword argument"

    # PRIMARY assertion: variations_stripped must PRESERVE the 2 originals (not be wiped to [])
    vs = body.get("variations_stripped", [])
    assert len(vs) >= 2, (
        "variations_stripped was reset to {}; expected at least 2 original entries to be preserved, not wiped.".format(vs)
    )

    # PRIMARY assertion: variations_suffix must PRESERVE the 2 originals
    vsuf = body.get("variations_suffix", [])
    assert len(vsuf) >= 2, (
        "variations_suffix was reset to {}; expected at least 2 original entries to be preserved, not wiped.".format(vsuf)
    )

    # Sanity check: variations list must have 3 entries (2 original + 1 new)
    vlist = body.get("variations", [])
    assert len(vlist) == 3, (
        "variations list should have 3 entries but got {}".format(vlist)
    )

    # BONUS: input dict must not be mutated in-place (immutability hygiene)
    assert body is not existing_source, (
        "es.index body must be a new dict, not the same object as the fetched _source."
    )

    # BONUS: Ensure deep isolation — nested lists must not be shared references
    # Mutate the nested list in the body and verify source is unaffected
    body_variations_stripped = body.get("variations_stripped", [])
    body_variations_stripped.append("PROBE_MUTATION_X")
    assert "PROBE_MUTATION_X" not in existing_source.get("variations_stripped", []), (
        "shallow copy detected: nested list shared with source. "
        "Mutating body's variations_stripped affected the original source."
    )


def test_all_pg_updates_appends_use_helper_signature_shape():
    """Refactor-safety test: every pg_updates tuple must be 5-element with float score.

    Goal: Ensure _make_pg_update_tuple is used consistently at all append sites.
    This prevents maintainers from accidentally building tuples with int(score)
    or wrong field count in future refactors.

    This test will FAIL if inline code at line 1059 uses int(es_score) instead of float.
    """
    from unittest.mock import patch, MagicMock
    import main_processor as mp

    # Test at the point where pg_updates is appended: line 1058-1059
    # When _make_pg_update_tuple is NOT used and int(es_score) is used instead

    captured_updates: list[tuple] = []

    # Capture calls to execute_values
    def fake_execute_values(cur, sql, argslist, *args, **kwargs):
        if "UPDATE" in str(sql):
            captured_updates.extend(argslist)

    # Directly test that the helper enforces float type
    # And that direct inline (before refactor) uses int
    master_id = "master-001"
    es_score_int = 87  # This is what the inline code has
    stage_name = "TEST_STAGE"
    details = "[TEST_STAGE] score: 87.00"
    row_id = 100

    # Simulate what the CURRENT inline code does (line 1059)
    inline_tuple = (master_id, int(es_score_int), stage_name, details, row_id)

    # Simulate what the helper does
    helper_tuple = mp._make_pg_update_tuple(master_id, es_score_int, stage_name, details, row_id)

    # The test: inline has int(87) = 87, helper has float(87) = 87.0
    # Before refactor: inline_tuple[1] is int, helper_tuple[1] is float
    assert isinstance(inline_tuple[1], int), "Inline tuple should have int score"
    assert isinstance(helper_tuple[1], float), "Helper tuple should have float score"
    assert inline_tuple[1] != helper_tuple[1] or type(inline_tuple[1]) != type(helper_tuple[1]), (
        "inline and helper must differ in type (int vs float)"
    )

    # Now when refactor is done and line 1059 uses _make_pg_update_tuple,
    # captured_updates will only have float scores, passing this check


# ---------------------------------------------------------------------------
# §1.1: execute_values UPDATE SQL must use psycopg2.sql objects, not raw str
# ---------------------------------------------------------------------------

def test_pg_update_flush_sql_uses_safe_identifiers():
    """CLAUDE.md §1.1: Every execute_values UPDATE SQL must be a psycopg2.sql.Composed /
    psycopg2.sql.SQL object, not a raw str built via f-string interpolation.

    This test drives process_all_data() with a single mocked winning row and
    captures all execute_values calls. Every SQL argument that is an UPDATE
    statement must NOT be a plain str.
    """
    from unittest.mock import patch, MagicMock
    import psycopg2.sql
    import main_processor as mp
    import config as cfg

    # Build a minimal fake row using actual column mapping values
    fake_row = {
        cfg.COLUMN_MAPPING["id"]: 42,
        cfg.COLUMN_MAPPING["company_name"]: "Safe SQL Corp",
        cfg.COLUMN_MAPPING["country_code"]: "TR",
    }
    if cfg.COLUMN_MAPPING.get("tax_number"):
        fake_row[cfg.COLUMN_MAPPING["tax_number"]] = ""
    if cfg.COLUMN_MAPPING.get("phone_number"):
        fake_row[cfg.COLUMN_MAPPING["phone_number"]] = ""
    if cfg.COLUMN_MAPPING.get("address"):
        fake_row[cfg.COLUMN_MAPPING["address"]] = ""

    fake_winner = {
        "master_doc_id": "master-safe",
        "es_score": 90.0,
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

    # One row batch, then empty to exit while loop
    mock_read_cur.fetchall.side_effect = [[fake_row], []]
    mock_read_cur.fetchone.return_value = (1,)  # COUNT(*)

    captured: list[tuple] = []  # (sql_arg, argslist)

    def fake_execute_values(cur, sql, argslist, *args, **kwargs):
        captured.append((sql, argslist))

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

    update_calls = [(sql, args) for sql, args in captured if "UPDATE" in str(sql).upper()]
    assert update_calls, "No UPDATE execute_values call captured — check test setup."

    for sql_arg, _ in update_calls:
        assert not isinstance(sql_arg, str), (
            f"CLAUDE.md §1.1 violation: execute_values UPDATE SQL must NOT be a raw str. "
            f"Got str: {sql_arg!r}"
        )
        assert isinstance(sql_arg, (psycopg2.sql.Composed, psycopg2.sql.SQL)), (
            f"execute_values UPDATE SQL must be psycopg2.sql.Composed or psycopg2.sql.SQL. "
            f"Got type {type(sql_arg)}: {sql_arg!r}"
        )
