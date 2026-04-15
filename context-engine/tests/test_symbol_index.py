"""
Unit tests for ambient.indexer.symbol_index — tree-sitter symbol extraction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ambient.indexer.symbol_index import SymbolIndexer


@pytest.fixture()
def indexer() -> SymbolIndexer:
    return SymbolIndexer()


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


class TestPythonIndexing:
    def test_extracts_top_level_functions(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text(
            "def login(username, password):\n"
            "    return True\n"
            "\n"
            "def logout():\n"
            "    pass\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "python")
        names = {s.name for s in symbols}
        assert "login" in names
        assert "logout" in names

    def test_extracts_class(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "service.py"
        src.write_text("class UserService:\n    pass\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "python")
        kinds = {s.kind for s in symbols}
        assert "class" in kinds
        assert any(s.name == "UserService" for s in symbols)

    def test_extracts_methods_inside_class(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "service.py"
        src.write_text(
            "class UserService:\n"
            "    def get_user(self, uid):\n"
            "        return uid\n"
            "    def delete_user(self, uid):\n"
            "        pass\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "python")
        names = {s.name for s in symbols}
        assert "get_user" in names
        assert "delete_user" in names

    def test_line_numbers_are_correct(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text(
            "def first():\n"    # line 0
            "    pass\n"
            "\n"
            "def second():\n"   # line 3
            "    pass\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "python")
        by_name = {s.name: s for s in symbols}
        assert by_name["first"].start_line == 0
        assert by_name["second"].start_line == 3

    def test_signature_is_first_line(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text("def login(username, password):\n    return True\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "python")
        login = next(s for s in symbols if s.name == "login")
        assert "def login" in login.signature

    def test_workspace_stored_on_symbol(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text("def foo(): pass\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "my-workspace", "python")
        assert all(s.workspace == "my-workspace" for s in symbols)

    def test_file_path_stored_on_symbol(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text("def foo(): pass\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "python")
        assert all(s.file_path == str(src) for s in symbols)

    def test_no_duplicate_symbols(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.py"
        src.write_text("def foo(): pass\ndef foo(): pass\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "python")
        foo_syms = [s for s in symbols if s.name == "foo"]
        # Two separate definitions at different lines are both valid
        start_lines = {s.start_line for s in foo_syms}
        assert len(start_lines) == len(foo_syms), "Same (name, line) should not appear twice"

    def test_empty_file_returns_empty(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "empty.py"
        src.write_text("", encoding="utf-8")
        assert indexer.index_file(str(src), "ws", "python") == []


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


class TestTypeScriptIndexing:
    def test_extracts_function_declaration(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "auth.ts"
        src.write_text(
            "function login(username: string, password: string): boolean {\n"
            "  return true;\n"
            "}\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "typescript")
        names = {s.name for s in symbols}
        assert "login" in names

    def test_extracts_class(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "service.ts"
        src.write_text("class UserService {\n  run(): void {}\n}\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "typescript")
        assert any(s.name == "UserService" and s.kind == "class" for s in symbols)

    def test_extracts_method(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "service.ts"
        src.write_text(
            "class UserService {\n  getUser(id: string): User { return {} as User; }\n}\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "typescript")
        assert any(s.name == "getUser" and s.kind == "method" for s in symbols)

    def test_extracts_interface(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "types.ts"
        src.write_text("interface AuthPayload {\n  token: string;\n}\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "typescript")
        assert any(s.name == "AuthPayload" and s.kind == "interface" for s in symbols)

    def test_extracts_type_alias(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "types.ts"
        src.write_text("type UserId = string;\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "typescript")
        assert any(s.name == "UserId" and s.kind == "type_alias" for s in symbols)

    def test_extracts_enum(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "enums.ts"
        src.write_text("enum Status {\n  Active,\n  Inactive,\n}\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "typescript")
        assert any(s.name == "Status" and s.kind == "enum" for s in symbols)

    def test_multiple_kinds_in_one_file(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "mixed.ts"
        src.write_text(
            "function helper(): void {}\n"
            "interface Config { debug: boolean; }\n"
            "class App { start(): void {} }\n"
            "type ID = string;\n",
            encoding="utf-8",
        )
        symbols = indexer.index_file(str(src), "ws", "typescript")
        kinds = {s.kind for s in symbols}
        assert "function" in kinds
        assert "interface" in kinds
        assert "class" in kinds
        assert "type_alias" in kinds


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


class TestJavaScriptIndexing:
    def test_extracts_function_declaration(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "utils.js"
        src.write_text("function add(a, b) { return a + b; }\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "javascript")
        assert any(s.name == "add" for s in symbols)

    def test_extracts_class(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "service.js"
        src.write_text("class EventBus { emit(e) {} }\n", encoding="utf-8")
        symbols = indexer.index_file(str(src), "ws", "javascript")
        assert any(s.name == "EventBus" and s.kind == "class" for s in symbols)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unsupported_language_returns_empty(self, indexer: SymbolIndexer, tmp_path: Path):
        src = tmp_path / "script.rb"
        src.write_text("def hello\n  puts 'hi'\nend\n", encoding="utf-8")
        assert indexer.index_file(str(src), "ws", "ruby") == []

    def test_file_not_found_returns_empty(self, indexer: SymbolIndexer):
        result = indexer.index_file("/nonexistent/file.py", "ws", "python")
        assert result == []

    def test_supported_languages_not_empty(self, indexer: SymbolIndexer):
        langs = indexer.supported_languages
        assert "python" in langs
        assert "typescript" in langs
        assert "javascript" in langs

    def test_parser_cache_reused(self, indexer: SymbolIndexer, tmp_path: Path):
        """Parsing the same language twice should hit the cache."""
        src = tmp_path / "a.py"
        src.write_text("def foo(): pass\n", encoding="utf-8")
        indexer.index_file(str(src), "ws", "python")
        indexer.index_file(str(src), "ws", "python")
        # No assertion needed — just ensure no error; coverage confirms cache branch
        assert "python" in indexer._cache
