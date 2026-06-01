# Match Details Column Fix Design

## Background
The `main_processor.py` orchestrator attempts to write stage matching logic details into the `match_details` column of the `p7_firms_v2` tracking table. However, since `match_details` is not currently tracked by the system's `MANDATORY_UPDATE_COLUMNS` schema verifier, the program fails with an `UndefinedColumn` error during its batch database updates.

## Architecture & Code Changes
1. **Target**: `config.py`
2. **Action**: Expand `MANDATORY_UPDATE_COLUMNS` from `["master_code", "match_score", "match_type"]` to `["master_code", "match_score", "match_type", "match_details"]`.
3. **Execution Flow**: When `main_processor.py` runs, `validate_db_schema()` will detect that `match_details` is missing from the database and will leverage the `AUTO_CREATE_UPDATE_COLUMNS = True` flag to automatically issue an `ALTER TABLE p7_firms_v2 ADD COLUMN match_details TEXT;` query.

## Error Handling & Testing
- The system naturally handles the column addition because `col_type` defaults to `TEXT` for unrecognized internal column names in `validate_db_schema()`, which perfectly fits the string format of `match_details` (e.g., `[CANONICAL_EXACT] score: 100.00`).
- No complex data migrations are needed. Restarting `main_processor.py` will smoothly verify schema and resume processing unmatched records.
