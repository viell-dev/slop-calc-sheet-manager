"""The real-input fixtures and checks load without a runner's command-line entry point (#195).

`run_ui.py`, `run_windows_ui.py` and `update_dialog.py` own their platform setup, their lists of
checks and their exit status. Every other module under `tests/ui/` is imported by them, never the
other way round, so a runner can reuse the workbook, the lab and the checks on its own.
"""

import ast
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "tests" / "ui"
RUNNERS = {"run_ui", "run_windows_ui", "update_dialog"}


def imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    "path",
    sorted(path for path in UI.glob("*.py") if path.stem not in RUNNERS),
    ids=lambda path: path.name,
)
def test_shared_ui_modules_import_no_runner(path: Path) -> None:
    assert not imported(path) & RUNNERS


def test_the_runners_exist() -> None:
    assert {path.stem for path in UI.glob("*.py")} >= RUNNERS


def test_the_update_dialog_closes_its_document_only_through_the_shared_helper() -> None:
    # `main_thread.close_document` refuses to close after a stall (#45); a direct close would not.
    tree = ast.parse((UI / "update_dialog.py").read_text(encoding="utf-8"))
    direct = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "document"
    ]
    assert direct == []
