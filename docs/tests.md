# Test Reference — Ambient Code Context Engine (Layer 2)

> **120 tests · 6 modules · all pass in < 5 seconds**
>
> Run: `cd context-engine && pytest tests/ -v`

---

## Table of Contents

1. [Overview](#overview)
2. [Test Infrastructure](#test-infrastructure)
3. [test_models.py — 19 tests](#test_modelspy--19-tests)
4. [test_tailer.py — 17 tests](#test_tailerpy--17-tests)
5. [test_store.py — 23 tests](#test_storepy--23-tests)
6. [test_symbol_index.py — 22 tests](#test_symbol_indexpytest_symbol_indexpy--22-tests)
7. [test_velocity.py — 16 tests](#test_velocitypy--16-tests)
8. [test_integration.py — 13 tests](#test_integrationpy--13-tests)
9. [Coverage Map](#coverage-map)

---

## Overview

| Module | Class(es) / Area | Tests |
|---|---|---|
| `test_models.py` | `CodeEvent`, `EventType`, metadata accessors, `Symbol` | 19 |
| `test_tailer.py` | `Tailer` — file reading, cursor, crash safety | 17 |
| `test_store.py` | `Store` — schema, events, symbols, velocity | 23 |
| `test_symbol_index.py` | `SymbolIndexer` — Python, TypeScript, JavaScript, edge cases | 22 |
| `test_velocity.py` | `VelocityTracker` — record, hot_files, file_trend, UTC helper | 16 |
| `test_integration.py` | Full NDJSON → `ContextEngine` → SQLite pipeline | 13 |
| **Total** | | **120** |

All tests are isolated: they use pytest's `tmp_path` fixture and write nothing outside the OS temp directory. No VS Code, running extension, or network access is required.

---

## Test Infrastructure

### `tests/conftest.py`

Shared fixtures and event factories used across all modules.

#### Fixtures

| Fixture | Type | Description |
|---|---|---|
| `store` | `Store` | Fresh `Store` backed by a temp SQLite file; automatically closed after each test |
| `sample_file_save` | `CodeEvent` | A `file_save` event whose `file_path` points to a real temp Python source file (`auth.py`) |
| `ndjson_log` | `tuple[Path, list[CodeEvent]]` | Writes three events to a temp NDJSON file and returns `(path, events)` |

#### Event Factories

| Factory | Event type | Key parameters |
|---|---|---|
| `make_file_save_event(file_path, workspace, language, lines_added, lines_removed, timestamp)` | `file_save` | All optional; defaults to a Python file save with `linesAdded=5, linesRemoved=1` |
| `make_file_change_event(file_path, workspace)` | `file_change` | Emits an in-progress edit with `isPaste=False` |
| `make_cursor_move_event(file_path, workspace, line, character)` | `cursor_move` | Defaults to `line=10, character=4` |
| `make_git_event(workspace, action, branch, previous_branch)` | `git_event` | Defaults to a `branch_change` from `main` to `feature/x` |

---

## `test_models.py` — 19 tests

**Module under test:** `ambient/models.py`

Tests that all four event types are parsed correctly from JSON, that camelCase aliases are honoured, that typed metadata accessors return the right model, and that invalid input is rejected.

---

### Class `TestCodeEventParsing` — 11 tests

#### `test_file_save_parses_correctly`
Parses a complete `file_save` JSON line and asserts all five required fields: `event_type`, `file_path`, `workspace`, `language`, `timestamp`. Also asserts `diff` is not `None`.

#### `test_file_change_parses_correctly`
Parses a `file_change` JSON line. Asserts `event_type == EventType.FILE_CHANGE`.

#### `test_cursor_move_parses_correctly`
Parses a `cursor_move` JSON line. Asserts `event_type == EventType.CURSOR_MOVE` and `diff is None` (cursor moves carry no diff).

#### `test_git_event_parses_correctly`
Parses a `git_event` JSON line. Asserts `event_type == EventType.GIT_EVENT` and `language == ""` (git events have no language).

#### `test_camelcase_file_path_alias`
Asserts that the JSON key `filePath` (camelCase) maps to `event.file_path` (snake_case) in the Python model. Tests both via `model_validate_json` and `model_validate`.

#### `test_snake_case_file_path_also_accepted`
Asserts that `file_path` (snake_case) is also accepted as an input key because the model is configured with `populate_by_name=True`.

#### `test_event_type_alias`
Asserts that the JSON key `type` maps to `event.event_type` in the Python model.

#### `test_optional_diff_defaults_to_none`
Constructs a `cursor_move` event without a `diff` field. Asserts `event.diff is None`.

#### `test_optional_metadata_defaults_to_none`
Constructs a `cursor_move` event without a `metadata` field. Asserts `event.metadata is None`.

#### `test_invalid_event_type_raises_validation_error`
Passes `"unknown_future_type"` as the `type` field. Asserts Pydantic raises `ValidationError` (enum validation is strict).

#### `test_missing_required_field_raises_validation_error`
Omits the required `timestamp` field. Asserts Pydantic raises `ValidationError`.

#### `test_extra_fields_are_ignored`
Passes an extra field `unknownField` that is not in the schema. Asserts the event is still parsed successfully (unknown fields are silently ignored).

---

### Class `TestMetadataAccessors` — 8 tests

#### `test_file_save_returns_file_change_metadata`
Calls `event.as_file_change_metadata()` on a `file_save` event. Asserts it returns a `FileChangeMetadata` instance with `lines_added=4`, `lines_removed=1`, `is_paste=False`.

#### `test_file_change_returns_file_change_metadata`
Calls `event.as_file_change_metadata()` on a `file_change` event. Asserts it returns `FileChangeMetadata` with `is_paste=True`, `lines_added=50`.

#### `test_cursor_move_returns_none_for_file_change_metadata`
Calls `event.as_file_change_metadata()` on a `cursor_move` event. Asserts the return value is `None` (wrong event type).

#### `test_cursor_move_returns_cursor_metadata`
Calls `event.as_cursor_move_metadata()` on a `cursor_move` event. Asserts it returns `CursorMoveMetadata` with `line=42`, `character=8`.

#### `test_git_event_returns_git_metadata`
Calls `event.as_git_event_metadata()` on a `git_event`. Asserts it returns `GitEventMetadata` with `action="branch_change"`, `branch="feature/auth"`, `previous_branch="main"`, `commit_hash="a3f9c12"`.

#### `test_file_save_returns_none_for_cursor_metadata`
Calls `event.as_cursor_move_metadata()` on a `file_save` event. Asserts the return value is `None`.

#### `test_no_metadata_returns_none_for_all_accessors`
Constructs a `file_save` event with no `metadata` field. Asserts `as_file_change_metadata()` returns `None`.

#### `test_previous_branch_alias`
Asserts that the JSON key `previousBranch` (camelCase) maps to `meta.previous_branch` (snake_case) in `GitEventMetadata`.

---

### Class `TestEventType` — 2 tests

#### `test_string_values_are_stable`
Asserts the exact string values of all four `EventType` members: `"file_change"`, `"cursor_move"`, `"file_save"`, `"git_event"`. These values are part of the data contract with Layer 1 and must not change.

#### `test_is_str`
Asserts that `EventType.FILE_SAVE` is an instance of `str` (confirming `StrEnum` inheritance).

---

### Class `TestSymbol` — 1 test

#### `test_symbol_construction`
Constructs a `Symbol` model directly with all fields. Asserts `name == "login"` and `kind == "function"`. Confirms the model can be instantiated without going through the indexer.

---

## `test_tailer.py` — 17 tests

**Module under test:** `ambient/tailer.py`

Tests that the `Tailer` class correctly reads NDJSON events from disk, tracks a byte-offset cursor, commits the cursor after processing, and handles crash/restart scenarios.

---

### Class `TestMissingFile` — 2 tests

#### `test_returns_empty_when_file_does_not_exist`
Creates a `Tailer` pointing at a path that doesn't exist. Asserts `read_new_events()` returns `[]` without raising.

#### `test_offset_stays_zero_when_file_missing`
After calling `read_new_events()` on a missing file, asserts `tailer.offset == 0` (cursor not advanced).

---

### Class `TestBasicReading` — 4 tests

#### `test_reads_all_events_from_fresh_file`
Writes three events (`file_save`, `cursor_move`, `git_event`) to an NDJSON file. Asserts `read_new_events()` returns all three with the correct `event_type` in order.

#### `test_returns_empty_on_empty_file`
Creates an empty NDJSON file. Asserts `read_new_events()` returns `[]`.

#### `test_returns_empty_on_file_with_only_blank_lines`
Creates an NDJSON file containing only `\n\n\n`. Asserts `read_new_events()` returns `[]` (blank lines are skipped).

#### `test_event_fields_preserved`
Writes a `file_save` event with `workspace="acme"` and `language="go"`. Asserts the parsed event preserves both field values exactly.

---

### Class `TestCursorAndCommit` — 6 tests

#### `test_offset_not_advanced_before_commit`
Calls `read_new_events()` but does **not** call `commit()`. Asserts `tailer.offset == 0` (the offset is only advanced after an explicit commit).

#### `test_commit_advances_offset`
Calls `read_new_events()` then `commit()`. Asserts `tailer.offset > 0`.

#### `test_no_redelivery_after_commit`
Calls `read_new_events()`, then `commit()`, then `read_new_events()` again. Asserts the second read returns `[]` (already-committed events are not re-delivered).

#### `test_cursor_persists_across_restart`
First `Tailer`: reads and commits two events. Appends one new event to the file. Second `Tailer` (same cursor file): asserts only the new event is returned (previously committed events are not replayed).

#### `test_commit_without_prior_read_is_noop`
Calls `commit()` without any prior `read_new_events()`. Asserts `tailer.offset == 0` and no exception is raised.

#### `test_cursor_file_written_on_commit`
After `read_new_events()` and `commit()`, asserts the cursor file exists on disk and contains a positive integer.

---

### Class `TestAtLeastOnceDelivery` — 1 test

#### `test_redelivers_uncommitted_batch_on_restart`
Simulates a crash: first `Tailer` reads two events but never commits. A second `Tailer` (same cursor file) reads again and receives the same two events. Asserts the event types match. This verifies the at-least-once delivery guarantee.

---

### Class `TestReset` — 2 tests

#### `test_reset_reprocesses_all_events`
Reads and commits two events. Calls `tailer.reset()`. Asserts `offset == 0`. Then reads again and asserts both events are returned (full replay from the beginning of the file).

#### `test_reset_updates_cursor_file`
After committing, the cursor file contains a positive offset. After `reset()`, asserts the cursor file contains `0`.

---

### Class `TestMalformedInput` — 2 tests

#### `test_malformed_json_line_is_skipped`
Writes a valid NDJSON line, then `{ not valid json }`, then another valid line. Asserts `read_new_events()` returns exactly 2 events (the bad line is silently skipped) and both have `event_type == FILE_SAVE`.

#### `test_empty_lines_skipped`
Writes `\n` + a valid event line + `\n`. Asserts `read_new_events()` returns exactly 1 event (the surrounding blank lines are ignored).

---

## `test_store.py` — 23 tests

**Module under test:** `ambient/db/store.py`

Tests that the SQLite schema is created correctly, that event/symbol/velocity rows are persisted and queried accurately, and that all isolation and ordering guarantees hold.

---

### Class `TestSchemaCreation` — 4 tests

#### `test_tables_exist_after_init`
Queries `sqlite_master` after `Store.__init__`. Asserts the three expected tables — `events`, `symbols`, `velocity` — all exist.

#### `test_wal_mode_enabled`
Queries `PRAGMA journal_mode`. Asserts the result is `"wal"` (Write-Ahead Logging mode for concurrent read safety).

#### `test_creates_parent_directory`
Creates a `Store` at a deeply nested path (`tmp/a/b/context.db`) that doesn't yet exist. Asserts the file is created (parent directories are auto-created).

#### `test_idempotent_init`
Creates a `Store` at the same path twice. Asserts no exception is raised (schema creation uses `CREATE TABLE IF NOT EXISTS`).

---

### Class `TestInsertEvent` — 6 tests

#### `test_insert_single_event`
Inserts one `file_save` event. Asserts `SELECT COUNT(*) FROM events` returns `1`.

#### `test_event_fields_persisted`
Inserts an event with `workspace="acme"` and `language="go"`. Fetches the row and asserts all three fields (`workspace`, `language`, `type`) match exactly.

#### `test_event_diff_persisted`
Inserts a `file_save` event with a non-null diff. Asserts the `diff` column is not `None` and contains `"@@"` (standard unified diff format).

#### `test_event_metadata_persisted_as_json`
Inserts an event with `linesAdded=7, linesRemoved=2`. Asserts the `metadata` column is stored as valid JSON and the decoded dict contains the correct values.

#### `test_null_diff_persisted_as_null`
Inserts a `cursor_move` event (which has no diff). Asserts the `diff` column in the database is `NULL`.

#### `test_autoincrement_id`
Inserts two events. Asserts their `id` values are `1` and `2` (AUTOINCREMENT works correctly).

---

### Class `TestBulkInsertEvents` — 3 tests

#### `test_inserts_all_events`
Bulk-inserts three events. Asserts total row count is `3`.

#### `test_empty_list_is_noop`
Calls `bulk_insert_events([])`. Asserts no rows are inserted and no exception is raised.

#### `test_preserves_event_types`
Bulk-inserts `file_save`, `cursor_move`, `git_event`. Fetches all `type` values ordered by `id`. Asserts the order matches the insertion order.

---

### Class `TestUpsertSymbols` — 6 tests

#### `test_inserts_symbols`
Calls `upsert_symbols` with 3 `Symbol` objects. Asserts `symbols` table row count is `3`.

#### `test_replaces_existing_symbols_for_file`
Upserts 3 symbols for `auth.py`, then upserts 5 symbols for the same file. Asserts the total count is `5` (old rows replaced, not accumulated).

#### `test_does_not_affect_other_files`
Upserts symbols for `auth.py` and `user.py`. Re-upserts `auth.py` with fewer symbols. Asserts `user.py`'s symbol count is unchanged (delete-and-insert is scoped to a single file).

#### `test_empty_list_clears_symbols_for_file`
Upserts 3 symbols then calls `upsert_symbols("/src/auth.py", [])`. Asserts the table is now empty (upsert with an empty list removes all symbols for that file).

#### `test_get_symbols_returns_ordered_by_line`
Upserts two symbols in reverse line order (`z_last` at line 20, `a_first` at line 0). Asserts `get_symbols` returns them ordered ascending by `start_line`.

#### `test_get_symbols_returns_empty_for_unknown_file`
Calls `get_symbols("/nonexistent.py")` with no prior inserts. Asserts the return value is `[]`.

---

### Class `TestIncrementVelocity` — 4 tests

#### `test_creates_row_on_first_call`
Calls `increment_velocity` for a new `(file_path, date)` pair. Asserts the `velocity` table now has `1` row.

#### `test_increments_edits_on_repeated_calls`
Calls `increment_velocity` three times for the same file and date with different `lines_added`/`lines_removed` values. Asserts `edits == 3`, `lines_added` is the sum of all three calls, and `lines_removed` is the sum of all three calls.

#### `test_separate_dates_create_separate_rows`
Calls `increment_velocity` for the same file on two different dates. Asserts `2` rows exist (one per date).

#### `test_separate_files_create_separate_rows`
Calls `increment_velocity` for two different files on the same date. Asserts `2` rows exist (one per file).

---

### Class `TestGetHotFiles` — 4 tests

#### `test_returns_files_ordered_by_edits_desc`
Inserts velocity for `auth.py` (3 edits) and `user.py` (10 edits). Asserts `get_hot_files` returns `user.py` first with `total_edits == 10`.

#### `test_respects_top_n`
Inserts 5 files with 1 edit each. Calls `get_hot_files(top_n=3)`. Asserts exactly 3 rows are returned.

#### `test_workspace_scoped`
Inserts velocity for the same file under two different workspaces (`ws-a` and `ws-b`). Calls `get_hot_files("ws-a")`. Asserts only `ws-a`'s file is returned.

#### `test_returns_empty_for_unknown_workspace`
Inserts data for `ws` but queries `other-ws`. Asserts `[]` is returned.

---

### Class `TestGetVelocityForFile` — 2 tests

#### `test_returns_rows_ordered_by_date`
Inserts velocity rows for dates `2026-04-12`, `2026-04-14`, `2026-04-13` (out of order). Asserts `get_velocity_for_file` returns them in ascending date order.

#### `test_returns_empty_for_unknown_file`
Calls `get_velocity_for_file("/nonexistent.py")` with no prior inserts. Asserts `[]`.

---

## `test_symbol_index.py` — 22 tests

**Module under test:** `ambient/indexer/symbol_index.py`

Tests that `SymbolIndexer.index_file` correctly extracts named symbols from real source files written to disk, using tree-sitter grammars for Python, TypeScript, and JavaScript.

> All tests write source files to `tmp_path` and call `indexer.index_file(str(src), workspace, language)`.

---

### Class `TestPythonIndexing` — 9 tests

#### `test_extracts_top_level_functions`
Source: `def login(...)` + `def logout()`. Asserts both names appear in the result set.

#### `test_extracts_class`
Source: `class UserService: pass`. Asserts a symbol with `kind == "class"` and `name == "UserService"` is returned.

#### `test_extracts_methods_inside_class`
Source: class with `get_user` and `delete_user` methods. Asserts both method names appear in the results.

#### `test_line_numbers_are_correct`
Source: `def first()` at line 0 and `def second()` at line 3. Asserts `start_line` values are `0` and `3` respectively.

#### `test_signature_is_first_line`
Source: `def login(username, password): ...`. Asserts `symbol.signature` contains `"def login"` (the first line of the definition node).

#### `test_workspace_stored_on_symbol`
Indexes with `workspace="my-workspace"`. Asserts all returned symbols have `workspace == "my-workspace"`.

#### `test_file_path_stored_on_symbol`
Indexes a file at a temp path. Asserts all returned symbols have `file_path` equal to the full path of that file.

#### `test_no_duplicate_symbols`
Source: two `def foo()` definitions on different lines. Asserts each definition has a unique `start_line` (no row is returned twice for the same node).

#### `test_empty_file_returns_empty`
Source: empty string. Asserts `index_file` returns `[]`.

---

### Class `TestTypeScriptIndexing` — 7 tests

#### `test_extracts_function_declaration`
Source: `function login(username: string, ...): boolean { ... }`. Asserts `"login"` appears in the result names.

#### `test_extracts_class`
Source: `class UserService { run(): void {} }`. Asserts a symbol with `name == "UserService"` and `kind == "class"`.

#### `test_extracts_method`
Source: class containing `getUser(id: string): User { ... }`. Asserts a symbol with `name == "getUser"` and `kind == "method"`.

#### `test_extracts_interface`
Source: `interface AuthPayload { token: string; }`. Asserts a symbol with `name == "AuthPayload"` and `kind == "interface"`.

#### `test_extracts_type_alias`
Source: `type UserId = string;`. Asserts a symbol with `name == "UserId"` and `kind == "type_alias"`.

#### `test_extracts_enum`
Source: `enum Status { Active, Inactive }`. Asserts a symbol with `name == "Status"` and `kind == "enum"`.

#### `test_multiple_kinds_in_one_file`
Source contains a function, an interface, a class, and a type alias. Asserts all four `kind` values — `"function"`, `"interface"`, `"class"`, `"type_alias"` — appear in the result set.

---

### Class `TestJavaScriptIndexing` — 2 tests

#### `test_extracts_function_declaration`
Source: `function add(a, b) { return a + b; }`. Asserts `"add"` appears in the result names.

#### `test_extracts_class`
Source: `class EventBus { emit(e) {} }`. Asserts a symbol with `name == "EventBus"` and `kind == "class"`.

---

### Class `TestEdgeCases` — 4 tests

#### `test_unsupported_language_returns_empty`
Calls `index_file` with `language="ruby"` (no grammar registered). Asserts `[]` is returned without raising.

#### `test_file_not_found_returns_empty`
Calls `index_file("/nonexistent/file.py", ...)` where the path does not exist. Asserts `[]` is returned without raising.

#### `test_supported_languages_not_empty`
Reads `indexer.supported_languages`. Asserts `"python"`, `"typescript"`, and `"javascript"` are all present.

#### `test_parser_cache_reused`
Calls `index_file` for the same language twice. Asserts `"python"` key exists in `indexer._cache` (confirming the parser object is cached between calls and not reconstructed each time).

---

## `test_velocity.py` — 16 tests

**Module under test:** `ambient/velocity/tracker.py`

Tests that `VelocityTracker` correctly filters events by type, accumulates save counts, exposes hot-file rankings, and returns chronological per-file trends.

---

### Class `TestRecord` — 7 tests

#### `test_file_save_increments_velocity`
Calls `tracker.record(file_save_event)`. Queries `store.get_velocity_for_file`. Asserts `edits == 1`, `lines_added == 5`, `lines_removed == 2`, and the `date` matches the event's UTC timestamp.

#### `test_multiple_saves_accumulate`
Calls `tracker.record` three times with the same event. Asserts `edits == 3`, `lines_added == 9`, `lines_removed == 3` (all three saves accumulated into one daily row).

#### `test_file_change_is_ignored`
Calls `tracker.record` with a `file_change` event. Asserts the `velocity` table is empty (only `file_save` events count).

#### `test_cursor_move_is_ignored`
Calls `tracker.record` with a `cursor_move` event. Asserts the `velocity` table is empty.

#### `test_git_event_is_ignored`
Calls `tracker.record` with a `git_event`. Asserts the `velocity` table is empty.

#### `test_event_without_metadata_is_skipped_gracefully`
Calls `tracker.record` with a `file_save` event that has no `metadata` field. Asserts no exception is raised and the `velocity` table is empty (the record is skipped, not crashed).

#### `test_different_files_create_separate_rows`
Calls `tracker.record` for `/src/a.py` and `/src/b.py`. Asserts `2` rows exist in the velocity table (one per file).

---

### Class `TestHotFiles` — 4 tests

#### `test_returns_files_ordered_by_edit_count`
Records 2 saves for `/src/a.py` and 7 saves for `/src/b.py`. Asserts `hot_files` returns `/src/b.py` first with `total_edits == 7`.

#### `test_respects_top_n`
Records 6 different files with 1 save each. Calls `hot_files(top_n=3)`. Asserts exactly 3 rows are returned.

#### `test_returns_empty_for_unknown_workspace`
Records saves for `ws-a`. Calls `hot_files("ws-b")`. Asserts `[]` is returned.

#### `test_returns_dict_list`
Calls `hot_files` after one save. Asserts the return value is a non-empty `list` of `dict` objects, each containing `"file_path"` and `"total_edits"` keys.

---

### Class `TestFileTrend` — 3 tests

#### `test_returns_chronological_rows`
Directly inserts velocity rows for dates `2026-04-10`, `2026-04-12`, `2026-04-11` (out of order). Asserts `file_trend` returns them in ascending date order.

#### `test_returns_empty_for_unknown_file`
Calls `file_trend("/nonexistent.py")` with no prior inserts. Asserts `[]`.

#### `test_returns_dict_list`
After inserting one velocity row, calls `file_trend`. Asserts the return value is a non-empty `list` of `dict` objects, each containing `"date"` and `"edits"` keys.

---

### Class `TestUtcDate` — 2 tests

#### `test_returns_iso_date_string`
Passes the timestamp `1744675200000` (= `2025-04-15 00:00:00 UTC`) to `_utc_date`. Asserts the return value is `"2025-04-15"`.

#### `test_format_is_yyyy_mm_dd`
Passes the current time to `_utc_date`. Asserts the return value splits into exactly 3 parts, with a 4-character year, 2-character month, and 2-character day.

---

## `test_integration.py` — 13 tests

**End-to-end tests for the full Layer 2 pipeline.**

These tests use real files on disk, a real SQLite database, and the full `ContextEngine` orchestration — no mocking. Each test uses the `engine` fixture, which creates a `ContextEngine` with all paths inside `tmp_path` and closes it after the test.

#### Fixtures in this module

| Fixture | Description |
|---|---|
| `engine` | A `ContextEngine` with `log_path`, `db_path`, `cursor_path` all in `tmp_path`. `poll_ms=100`. Auto-closed after each test. |
| `py_source` | A real Python file at `tmp_path/auth.py` containing `login`, `logout`, and `AuthService.validate`. |
| `ts_source` | A real TypeScript file at `tmp_path/user.ts` containing `User` interface, `getUser` function, and `UserService` class. |

---

### Class `TestBasicPipeline` — 5 tests

#### `test_file_save_populates_all_three_tables`
Writes one `file_save` event pointing at `py_source`. Runs one batch. Asserts:
- `events` table has 1 row
- `symbols` table contains `login`, `logout`, `AuthService`
- `velocity` table has 1 row with `edits == 1`

This is the canonical "happy path" test confirming the full pipeline works.

#### `test_cursor_move_stored_in_events_only`
Writes one `cursor_move` event. Runs one batch. Asserts:
- `events` table has 1 row
- `symbols` table is empty (no indexing for cursor moves)
- `velocity` table is empty (no velocity for cursor moves)

#### `test_git_event_stored_in_events_only`
Writes one `git_event`. Runs one batch. Asserts:
- `events` table has 1 row
- `symbols` table is empty

#### `test_mixed_batch_processed_correctly`
Writes a batch of 3 events (`file_save`, `cursor_move`, `git_event`). Runs the batch. Asserts the `events` table has 3 rows (all event types are stored regardless of type).

#### `test_typescript_symbols_indexed`
Writes a `file_save` event pointing at `ts_source`. Runs one batch. Asserts symbols table contains `getUser`, `UserService`, and `User` (function, class, and interface all extracted from a TypeScript file).

---

### Class `TestIncrementalProcessing` — 3 tests

#### `test_second_batch_appended_to_events`
Processes a first batch of 1 event, commits. Appends 2 more events, processes second batch. Asserts total event count is 3 (incremental reads work correctly after a commit).

#### `test_symbols_updated_on_re_save`
Processes an initial save of `py_source` and records the symbol count. Appends a new function to `py_source`, processes a second save. Asserts the symbol count after the second batch is greater than after the first (symbols are replaced, not accumulated — the new function appears).

#### `test_velocity_accumulates_across_batches`
Processes the same `file_save` event twice in two separate batches. Asserts `edits == 2` and `lines_added == 6` (velocity rows accumulate correctly across multiple commits).

---

### Class `TestCrashSafety` — 2 tests

#### `test_uncommitted_batch_redelivered`
First engine reads 2 events but never calls `commit()`, then closes. A second `ContextEngine` (same paths) reads again. Asserts the same 2 events are re-delivered. This confirms at-least-once delivery across process restarts.

#### `test_duplicate_event_rows_on_redelivery`
First engine processes 1 event (writes to DB) but never commits, then closes. A second engine reads and processes the same event again and commits. Asserts the `events` table has **2 rows** — one from each delivery. This documents the known at-least-once semantic: duplicate event rows are expected and acceptable at the current stage; Layer 3 is responsible for de-duplication.

---

### Class `TestEmptyLog` — 3 tests

#### `test_no_events_returns_empty_batch`
Creates an empty NDJSON file. Asserts `read_new_events()` returns `[]`.

#### `test_missing_log_returns_empty_batch`
Does not create the NDJSON file at all. Asserts `read_new_events()` returns `[]` (the engine starts gracefully even before Layer 1 has written anything).

#### `test_process_empty_batch_is_noop`
Calls `_process_batch([])` directly. Asserts the `events` table is still empty (an empty batch does not cause any side effects).

---

## Coverage Map

| Component | Unit test class(es) | Integration coverage |
|---|---|---|
| `models.py` — `CodeEvent` | `TestCodeEventParsing`, `TestMetadataAccessors` | All integration tests use `CodeEvent` |
| `models.py` — `EventType` | `TestEventType` | All integration tests dispatch on `event_type` |
| `models.py` — `Symbol` | `TestSymbol` | Symbol construction verified in `test_store.py` |
| `tailer.py` — `Tailer` | All `test_tailer.py` classes | `TestCrashSafety`, `TestEmptyLog`, `TestIncrementalProcessing` |
| `db/store.py` — `Store` | All `test_store.py` classes | `TestBasicPipeline`, `TestIncrementalProcessing` |
| `indexer/symbol_index.py` — `SymbolIndexer` | All `test_symbol_index.py` classes | `TestBasicPipeline::test_file_save_populates_all_three_tables`, `test_typescript_symbols_indexed`, `test_symbols_updated_on_re_save` |
| `velocity/tracker.py` — `VelocityTracker` | All `test_velocity.py` classes | `TestBasicPipeline`, `TestIncrementalProcessing::test_velocity_accumulates_across_batches` |
| `main.py` — `ContextEngine` | — (orchestration layer) | All `test_integration.py` classes |
