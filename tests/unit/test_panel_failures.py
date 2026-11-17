"""Panel, move-button and refresh failure boundaries (#186, #187, #188, #189).

Native creation and disposal are covered in `tests/integration/test_adapter_failures.py`.
"""

import contextlib
import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method

PANEL = "src/sheet_manager/uno_panel.py"
MOVES = "src/sheet_manager/uno_moves.py"
LIST = "src/sheet_manager/uno_list.py"


def failing(message: str) -> Mock:
    return Mock(side_effect=RuntimeError(message))


def panel_owner(**overrides: Any) -> Any:
    owner = SimpleNamespace(
        _disposed=False,
        _attached=True,
        _parent=SimpleNamespace(removeWindowListener=Mock()),
        list=SimpleNamespace(dispose=Mock()),
        _failure=SimpleNamespace(dispose=Mock()),
        _backdrop=SimpleNamespace(dispose=Mock()),
        Window=SimpleNamespace(dispose=Mock()),
        _listeners=[SimpleNamespace(disposing=Mock()), SimpleNamespace(disposing=Mock())],
    )
    for name, value in overrides.items():
        setattr(owner, name, value)
    detach = method(PANEL, "SheetPanel", "_detach", {})
    owner._detach = lambda: detach(owner)
    return owner


def test_panel_disposal_finishes_every_step_after_failures() -> None:
    report = Mock()
    owner = panel_owner(
        _parent=SimpleNamespace(removeWindowListener=failing("detach")),
        list=SimpleNamespace(dispose=failing("list")),
        _backdrop=SimpleNamespace(dispose=failing("backdrop")),
    )
    listeners = list(owner._listeners)
    listeners[0].disposing.side_effect = RuntimeError("listener")
    dispose = method(PANEL, "SheetPanel", "dispose", {"EventObject": Mock(), "report": report})
    dispose(owner)
    owner._failure.dispose.assert_called_once_with()
    owner.Window.dispose.assert_called_once_with()
    assert all(listener.disposing.call_count == 1 for listener in listeners)
    assert [call.args[0] for call in report.call_args_list] == [
        "detaching the panel",
        "disposing the sheet list",
        "disposing the panel backdrop",
        "telling a listener that the panel was disposed",
    ]
    dispose(owner)  # Idempotent: nothing runs or reports twice.
    owner.Window.dispose.assert_called_once_with()
    assert report.call_count == 4 and not owner._listeners


def test_a_partly_constructed_panel_disposes_only_what_it_created() -> None:
    report = Mock()
    window = SimpleNamespace(dispose=Mock())
    owner = panel_owner(_attached=False, list=None, _failure=None, _backdrop=None, Window=window)
    owner._listeners = []
    dispose = method(PANEL, "SheetPanel", "dispose", {"EventObject": Mock(), "report": report})
    dispose(owner)
    owner._parent.removeWindowListener.assert_not_called()
    window.dispose.assert_called_once_with()
    report.assert_not_called()


def test_a_failing_construction_step_disposes_the_panel_and_raises() -> None:
    disposed: list[bool] = []

    def initialize(context: object, toolkit: object, bounds: object) -> None:
        raise RuntimeError("backdrop")

    def dispose() -> None:
        disposed.append(True)

    def create_window(*args: object) -> object:
        return object()

    owner = SimpleNamespace(_initialize=initialize, dispose=dispose)
    construct = method(
        PANEL, "SheetPanel", "__init__", {"TOOLPANEL": 3, "_create_window": create_window}
    )
    parent = SimpleNamespace(getPosSize=object, getToolkit=object)
    arguments = {"Frame": object(), "ParentWindow": parent}
    with pytest.raises(RuntimeError, match="backdrop"):
        construct(owner, object(), "private:resource/toolpanel/SheetManager/Panel", arguments)
    assert disposed == [True]


@pytest.mark.parametrize("step", ["constructor", "bounds"])
def test_a_failed_list_shows_its_error_type_and_still_completes_the_panel(step: str) -> None:
    created: list[str] = []
    failure = RuntimeError("Sheet 'Private payroll' is unreadable")

    class FailingList:
        def __init__(self, *args: object) -> None:
            if step == "constructor":
                raise failure
            self.dispose = Mock()

        def set_bounds(self, width: int, height: int) -> None:
            raise failure

    def create_window(toolkit: object, service: str, parent: object, bounds: object) -> Any:
        created.append(service)
        return SimpleNamespace(setEnable=Mock())

    shown: list[str] = []

    def show_failure(context: object, kind: str, size: object) -> None:
        shown.append(kind)

    bounds = SimpleNamespace(Width=240, Height=500)
    owner = SimpleNamespace(
        Frame=object(),
        Window=object(),
        _parent=SimpleNamespace(addWindowListener=Mock()),
        list=None,
        _show_failure=show_failure,
    )
    report = Mock()
    initialize = method(
        PANEL,
        "SheetPanel",
        "_initialize",
        {
            "SheetList": FailingList,
            "_create_window": create_window,
            "report": report,
            "suppress": contextlib.suppress,
        },
    )
    initialize(owner, object(), object(), bounds)
    assert owner.list is None and shown == ["RuntimeError"]
    report.assert_called_once_with("creating the sheet list")
    assert created == ["window"] and owner._attached  # The backdrop, after the message.


