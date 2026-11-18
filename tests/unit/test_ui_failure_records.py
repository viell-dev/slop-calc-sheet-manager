"""A failed UI check's record survives failures of its own diagnostics and clean-up (#190).

The UI check loop imports UNO through the workbook fixture, so `run_named` and `after_failure`
are read from its source and run against a fake lab, with the real `teardown` module, as in
`test_stalled_cleanup.py`.
"""

import json
import time
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration.teardown import record_stalled_callback, stalled_callbacks, start_session
from tests.unit.source_methods import function

RUNNER = "tests/ui/check_loop.py"
STEPS = ("screenshot", "desktop", "release_held", "escape")
PRIMARY = "AssertionError: original synthetic assertion"


@pytest.fixture(autouse=True)
def fresh_session() -> Iterator[None]:
    start_session()
    yield
    start_session()


class Lab:
    """Records each diagnostic and clean-up step, and what `checks.json` held as it began."""

    def __init__(self, output: Path, failing: str | None = None) -> None:
        self.output, self.failing = output, failing
        self.input = self
        self.steps: list[str] = []
        self.on_disk: dict[str, Any] = {}

    def _step(self, step: str) -> None:
        self.steps.append(step)
        self.on_disk.setdefault(step, json.loads((self.output / "checks.json").read_text("utf-8")))
        if step == self.failing:
            raise RuntimeError(f"synthetic {step} failure")

    def screenshot(self, name: str) -> None:
        assert name == "failed-synthetic"
        self._step("screenshot")

    def failure_evidence(self) -> dict[str, object]:
        self._step("desktop")
        return {"foreground": "synthetic window"}

    def release_held(self) -> None:
        self._step("release_held")

    def tap(self, key: str, pause: float = 0) -> None:
        assert key == "Escape"
        self._step("escape")


def runner(resets: list[str]) -> Callable[..., dict[str, Any]]:
    def reset(book: object) -> None:
        resets.append("reset")

    namespace: dict[str, Any] = {
        "reset": reset,
        "time": time,
        "json": json,
        "traceback": traceback,
        "stalled_callbacks": stalled_callbacks,
    }
    function(RUNNER, "after_failure", namespace)
    return function(RUNNER, "run_named", namespace)


def failing() -> object:
    raise AssertionError("original synthetic assertion")


def saved(output: Path) -> dict[str, Any]:
    return json.loads((output / "checks.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("failing_step", STEPS)
def test_a_failing_step_keeps_the_check_record_and_every_other_step(
    tmp_path: Path, failing_step: str, capsys: pytest.CaptureFixture[str]
) -> None:
    lab = Lab(tmp_path, failing_step)
    checks = [
        ("earlier", lambda: "earlier evidence"),
        ("synthetic", failing),
        ("later", lambda: "later evidence"),
    ]
    resets: list[str] = []
    results = runner(resets)(lab, None, tmp_path, checks)

    assert saved(tmp_path) == results and len(resets) == 3, "The next check still runs"
    assert results["earlier"]["evidence"] == "earlier evidence" and results["later"]["pass"]
    record = results["synthetic"]
    assert record["pass"] is False and PRIMARY in record["error"]
    errors = record["diagnostic_errors"]
    assert list(errors) == [failing_step]
    assert f"RuntimeError: synthetic {failing_step} failure" in errors[failing_step]
    assert ("desktop" in record) == (failing_step != "desktop")
    assert list(dict.fromkeys(lab.steps)) == list(STEPS), "Every step runs, in order"
    assert f"synthetic FAIL (diagnostics failed: {failing_step})" in capsys.readouterr().out

    # Each step began with the primary record, and everything collected before it, on disk.
    for index, step in enumerate(STEPS):
        on_disk = lab.on_disk[step]
        assert on_disk["earlier"] == results["earlier"]
        assert on_disk["synthetic"]["pass"] is False and PRIMARY in on_disk["synthetic"]["error"]
        assert ("desktop" in on_disk["synthetic"]) == (
            STEPS.index("desktop") < index and failing_step != "desktop"
        )
        failed_before = STEPS.index(failing_step) < index
        assert ("diagnostic_errors" in on_disk["synthetic"]) == failed_before


def test_every_step_failing_still_leaves_the_primary_failure(tmp_path: Path) -> None:
    class Broken(Lab):
        def _step(self, step: str) -> None:
            super()._step(step)
            raise RuntimeError(f"synthetic {step} failure")

    lab = Broken(tmp_path)
    results = runner([])(lab, None, tmp_path, [("synthetic", failing)])
    record = saved(tmp_path)["synthetic"]
    assert record == results["synthetic"] and PRIMARY in record["error"]
    assert list(record["diagnostic_errors"]) == list(STEPS)
    assert "desktop" not in record and "seconds" in record


def test_a_stall_with_failing_diagnostics_still_stops_before_another_reset(
    tmp_path: Path,
) -> None:
    def stalls() -> object:
        record_stalled_callback("work on LibreOffice's main thread did not finish")
        raise AssertionError("original synthetic assertion")

    lab = Lab(tmp_path, "screenshot")
    resets: list[str] = []
    checks = [("synthetic", stalls), ("later", lambda: pytest.fail("ran after a stall"))]
    with pytest.raises(TimeoutError, match="main thread did not finish"):
        runner(resets)(lab, None, tmp_path, checks)
    assert resets == ["reset"], "No reset or check follows a stalled main thread"
    record = saved(tmp_path)["synthetic"]
    assert record["pass"] is False and PRIMARY in record["error"]
    assert list(record["diagnostic_errors"]) == ["screenshot"] and "seconds" in record
    assert list(dict.fromkeys(lab.steps)) == list(STEPS), "Display-only clean-up still runs"
