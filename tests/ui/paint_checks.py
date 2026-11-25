"""Painted rows and colours, checked against native geometry with screenshot pixels.

Each case writes the native measurements as JSON beside its screenshot. The pixel oracles,
`row_paint.py` and `theme_pixels.py`, run with the lab's system Python/Pillow outside
LibreOffice's Python environment, and the PNG and JSON stay in the artifacts as failure evidence.
Only the Linux runner registers these checks.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import sheet_list_view as view
from teardown import Configured
from test_document_theme import (
    FAINT_BLUE_SOURCE,
    STYLE_COLORS,
    check_selection_colors,
    color_settings,
    scheme_of,
    set_colors,
    set_source_colors,
)
from workbook import NAMES, Workbook, wait_until

from sheet_manager.theme import contrast, text_color

HERE = Path(__file__).resolve().parent


def check_document_colors(book):
    """Actual native labels, selection, dividers and empty space follow a custom document."""
    lab = book.lab
    sample = Workbook(lab, "document-colours", ["Alfa", "Bravo", "Charlie"])
    settings = color_settings(lab.context)
    scheme = scheme_of(settings)
    original = tuple(
        scheme.getByName(name).getByName("Color")
        for name in ("DocColor", "FontColor", "DocBoundaries")
    )
    evidence = {}
    try:
        sample.click(1)
        root = view.root(sample.tree)
        source_style = sample.document.CurrentController.Frame.ComponentWindow.StyleSettings
        native = tuple(getattr(source_style, name) for name in STYLE_COLORS)
        check_selection_colors(sample.tree.StyleSettings, source_style, source_style.FieldColor)
        original_height = sample.tree.getNodeRect(sample.nodes()[0]).Height
        before = sample.active(), sample.calc_tabs(), sample.undo_titles()
        with (
            Configured(lambda: None, lambda: set_colors(settings, original)),
            Configured(lambda: None, lambda: set_source_colors(lab.context, source_style, native)),
        ):
            for label, background, foreground, source in (
                ("dark", 0x112233, 0xEEF4FF, native),
                ("light", 0xF1EAD1, 0x342C1D, native),
                ("poor-contrast", 0xFFFFFF, 0xFFFFFF, native),
                (
                    "selection-background",
                    source_style.HighlightColor,
                    text_color(source_style.HighlightColor, None),
                    native,
                ),
                ("faint-native-selection", 0xFFFFFF, 0, FAINT_BLUE_SOURCE),
            ):
                set_source_colors(lab.context, source_style, source)
                set_colors(settings, (background, foreground, background))
                wait_until(
                    lambda expected=background: sample.tree.StyleSettings.FieldColor == expected,
                    "the custom document colour",
                )
                view.on_main_thread(lab.context, sample.panel.getToolkit().processEventsToIdle)
                style = sample.tree.StyleSettings
                assert contrast(background, style.FieldTextColor) >= 4.5
                assert contrast(background, style.ShadowColor) >= 3
                check_selection_colors(style, source_style, background)
                size = sample.tree.getOutputSize()
                rows = [sample.tree.getNodeRect(node) for node in sample.nodes()]
                assert rows[0].Height == original_height, (original_height, rows[0].Height)
                data = {
                    "offset": sample.pointer.offset,
                    "width": size.Width,
                    "height": size.Height,
                    "background": background,
                    "foreground": style.FieldTextColor,
                    "expected_foreground": 0 if background == foreground else foreground,
                    "highlight": style.HighlightColor,
                    "highlight_text": style.HighlightTextColor,
                    "border": style.ShadowColor,
                    "rows": [
                        {"x": row.X, "y": row.Y, "width": row.Width, "height": row.Height}
                        for row in rows
                    ],
                }
                stem = "document-colours-" + label
                path = lab.output / (stem + ".json")
                path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                lab.screenshot(stem)
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
                }
                checked = subprocess.run(
                    ["/usr/bin/python3", "-I", str(HERE / "theme_pixels.py"), str(path)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert checked.returncode == 0, checked.stdout + checked.stderr
                assert view.root(sample.tree) == root and sample.selection() == ["Bravo"]
                assert (sample.active(), sample.calc_tabs(), sample.undo_titles()) == before
                assert not sample.document.isModified()
                evidence[label] = json.loads(checked.stdout)
    finally:
        sample.close()
    return evidence


def check_row_paint_scroll(book, horizontal=False, prefix="row-paint-"):
    """Native geometry and screenshot pixels must agree throughout scrolling."""
    tree = book.tree
    original_height = tree.getProperty("RowHeight")
    native_view = book.active(), book.calc_tabs()
    evidence = {}

    def capture(name):
        if name != "native-height-picked":
            assert book.selection() == picked, "Scrolling or row sizing changed the picks"
        size = tree.getOutputSize()
        nodes = book.nodes()
        first = next(node for node in nodes if tree.getNodeRect(node).Y >= 0)
        rect = tree.getNodeRect(first)
        y = min(size.Height - 1, rect.Y + rect.Height // 2)
        viewport = next(
            x
            for x in range(size.Width, size.Width // 2, -1)
            if tree.getClosestNodeForLocation(x, y) is not None
        )
        content_height = next(
            bottom
            for bottom in range(size.Height, -1, -1)
            if tree.getClosestNodeForLocation(viewport // 2, bottom) is not None
        )
        rows = [tree.getNodeRect(node) for node in nodes]
        data = {
            "offset": book.pointer.offset,
            "width": size.Width,
            "height": size.Height,
            "viewport": viewport,
            "content_height": content_height,
            "last_label_width": rows[-1].Width,
            "shadow": tree.StyleSettings.ShadowColor,
            "rows": [{"Y": row.Y, "Height": row.Height} for row in rows],
        }
        stem = prefix + name
        path = book.lab.output / (stem + ".json")
        path.write_text(json.dumps(data, indent=2) + "\n")
        book.lab.screenshot(stem)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
        }
        checked = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                str(HERE / "row_paint.py"),
                str(path.with_suffix(".png")),
                str(path),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr
        evidence[name] = json.loads(checked.stdout)

    try:
        book.show_row(0)
        book.click(2)
        picked = book.selection()
        capture("initial")
        if horizontal:
            # The final fixture row is long. A short first row's text extent does not
            # change when it scrolls, so it cannot prove that the thumb gesture worked.
            long_node = book.nodes()[-1]
            before = tree.getNodeRect(long_node).Width
            y = tree.getOutputSize().Height - 7
            assert tree.getClosestNodeForLocation(90, y) is None, "No horizontal scrollbar"
            book.pointer.press(35, y)
            book.pointer.glide((35, y), (120, y))
            book.pointer.release()
            wait_until(
                lambda: tree.getNodeRect(long_node).Width > before,
                "horizontal thumb movement",
            )
            capture("thumb-right")
            book.pointer.press(120, y)
            book.pointer.glide((120, y), (tree.getOutputSize().Width - 18, y))
            book.pointer.release()
            time.sleep(0.4)
            capture("thumb-end")
        book.pointer.wheel(90, 200, True, 4)
        capture("wheel-down")
        book.pointer.wheel(90, 200, False, 1)
        capture("wheel-up")
        book.show_row(0)
        time.sleep(0.3)
        x = tree.getOutputSize().Width - 7
        book.pointer.press(x, 20)
        book.pointer.glide((x, 20), (x, 120))
        book.pointer.release()
        time.sleep(0.4)
        assert tree.getNodeRect(book.nodes()[0]).Y < 0, "The thumb gesture did not scroll"
        capture("thumb-down")
        book.pointer.press(x, 120)
        book.pointer.glide((x, 120), (x, 60))
        book.pointer.release()
        time.sleep(0.4)
        capture("thumb-up")
        book.show_row(-1)
        time.sleep(0.4)
        capture("last-row")
        # Like a font/DPI change, VCL may choose a height larger than the model requested.
        tree.setProperty("RowHeight", original_height + 4)
        book.show_row(0)
        tree.invalidate(0)
        time.sleep(0.4)
        capture("native-height-change")
        rect = tree.getNodeRect(book.nodes()[10])
        book.pointer.click(5, rect.Y + rect.Height - 2)
        wait_until(
            lambda: book.selection() == [book.order()[10]], "hit testing the native row bottom"
        )
        capture("native-height-picked")
        assert (book.active(), book.calc_tabs()) == native_view
    finally:
        tree.setProperty("RowHeight", original_height)
        tree.invalidate(0)
    return evidence


def check_row_paint_long_names(lab):
    """Exercise both native scrollbars without changing the ordinary workbook's state."""
    evidence = {}
    for name, names in (
        ("equal", ["W" * 28 + f"{n:02}" for n in range(80)]),
        ("mixed", [*NAMES[:-1], "W" * 30]),
    ):
        book = Workbook(lab, "synthetic long labels " + name, names)
        try:
            evidence[name] = check_row_paint_scroll(
                book, horizontal=True, prefix="row-paint-" + name + "-"
            )
        finally:
            book.close()
    return evidence
