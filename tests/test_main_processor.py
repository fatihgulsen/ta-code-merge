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
