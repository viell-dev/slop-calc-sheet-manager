"""Document colours update the installed list without changing rows, input or workbook (#141).

Only public native panel peers are observed. Configuration changes stay in the runner's private
profile and are restored before other suites run. Painted label/background pixels are covered
by the corresponding real-input check; these assertions alone do not establish native painting.
The initial pick retains public input/geometry diagnostics without retrying a failed click (#160).
"""

import json
import time

import unohelper
from com.sun.star.awt import XMouseListener
from main_thread import close_after
from sheet_list_view import names, on_main_thread, open_list, poll, root, row_point, selection
from teardown import Configured
from test_sheet_list import Robot

from sheet_manager.theme import contrast, text_color
from sheet_manager.uno_calc import prop, selected_tabs


class _MouseEvents(unohelper.Base, XMouseListener):
    """Record delivered event values only; never call UNO from a listener."""

    def __init__(self):
        self.events = []

    def _record(self, kind, event):
        self.events.append(
            {
                "kind": kind,
                "point": [event.X, event.Y],
                "buttons": event.Buttons,
                "modifiers": event.Modifiers,
                "clicks": event.ClickCount,
            }
        )

    def mousePressed(self, e):
        self._record("pressed", e)

    def mouseReleased(self, e):
        self._record("released", e)

    def mouseEntered(self, e):
        pass

    def mouseExited(self, e):
        pass

    def disposing(self, Source):
        pass


def pick_state(context, document, tree, point):
    controller = document.CurrentController
    node = tree.getNodeForLocation(*point)
    bounds = tree.getPosSize()
    return {
        "rows": names(tree),
        "selection": selection(tree, names(tree)),
        "point_target": node.DataValue if node is not None else None,
        "bounds": [bounds.X, bounds.Y, bounds.Width, bounds.Height],
        "visible": tree.isVisible(),
        "enabled": tree.isEnabled(),
        "focus": tree.hasFocus(),
        "viewed": controller.ActiveSheet.Name,
        "tabs": selected_tabs(context, controller),
        "frame_active": tree.getToolkit().getActiveTopWindow() == controller.Frame.ContainerWindow,
    }


def pick_bravo(context, document, tree, output):
    point = row_point(tree, 1)
    diagnostics: dict[str, object] = {
        "point": point,
        "before": pick_state(context, document, tree, point),
    }
    listener = _MouseEvents()
    transitions = []
    started = time.monotonic()

    def picked():
        actual = selection(tree, names(tree))
        if not transitions or actual != transitions[-1]["selection"]:
            transitions.append({"seconds": time.monotonic() - started, "selection": actual})
        return actual == ["Bravo"]

    def finish():
        tree.removeMouseListener(listener)
        diagnostics.update(
            after=pick_state(context, document, tree, point),
            mouse_events=listener.events,
            selection_transitions=transitions,
        )
        (output / "document-theme-initial-pick.json").write_text(
            json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8"
        )

    with Configured(lambda: tree.addMouseListener(listener), finish):
        Robot(context).click(tree, point)
        poll(picked, "the independent Bravo pick")


def color_settings(context):
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", context
    )
    return provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess",
        (prop("nodepath", "/org.openoffice.Office.UI/ColorScheme"),),
    )


def scheme_of(settings):
    return settings.getByName("ColorSchemes").getByName(settings.getByName("CurrentColorScheme"))


def set_colors(settings, values):
    scheme = scheme_of(settings)
    for name, value in zip(("DocColor", "FontColor", "DocBoundaries"), values, strict=True):
        scheme.getByName(name).setPropertyValue("Color", value)
    settings.commitChanges()


def check_selection_colors(style, source, background):
    native = source.HighlightColor, source.HighlightTextColor
    actual = style.HighlightColor, style.HighlightTextColor
    if background == source.FieldColor or contrast(background, native[0]) >= 3:
        assert actual == native, ("The native selection pair changed", native, actual)
    else:
        assert actual[0] != native[0]
        assert contrast(background, actual[0]) >= 3
        assert contrast(*actual) >= 4.5


