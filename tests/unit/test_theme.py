"""Palette readability; native rendering and live updates are covered by host tests."""

import ast
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.theme import contrast, palette, text_color
from tests.unit.source_methods import ROOT, method


def test_known_contrast_and_explicit_readable_colours() -> None:
    assert contrast(0, 0xFFFFFF) == 21
    assert contrast(0x123456, 0x123456) == 1
    result = palette(0x112233, 0xEEF4FF, 0x0078D4, 0xFFFFFF, 0x708090)
    assert result.background == 0x112233 and result.foreground == 0xEEF4FF
    assert result.highlight == 0x0078D4 and result.highlight_text == 0xFFFFFF
    assert result.border == 0x708090


@pytest.mark.parametrize("highlight", [0x3584E4, 0x3DAEE9, 0x007AFF, 0x0078D7, 0x0078D4])
def test_default_native_selection_pair_is_preserved(highlight: int) -> None:
    result = palette(0xFFFFFF, None, highlight, 0xFFFFFF, None, 0xFFFFFF)
    assert (result.highlight, result.highlight_text) == (highlight, 0xFFFFFF)


def test_retaining_a_distinct_selection_also_retains_its_native_text() -> None:
    result = palette(0xFFFFFF, None, 0x3584E4, 0xFFFFFF, None)
    assert (result.highlight, result.highlight_text) == (0x3584E4, 0xFFFFFF)


def test_selection_is_synthesised_only_when_the_document_background_hides_it() -> None:
    result = palette(0x3584E4, None, 0x3584E4, 0xFFFFFF, None, 0xFFFFFF)
    assert result.highlight != 0x3584E4
    assert contrast(result.highlight, result.background) >= 3
    assert contrast(result.highlight, result.highlight_text) >= 4.5


@pytest.mark.parametrize("background", [0, 0xFFFFFF, 0x1C1C1C, 0x808080, 0x112233, 0xFFFF00])
@pytest.mark.parametrize("preferred", [None, -1, 0, 0xFFFFFF, 0x123456, 0x1000000])
def test_unreadable_colours_are_replaced_together(background: int, preferred: int | None) -> None:
    result = palette(background, preferred, background, background, preferred)
    assert result.background == background
    assert contrast(background, result.foreground) >= 4.5
    assert contrast(background, result.border) >= 3
    assert contrast(background, result.highlight) >= 3
    assert contrast(result.highlight, result.highlight_text) >= 4.5
    assert text_color(background, preferred) == result.foreground


