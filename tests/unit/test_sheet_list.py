"""Row labels and the geometry that maps pointer positions to rows and gaps."""

from sheet_manager.sheet_list import (
    RowGeometry,
    SheetRow,
    ordered,
    row_label,
    tab_color,
)


def test_row_labels() -> None:
    assert row_label(SheetRow("Plan")) == "Plan"
    assert row_label(SheetRow("Plan", active=True)) == "Plan"
    assert row_label(SheetRow("Old", visible=False)) == "Old (hidden)"
    assert row_label(SheetRow("Key", visible=False, protected=True, scenario=True)) == (
        "Key (hidden, protected, scenario)"
    )


def test_tab_color() -> None:
    assert tab_color(-1) is None
    assert tab_color(0xFFFFFFFF) is None
    assert tab_color(0x123456) == 0x123456
    assert tab_color(0) == 0


def test_gaps_follow_row_midpoints() -> None:
    rows = RowGeometry(first_top=0, row_height=20, count=5)
    assert [rows.gap_at(y) for y in (0, 9, 10, 29, 30, 95, 500)] == [0, 0, 1, 1, 2, 5, 5]
    assert rows.gap_at(-40) == 0
    assert [rows.gap_y(gap) for gap in (0, 3, 5)] == [0, 60, 100]


def test_rows_when_scrolled() -> None:
    rows = RowGeometry(first_top=-60, row_height=20, count=10)
    assert rows.first_visible() == 3
    assert rows.row_at(0) == 3
    assert rows.row_at(19) == 3
    assert rows.row_at(20) == 4
    assert rows.row_at(200) is None
    assert rows.gap_at(5) == 3
    assert rows.gap_at(15) == 4
    assert rows.visible_rows(95) == 4


def test_empty_geometry() -> None:
    rows = RowGeometry(0, 0, 0)
    assert rows.row_at(10) is None
    assert rows.gap_at(10) == 0
    assert rows.first_visible() == 0
    assert rows.visible_rows(100) == 1


def test_ordered() -> None:
    assert ordered(["a", "b", "c", "d"], {"d", "b"}) == ["b", "d"]
