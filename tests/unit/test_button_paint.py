"""The disabled paint workaround keeps permission state and rejects solid-mask pixels."""

import ast
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.ui.button_pixels import label_pixels
from tests.unit.source_methods import ROOT


def enable_button(platform: str) -> Any:
    path = "src/sheet_manager/uno_calc.py"
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "enable_button"
    )
    namespace: dict[str, Any] = {"sys": SimpleNamespace(platform=platform), "Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace["enable_button"]


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_other_platforms_keep_their_native_painting(platform: str) -> None:
    model = SimpleNamespace(Enabled=True)
    button = SimpleNamespace(getModel=lambda: model, getPeer=Mock())
    enable_button(platform)(button, False)
    assert model.Enabled is False
    button.getPeer.assert_not_called()


def test_a_paint_failure_cannot_leave_a_refused_command_enabled() -> None:
    model = SimpleNamespace(Enabled=True)

    def fail(name: str, value: bool) -> None:
        assert model.Enabled is False
        raise RuntimeError("paint setter failed")

    peer = SimpleNamespace(getProperty=Mock(return_value=True), setProperty=fail)
    button = SimpleNamespace(getModel=lambda: model, getPeer=lambda: peer)
    with pytest.raises(RuntimeError, match="paint setter failed"):
        enable_button("linux")(button, False)
    assert model.Enabled is False


def test_readable_antialiased_glyphs_count_but_solid_masks_do_not() -> None:
    pixels = [(240, 240, 240)] * 96 + [(150, 150, 150)] * 4
    assert label_pixels(pixels, 0xF0F0F0, 0x808080) == 4
    for broken in ([(128, 128, 128)] * 100, [(240, 240, 240)] * 100):
        with pytest.raises(AssertionError):
            label_pixels(broken, 0xF0F0F0, 0x808080)