def test_the_failure_message_names_only_the_error_type() -> None:
    model = SimpleNamespace(Label="")
    control = SimpleNamespace(getModel=lambda: model, setVisible=Mock())
    owner = SimpleNamespace(Window=object(), _place_failure=Mock())

    def text_control(context: object, parent: object) -> object:
        owner._failure = control
        return control

    show = method(PANEL, "SheetPanel", "_show_failure", {"text_control": text_control, "tr": str})
    show(owner, object(), "RuntimeException", SimpleNamespace(Width=240, Height=500))
    assert "(RuntimeException)" in model.Label and "Troubleshooting" in model.Label
    control.setVisible.assert_called_once_with(True)
    owner._place_failure.assert_called_once_with(240, 500)


def test_a_failing_failure_message_is_reported_not_raised() -> None:
    report = Mock()

    def text_control(context: object, parent: object) -> object:
        raise RuntimeError("no toolkit")

    owner = SimpleNamespace(Window=object(), _failure=None)
    show = method(
        PANEL,
        "SheetPanel",
        "_show_failure",
        {"text_control": text_control, "tr": str, "report": report},
    )
    show(owner, object(), "RuntimeError", SimpleNamespace(Width=1, Height=1))
    report.assert_called_once_with("showing that the sheet list failed")


@pytest.mark.parametrize("callback", ["actionPerformed", "mousePressed", "mouseReleased"])
def test_move_button_callbacks_report_failures_and_keep_working(callback: str) -> None:
    report = Mock()
    requested: list[str] = []
    stamped: list[bool] = []
    owner = SimpleNamespace(_request=failing("request"), _note_input=failing("stamp"))
    note = method(MOVES, "MoveButtons", "_note_button", {"report": report})

    def note_button(event: object, where: str) -> None:
        note(owner, event, where)

    owner._note_button = note_button
    handle = method(MOVES, "MoveButtons", callback, {"report": report})
    event = SimpleNamespace(ActionCommand="up", Buttons=1)
    handle(owner, event)  # Nothing escapes into LibreOffice.
    assert report.call_count == 1
    owner._request = requested.append
    owner._note_input = lambda: stamped.append(True)
    handle(owner, event)
    if callback == "actionPerformed":
        assert requested == ["up"] and not stamped
    else:
        assert stamped == [True] and not requested  # Stamped exactly once per press or release.
    handle(owner, SimpleNamespace(ActionCommand="up", Buttons=2))  # Not the left button.
    assert len(stamped) == (0 if callback == "actionPerformed" else 1)
    assert report.call_count == 1


def refreshing_list(fail: int) -> tuple[Any, list[float]]:
    """A list whose next `fail` refreshes raise; `scheduled` records the retry waits."""
    scheduled: list[float] = []
    calls = {"left": fail}

    def run(renamed: object) -> None:
        if calls["left"]:
            calls["left"] -= 1
            raise RuntimeError("synthetic property-read failure")

    owner = SimpleNamespace(
        _disposed=False,
        _stale_since=None,
        _refresh_failures=0,
        _refreshed_at=0.0,
        _refresh_cost=0.0,
        _refresh=run,
        _schedule=scheduled.append,
    )
    namespace: dict[str, Any] = {
        "time": time,
        "Mapping": Mapping,
        "REFRESH_RETRY": 0.5,
        "REFRESH_RETRY_MAX": 8.0,
        "REFRESH_RETRIES": 5,
    }
    mark = method(LIST, "SheetList", "_mark_stale", {})
    failed = method(LIST, "SheetList", "_refresh_failed", namespace)
    refresh = method(LIST, "SheetList", "refresh", namespace)

    def mark_stale(now: float) -> None:
        mark(owner, now)

    owner._mark_stale = mark_stale
    owner._refresh_failed = lambda: failed(owner)
    owner.refresh = lambda: refresh(owner)
    return owner, scheduled


def test_a_failed_refresh_stays_pending_and_retries_with_backoff() -> None:
    owner, scheduled = refreshing_list(fail=2)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="property-read"):
            owner.refresh()
        assert owner._stale_since is not None
    assert scheduled == [0.5, 1.0]
    owner.refresh()  # The retry succeeds with unchanged names and generation.
    assert owner._stale_since is None and owner._refresh_failures == 0
    assert scheduled == [0.5, 1.0]


def test_retries_stop_after_the_limit_instead_of_looping() -> None:
    owner, scheduled = refreshing_list(fail=7)
    for _ in range(7):
        with pytest.raises(RuntimeError):
            owner.refresh()
    assert scheduled == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert owner._stale_since is not None  # A later change refreshes again.


def test_disposal_cancels_a_pending_retry() -> None:
    timer = SimpleNamespace(cancel=Mock())
    owner = SimpleNamespace(
        _disposed=False,
        _main=SimpleNamespace(closed=False),
        _scroll=1,
        _refresh_timer=timer,
        _view_token=object(),
        _view_timer=None,
        _notice_token=None,
        _notice_timer=None,
        _view_controls=None,
        _cleanup=SimpleNamespace(close=Mock()),
        _theme=object(),
    )
    method(LIST, "SheetList", "dispose", {})(owner)
    timer.cancel.assert_called_once_with()
    assert owner._main.closed
