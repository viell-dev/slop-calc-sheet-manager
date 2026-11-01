"""Document colours update the installed list without changing rows, input or workbook (#141).

Only public native panel peers are observed. Configuration changes stay in the runner's private
profile and are restored before other suites run. Painted label/background pixels are covered
by the corresponding real-input check; these assertions alone do not establish native painting.
Input listeners are attached before fixture cleanup, with the accessibility suite as a delivery
control. Take detailed state only after a failed initial pick, never between cleanup and click
(#160). A passing observed run does not establish a fix for the unobserved failure.
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


def check_selection_colors(style, source, background):
    native = source.HighlightColor, source.HighlightTextColor
    actual = style.HighlightColor, style.HighlightTextColor
    if background == source.FieldColor or contrast(background, native[0]) >= 3:
        assert actual == native, ("The native selection pair changed", native, actual)
    else:
        assert actual[0] != native[0]
        assert contrast(background, actual[0]) >= 3
        assert contrast(*actual) >= 4.5


def check_document_colors(context, desktop, *, trace_input=True):
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
        panel, tree = open_list(context, document, trace_input=trace_input)
        poll(lambda: names(tree) == ["Alfa", "Bravo", "Charlie"], "the theme fixture rows")
        toolkit = panel.getToolkit()
        document.UndoManager.clear()
        document.setModified(False)
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
        "initial_input": initial_input,
        "palettes": evidence,
        "native_selection_kept": True,
        "model_input_and_document_kept": True,
    }


def exercise(context, desktop, directory, output):
    return check_document_colors(context, desktop)
