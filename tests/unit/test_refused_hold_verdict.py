"""The real-input `selected_press_cursor` check passes a case only when it shows the case (#71).

`_verdict` judges each case's record of a refused held press: the picks set up before the hold,
the cursor row heard when the button went up, and the rows heard after that, split where the
tree's mouse listeners heard the release. It is read from `tests/ui/focus_checks.py`, which
imports UNO, and run against synthetic records: the unpicked Delta and the Charlie event from
before button-up are the two ways an earlier version of the check passed without showing its
case.
"""

from collections.abc import Callable
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
