"""Apply the document's colours to the list without changing global settings (#141).

Calc's DOCUMENT_SPREADSHEET accessibility context exposes ColorConfig's resolved document
background, including automatic appearance and white-document overrides (measured on Windows
26.8.1.1; ScAccessibleDocument::getBackground in 26.8.2.2). Its foreground is always black, so
explicit FontColor/DocBoundaries come from the selected scheme and automatic text uses a readable
fallback. Do not duplicate the host's automatic-background table or inspect cells.
Creating this accessible also enables Calc's document/shape accessibility listeners for that
view (ScGridWindow::CreateAccessible and ScAccessibleDocument::Init in 26.8.2.2). This is not a
side-effect-free read. Cache the document context, never its changing background; drop it after
a disposed/out-of-bounds read or a component-window change, and retry on the next idle sample.

The native tree and RowPaint share the tree peer's local style settings. Set its model's
background and those local settings, never Application settings or the user's configuration.
TreeControlModel has no TextColor property; its native labels use the local FieldTextColor.
Colour setters reset the native entry height (22 to 18 pixels on GTK and 13 on gen in #141),
so reapply the model's requested RowHeight; the toolkit still enlarges it for its native font.
Use the list's existing main-thread view sampler, under its input/lock/replay barriers. A
configuration notification alone is not a readiness barrier for the resolved background; the
next ordinary sample follows the settled value. Repaint keeps the model, picks, scroll and focus;
there are no additional listeners or timers. A hidden list catches up when it is shown.
"""

from typing import Any

import uno
from com.sun.star.lang import DisposedException, IndexOutOfBoundsException

from sheet_manager.theme import Palette, palette
from sheet_manager.uno_calc import prop, report

DOCUMENT = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.DOCUMENT_SPREADSHEET")
LEAVES = {
    uno.getConstantByName(f"com.sun.star.accessibility.AccessibleRole.{name}")
    for name in ("TABLE", "TREE")
}


def document_surface(item: Any, depth: int = 0, budget: list[int] | None = None) -> Any:
    """Find only the document surface; never enumerate its billions of accessible cells."""
    if budget is None:
        budget = [128]
    if item is None or budget[0] <= 0:
        return None
    budget[0] -= 1
    role = item.getAccessibleRole()
    if role == DOCUMENT:
        return item
    count = item.getAccessibleChildCount()
    if depth >= 8 or count > 64 or role in LEAVES:
        return None
    for index in range(count):
        if budget[0] <= 0:
            return None
        child = item.getAccessibleChild(index)
        value = document_surface(
            child.getAccessibleContext() if child is not None else None, depth + 1, budget
        )
        if value is not None:
            return value
    return None


class ListTheme:
    def __init__(self, context, frame, tree):
        self.tree, self.frame = tree, frame
        self._current: Palette | None = None
        self._surface = self._window = None
        provider = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", context
        )
        self.colors = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess",
            (prop("nodepath", "/org.openoffice.Office.UI/ColorScheme"),),
        )
        self.failed = False
        self.apply()

    def apply(self):
        if self.failed:
            return
        try:
            self._apply()
        except (DisposedException, IndexOutOfBoundsException):
            self._surface = self._window = None
        except Exception:
            self.failed = True
            report("following document colours")

    def _background(self, window):
        if window != self._window:
            self._surface, self._window = None, window
        if self._surface is None:
            accessible = window.getProperty("XAccessible")
            self._surface = document_surface(
                accessible.getAccessibleContext() if accessible is not None else None
            )
        if self._surface is None:
            return None
        value = int(self._surface.getBackground())
        return value if 0 <= value <= 0xFFFFFF else None

    def _apply(self):
        window = self.frame.getComponentWindow()
        if window is None:
            self._surface = self._window = None
            return
        background = self._background(window)
        if background is None:
            # A document surface can be absent during view creation. Retain the preceding
            # palette and try on the next visible sample, without guessing an automatic colour.
            return
        schemes = self.colors.getByName("ColorSchemes")
        name = self.colors.getByName("CurrentColorScheme")
        if not schemes.hasByName(name):
            name = "COLOR_SCHEME_LIBREOFFICE_AUTOMATIC"
        scheme = schemes.getByName(name)
        foreground = scheme.getByName("FontColor").getByName("Color")
        border = scheme.getByName("DocBoundaries").getByName("Color")
        self.style = window.StyleSettings
        current = palette(
            background,
            foreground if foreground is not None else self.style.FieldTextColor,
            self.style.HighlightColor,
            self.style.HighlightTextColor,
            border if border is not None else self.style.ShadowColor,
            self.style.FieldColor,
        )
        peer = self.tree.getPeer()
        style = peer.StyleSettings
        # The host can reset local styles without changing the desired palette.
        settings = {
            "FieldColor": current.background,
            "FieldTextColor": current.foreground,
            "HighlightColor": current.highlight,
            "HighlightTextColor": current.highlight_text,
            "ShadowColor": current.border,
        }
        previous = {name: getattr(style, name) for name in settings}
        model = self.tree.getModel()
        previous_background = model.getPropertyValue("BackgroundColor")
        row_height = model.getPropertyValue("RowHeight")
        previous_height = peer.getProperty("RowHeight")
        changed = False
        try:
            for name, value in settings.items():
                if previous[name] != value:
                    setattr(style, name, value)
                    changed = True
            if previous_background != current.background:
                model.setPropertyValue("BackgroundColor", current.background)
                changed = True
            if changed and row_height:
                peer.setProperty("RowHeight", row_height)
            if changed or current != self._current:
                peer.invalidate(0)
        except Exception:
            # A failed setter may already have changed its field. Keep the preceding palette
            # as a whole rather than leave new dark backgrounds with old dark text.
            for name, value in previous.items():
                try:
                    setattr(style, name, value)
                except Exception:
                    report("restoring a list colour")
            try:
                model.setPropertyValue("BackgroundColor", previous_background)
                peer.setProperty("RowHeight", previous_height)
                peer.invalidate(0)
            except Exception:
                report("restoring the list background")
            raise
        self._current = current