def surface_finder() -> Any:
    path = "src/sheet_manager/uno_theme.py"
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "document_surface"
    )
    namespace: dict[str, Any] = {"Any": Any, "DOCUMENT": 84, "LEAVES": {58, 65}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace["document_surface"]


def test_document_surface_does_not_enumerate_cells() -> None:
    item = SimpleNamespace(
        getAccessibleRole=lambda: 84,
        getBackground=lambda: 0x112233,
        getAccessibleChildCount=Mock(side_effect=AssertionError("enumerated document cells")),
    )
    assert surface_finder()(item) is item
    item.getAccessibleChildCount.assert_not_called()


def test_missing_children_and_contexts_are_skipped() -> None:
    document = SimpleNamespace(getAccessibleRole=lambda: 84)
    children = [
        None,
        SimpleNamespace(getAccessibleContext=lambda: None),
        SimpleNamespace(getAccessibleContext=lambda: document),
    ]

    def child(index: int) -> Any:
        return children[index]

    parent = SimpleNamespace(
        getAccessibleRole=lambda: 40,
        getAccessibleChildCount=lambda: 3,
        getAccessibleChild=child,
    )
    assert surface_finder()(parent) is document


def test_cached_surface_is_read_again_without_rewalking_and_replaced_with_the_window() -> None:
    surface = SimpleNamespace(getBackground=Mock(side_effect=[0xFFFFFF, 0x112233, 0xF1EAD1]))
    find = Mock(return_value=surface)
    window = SimpleNamespace(
        getProperty=Mock(
            return_value=SimpleNamespace(getAccessibleContext=Mock(return_value=object()))
        )
    )
    owner = SimpleNamespace(_window=None, _surface=None)
    read = method(
        "src/sheet_manager/uno_theme.py", "ListTheme", "_background", {"document_surface": find}
    )
    assert read(owner, window) == 0xFFFFFF
    assert read(owner, window) == 0x112233
    assert find.call_count == 1 and window.getProperty.call_count == 1
    other = SimpleNamespace(getProperty=Mock(return_value=window.getProperty.return_value))
    assert read(owner, other) == 0xF1EAD1
    assert find.call_count == 2


@pytest.mark.parametrize("transient", ["disposed", "index"])
def test_transient_surface_failure_retries_on_the_next_sample(transient: str) -> None:
    class Disposed(Exception):
        pass

    class MissingIndex(Exception):
        pass

    error = Disposed if transient == "disposed" else MissingIndex
    work = Mock(side_effect=[error(), None])
    owner = SimpleNamespace(failed=False, _surface=object(), _window=object(), _apply=work)
    reports = Mock()
    apply = method(
        "src/sheet_manager/uno_theme.py",
        "ListTheme",
        "apply",
        {
            "DisposedException": Disposed,
            "IndexOutOfBoundsException": MissingIndex,
            "report": reports,
        },
    )
    apply(owner)
    assert owner._surface is None and owner._window is None and not owner.failed
    apply(owner)
    assert work.call_count == 2
    reports.assert_not_called()


def test_unexpected_theme_failure_is_still_reported_once_and_stops_sampling() -> None:
    reports = Mock()
    work = Mock(side_effect=RuntimeError("unexpected failure"))
    owner = SimpleNamespace(failed=False, _apply=work)
    apply = method(
        "src/sheet_manager/uno_theme.py",
        "ListTheme",
        "apply",
        {
            "DisposedException": type("Disposed", (Exception,), {}),
            "IndexOutOfBoundsException": type("MissingIndex", (Exception,), {}),
            "report": reports,
        },
    )
    apply(owner)
    apply(owner)
    assert owner.failed
    work.assert_called_once()
    reports.assert_called_once_with("following document colours")


@pytest.mark.parametrize("role,count", [(58, 2**34), (65, 1000), (40, 65)])
def test_cell_tables_rows_and_large_child_sets_are_not_walked(role: int, count: int) -> None:
    item = SimpleNamespace(
        getAccessibleRole=lambda: role,
        getAccessibleChildCount=lambda: count,
        getAccessibleChild=Mock(side_effect=AssertionError("walked a leaf")),
    )
    assert surface_finder()(item) is None
    item.getAccessibleChild.assert_not_called()


def test_a_cyclic_or_branching_native_hierarchy_has_a_total_visit_budget() -> None:
    role = Mock(return_value=40)
    item = SimpleNamespace(getAccessibleRole=role, getAccessibleChildCount=lambda: 64)
    item.getAccessibleChild = Mock(
        return_value=SimpleNamespace(getAccessibleContext=Mock(return_value=item))
    )
    assert surface_finder()(item) is None
    assert role.call_count == 128


@pytest.mark.parametrize("where", ["FieldTextColor", "BackgroundColor", "RowHeight", "invalidate"])
@pytest.mark.parametrize("after", [False, True])
def test_a_failed_native_colour_update_restores_the_whole_previous_palette(
    where: str, after: bool
) -> None:
    old = {
        "FieldColor": 0xFFFFFF,
        "FieldTextColor": 0,
        "HighlightColor": 0x0078D4,
        "HighlightTextColor": 0xFFFFFF,
        "ShadowColor": 0x737373,
    }
    failures: list[str] = []

    def fail(name: str, action: Any) -> None:
        if name == where and not failures:
            failures.append(name)
            if after:
                action()
            raise RuntimeError("native setter failed")
        action()

    class Style:
        def __init__(self) -> None:
            self.values = old.copy()

        def __getattr__(self, name: str) -> int:
            return self.values[name]

        def __setattr__(self, name: str, value: Any) -> None:
            if name == "values":
                object.__setattr__(self, name, value)
            else:
                fail(name, lambda: self.values.__setitem__(name, value))

    style = Style()
    background: list[Any] = [None]

    def set_background(name: str, value: Any) -> None:
        fail(name, lambda: background.__setitem__(0, value))

    def invalidate(flags: int) -> None:
        fail("invalidate", lambda: None)

    height = [22]

    def set_height(name: str, value: int) -> None:
        fail(name, lambda: height.__setitem__(0, value))

    peer = SimpleNamespace(
        StyleSettings=style,
        invalidate=invalidate,
        getProperty=Mock(return_value=22),
        setProperty=set_height,
    )

    def model_property(name: str) -> Any:
        return 22 if name == "RowHeight" else None

    model = SimpleNamespace(getPropertyValue=model_property, setPropertyValue=set_background)
    source = SimpleNamespace(**old)
    window = SimpleNamespace(
        StyleSettings=source,
        getProperty=Mock(
            return_value=SimpleNamespace(getAccessibleContext=Mock(return_value=object()))
        ),
    )
    desired = {"FontColor": 0xEEF4FF, "DocBoundaries": 0x708090}

    def entry(name: str) -> Any:
        return SimpleNamespace(getByName=Mock(return_value=desired[name]))

    scheme = SimpleNamespace(getByName=entry)
    schemes = SimpleNamespace(
        hasByName=Mock(return_value=True), getByName=Mock(return_value=scheme)
    )

    def configuration(name: str) -> Any:
        return schemes if name == "ColorSchemes" else "test"

    colors = SimpleNamespace(getByName=configuration)
    owner = SimpleNamespace(
        frame=SimpleNamespace(getComponentWindow=lambda: window),
        tree=SimpleNamespace(getPeer=lambda: peer, getModel=lambda: model),
        colors=colors,
        _background=Mock(return_value=0x112233),
        _current=None,
    )
    reports = Mock()
    apply = method(
        "src/sheet_manager/uno_theme.py",
        "ListTheme",
        "_apply",
        {
            "palette": palette,
            "report": reports,
        },
    )
    with pytest.raises(RuntimeError, match="native setter failed"):
        apply(owner)
    assert failures == [where] and style.values == old and background == [None] and height == [22]
    assert owner._current is None
    reports.assert_not_called()
