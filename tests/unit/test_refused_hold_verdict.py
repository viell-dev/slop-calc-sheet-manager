"""The real-input `selected_press_cursor` check passes a case only when it shows the case (#71).

`_verdict` judges each case's record of a refused held press: the picks set up before the hold,
the cursor row heard when the button went up, and the rows heard after that, split where the
tree's mouse listeners heard the release. `_refused_hold` makes that record. Both are read from
`tests/ui/focus_checks.py`, which imports UNO. `_verdict` runs against synthetic records, and
`_refused_hold` against `Office`, a fake LibreOffice main thread and list. The unpicked Delta,
a Charlie event from before button-up, and a rename case whose key never reached Hotel are ways
earlier versions of the check passed without showing their case.
"""

import itertools
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.source_methods import function

NAMES = [
    "Alfa",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliett",
    "Kilo",
    "Lima",
    "Mike",
]
MOVED = [NAMES[0], *NAMES[2:7], NAMES[1], *NAMES[7:]]
RENAMED = [name if name != "Hotel" else "Hotel 2" for name in MOVED]

# Each case as a correct run records it: Bravo moved to row 6, the pointer over row 1, Charlie.
SHOWN: dict[str, dict[str, Any]] = {
    "pressed": {"setup": ["Bravo"], "wanted": ["Bravo"], "held": 6, "toggled": []},
    "typed": {"setup": ["Bravo"], "wanted": ["Delta"], "held": 2, "toggled": []},
    "unpicked": {"setup": ["Bravo"], "wanted": ["Bravo"], "held": 7, "toggled": ["Bravo", "Hotel"]},
    "other_pick": {
        "setup": ["Bravo", "Delta"],
        "wanted": ["Delta", "Bravo"],
        "held": 2,
        "toggled": ["Bravo"],
    },
    "repeat": {"setup": ["Bravo"], "wanted": ["Bravo"], "held": 10, "toggled": ["Bravo", "Kilo"]},
    "renamed": {
        "setup": ["Alfa", "Bravo"],
        "wanted": ["Alfa", "Bravo"],
        "held": 6,
        "toggled": ["Alfa"],
        "order": RENAMED,
    },
}


def verdict() -> Callable[[str, dict[str, Any]], tuple[str | None, list[str]]]:
    return function("tests/ui/focus_checks.py", "_verdict", {"NAMES": NAMES})


