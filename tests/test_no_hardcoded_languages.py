"""AC-18: no hard-coded languages in the ``lianiq`` package (CAP-0169 WI-07).

The scan parses every module under ``lianiq/`` except ``languages/registry.py`` (the
registry) and ``config_migration.py`` (the schema v1 mapping) and fails on:

* the removed enums: ``Language``, ``ConversationMode`` and their members ``GERMAN``,
  ``MANDARIN``, ``DE_TO_ZH``, ``ZH_TO_DE``;
* the property-style ``.other`` of the removed ``Language`` enum. ``LanguagePair.other(id)``
  from contract.md §3.1.1 is the only accepted form: a call with exactly one argument;
* the label and direction literals ``"DE"``, ``"ZH"`` (also as words inside a string, such as
  ``"DE: "``), ``"de-zh"`` and ``"zh-de"``;
* registered language IDs or directed edge keys as string literals, outside the repository
  default settings in ``config.py`` (they mirror ``config/settings.json``) and the functional
  route-test phrase table ``ROUTE_TEST_TEXT`` in ``ui/main_window.py``. Phrases are
  multilingual functional data keyed by language ID; a language without a phrase gets a
  named error, never another language's phrase.

``scripts/`` is outside the scan: its de/zh-Hans phrases (for example ``SOURCE_TEXT`` in
``scripts/call_bridge_self_test.py``) are regression inputs of the de↔zh-Hans suites (AC-21).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lianiq.languages import BUILTIN_REGISTRY, DirectedEdge

PACKAGE = Path(__file__).resolve().parents[1] / "lianiq"
EXCLUDED = {Path("languages/registry.py"), Path("config_migration.py")}

REMOVED_NAMES = {"Language", "ConversationMode", "GERMAN", "MANDARIN", "DE_TO_ZH", "ZH_TO_DE"}
FORBIDDEN_LITERALS = {"DE", "ZH", "de-zh", "zh-de"}
LABEL_WORD = re.compile(r"\b(DE|ZH)\b")
ROUTE_TEST_TABLE = "ROUTE_TEST_TEXT"
DEFAULT_EDGES_FUNCTION = "_default_edges"


def registered_literals() -> frozenset[str]:
    ids = [definition.id for definition in BUILTIN_REGISTRY.languages()]
    edges = [DirectedEdge(a, b).key for a in ids for b in ids if a != b]
    return frozenset([*ids, *edges])


def _subtree_ids(node: ast.AST) -> set[int]:
    return {id(child) for child in ast.walk(node)}


def allowed_language_id_nodes(tree: ast.Module, relative: Path) -> set[int]:
    """Nodes in which registered language IDs are accepted as functional data."""
    allowed: set[int] = set()
    if relative == Path("config.py"):
        # Repository defaults only: class-level field defaults and ``_default_edges``.
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    if isinstance(statement, ast.AnnAssign) and statement.value is not None:
                        allowed |= _subtree_ids(statement.value)
            elif isinstance(node, ast.FunctionDef) and node.name == DEFAULT_EDGES_FUNCTION:
                allowed |= _subtree_ids(node)
    if relative == Path("ui/main_window.py"):
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            if any(isinstance(t, ast.Name) and t.id == ROUTE_TEST_TABLE for t in targets):
                allowed |= _subtree_ids(node)
    return allowed


def scan_source(source: str, relative: Path) -> list[str]:
    """Return one finding per hard-coded language reference in ``source``."""
    tree = ast.parse(source)
    called_other = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "other"
        and len(node.args) == 1
        and not node.keywords
    }
    allowed = allowed_language_id_nodes(tree, relative)
    language_ids = registered_literals()
    findings: list[str] = []

    def report(node: ast.AST, message: str) -> None:
        findings.append(f"{relative.as_posix()}:{getattr(node, 'lineno', 0)}: {message}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in REMOVED_NAMES:
            report(node, f"removed language name {node.id}")
        elif isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] in REMOVED_NAMES:
            report(node, f"import of removed language name {node.name}")
        elif isinstance(node, ast.Attribute):
            if node.attr in REMOVED_NAMES and not (
                isinstance(node.value, ast.Name) and node.value.id in REMOVED_NAMES
            ):
                report(node, f"removed language member .{node.attr}")
            elif node.attr == "other" and id(node) not in called_other:
                report(node, "property-style .other (use LanguagePair.other(language_id))")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value in FORBIDDEN_LITERALS or LABEL_WORD.search(value):
                report(node, f"hard-coded language literal {value!r}")
            elif value in language_ids and id(node) not in allowed:
                report(node, f"hard-coded language ID literal {value!r}")
    return findings


def scan_package(package: Path = PACKAGE) -> list[str]:
    findings: list[str] = []
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if relative in EXCLUDED:
            continue
        findings += scan_source(path.read_text(encoding="utf-8"), relative)
    return findings


def test_ac18_lianiq_package_has_no_hard_coded_languages() -> None:
    assert scan_package() == []


def test_ac18_scan_covers_the_package_and_excludes_only_registry_and_migration() -> None:
    scanned = {path.relative_to(PACKAGE) for path in PACKAGE.rglob("*.py")} - EXCLUDED
    assert Path("ui/main_window.py") in scanned
    assert Path("config.py") in scanned
    assert Path("languages/registry.py") not in scanned
    assert Path("config_migration.py") not in scanned
    for excluded in EXCLUDED:
        assert (PACKAGE / excluded).is_file()  # a moved module must not escape the scan


@pytest.mark.parametrize(
    ("source", "relative", "expected"),
    [
        ("from lianiq.domain import Language\n", "x.py", "import of removed language name"),
        ("target = Language.MANDARIN\n", "x.py", "removed language name Language"),
        ("target = source.other\n", "x.py", "property-style .other"),
        ("target = source.other()\n", "x.py", "property-style .other"),
        ("mode = ConversationMode.DE_TO_ZH\n", "x.py", "removed language name ConversationMode"),
        ("mode = settings.ZH_TO_DE\n", "x.py", "removed language member .ZH_TO_DE"),
        ('label = "DE"\n', "x.py", "hard-coded language literal 'DE'"),
        ('label = f"ZH: {text}"\n', "x.py", "hard-coded language literal 'ZH: '"),
        ('mode = "de-zh"\n', "x.py", "hard-coded language literal 'de-zh'"),
        ('source = LanguageId("de")\n', "x.py", "hard-coded language ID literal 'de'"),
        ('edge = "zh-Hans>de"\n', "x.py", "hard-coded language ID literal 'zh-Hans>de'"),
        (
            'class TtsConfig:\n    @property\n    def zh(self):\n        return self.voices["zh-Hans"]\n',
            "config.py",
            "hard-coded language ID literal 'zh-Hans'",
        ),
        ('OTHER_TABLE = {LanguageId("de"): "Test."}\n', "ui/main_window.py", "language ID"),
    ],
)
def test_ac18_scan_reports_each_forbidden_reference(source, relative, expected) -> None:
    findings = scan_source(source, Path(relative))
    assert len(findings) == 1, findings
    assert expected in findings[0]


@pytest.mark.parametrize(
    ("source", "relative"),
    [
        ("target = session.pair.other(source)\n", "x.py"),
        ("language = LanguageId(code)\n", "x.py"),
        ('label = "Mandarin (Simplified)"\n', "x.py"),
        ('voice = "models/piper/de_DE-thorsten-medium.onnx"\n', "x.py"),
        ('path = "models/opus-mt-de-zh"\n', "x.py"),
        (
            'class TtsConfig:\n    voices: dict = field(default_factory=lambda: {"de": "a"})\n',
            "config.py",
        ),
        ('def _default_edges():\n    return {"de>zh-Hans": 1}\n', "config.py"),
        ('ROUTE_TEST_TEXT = {LanguageId("de"): "Kopfhörer-Test."}\n', "ui/main_window.py"),
    ],
)
def test_ac18_scan_accepts_contract_calls_defaults_and_phrase_data(source, relative) -> None:
    assert scan_source(source, Path(relative)) == []


def test_route_test_phrases_cover_every_qualified_language() -> None:
    pytest.importorskip("PySide6")
    from lianiq.languages.registry import Availability
    from lianiq.ui.main_window import ROUTE_TEST_TEXT

    qualified = {
        definition.id
        for definition in BUILTIN_REGISTRY.languages()
        if definition.availability is Availability.QUALIFIED
    }
    assert set(ROUTE_TEST_TEXT) == qualified
