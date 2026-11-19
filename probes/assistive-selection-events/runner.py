"""Drive the #294 probe with real XTEST input in the CI image; run with LibreOffice's Python.

Measurement only; never shipped. `session.sh` starts it under Xvfb and Openbox as
`ci/desktop-session.sh` starts the UI suite. It uses the repository's own UI fixture (the checkout
mounted read-only at /work) to open a synthetic workbook of eight sheets, Alfa to Hotel, with the
sheet list, installs `a11y_probe.py` into the private profile's user scripts, and runs each phase
below once per VCL plugin, in its own office. A phase prepares the picks without recording,
resets the probe, acts, waits for the list's queued work and the tab sample to settle, and keeps
the probe's records with the list's state and the tree's selection.
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path("/work")
sys.path[:0] = [str(ROOT / "tests" / "ui"), str(ROOT / "tests" / "integration"), str(ROOT / "src")]

from lab import Lab  # noqa: E402
from run import office_session  # noqa: E402
from workbook import NAMES, Workbook, wait_until  # noqa: E402

HERE = Path(__file__).resolve().parent
PROBE = (HERE / "a11y_probe.py").read_text("utf-8")
EIGHT = NAMES[:8]
CTRL = ("Control_L",)
CTRL_SHIFT = ("Control_L", "Shift_L")
SETTLE = 1.5
SETTLE_LIMIT = 8.0
QUIET = 900.0
ROUTINE = {"observing Calc's selected tabs", "finishing sheet row borders"}


def significant(entry):
    """A record other than the tab sample's routine work when it finds nothing to do."""
    if entry["kind"] in ("post", "run") and entry["where"] in ROUTINE:
        return False
    if entry.get("method") == "_take_tree_selection" and not entry["inside"]:
        return entry["kind"] == "exit" and entry["result"] is True
    return True

SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Appearance">
<prop oor:name="LibreOfficeTheme" oor:op="fuse"><value>1</value></prop>
<prop oor:name="ApplicationAppearance" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.UI/ColorScheme">
<prop oor:name="CurrentColorScheme" oor:op="fuse">
<value>COLOR_SCHEME_LIBREOFFICE_LIGHT</value></prop>
</item></oor:items>"""


class Probe:
    def __init__(self, lab, directory):
        scripts = directory / "profile" / "user" / "Scripts" / "python"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "a11y_probe.py").write_text(PROBE, "utf-8")
        context = lab.context
        factory = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.script.provider.MasterScriptProviderFactory", context
        )
        self._provider = factory.createScriptProvider("")

    def __call__(self, name, *arguments):
        url = f"vnd.sun.star.script:a11y_probe.py${name}?language=Python&location=user"
        return json.loads(self._provider.getScript(url).invoke(arguments, (), ())[0])


def run_phases(lab, directory):
    book = Workbook(lab, "probe", EIGHT)
    probe = Probe(lab, directory)
    phases = []
    installed = probe("install")

    def picks():
        return probe("state")["picks"]

    def pick(names):
        """Plain click on the first, Ctrl+click on the rest; wait until the list shows them."""
        book.click(EIGHT.index(names[0]))
        for name in names[1:]:
            book.click(EIGHT.index(name), modifiers=CTRL)
        wait_until(lambda: book.selection() == names and picks() == names, f"picks {names}")
        time.sleep(0.8)

    def settle():
        """Wait until the list's own work has gone quiet: no record for `QUIET` ms but the tab
        sample's routine ones, or `SETTLE_LIMIT` seconds."""
        time.sleep(SETTLE)
        deadline = time.monotonic() + SETTLE_LIMIT
        while time.monotonic() < deadline:
            events = probe("report")["events"]
            last = max((entry["ms"] for entry in events if significant(entry)), default=0.0)
            if probe("elapsed") - last > QUIET:
                return events
            time.sleep(0.3)
        return probe("report")["events"]

    def phase(name, action, prepare=None, solar=True):
        if prepare is not None:
            prepare()
        started = probe("reset", name, solar)
        record = {"phase": name, "start": started, "solar_probes": solar}
        try:
            record["detail"] = action() or {}
        except Exception:
            record["error"] = traceback.format_exc()
        record["events"] = settle()
        record["end"] = probe("state")
        phases.append(record)
        print(
            f"{name}: picks {record['end'].get('picks')} tree {record['end'].get('tree')}",
            flush=True,
        )
        return record

    def click(index, modifiers=()):
        point = book.point(index)
        return lambda: book.pointer.click(*point, modifiers=modifiers)

    # 1. A plain click: the native press and the list's own write after it.
    phase("plain_click_alfa", click(0), prepare=lambda: pick(["Bravo"]))

    # 2. Selections through XAccessibleSelection on the main thread, as ATK's bridge makes them,
    #    with the tree focused by the click before.
    phase("assistive_select_bravo", lambda: probe("assistive", "select", 1, "main", 0.0))
    phase("assistive_deselect_alfa", lambda: probe("assistive", "deselect", 0, "main", 0.0))
    phase("assistive_clear", lambda: probe("assistive", "clear", -1, "main", 0.0),
          prepare=lambda: pick(["Alfa", "Bravo"]))
    phase("assistive_select_all", lambda: probe("assistive", "all", -1, "main", 0.0))
    # 3. The same from a UNO client's bridge thread, and with the focus in the document.
    phase("assistive_select_charlie_bridge_thread",
          lambda: probe("assistive", "select", 2, "here", 0.0), prepare=lambda: pick(["Alfa"]))

    def unfocus():
        pick(["Alfa"])
        book.frame.getComponentWindow().setFocus()
        time.sleep(0.5)

    phase("assistive_select_delta_unfocused",
          lambda: probe("assistive", "select", 3, "main", 0.0), prepare=unfocus)

    # 4. Native Ctrl+click and Ctrl+Shift+click by real input.
    phase("ctrl_click_add_charlie", click(2, CTRL), prepare=lambda: pick(["Alfa"]))
    phase("ctrl_click_remove_charlie", click(2, CTRL))
    phase("ctrl_click_remove_alfa_off_cursor", click(0, CTRL),
          prepare=lambda: pick(["Alfa", "Charlie"]))
    phase("ctrl_shift_click_delta", click(3, CTRL_SHIFT), prepare=lambda: pick(["Bravo"]))

    # 5. The list's own writes: a key's coalesced write, and a refresh that rebuilds the rows.
    phase("key_down_write", lambda: book.lab.input.tap("Down"), prepare=lambda: pick(["Bravo"]))
    phase("key_ctrl_space_write", lambda: book.lab.input.tap("space", modifiers=CTRL))

    def protect():
        book.document.getSheets().getByName("Hotel").protect("")
        wait_until(lambda: "Hotel (protected)" in book.labels(), "the rebuilt rows")

    def unprotect():
        book.document.getSheets().getByName("Hotel").unprotect("")
        wait_until(lambda: "Hotel (protected)" not in book.labels(), "the rows again")

    phase("refresh_rebuild", protect, prepare=lambda: pick(["Alfa", "Bravo"]))
    phase("refresh_rebuild_back", unprotect)

    # 6. #294: an accessibility selection just before a Ctrl+click, no wait in between.
    def assistive_then(action, index, point, modifiers, hold=0.0, where="main"):
        def act():
            started = time.monotonic()
            answer = probe("assistive", action, index, where, hold)
            returned = time.monotonic()
            book.pointer.click(*point, modifiers=modifiers)
            return {
                "assistive": answer,
                "invoke_s": round(returned - started, 3),
                "click_done_s": round(time.monotonic() - started, 3),
            }

        return act

    for attempt in range(6):
        phase(
            f"issue294_select_bravo_then_ctrl_click_bravo_{attempt + 1}",
            assistive_then("select", 1, book.point(1), CTRL),
            prepare=lambda: pick(["Alfa"]),
            solar=False,
        )
    for attempt in range(2):
        phase(
            f"issue294_select_bravo_hold_then_ctrl_click_bravo_{attempt + 1}",
            assistive_then("select", 1, book.point(1), CTRL, hold=0.3),
            prepare=lambda: pick(["Alfa"]),
            solar=False,
        )
    for attempt in range(4):
        phase(
            f"issue294_clear_then_ctrl_shift_click_delta_{attempt + 1}",
            assistive_then("clear", -1, book.point(3), CTRL_SHIFT),
            prepare=lambda: pick(["Alfa", "Bravo"]),
            solar=False,
        )

    def after_intake():
        probe("assistive", "select", 1, "main", 0.0)
        time.sleep(1.0)
        book.pointer.click(*book.point(1), modifiers=CTRL)

    for attempt in range(2):
        phase(
            f"issue294_bridge_select_bravo_then_ctrl_click_bravo_{attempt + 1}",
            assistive_then("select", 1, book.point(1), CTRL, where="here"),
            prepare=lambda: pick(["Alfa"]),
            solar=False,
        )
    phase("control_select_bravo_intake_then_ctrl_click_bravo", after_intake,
          prepare=lambda: pick(["Alfa"]), solar=False)

    # A waiting assistive selection shown again by a rebuilding refresh (`_show_native`).
    def shown_again():
        answer = probe("assistive_then_refresh", 3, "Golf")
        wait_until(lambda: "Golf (protected)" in book.labels(), "the rebuilt rows")
        return answer

    phase("refresh_shows_waiting_assistive_selection", shown_again,
          prepare=lambda: pick(["Alfa"]))
    phase("refresh_rebuild_back_golf",
          lambda: book.document.getSheets().getByName("Golf").unprotect(""))

    # Keys that reach the tree: does any change the selection natively, outside the list?
    phase("key_type_ahead_e", lambda: book.lab.input.tap("e"), prepare=lambda: pick(["Alfa"]))
    phase("key_shift_down", lambda: book.lab.input.tap("Down", modifiers=("Shift_L",)))
    phase("key_ctrl_a", lambda: book.lab.input.tap("a", modifiers=CTRL))
    phase("key_end", lambda: book.lab.input.tap("End"))

    # 7. Direction 2: the list's own work posted between a press and its listener.
    def armed(what, index, modifiers):
        point = book.point(index)

        def act():
            probe("arm", what)
            book.pointer.click(*point, modifiers=modifiers)

        return act

    phase("q3_flush_ahead_ctrl_click_bravo", armed("flush", 1, CTRL),
          prepare=lambda: pick(["Alfa", "Bravo"]), solar=False)
    phase("q3_rebuild_ahead_ctrl_click_bravo", armed("rebuild", 1, CTRL),
          prepare=lambda: pick(["Alfa", "Bravo"]), solar=False)
    phase("q3_flush_ahead_ctrl_click_charlie", armed("flush", 2, CTRL),
          prepare=lambda: pick(["Alfa"]), solar=False)

    def dispose_ahead():
        probe("save_handles")
        armed("dispose", 2, CTRL)()
        time.sleep(3 * SETTLE)
        return {"stale_calls_from_bridge_thread": probe("stale_calls")}

    phase("q3_dispose_ahead_ctrl_click_charlie", dispose_ahead, prepare=lambda: pick(["Alfa"]), solar=False)
    book.close()
    return {"installed": installed, "phases": phases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vcl", action="append", choices=["gtk3", "gen"])
    arguments = parser.parse_args()
    summary = {}
    failed = False
    for vcl in arguments.vcl or ["gtk3", "gen"]:
        output = (arguments.output / f"probe-{vcl}").resolve()
        output.mkdir(parents=True, exist_ok=True)
        result = {"vcl": vcl}
        summary[vcl] = result
        try:
            with office_session(
                arguments.program.resolve(),
                arguments.oxt.resolve(),
                output,
                result,
                headless=False,
                vcl=vcl,
                settings=SETTINGS,
            ) as (context, desktop, directory):
                result.update(run_phases(Lab(context, desktop, directory, output), directory))
        except Exception:
            result["error"] = traceback.format_exc()
            failed = True
        logs = "".join(p.read_text("utf-8", "replace") for p in output.glob("soffice-*.log"))
        result["extension_errors"] = logs.count("Sheet Manager: ")
        (output / "probe-results.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    (arguments.output / "probe-results.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