def record(case: str, **changes: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {"order": MOVED, **SHOWN[case]}
    seen.update(between=[1], after=[seen["held"]], restored=seen["wanted"])
    seen.update(changes)
    return seen


@pytest.mark.parametrize("case", sorted(SHOWN))
def test_a_case_that_shows_its_claim_passes(case: str) -> None:
    cursor, problems = verdict()(case, record(case))
    assert problems == []
    assert cursor == record(case)["order"][record(case)["held"]]


def test_a_cursor_event_from_before_button_up_cannot_stand_for_the_release() -> None:
    """Ctrl+Down reached Hotel, an unrelated focus event reported Charlie while the button was
    still down, and button-up moved nothing: the tree's cursor was already on Charlie."""
    _, problems = verdict()("unpicked", record("unpicked", held=1, between=[]))
    assert "the cursor was not on the case's row when the button went up" in problems
    assert "the release did not reach the pressed row after the button went up" in problems


@pytest.mark.parametrize("between", [[], [7], [1, 7]])
def test_the_native_release_must_reach_the_pressed_row_after_button_up(between: list[int]) -> None:
    _, problems = verdict()("unpicked", record("unpicked", between=between))
    assert problems == ["the release did not reach the pressed row after the button went up"]


def test_other_pick_needs_both_picks_before_the_hold() -> None:
    """The setup Ctrl+click on Delta did nothing; Ctrl+Up then reached an unpicked Delta, and
    Ctrl+Space added it, which is what toggling the cursor's row would do anyway."""
    seen = record(
        "other_pick",
        setup=["Bravo"],
        wanted=["Bravo"],
        restored=["Bravo"],
        toggled=["Delta", "Bravo"],
    )
    _, problems = verdict()("other_pick", seen)
    assert problems == ["the picks before the hold were not the case's"]


@pytest.mark.parametrize("case", ["pressed", "typed", "unpicked", "repeat"])
def test_the_other_cases_start_from_bravo_alone(case: str) -> None:
    _, problems = verdict()(case, record(case, setup=["Bravo", "Delta"]))
    assert problems == ["the picks before the hold were not the case's"]


def test_the_repeat_target_is_the_cursor_heard_when_the_button_went_up() -> None:
    judge = verdict()
    seen = record("repeat", held=11, after=[11], toggled=["Bravo", "Lima"])
    assert judge("repeat", seen) == ("Lima", [])
    _, problems = judge("repeat", record("repeat", after=[11]))
    assert problems == ["the tree's cursor was not put back on the list's"]
    _, problems = judge("repeat", record("repeat", held=8, after=[8], toggled=["Bravo", "India"]))
    assert problems == ["the server did not repeat Down"]


def test_a_refresh_that_hands_the_cursor_to_another_pick_fails_the_renamed_case() -> None:
    """Hotel's rename dropped the cursor during the hold, and the first pick, Alfa, took it."""
    seen = record("renamed", held=0, after=[0], toggled=["Bravo"])
    _, problems = verdict()("renamed", seen)
    assert problems == [
        "the cursor was not on the case's row when the button went up",
        "the tree's cursor was not put back on the list's",
        "Ctrl+Space toggled another row",
    ]


CASES = ("pressed", "typed", "unpicked", "other_pick", "repeat", "renamed")


class Office:
    """LibreOffice's main thread, the list and real input, as `_refused_hold` meets them.

    The list answers input as the real one does, and each cursor event it or the tree makes
    reaches the probe with the time it was emitted. LibreOffice emits events only while its
    main thread is free, which it is at every step the check takes outside a callback from
    `view.on_main_thread`, before and after each clock reading. It handles a button-up injected
    outside such a callback at once, and one injected inside it once the callback returns.
    `stray` names the free moment, counted from the start, at which LibreOffice emits one
    unrelated cursor event on the pressed row. `release_moves` is whether the tree's native
    release moves its cursor there; `keys` whether the keyboard reaches the list.
    """

    def __init__(
        self, case: str, *, stray: int | None = None, release_moves: bool = True, keys: bool = True
    ) -> None:
        self.case, self.stray, self.release_moves, self.keys = case, stray, release_moves, keys
        self.clock = itertools.count(1)
        self.free_moments = 0
        self.busy = self.pending_up = False
        self.order = list(NAMES)
        self.picked: set[str] = set()
        self.cursor = NAMES[0]
        self.probe = SimpleNamespace(heard=[])
        self.probe.rows = lambda: [row for _, row in self.probe.heard]
        self.press = SimpleNamespace(heard=[])
        sheets = SimpleNamespace(moveByName=self.move, getByName=self.sheet)
        keyboard = SimpleNamespace(tap=self.tap, repeat=self.repeat)
        self.book = SimpleNamespace(
            tree=SimpleNamespace(makeNodeVisible=self.step),
            nodes=lambda: list(range(len(self.order))),
            first_visible=lambda: 0,
            click=self.click,
            selection=self.selection,
            hold=self.hold,
            order=lambda: list(self.order),
            document=SimpleNamespace(getSheets=lambda: sheets),
            lab=SimpleNamespace(context=None, input=keyboard),
            pointer=SimpleNamespace(release=self.button_up),
        )

    def run(self) -> dict[str, Any]:
        """`_refused_hold`'s record, completed as `check_selected_press_cursor` completes it."""
        view = SimpleNamespace(names=self.shown, on_main_thread=self.on_main)
        namespace: dict[str, Any] = {"NAMES": NAMES, "RENAMED": "Hotel 2", "Any": Any, "view": view}
        clock = SimpleNamespace(monotonic=self.now, sleep=self.step)
        namespace.update(time=clock, wait_until=self.wait_until)
        hold = function("tests/ui/focus_checks.py", "_refused_hold", namespace)
        seen = hold(self.book, self.case, self.probe, self.press, [])
        seen["restored"] = self.selection()
        seen["toggled"] = [name for name in self.order if name in self.picked ^ {self.cursor}]
        return seen

    # LibreOffice's main thread

    def tick(self) -> int:
        return next(self.clock)

    def free(self) -> None:
        if not self.busy:
            if self.free_moments == self.stray:
                self.emit(1)
            self.free_moments += 1

    def step(self, *ignored: object) -> None:
        """A step of the check, such as a pause, with the main thread free meanwhile."""
        self.free()

    def now(self) -> int:
        self.free()
        when = self.tick()
        self.free()
        return when

    def wait_until(self, condition: Callable[[], bool], what: str) -> None:
        self.free()
        if not condition():
            raise AssertionError(f"Timed out waiting for {what}")

    def on_main(self, context: object, work: Callable[[], None]) -> None:
        self.free()
        self.busy = True
        try:
            work()
        finally:
            self.busy = False
        if self.pending_up:
            self.pending_up = False
            self.handle_up()
        self.free()

    def emit(self, row: int) -> None:
        self.probe.heard.append((self.tick(), row))

    # The list and the tree

    def show_cursor(self) -> None:
        self.emit(self.order.index(self.cursor))

    def shown(self, tree: object) -> list[str]:
        return list(self.order)

    def selection(self) -> list[str]:
        return [name for name in self.order if name in self.picked]

    def click(self, index: int, modifiers: tuple[str, ...] = ()) -> None:
        self.step()
        name = self.order[index]
        self.picked = self.picked ^ {name} if modifiers else {name}
        self.cursor = name
        self.show_cursor()

    def hold(self, index: int, probe: object) -> None:
        """The press keeps the picks and puts the cursor on the pressed row."""
        self.step()
        self.press.heard.append(("pressed", self.tick()))
        self.cursor = self.order[index]
        self.show_cursor()

    def move(self, name: str, index: int) -> None:
        """The refresh rebuilds the rows and puts the cursor back on its sheet's new row."""
        self.step()
        self.order.remove(name)
        self.order.insert(index, name)
        self.show_cursor()

    def sheet(self, name: str) -> Any:
        def rename(new: str) -> None:
            # The refresh drops the cursor of a renamed sheet: the pressed pick takes it.
            self.step()
            self.order[self.order.index(name)] = new
            if self.cursor == name:
                self.cursor = NAMES[1] if NAMES[1] in self.picked else self.selection()[0]
            self.show_cursor()

        return SimpleNamespace(setName=rename)

    def tap(self, key: str, modifiers: tuple[str, ...] = (), pause: float = 0) -> None:
        self.step()
        if not self.keys:
            return
        index = self.order.index(self.cursor)
        if key == "d":
            self.picked, self.cursor = {"Delta"}, "Delta"
        elif key in ("Down", "Up"):
            self.cursor = self.order[index + (1 if key == "Down" else -1)]
        self.show_cursor()
        self.step()

    def repeat(self, key: str, modifiers: tuple[str, ...] = ()) -> None:
        self.step()
        for _ in range(4):
            self.cursor = self.order[self.order.index(self.cursor) + 1]
            self.show_cursor()

    def button_up(self) -> None:
        self.free()  # Only outside a main-thread callback can anything come before injection.
        if self.busy:
            self.pending_up = True
        else:
            self.handle_up()

    def handle_up(self) -> None:
        """The tree's native release, the mouse listeners, and the list's own cursor again."""
        if self.release_moves:
            self.emit(1)
        self.press.heard.append(("released", self.tick()))
        self.show_cursor()


@pytest.mark.parametrize("case", CASES)
def test_a_correct_run_of_each_case_passes(case: str) -> None:
    assert verdict()(case, Office(case).run())[1] == []


def test_the_renamed_case_needs_the_cursor_heard_on_hotel_after_the_key() -> None:
    """Ctrl+Down never reached the list: Bravo kept the cursor through Hotel's rename, so the
    rename dropped nothing, and the record alone would look like a correct run."""
    with pytest.raises(AssertionError, match="the cursor on Hotel"):
        Office("renamed", keys=False).run()


@pytest.mark.parametrize("case", CASES)
def test_no_cursor_event_from_before_button_up_can_stand_for_the_release(case: str) -> None:
    """The native release reaches no row, and LibreOffice emits one unrelated event on the
    pressed row at some free moment of the hold. At every such moment the case fails: no event
    can come between the cursor sampled at button-up and the injection.
    """
    control = Office(case)
    control.run()
    for stray in range(control.free_moments + 1):
        office = Office(case, stray=stray, release_moves=False)
        try:
            seen = office.run()
        except AssertionError:
            continue  # A wait saw the stray event instead of the one it waits for.
        _, problems = verdict()(case, seen)
        assert "the release did not reach the pressed row after the button went up" in problems, (
            stray,
            seen,
        )
