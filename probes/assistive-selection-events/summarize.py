"""Print the #294 probe's records as compact timelines and event counts; host Python, stdlib only.

Usage: python summarize.py <results directory> [phase substring ...]
"""

import json
import sys
from collections import Counter
from pathlib import Path

QUIET = {"_hold_toggles", "_toggles_shown", "follow_tabs", "_drop_all_picks", "_drop_picks"}


def solar(entry):
    if "solar_free" not in entry:
        return ""
    return " [mutex free]" if entry["solar_free"] else " [mutex held]"


def thread(entry):
    return "main" if entry["main"] else f"t{entry['tid']}"


def token(entry):
    kind = entry["kind"]
    inside = ("/".join(entry["inside"]) + ": ") if entry["inside"] else ""
    if kind == "a11y":
        where = entry["channel"] + (f"[{entry['row']}]" if "row" in entry else "")
        values = ""
        if entry.get("new") is not None or entry.get("old") is not None:
            values = f" old={entry.get('old')} new={entry.get('new')}"
        why = f" ({entry['why']})" if entry.get("why") else ""
        return f"{inside}A11Y {where} {entry['id']}{values}{why} @{thread(entry)}{solar(entry)}"
    if kind == "selection":
        why = f" ({entry['why']})" if entry.get("why") else ""
        return f"{inside}SEL tree={entry['tree'].get('names', entry['tree'])}{why} @{thread(entry)}{solar(entry)}"
    if kind in ("enter", "exit", "raise"):
        method = entry["method"]
        if method in QUIET and kind != "raise":
            return None
        if kind == "enter":
            extra = ""
            if method in ("mouse_pressed", "mouse_released"):
                extra = f" mods={entry['modifiers']} clicks={entry['clicks']}"
                if method == "mouse_pressed":
                    extra += f" tree_at_listener={entry['tree_at_listener'].get('names', entry['tree_at_listener'])}"
            if method == "_take_tree_selection":
                extra = f" defer={entry['defer']}"
            return f"{inside}> {method}{extra} picks={entry.get('picks')} shown={entry.get('shown')} @{thread(entry)}{solar(entry)}"
        if kind == "exit":
            return f"{inside}< {method} -> {entry['result']} picks={entry.get('picks')} shown={entry.get('shown')} held={entry.get('held')}"
        return f"{inside}! {method} raised {entry['error']}"
    if kind == "post":
        return f"{inside}post #{entry['number']} {entry['where']}"
    if kind == "run":
        return f"run #{entry['number']} {entry['where']}{solar(entry)}"
    if kind == "posted-from-event":
        return f"marker posted from event {entry['after']} runs @{thread(entry)}"
    if kind in ("assistive-start", "assistive-end"):
        rest = {k: v for k, v in entry.items() if k not in ("seq", "ms", "kind", "tid", "main", "inside")}
        return f"{kind} {rest} @{thread(entry)}"
    rest = {k: v for k, v in entry.items() if k not in ("seq", "ms", "kind", "tid", "main", "inside")}
    return f"{inside}{kind} {rest} @{thread(entry)}"


def counts(events):
    found = Counter()
    for entry in events:
        if entry["kind"] == "a11y":
            channel = entry["channel"]
            why = entry.get("why") or "unexplained"
            found[f"a11y {channel} {entry['id']} ({why})"] += 1
        elif entry["kind"] == "selection":
            found[f"selection ({entry.get('why') or 'unexplained'})"] += 1
    return found


def main():
    directory = Path(sys.argv[1])
    wanted = sys.argv[2:]
    for path in sorted(directory.glob("probe-*/probe-results.json")):
        result = json.loads(path.read_text("utf-8"))
        print(f"===== {result['vcl']} (extension errors: {result.get('extension_errors')})")
        if "error" in result:
            print(result["error"])
        for phase in result.get("phases", []):
            if wanted and not any(item in phase["phase"] for item in wanted):
                continue
            end = phase["end"]
            print(f"\n--- {phase['phase']}: start {phase['start']}")
            if phase.get("detail"):
                print(f"    detail {phase['detail']}")
            if phase.get("error"):
                print(phase["error"])
            for entry in phase["events"]:
                text = token(entry)
                if text is not None:
                    print(f"  {entry['seq']:4d} {entry['ms']:8.1f}  {text}")
            print(f"    counts {dict(counts(phase['events']))}")
            print(f"    end picks={end.get('picks')} tree={end.get('tree')} held={end.get('held')}")


if __name__ == "__main__":
    main()
