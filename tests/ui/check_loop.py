"""The check loop that both real-input runners share.

Each runner owns its platform setup, its explicit list of checks and its exit status;
`run_named` runs that list, or the runner's `--check` selection from it, each check from a reset
workbook. It writes a failed check's record before collecting that failure's screenshot and
desktop state or releasing its input, and a failing diagnostic step is recorded beside the
check's error, never in place of it (#190). After a stalled main-thread callback it stops without
another reset or check (#52).
"""

import json
import time
import traceback

from teardown import note_progress, stalled_callbacks
from workbook import reset


def run_named(lab, book, output, checks, only=()):
    """Run `checks`, (name, function) pairs, each from a reset workbook; `only` selects some.

    `checks.json` is rewritten after every check. A failed check's record, with its traceback,
    is written before anything else runs; `after_failure` then keeps its diagnostics and cleans
    up its input (#190). The next check still runs, unless LibreOffice's main thread is stuck.
    """
    if only:
        unknown = set(only) - {name for name, _ in checks}
        if unknown:
            raise ValueError(f"Unknown checks: {sorted(unknown)}")
        checks = [(name, check) for name, check in checks if name in only]
    results = {}

    def save():
        (output / "checks.json").write_text(json.dumps(results, indent=2) + "\n", "utf-8")

    for name, check in checks:
        started = time.monotonic()
        note_progress()  # The session's stall watch counts checks as progress (#45).
        try:
            reset(book)
            results[name] = {"pass": True, "evidence": check()}
        except Exception:
            results[name] = {"pass": False, "error": traceback.format_exc()}
            save()
            after_failure(lab, name, results[name], save)
        results[name]["seconds"] = round(time.monotonic() - started, 2)
        failed_steps = ", ".join(results[name].get("diagnostic_errors", {}))
        note = f" (diagnostics failed: {failed_steps})" if failed_steps else ""
        print(name, ("pass" if results[name]["pass"] else "FAIL") + note, flush=True)
        save()
        if stalled_callbacks():  # The main thread is stuck: no reset, check, or close (#52).
            raise TimeoutError(stalled_callbacks()[0])
    return results


def after_failure(lab, name, record, save):
    """Keep a failed check's screenshot and desktop state, then clean up its input.

    Each step runs on its own, and `save` checkpoints the record after each. A step that raises
    adds its traceback to `record["diagnostic_errors"]` under its name, and the later steps still
    run: the check's own failure stays its `error`, and the check stays failed (#190). Every step
    reaches only the display through the lab, never UNO, so they also run after a stalled main
    thread, before `run_named` stops.
    """

    def screenshot():
        lab.screenshot(f"failed-{name}")

    def desktop():
        evidence = lab.failure_evidence()
        if evidence:
            record["desktop"] = evidence

    def release_held():
        lab.input.release_held()  # A press held across the failure would drag in the next.

    def escape():
        for _ in range(2):
            lab.input.tap("Escape", pause=0.3)

    for step, action in (
        ("screenshot", screenshot),
        ("desktop", desktop),
        ("release_held", release_held),
        ("escape", escape),
    ):
        try:
            action()
        except Exception:
            record.setdefault("diagnostic_errors", {})[step] = traceback.format_exc()
        save()
