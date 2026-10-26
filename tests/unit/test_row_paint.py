"""Decorations use native entry geometry and stay outside the native scrollbar."""

from types import SimpleNamespace
from unittest.mock import Mock

from sheet_manager.sheet_list import RowGeometry, SheetRow
from sheet_manager.uno_rows import RowPaint
from tests.unit.source_methods import method


def test_native_font_can_enlarge_the_requested_row_height() -> None:
    owner = SimpleNamespace(
        _nodes=[object()] * 80,
        _row_height=22,
        tree=SimpleNamespace(getNodeRect=Mock(return_value=SimpleNamespace(Y=-69, Height=23))),
    )
    geometry = method(
        "src/sheet_manager/uno_list.py", "SheetList", "geometry", {"RowGeometry": RowGeometry}
    )(owner)
    assert geometry.first_top == -69 and geometry.row_height == 23
    assert geometry.row_at(22) == 3
    assert geometry.row_at(23) == 4
    assert geometry.gap_y(4) == 23


def test_scrollbar_is_outside_both_background_and_divider_painting() -> None:
    graphics = Mock()
    peer = SimpleNamespace(
        getOutputSize=lambda: SimpleNamespace(Width=321, Height=88),
        StyleSettings=SimpleNamespace(
            HighlightColor=1, FieldColor=2, HighlightTextColor=3, FieldTextColor=4, ShadowColor=5
        ),
        createGraphics=lambda: graphics,
    )

    def hit(x: int, y: int) -> object | None:
        return object() if 22 <= x <= 307 else None

    tree = SimpleNamespace(getClosestNodeForLocation=hit)
    paint = RowPaint(peer, tree)
    geometry = RowGeometry(-22, 22, 10)
    paint.draw([SheetRow(str(i)) for i in range(10)], geometry, set())
    assert all(call.args[0] + call.args[2] <= 307 for call in graphics.drawRect.call_args_list)
    paint.decorate(geometry, None)
    lines = [call.args for call in graphics.drawLine.call_args_list]
    assert all(max(x1, x2) < 307 for x1, _, x2, _ in lines)
    assert (0, 0, 306, 0) not in lines, "A fixed top edge would be blitted into scrolled rows"
    assert [(y1, y2) for x1, y1, x2, y2 in lines if x1 != x2] == [
        (21, 21),
        (43, 43),
        (65, 65),
        (87, 87),
    ]


def test_both_scrollbars_clip_swatches_and_drop_marker_too() -> None:
    graphics = Mock()
    peer = SimpleNamespace(
        getOutputSize=lambda: SimpleNamespace(Width=321, Height=88),
        StyleSettings=SimpleNamespace(
            HighlightColor=1, FieldColor=2, HighlightTextColor=3, FieldTextColor=4, ShadowColor=5
        ),
        createGraphics=lambda: graphics,
    )

    def hit(x: int, y: int) -> object | None:
        return object() if 22 <= x <= 307 and 0 <= y <= 74 else None

    paint = RowPaint(peer, SimpleNamespace(getClosestNodeForLocation=hit))
    geometry = RowGeometry(0, 22, 10)
    paint.draw([SheetRow(str(i), active=True, color=9) for i in range(10)], geometry, set())
    paint.decorate(geometry, 7)
    assert all(
        x >= 0 and x + width <= 307 and y >= 0 and y + height <= 74
        for x, y, width, height in (call.args for call in graphics.drawRect.call_args_list)
    )


def test_scrolling_to_the_end_retains_the_last_rows_bottom_pixel() -> None:
    graphics = Mock()
    peer = SimpleNamespace(
        getOutputSize=lambda: SimpleNamespace(Width=412, Height=734),
        StyleSettings=SimpleNamespace(HighlightColor=1, ShadowColor=5),
        createGraphics=lambda: graphics,
    )
    geometry = RowGeometry(-1127, 23, 80)

    def hit(x: int, y: int) -> object | None:
        return object() if 22 <= x <= 398 and 0 <= y < geometry.gap_y(80) else None

    paint = RowPaint(peer, SimpleNamespace(getClosestNodeForLocation=hit))
    paint.decorate(geometry, None)
    assert (0, 712, 397, 712) in [call.args for call in graphics.drawLine.call_args_list]
