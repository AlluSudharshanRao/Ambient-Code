"""
Tree-sitter symbol extractor.

Parses source files on-demand (triggered by ``file_save`` events) and
extracts top-level and class-level symbols: functions, classes, methods,
interfaces, type aliases, and enums.

Supported languages
-------------------
- Python       (tree-sitter-python)
- JavaScript   (tree-sitter-javascript)
- TypeScript   (tree-sitter-typescript)
- TSX          (tree-sitter-typescript, tsx grammar)

Adding a language
-----------------
1. Install the corresponding ``tree-sitter-<lang>`` package.
2. Add an entry to :data:`_LANGUAGE_REGISTRY` mapping the VS Code
   language identifier to a :class:`_LangConfig`.
3. Write tree-sitter query strings using ``@<kind>.name`` / ``@<kind>.def``
   capture pairs (see the existing entries for examples).

Query capture convention
------------------------
Every query string must use **two** captures per pattern:

- ``@<kind>.name``  — the identifier node (provides the symbol name)
- ``@<kind>.def``   — the definition node (provides start/end lines and
                       the first-line signature)

tree-sitter 0.22+ API
---------------------
This module targets tree-sitter ≥ 0.22.  Key API differences from 0.21:

- ``Parser(language)``   — language is passed to the constructor
- ``Query(language, s)`` — replaces the deprecated ``Language.query()``
- ``QueryCursor(query).matches(node)``
  Returns ``list[tuple[int, dict[str, list[Node]]]]``.
  Each tuple is ``(pattern_index, {capture_name: [Node, ...]})``.
  Use this to pair ``@<kind>.def`` and ``@<kind>.name`` nodes from the
  same pattern match reliably.
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

from ambient.models import Symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LangConfig:
    """Associates a language factory callable with a list of query strings."""

    language_factory: object   # () -> tree_sitter.Language
    queries: list[str]


def _make_language_registry() -> dict[str, _LangConfig]:
    """Build the registry, silently skipping unavailable grammar packages."""
    registry: dict[str, _LangConfig] = {}

    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language

        registry["python"] = _LangConfig(
            language_factory=lambda: Language(tspython.language()),
            queries=[
                """
                (function_definition
                  name: (identifier) @function.name) @function.def
                """,
                """
                (class_definition
                  name: (identifier) @class.name) @class.def
                """,
            ],
        )
    except ImportError:
        logger.debug("tree-sitter-python not installed; Python files will not be indexed.")

    try:
        import tree_sitter_javascript as tsjavascript
        from tree_sitter import Language

        registry["javascript"] = _LangConfig(
            language_factory=lambda: Language(tsjavascript.language()),
            queries=[
                """
                (function_declaration
                  name: (identifier) @function.name) @function.def
                """,
                """
                (class_declaration
                  name: (identifier) @class.name) @class.def
                """,
                """
                (method_definition
                  name: (property_identifier) @method.name) @method.def
                """,
                # Arrow functions assigned to const/let: const foo = () => {}
                """
                (variable_declarator
                  name: (identifier) @function.name
                  value: (arrow_function)) @function.def
                """,
            ],
        )
    except ImportError:
        logger.debug(
            "tree-sitter-javascript not installed; JavaScript files will not be indexed."
        )

    try:
        import tree_sitter_typescript as tsts
        from tree_sitter import Language

        _ts_queries = [
            """
            (function_declaration
              name: (identifier) @function.name) @function.def
            """,
            """
            (class_declaration
              name: (type_identifier) @class.name) @class.def
            """,
            """
            (method_definition
              name: (property_identifier) @method.name) @method.def
            """,
            """
            (interface_declaration
              name: (type_identifier) @interface.name) @interface.def
            """,
            """
            (type_alias_declaration
              name: (type_identifier) @type_alias.name) @type_alias.def
            """,
            """
            (enum_declaration
              name: (identifier) @enum.name) @enum.def
            """,
            # Arrow functions assigned to const/let
            """
            (variable_declarator
              name: (identifier) @function.name
              value: (arrow_function)) @function.def
            """,
        ]

        registry["typescript"] = _LangConfig(
            language_factory=lambda: Language(tsts.language_typescript()),
            queries=_ts_queries,
        )
        registry["typescriptreact"] = _LangConfig(
            language_factory=lambda: Language(tsts.language_tsx()),
            queries=_ts_queries,
        )
        registry["tsx"] = registry["typescriptreact"]

    except ImportError:
        logger.debug(
            "tree-sitter-typescript not installed; TypeScript files will not be indexed."
        )

    return registry


_LANGUAGE_REGISTRY: dict[str, _LangConfig] = _make_language_registry()


# ---------------------------------------------------------------------------
# SymbolIndexer
# ---------------------------------------------------------------------------


class SymbolIndexer:
    """Extracts symbols from source files using tree-sitter.

    Parsers and queries are lazily initialised and cached per language.

    Usage
    -----
    ::

        indexer = SymbolIndexer()
        symbols = indexer.index_file(
            file_path="/home/u/project/src/auth.ts",
            workspace="my-project",
            language="typescript",
        )
    """

    def __init__(self) -> None:
        # Cache: language_id -> (Parser, list[Query])
        self._cache: dict[str, tuple[object, list[object]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_file(
        self,
        file_path: str,
        workspace: str,
        language: str,
    ) -> list[Symbol]:
        """Parse *file_path* and return all extracted symbols.

        Returns an empty list if:
        - the language is unsupported,
        - the file cannot be read from disk, or
        - tree-sitter raises a parse error.

        Parameters
        ----------
        file_path:
            Absolute path to the source file.
        workspace:
            VS Code workspace name (stored on each symbol for scoping).
        language:
            VS Code language identifier (e.g. ``"typescript"``).
        """
        config = _LANGUAGE_REGISTRY.get(language)
        if config is None:
            return []

        try:
            source = Path(file_path).read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s for indexing: %s", file_path, exc)
            return []

        parser, queries = self._get_parser_and_queries(language, config)
        if parser is None:
            return []

        try:
            tree = parser.parse(source)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("tree-sitter parse error for %s: %s", file_path, exc)
            return []

        source_lines = source.splitlines()
        now_ms = int(time.time() * 1000)
        symbols: list[Symbol] = []
        seen: set[tuple[str, int]] = set()  # deduplicate on (name, start_line)

        from tree_sitter import QueryCursor

        for query in queries:
            try:
                matches = QueryCursor(query).matches(tree.root_node)
            except Exception as exc:  # noqa: BLE001
                logger.debug("QueryCursor error (%s): %s", language, exc)
                continue

            for _pattern_idx, capture_dict in matches:
                # Each match provides a dict: capture_name -> list[Node]
                # We expect exactly one @<kind>.def and one @<kind>.name per match.
                # Determine the kind from whichever key ends with ".def"
                kind = None
                for cap_name in capture_dict:
                    if cap_name.endswith(".def"):
                        kind = cap_name[: -len(".def")]
                        break

                if kind is None:
                    continue

                def_nodes = capture_dict.get(f"{kind}.def", [])
                name_nodes = capture_dict.get(f"{kind}.name", [])

                if not def_nodes or not name_nodes:
                    continue

                def_node = def_nodes[0]
                name_node = name_nodes[0]

                name_text: str = name_node.text.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
                start_line: int = def_node.start_point[0]  # type: ignore[attr-defined]
                end_line: int = def_node.end_point[0]  # type: ignore[attr-defined]

                dedup_key = (name_text, start_line)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                signature = _first_line(def_node, source_lines)

                symbols.append(
                    Symbol(
                        file_path=file_path,
                        workspace=workspace,
                        name=name_text,
                        kind=kind,
                        start_line=start_line,
                        end_line=end_line,
                        signature=signature,
                        updated_at=now_ms,
                    )
                )

        return symbols

    @property
    def supported_languages(self) -> list[str]:
        """Languages for which a grammar package is available."""
        return list(_LANGUAGE_REGISTRY.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_parser_and_queries(
        self, language: str, config: _LangConfig
    ) -> tuple[object | None, list[object]]:
        """Return a cached (Parser, list[Query]) pair, creating if needed."""
        if language in self._cache:
            return self._cache[language]

        try:
            from tree_sitter import Parser, Query

            ts_language = config.language_factory()
            parser = Parser(ts_language)

            queries: list[object] = []
            for query_str in config.queries:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    q = Query(ts_language, query_str.strip())
                queries.append(q)

            self._cache[language] = (parser, queries)
            return parser, queries

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialise tree-sitter for %s: %s", language, exc)
            return None, []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_line(node: object, source_lines: list[bytes]) -> str:
    """Return the first source line of *node* as a UTF-8 string."""
    start_row: int = node.start_point[0]  # type: ignore[attr-defined]
    if start_row < len(source_lines):
        return source_lines[start_row].decode("utf-8", errors="replace").rstrip()
    return ""
