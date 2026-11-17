"""Input in the list makes its window Calc's active one; enablement does not wait for it (#211).

The native behaviour, LibreOffice leaving a focused window's frame inactive, is reproduced with
real input in the UI suite and through the toolkit robot in integration.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.keys import (
    RETURN,
    SHIFT,
    SPACE,
    TAB,
    KeyRoute,
    button_route,
    move_action,
    route_key,
    unbound_route,
)
from tests.unit.source_methods import function, method

LIST = "src/sheet_manager/uno_list.py"
REORDER = "src/sheet_manager/uno_reorder.py"
ACTIVATION = "Activate this document's window before moving sheets."


@dataclass(frozen=True)
class Availability:
    allowed: bool
    reason: str = ""
    detail: str = ""
    undo_steps: int = 0


def sheet_list(active: bool, *, disposed: bool = False) -> tuple[Any, list[Any]]:
    queued: list[Any] = []
    controller = object()
    frame = SimpleNamespace(
        isActive=Mock(return_value=active), activate=Mock(), getController=lambda: controller
    )

    def post(work: Any, where: str) -> None:
        queued.append(work)

    owner = SimpleNamespace(
        _disposed=disposed, _claim_pending=False, frame=frame, controller=controller, post=post
    )
    claim = method(LIST, "SheetList", "claim_window", {})
    run = method(LIST, "SheetList", "_activate_window", {})
    owner.claim_window = lambda: claim(owner)
    owner._activate_window = lambda: run(owner)
    return owner, queued


def test_input_activates_an_inactive_window_once_ahead_of_its_own_work() -> None:
    owner, queued = sheet_list(active=False)
    owner.claim_window()
    owner.claim_window()  # A press and its release, or several keys, before the queue runs.
    assert len(queued) == 1
    queued.pop()()
    owner.frame.activate.assert_called_once_with()
    owner.claim_window()  # Later input claims again.
    assert len(queued) == 1


@pytest.mark.parametrize("state", ["active", "replaced", "disposed"])
def test_a_claim_leaves_an_active_replaced_or_closed_window_alone(state: str) -> None:
    owner, queued = sheet_list(active=state == "active")
    owner.claim_window()
    if state == "replaced":
        owner.frame.getController = object  # Reload: another controller's panel owns it.
    elif state == "disposed":
        owner._disposed = True
    queued.pop()()
    owner.frame.activate.assert_not_called()
    assert not owner._claim_pending


def test_a_closed_list_posts_no_claim() -> None:
    owner, queued = sheet_list(active=False, disposed=True)
    owner.claim_window()
    assert not queued


def permitted_document(active: bool | None) -> Any:
    """A document every move permission allows; `active` None means never ask its frame."""

    def frame() -> Any:
        if active is None:
            raise AssertionError("enablement must not depend on window activation")
        return SimpleNamespace(isActive=lambda: active)

    undo = SimpleNamespace(
        isLocked=lambda: False, getAllUndoActionTitles=lambda: (), isUndoPossible=lambda: False
    )
    properties = {"RecordChanges": False, "IsUndoEnabled": True}
    return SimpleNamespace(
        isReadonly=lambda: False,
        isProtected=lambda: False,
        getPropertyValue=properties.__getitem__,
        getUndoManager=lambda: undo,
        getCurrentController=lambda: SimpleNamespace(getFrame=frame),
    )


def test_move_enablement_does_not_ask_whether_the_window_is_active() -> None:
    def undo_steps(context: object) -> int:
        return 100

    availability = function(
        REORDER,
        "move_availability",
        {"Any": Any, "Availability": Availability, "tr": str, "_undo_steps": undo_steps},
    )
    assert availability(object(), permitted_document(None)) == Availability(True, undo_steps=100)


@pytest.mark.parametrize("active", [True, False])
def test_the_move_itself_still_requires_the_active_window(active: bool) -> None:
    plan = SimpleNamespace(before=("Alfa",), target=("Alfa",))
    permission = Availability(True, undo_steps=100)
    conflicts: list[object] = []

    def lookup_conflict(document: object, checked: object) -> None:
        conflicts.append(checked)

    def current(document: object, observed: object) -> bool:
        return True

    def plan_order(sheets: object, target: object) -> object:
        return plan

    def plan_availability(found: Availability, checked: object) -> Availability:
        return found

    def move_availability(context: object, document: object) -> Availability:
        return permission

    preflight = function(
        REORDER,
        "preflight",
        {
            "Any": Any,
            "Snapshot": object,
            "Plan": object,
            "Availability": Availability,
            "tr": str,
            "is_current": current,
            "plan_order": plan_order,
            "plan_availability": plan_availability,
            "move_availability": move_availability,
            "_lookup_conflict": lookup_conflict,
        },
    )
    observed = SimpleNamespace(sheets=("Alfa",))
    result = preflight(object(), permitted_document(active), observed, plan)
    assert result == (permission if active else Availability(False, ACTIVATION))
    assert conflicts == ([plan] if active else [])


@pytest.mark.parametrize("owned", [True, False])
def test_an_owned_key_claims_the_window_before_any_work_it_posts(owned: bool) -> None:
    calls: list[str] = []

    def record(name: str, result: Any = None) -> Any:
        def call(*args: Any) -> Any:
            calls.append(name)
            return result

        return call

    sheet = SimpleNamespace(
        owns_keys=record("owns_keys", owned),
        claim_window=record("claim_window"),
        owns_tree_keys=record("owns_tree_keys", True),
        travel_focus=record("travel_focus", True),
        queue_input=record("queue_input"),
        activate_selection=record("activate_selection"),
    )
    handler = SimpleNamespace(_list=sheet, _consumed={})
    pressed = method(
        "src/sheet_manager/uno_keys.py",
        "ListKeyHandler",
        "keyPressed",
        {
            "route_key": route_key,
            "button_route": button_route,
            "move_action": move_action,
            "unbound_route": unbound_route,
            "KeyRoute": KeyRoute,
            "TAB": TAB,
            "SHIFT": SHIFT,
            "SPACE": SPACE,
            "report": Mock(),
        },
    )
    for code, char in ((RETURN, "\r"), (TAB, "\t")):
        calls.clear()
        pressed(handler, SimpleNamespace(KeyCode=code, KeyChar=char, Modifiers=0))
        assert calls[:2] == (["owns_keys", "claim_window"] if owned else ["owns_keys"]), calls
        assert calls.count("claim_window") == (1 if owned else 0)
