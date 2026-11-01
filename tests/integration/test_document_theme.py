"""Document colours update the installed list without changing rows, input or workbook (#141).

Only public native panel peers are observed. Configuration changes stay in the runner's private
profile and are restored before other suites run. Painted label/background pixels are covered
by the corresponding real-input check; these assertions alone do not establish native painting.
"""

from main_thread import close_after
from sheet_list_view import names, on_main_thread, open_list, poll, root, row_point, selection
from teardown import Configured
from test_sheet_list import Robot

from sheet_manager.theme import contrast
from sheet_manager.uno_calc import prop, selected_tabs


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


def check_document_colors(context, desktop):
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
        Robot(context).click(tree, row_point(tree, 1))
        poll(lambda: selection(tree, names(tree)) == ["Bravo"], "the independent Bravo pick")
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
        native = (source_style.FieldColor, source_style.FieldTextColor, source_style.ShadowColor)
        initial = tree.StyleSettings.FieldColor
        evidence = []
        with Configured(lambda: None, lambda: set_colors(settings, original)):
            for background, foreground, border in (
                (0x112233, 0xEEF4FF, 0x708090),
                (0xFFFFFF, 0xFFFFFF, 0xFFFFFF),
                (0xF1EAD1, 0x342C1D, 0xF1EAD1),
            ):
                set_colors(settings, (background, foreground, border))
                poll(
                    lambda expected=background: tree.StyleSettings.FieldColor == expected,
                    "the document colour to reach the list",
                )
                style = tree.StyleSettings
                assert contrast(background, style.FieldTextColor) >= 4.5
                assert contrast(background, style.HighlightColor) >= 3
                assert contrast(style.HighlightColor, style.HighlightTextColor) >= 4.5
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
                assert native == (
                    source_style.FieldColor,
                    source_style.FieldTextColor,
                    source_style.ShadowColor,
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
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {"palettes": evidence, "model_input_and_document_kept": True}


def exercise(context, desktop, directory, output):
    return check_document_colors(context, desktop)