def check_document_colors(context, desktop, output):
    settings = color_settings(context)
    scheme = scheme_of(settings)
    original = tuple(
        scheme.getByName(name).getByName("Color")
        for name in ("DocColor", "FontColor", "DocBoundaries")
    )
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        controller, sheets = document.CurrentController, document.Sheets
        sheets.getByIndex(0).Name = "Alfa"
        sheets.insertNewByName("Bravo", 1)
        sheets.insertNewByName("Charlie", 2)
        for index, name in enumerate(("Alfa", "Bravo", "Charlie")):
            sheets.getByIndex(index).getCellRangeByName("A1").String = name
        panel, tree = open_list(context, document)
        poll(lambda: names(tree) == ["Alfa", "Bravo", "Charlie"], "the theme fixture rows")
        toolkit = panel.getToolkit()
        document.UndoManager.clear()
        document.setModified(False)
        on_main_thread(context, toolkit.processEventsToIdle)
        pick_bravo(context, document, tree, output)
        model = root(tree)
        assert model is not None
        row_height = tree.getNodeRect(model.getChildAt(0)).Height
        baseline = (
            controller.ActiveSheet.Name,
            selected_tabs(context, controller),
            tree.hasFocus(),
            document.isModified(),
        )
        source_style = controller.Frame.ComponentWindow.StyleSettings
        native = tuple(
            getattr(source_style, name)
            for name in (
                "FieldColor",
                "FieldTextColor",
                "ShadowColor",
                "HighlightColor",
                "HighlightTextColor",
            )
        )
        initial = tree.StyleSettings.FieldColor
        assert initial == source_style.FieldColor, "The private profile should use native white"
        check_selection_colors(tree.StyleSettings, source_style, initial)
        evidence = []
        with Configured(lambda: None, lambda: set_colors(settings, original)):
            for background, foreground, border in (
                (0x112233, 0xEEF4FF, 0x708090),
                (0xFFFFFF, 0xFFFFFF, 0xFFFFFF),
                (0xF1EAD1, 0x342C1D, 0xF1EAD1),
                (native[3], text_color(native[3], None), native[3]),
            ):
                set_colors(settings, (background, foreground, border))
                poll(
                    lambda expected=background: tree.StyleSettings.FieldColor == expected,
                    "the document colour to reach the list",
                )
                style = tree.StyleSettings
                assert contrast(background, style.FieldTextColor) >= 4.5
                check_selection_colors(style, source_style, background)
                assert contrast(background, style.ShadowColor) >= 3
                if foreground != background:
                    assert style.FieldTextColor == foreground
                assert root(tree) == model, "A colour change rebuilt the rows"
                assert tree.getNodeRect(model.getChildAt(0)).Height == row_height
                assert selection(tree, names(tree)) == ["Bravo"]
                assert baseline == (
                    controller.ActiveSheet.Name,
                    selected_tabs(context, controller),
                    tree.hasFocus(),
                    document.isModified(),
                )
                assert not document.UndoManager.AllUndoActionTitles
                assert not document.UndoManager.AllRedoActionTitles
                assert [sheets.getByIndex(i).getCellRangeByName("A1").String for i in range(3)] == [
                    "Alfa",
                    "Bravo",
                    "Charlie",
                ]
                assert native == tuple(
                    getattr(source_style, name)
                    for name in (
                        "FieldColor",
                        "FieldTextColor",
                        "ShadowColor",
                        "HighlightColor",
                        "HighlightTextColor",
                    )
                ), "The list changed the document window's own styles"
                evidence.append(
                    {
                        "background": background,
                        "foreground": style.FieldTextColor,
                        "selection": style.HighlightColor,
                        "selection_text": style.HighlightTextColor,
                        "border": style.ShadowColor,
                    }
                )
        poll(lambda: tree.StyleSettings.FieldColor == initial, "the original document colour")
        check_selection_colors(tree.StyleSettings, source_style, initial)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {
        "palettes": evidence,
        "native_selection_kept": True,
        "model_input_and_document_kept": True,
    }


def exercise(context, desktop, directory, output):
    return check_document_colors(context, desktop, output)
