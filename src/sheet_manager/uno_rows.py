"""Full-width row decoration on the native tree, retaining its input and accessibility."""

from typing import Any

from sheet_manager.sheet_list import RowGeometry, SheetRow


class RowPaint:
    def __init__(self, peer: Any):
        self.peer = peer

    def _font(self) -> Any:
        return self.peer.getFont(self.peer.StyleSettings.FieldFont)

    def row_height(self) -> int:
        metric = self._font().getFontMetric()
        return max(22, int(metric.Ascent + metric.Descent) + 6)

    def draw(
        self,
        rows: list[SheetRow],
        geometry: RowGeometry,
        picked: set[str],
    ) -> None:
        width, height = self.peer.getOutputSize().Width, self.peer.getOutputSize().Height
        if width < 2 or height < 2 or geometry.row_height < 1:
            return
        style = self.peer.StyleSettings
        graphics = self.peer.createGraphics()
        graphics.push()
        try:
            first = geometry.first_visible()
            last = min(len(rows), first + geometry.visible_rows(height) + 2)
            for index in range(first, last):
                row = rows[index]
                top = geometry.gap_y(index)
                selected = row.name in picked
                background = style.HighlightColor if selected else style.FieldColor
                foreground = style.HighlightTextColor if selected else style.FieldTextColor
                graphics.setLineColor(background)
                graphics.setFillColor(background)
                graphics.drawRect(0, top, width, geometry.row_height)
                middle = top + geometry.row_height // 2
                if row.active:
                    graphics.setLineColor(foreground)
                    graphics.setFillColor(foreground)
                    for offset in range(-4, 5):
                        graphics.drawRect(5, middle + offset, 6 - abs(offset), 1)
                if row.color is not None:
                    graphics.setLineColor(style.ShadowColor)
                    graphics.setFillColor(row.color)
                    graphics.drawRect(16, middle - 4, 8, 8)
        finally:
            graphics.pop()

    def decorate(self, geometry: RowGeometry, gap: int | None) -> None:
        """Finish after native labels, whose opaque backgrounds can cover row dividers."""
        width, height = self.peer.getOutputSize().Width, self.peer.getOutputSize().Height
        if width < 2 or height < 2 or geometry.row_height < 1:
            return
        style = self.peer.StyleSettings
        graphics = self.peer.createGraphics()
        graphics.push()
        try:
            graphics.setLineColor(style.ShadowColor)
            first = geometry.first_visible()
            last = min(geometry.count, first + geometry.visible_rows(height) + 2)
            for index in range(first, last):
                y = geometry.gap_y(index + 1) - 1
                graphics.drawLine(0, y, width - 1, y)
            graphics.drawLine(0, 0, width - 1, 0)
            graphics.drawLine(0, 0, 0, height - 1)
            graphics.drawLine(width - 1, 0, width - 1, height - 1)
            if gap is not None:
                middle = max(4, min(height - 5, geometry.gap_y(gap)))
                graphics.setLineColor(style.HighlightColor)
                graphics.setFillColor(style.HighlightColor)
                graphics.drawRect(1, middle - 1, width - 2, 3)
                for offset in range(-4, 5):
                    extent = 7 - abs(offset)
                    graphics.drawRect(1, middle + offset, extent, 1)
                    graphics.drawRect(width - extent - 1, middle + offset, extent, 1)
        finally:
            graphics.pop()
