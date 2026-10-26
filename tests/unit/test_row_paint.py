"""Decorations use native entry geometry and stay outside the native scrollbar."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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

    tree = SimpleNamespace(
        getClosestNodeForLocation=hit,
        getNodeRect=Mock(return_value=SimpleNamespace(X=22, Width=285)),
    )
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


@pytest.mark.parametrize("origin", [0, 98, 500])
def test_both_scrollbars_clip_swatches_and_drop_marker_too(origin: int) -> None:
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

    paint = RowPaint(
        peer,
        SimpleNamespace(
            getClosestNodeForLocation=hit,
            getNodeRect=Mock(return_value=SimpleNamespace(X=22, Width=285 + origin)),
        ),
    )
    geometry = RowGeometry(0, 22, 10)
    paint.draw([SheetRow(str(i), active=True, color=9) for i in range(10)], geometry, set())
    paint.decorate(geometry, 7)
    assert all(
        x >= origin and x + width <= origin + 307 and y >= 0 and y + height <= 74
        for x, y, width, height in (call.args for call in graphics.drawRect.call_args_list)
    )
    assert all(
        call.args[0] == origin and call.args[2] == origin + 306
        for call in graphics.drawLine.call_args_list
    )


@pytest.mark.parametrize(
    ("geometry", "width", "height", "right", "bottom"),
    [
        (RowGeometry(-1127, 23, 80), 412, 734, 398, 712),
        (RowGeometry(-572, 22, 30), 321, 101, 307, 87),
    ],
)
def test_ambiguous_last_hit_never_paints_over_the_content_boundary(
    geometry: RowGeometry, width: int, height: int, right: int, bottom: int
) -> None:
    graphics = Mock()
    peer = SimpleNamespace(
        getOutputSize=lambda: SimpleNamespace(Width=width, Height=height),
        StyleSettings=SimpleNamespace(
            HighlightColor=1, FieldColor=2, HighlightTextColor=3, FieldTextColor=4, ShadowColor=5
        ),
        createGraphics=lambda: graphics,
    )

    def hit(x: int, y: int) -> object | None:
        return object() if 22 <= x <= right and 0 <= y <= bottom else None

    paint = RowPaint(
        peer,
        SimpleNamespace(
            getClosestNodeForLocation=hit,
            getNodeRect=Mock(return_value=SimpleNamespace(X=22, Width=right - 22)),
        ),
    )
    paint.draw([SheetRow(str(i)) for i in range(geometry.count)], geometry, set())
    paint.decorate(geometry, None)
    assert all(call.args[1] < bottom for call in graphics.drawLine.call_args_list)
    assert all(call.args[1] + call.args[3] <= bottom for call in graphics.drawRect.call_args_list)
