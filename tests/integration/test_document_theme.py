"""Document colours update the installed list without changing rows, input or workbook (#141).

Only public native panel peers are observed. Configuration changes stay in the runner's private
profile and are restored before other suites run. Painted label/background pixels are covered
by the corresponding real-input check; these assertions alone do not establish native painting.
Prepare and clean the hidden workbook before the view creates the list's structure monitor
(#160). Optional input listeners have the accessibility suite as a delivery control. Take
detailed state only after a failed initial pick. An observed pass alone is not causal evidence.
The faint-blue control changes only this document window's native palette. Restore it with the
private document colours, then wait for the complete selection pair as well as the background.
"""

from input_trace import events_for
from main_thread import close_after
from sheet_list_view import names, on_main_thread, open_list, poll, root, row_point, selection
from teardown import Configured
from test_sheet_list import Robot

from sheet_manager.theme import contrast, text_color
from sheet_manager.uno_calc import prop, selected_tabs


def failed_pick_details(context, document, tree, point):
    controller = document.CurrentController
    frame = controller.Frame
    bounds = tree.getPosSize()
    model = root(tree)
    target = tree.getNodeForLocation(*point)
    rectangles = []
    if model is not None:
        for index in range(model.getChildCount()):
            node = model.getChildAt(index)
            rect = tree.getNodeRect(node)
            rectangles.append([node.DataValue, rect.X, rect.Y, rect.Width, rect.Height])
    return {
        "stage": "initial_theme_pick",
        "point": point,
        "target_now": target.DataValue if target is not None else None,
        "rows": names(tree),
        "selection": selection(tree, names(tree)),
        "rectangles": rectangles,
        "bounds": [bounds.X, bounds.Y, bounds.Width, bounds.Height],
        "visible": tree.isVisible(),
        "enabled": tree.isEnabled(),
        "focus": tree.hasFocus(),
        "frame_active": frame.isActive(),
        "frame_is_active_top_window": tree.getToolkit().getActiveTopWindow()
        == frame.ContainerWindow,
        "viewed": controller.ActiveSheet.Name,
        "tabs": selected_tabs(context, controller),
        "controllers_locked": document.hasControllersLocked(),
        "actions_locked": document.isActionLocked(),
        "undo_locked": document.UndoManager.isLocked(),
        "undo_enabled": document.IsUndoEnabled,
        "modify_notifications_enabled": document.isSetModifiedEnabled(),
    }


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


STYLE_COLORS = (
    "FieldColor",
    "FieldTextColor",
    "ShadowColor",
    "HighlightColor",
    "HighlightTextColor",
)
FAINT_BLUE_SOURCE = (0x31363B, 0xFFFFFF, 0x767676, 0x3DAEE9, 0xFFFFFF)


def set_source_colors(context, style, values):
    """A controlled native window palette, private to this synthetic document (#167)."""

    def apply():
        for name, value in zip(STYLE_COLORS, values, strict=True):
            setattr(style, name, value)

    on_main_thread(context, apply)


def check_selection_colors(style, source, background):
    native = source.HighlightColor, source.HighlightTextColor
    actual = style.HighlightColor, style.HighlightTextColor
    if background == source.FieldColor or contrast(background, native[0]) >= 3:
        assert actual == native, ("The native selection pair changed", native, actual)
    else:
        assert actual[0] != native[0]
        assert contrast(background, actual[0]) >= 3
        assert contrast(*actual) >= 4.5
        native_channels = [(native[0] >> shift) & 255 for shift in (16, 8, 0)]
        if max(native_channels) - min(native_channels) >= 64:
            channels = [(actual[0] >> shift) & 255 for shift in (16, 8, 0)]
            assert max(channels) > min(channels), "The native selection tint became neutral"


def check_document_colors(context, desktop, *, trace_input=True):
    settings = color_settings(context)
    scheme = scheme_of(settings)
    original = tuple(
        scheme.getByName(name).getByName("Color")
        for name in ("DocColor", "FontColor", "DocBoundaries")
    )
    # Finish synthetic edits and cleanup before a visible view can create the list's monitor.
    # setModified(False) sends an unexplained modify notice; clicking before its deferred
    # refresh correctly refuses the now-stale sheet proof (#160).
    document = desktop.loadComponentFromURL(
        "private:factory/scalc", "_blank", 0, (prop("Hidden", True),)
    )
    try:
        controller, sheets = document.CurrentController, document.Sheets
        sheets.getByIndex(0).Name = "Alfa"
        sheets.insertNewByName("Bravo", 1)
        sheets.insertNewByName("Charlie", 2)
        for index, name in enumerate(("Alfa", "Bravo", "Charlie")):
            sheets.getByIndex(index).getCellRangeByName("A1").String = name
        document.UndoManager.clear()
        document.setModified(False)
        controller.Frame.ContainerWindow.setVisible(True)
        panel, tree = open_list(context, document, trace_input=trace_input)
        poll(lambda: names(tree) == ["Alfa", "Bravo", "Charlie"], "the theme fixture rows")
        toolkit = panel.getToolkit()
        on_main_thread(context, toolkit.processEventsToIdle)
        robot = Robot(context)
        point = row_point(tree, 1)
        robot.click(tree, point)
        poll(
            lambda: selection(tree, names(tree)) == ["Bravo"],
            "the independent Bravo pick",
            on_failure=lambda: failed_pick_details(context, document, tree, point),
        )
        initial_input = events_for(id(tree))
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
        native = tuple(getattr(source_style, name) for name in STYLE_COLORS)
        initial = tree.StyleSettings.FieldColor
        assert initial == source_style.FieldColor, "The private profile should use native white"
        check_selection_colors(tree.StyleSettings, source_style, initial)
        evidence = []
        with (
            Configured(lambda: None, lambda: set_colors(settings, original)),
            Configured(lambda: None, lambda: set_source_colors(context, source_style, native)),
        ):
            for background, foreground, border, source in (
                (0x112233, 0xEEF4FF, 0x708090, native),
                (0xFFFFFF, 0xFFFFFF, 0xFFFFFF, native),
                (0xF1EAD1, 0x342C1D, 0xF1EAD1, native),
                (native[3], text_color(native[3], None), native[3], native),
                (0xFFFFFF, 0, 0xFFFFFF, FAINT_BLUE_SOURCE),
            ):
                set_source_colors(context, source_style, source)
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
                assert source == tuple(getattr(source_style, name) for name in STYLE_COLORS), (
                    "The list changed the document window's own styles"
                )
                evidence.append(
                    {
                        "background": background,
                        "foreground": style.FieldTextColor,
                        "selection": style.HighlightColor,
                        "selection_text": style.HighlightTextColor,
                        "border": style.ShadowColor,
                        "source_background": source[0],
                        "source_selection": source[3],
                    }
                )
        poll(
            lambda: (
                tree.StyleSettings.FieldColor == initial
                and (tree.StyleSettings.HighlightColor, tree.StyleSettings.HighlightTextColor)
                == (native[3], native[4])
            ),
            "the original document and selection colours",
        )
        check_selection_colors(tree.StyleSettings, source_style, initial)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {
        "initial_input": initial_input,
        "palettes": evidence,
        "native_selection_kept": True,
        "model_input_and_document_kept": True,
    }


def exercise(context, desktop, directory, output):
    return check_document_colors(context, desktop)
