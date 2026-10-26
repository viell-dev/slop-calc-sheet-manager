"""A posted timeout cannot hide a newer notice or touch a disposed panel."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from tests.unit.source_methods import method

SOURCE = "src/sheet_manager/uno_list.py"


def owner() -> Any:
    def later(*args: object) -> Mock:
        return Mock()

    item = SimpleNamespace(
        _disposed=False,
        _status=SimpleNamespace(show_notice=Mock()),
        _notice_token=None,
        _notice_timer=None,
        _main=SimpleNamespace(later=Mock(side_effect=later), closed=False),
        _bounds=(300, 600),
        set_bounds=Mock(),
    )
    show = method(SOURCE, "SheetList", "_show_cleared_notice", {"NOTICE_SECONDS": 10.0})
    expire = method(SOURCE, "SheetList", "_expire_cleared_notice", {})
    item.show = lambda: show(item)

    def expire_notice(token: object) -> None:
        expire(item, token)

    item._expire_cleared_notice = expire_notice
    return item


def test_timeout_expires_after_ten_seconds() -> None:
    item = owner()
    item.show()
    seconds, callback, _ = item._main.later.call_args.args
    assert seconds == 10.0
    item._status.show_notice.assert_called_once_with(True)
    callback()
    item._status.show_notice.assert_called_with(False)
    assert item._notice_timer is None and item._notice_token is None
    assert item.set_bounds.call_count == 2


def test_old_callback_cannot_hide_a_newer_notice() -> None:
    item = owner()
    item.show()
    previous = item._notice_timer
    old_callback = item._main.later.call_args.args[1]
    item.show()
    token, timer = item._notice_token, item._notice_timer
    previous.cancel.assert_called_once()
    old_callback()
    assert (item._notice_token, item._notice_timer) == (token, timer)
    assert item._status.show_notice.call_args_list == [((True,),), ((True,),)]
    item._main.later.call_args.args[1]()
    item._status.show_notice.assert_called_with(False)


def test_disposal_cancels_notice_and_rejects_already_posted_work() -> None:
    item = owner()
    item._refresh_timer = item._view_timer = None
    item._view_token = item._view_controls = object()
    item._cleanup = Mock()
    item.show()
    timer, callback = item._notice_timer, item._main.later.call_args.args[1]
    dispose = method(SOURCE, "SheetList", "dispose", {})
    dispose(item)
    timer.cancel.assert_called_once()
    assert item._notice_token is None and item._main.closed
    callback()
    item.show()
    item._status.show_notice.assert_called_once_with(True)
