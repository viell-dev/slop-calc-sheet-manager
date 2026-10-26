"""Release ordering and exceptional exits must not leave a frame's guard registered."""

from collections.abc import Callable
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method


class Disposed(Exception):
    pass


@pytest.mark.parametrize("failure", ["none", "controller", "execute", "dispose", "post"])
def test_native_guard_release_survives_closed_list_queue(failure: str) -> None:
    queued: list[Callable[[], None]] = []
    events: list[str] = []
    frame, controller, popup = Mock(), Mock(), Mock()
    service = Mock()
    service.createInstanceWithArgumentsAndContext.return_value = controller
    if failure == "controller":
        service.createInstanceWithArgumentsAndContext.side_effect = RuntimeError("controller")
    if failure == "dispose":
        controller.dispose.side_effect = RuntimeError("dispose")

    def execute(*args: object) -> None:
        events.append("native-command-posted")
        if failure == "execute":
            raise RuntimeError("execute")

    def post(work: Callable[[], None], where: str) -> None:
        events.append("release-posted")
        if failure == "post":
            raise RuntimeError("post")
        queued.append(work)

    popup.execute.side_effect = execute

    def main_thread(context: object) -> SimpleNamespace:
        return SimpleNamespace(post=post)

    def prop(name: str, value: object) -> tuple[str, object]:
        return name, value

    owner = SimpleNamespace(
        _frame=frame,
        _context=SimpleNamespace(ServiceManager=service),
        _report_refusal=Mock(),
        _begin_command=Mock(),
        _end_command=Mock(),
        _popup=lambda: popup,
        _post=Mock(side_effect=AssertionError("Disposed list queue must not own guard cleanup")),
    )
    native = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "_native",
        {
            "_MenuGuard": Mock(),
            "MainThread": main_thread,
            "DisposedException": Disposed,
            "suppress": suppress,
            "Rectangle": Mock(),
            "prop": prop,
        },
    )
    observed = SimpleNamespace(sheets=[], handles=[])
    if failure == "none":
        native(owner, object(), 1, 2, observed, [], lambda: True)
    else:
        with pytest.raises(RuntimeError, match=failure):
            native(owner, object(), 1, 2, observed, [], lambda: True)
    guard = frame.registerDispatchProviderInterceptor.call_args.args[0]
    owner._post.assert_not_called()
    if failure in {"controller", "post"}:
        frame.releaseDispatchProviderInterceptor.assert_called_once_with(guard)
        assert not queued
    else:
        frame.releaseDispatchProviderInterceptor.assert_not_called()
        assert events == ["native-command-posted", "release-posted"]
        queued[0]()
        frame.releaseDispatchProviderInterceptor.assert_called_once_with(guard)
        frame.releaseDispatchProviderInterceptor.side_effect = Disposed("frame closed")
        queued[0]()  # Frame closure is harmless; other failures must still surface.
        frame.releaseDispatchProviderInterceptor.side_effect = RuntimeError("release")
        with pytest.raises(RuntimeError, match="release"):
            queued[0]()
