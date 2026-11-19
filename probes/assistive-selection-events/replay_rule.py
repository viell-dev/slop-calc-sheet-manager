"""Replay the native records through the counting rule proposed on #294; host Python, stdlib only.

The rule: count the tree's selection changes that the list did not make (the toolkit's
`selectionChanged` outside the list's own writes); count them as accounted for whenever the
tree shows exactly the picks because the list made it so (a complete write of the picks, which
accounts for the changes made before it began; the intake's take; a refresh that shows a waiting
native selection again restores the count it had); a Ctrl press toggles only when its own toggle
is the one change not accounted for, and a Ctrl+Shift press extends only when the changes not
accounted for are exactly the rows its range adds; the second press of a double click changes
nothing natively, so it acts only when nothing is unaccounted for. Otherwise it would take
#292's held path.

Usage: python replay_rule.py <results directory>
"""

import json
import sys
from pathlib import Path

WRITES = {"_apply_selection", "_move_tree_cursor", "_rebuild"}
MOD1, SHIFT = 2, 1


def replay(events):
    count = seen = 0
    write_start = None
    refresh_seen = None
    takes = []
    decisions = []
    for entry in events:
        kind = entry["kind"]
        if kind == "selection" and entry.get("why") in (None, "assistive"):
            count += 1
        elif kind == "enter":
            method = entry["method"]
            outer = not any(name in WRITES for name in entry["inside"])
            if method in WRITES and outer:
                write_start = count
            elif method == "_refresh":
                refresh_seen = seen
            elif method == "_take_tree_selection":
                takes.append(entry["defer"])
            elif method == "mouse_pressed" and entry["modifiers"] & MOD1 and entry["buttons"] & 1:
                decisions.append({"seq": entry["seq"], "mods": entry["modifiers"],
                                  "clicks": entry["clicks"], "u": count - seen,
                                  "before": entry["picks"]})
        elif kind == "exit":
            method = entry["method"]
            outer = not any(name in WRITES for name in entry["inside"])
            if method in WRITES and outer and entry.get("shown") == entry.get("picks"):
                seen = write_start
            elif method == "_show_native" and refresh_seen is not None:
                seen = refresh_seen
            elif method == "_take_tree_selection":
                deferring = takes.pop() if takes else True
                if entry["result"] is True and not deferring:
                    seen = count
            elif method == "mouse_pressed" and decisions and decisions[-1].get("after") is None \
                    and decisions[-1]["seq"] < entry["seq"]:
                decision = decisions[-1]
                decision["after"] = entry["picks"]
                added = len(set(entry["picks"]) - set(decision["before"]))
                # VCL's second press of a double click takes its double-click path and changes
                # no selection (`SvImpLBox::MouseButtonDown`, `GetClicks() % 2 == 0`), measured.
                if decision["clicks"] % 2 == 0:
                    expected = 0
                else:
                    expected = 1 if not decision["mods"] & SHIFT else added
                decision["acts"] = decision["u"] == expected
                decision["expected"] = expected
                if decision["acts"]:
                    seen = count
    return decisions


def load_results(directory):
    """Each backend's records: `probe-<vcl>/probe-results.json` from a run, or the committed
    `probe-<vcl>.json.gz` under `results/`."""
    import gzip

    directory = Path(directory)
    found = []
    for path in sorted(directory.glob("probe-*/probe-results.json")):
        found.append(json.loads(path.read_text("utf-8")))
    for path in sorted(directory.glob("probe-*.json.gz")):
        found.append(json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")))
    return found


def main():
    base = Path(sys.argv[1])
    for result in load_results(base):
        print(f"===== {result['vcl']}")
        for phase in result["phases"]:
            for decision in replay(phase["events"]):
                verdict = "acts as main" if decision["acts"] else "held: picks nothing"
                print(
                    f"{phase['phase']:52s} mods={decision['mods']} clicks={decision['clicks']} "
                    f"unaccounted={decision['u']} "
                    f"own={decision['expected']} -> {verdict}; main picks {decision['after']}, "
                    f"tree after {phase['end'].get('tree', {}).get('names')}"
                )


if __name__ == "__main__":
    main()
