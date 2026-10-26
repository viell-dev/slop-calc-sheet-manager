"""Full-width row decoration on the native tree, retaining its input and accessibility."""

from typing import Any

from sheet_manager.sheet_list import RowGeometry, SheetRow


class RowPaint:
    def __init__(self, peer: Any, tree: Any):
        self.peer = peer
        self.tree = tree

    def _bounds(self, geometry: RowGeometry, width: int, height: int) -> tuple[int, int]:
        """Find the native row viewport; the window's size also includes its scrollbars."""
        if not geometry.count or width < 2 or height < 2:
            return 0, 0
        y = min(height - 1, geometry.gap_y(geometry.first_visible()) + geometry.row_height // 2)
        left, right = width // 2, width
        if self.tree.getClosestNodeForLocation(left, y) is None:
            return 0, 0
        # Native hit testing extends each row through the content area's right boundary.
        # That boundary is exclusive for drawing, even though the native hit test includes it.
        while left < right:
            middle = (left + right + 1) // 2
            if self.tree.getClosestNodeForLocation(middle, y) is None:
                right = middle - 1
            else:
                left = middle
        if left < width:
            # A vertical scrollbar means the rows fill the viewport. Hit testing can then
            # locate its bottom too, excluding a horizontal scrollbar for long names.
            top, bottom = y, height
            x = left // 2
            while top < bottom:
                middle = (top + bottom + 1) // 2
                if self.tree.getClosestNodeForLocation(x, middle) is None:
                    bottom = middle - 1
                else:
                    top = middle
            # GetEntry includes a row's last pixel; the viewport boundary itself is
            # exclusive. At the list's end, retain that last pixel and its divider.
            height = top + 1 if top == geometry.gap_y(geometry.count) - 1 else top
        else:
            # All rows fit. Do not paint the empty area below them (or its scrollbar).
            height = min(height, geometry.gap_y(geometry.count))
        return left, height

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
        size = self.peer.getOutputSize()
        width, height = self._bounds(geometry, size.Width, size.Height)
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
                clipped_top, bottom = max(0, top), min(height, top + geometry.row_height)
                if bottom <= clipped_top:
                    continue
                graphics.drawRect(0, clipped_top, width, bottom - clipped_top)
                middle = top + geometry.row_height // 2
                if row.active and width >= 11:
                    graphics.setLineColor(foreground)
                    graphics.setFillColor(foreground)
                    for offset in range(-4, 5):
                        if 0 <= middle + offset < height:
                            graphics.drawRect(5, middle + offset, 6 - abs(offset), 1)
                if row.color is not None and width > 16:
                    graphics.setLineColor(style.ShadowColor)
                    graphics.setFillColor(row.color)
                    swatch_top, swatch_bottom = max(0, middle - 4), min(height, middle + 4)
                    if swatch_bottom > swatch_top:
                        graphics.drawRect(
                            16, swatch_top, min(8, width - 16), swatch_bottom - swatch_top
                        )
        finally:
            graphics.pop()

    def decorate(self, geometry: RowGeometry, gap: int | None) -> None:
        """Finish after native labels, whose opaque backgrounds can cover row dividers."""
        size = self.peer.getOutputSize()
        width, height = self._bounds(geometry, size.Width, size.Height)
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
                if 0 <= y < height:
                    graphics.drawLine(0, y, width - 1, y)
            # Fixed frame lines inside this window are copied into the rows by native
            # vertical/horizontal scrolling. Only draw dividers that belong to rows.
            if gap is not None:
                middle = max(4, min(height - 5, geometry.gap_y(gap)))
                graphics.setLineColor(style.HighlightColor)
                graphics.setFillColor(style.HighlightColor)
                graphics.drawRect(1, middle - 1, width - 2, 3)
                for offset in range(-4, 5):
                    if 0 <= middle + offset < height:
                        extent = min(width - 2, 7 - abs(offset))
                        graphics.drawRect(1, middle + offset, extent, 1)
                        graphics.drawRect(width - extent - 1, middle + offset, extent, 1)
        finally:
            graphics.pop()
