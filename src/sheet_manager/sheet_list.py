"""The sheet list's rows and geometry, independent of UNO."""

from dataclasses import dataclass

from sheet_manager.i18n import tr


@dataclass(frozen=True)
class SheetRow:
    name: str
    visible: bool = True
    active: bool = False
    protected: bool = False
    scenario: bool = False
    color: int | None = None  # 0xRRGGBB, or None for the default tab colour.


def row_label(row: SheetRow) -> str:
    """The sheet name and state words; the current-sheet marker is drawn separately."""
    states: list[str] = []
    if not row.visible:
        states.append(tr("hidden"))
    if row.protected:
        states.append(tr("protected"))
    if row.scenario:
        states.append(tr("scenario"))
    label = row.name
    return f"{label} ({', '.join(states)})" if states else label


def list_name(active: str | None) -> str:
    """The list's accessible name, naming the sheet Calc shows, which the painted arrow marks.

    Assistive technology reads it for the list itself; the list's picks cannot stand in for the
    viewed sheet, and row names stay plain (#83).
    """
    if active is None:
        return tr("Sheets")
    return tr("Sheets, current sheet: {name}").format(name=active)


def tab_color(value: int) -> int | None:
    """Convert a sheet's TabColor property, where -1 means no colour, to 0xRRGGBB or None."""
    return None if value < 0 or value == 0xFFFFFFFF else value & 0xFFFFFF


@dataclass(frozen=True)
class RowGeometry:
    """Rows of equal height; first_top is row 0's top edge, negative once scrolled."""

    first_top: int
    row_height: int
    count: int

    def row_at(self, y: int) -> int | None:
        if self.row_height <= 0:
            return None
        row = (y - self.first_top) // self.row_height
        return row if 0 <= row < self.count else None

    def gap_at(self, y: int) -> int:
        """The insertion gap (0..count) closest to y: above a row's midpoint means before it."""
        if self.row_height <= 0:
            return 0
        offset = y - self.first_top
        gap = (2 * offset + self.row_height) // (2 * self.row_height)
        return max(0, min(self.count, gap))

    def gap_y(self, gap: int) -> int:
        return self.first_top + gap * self.row_height

    def first_visible(self) -> int:
        if self.row_height <= 0:
            return 0
        return max(0, min(self.count - 1, -(self.first_top // self.row_height)))

    def visible_rows(self, height: int) -> int:
        return max(1, height // self.row_height) if self.row_height > 0 else 1


def ordered(names: list[str], picked: set[str]) -> list[str]:
    """The picked names in document order."""
    return [name for name in names if name in picked]
