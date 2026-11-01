"""In-memory tracing for a private investigation OXT; never part of the normal build (#160).

Wrappers keep arguments, return values and exceptions. They read Python-owned state only,
without UNO getters, input, sleeps or file writes during the gesture. Dump the bounded journal
when the synthetic three-sheet list is disposed. Instrumentation can still change scheduling.
"""

import functools
import json
import sys
import time
import zipfile
from collections import deque
from enum import Flag
from pathlib import Path
from typing import Any

MEMBER = "pythonpath/sheet_manager/uno_list.py"
PROBE_MEMBER = "pythonpath/sheet_manager/_input_probe.py"
SUFFIX = (
    b"\n\nfrom sheet_manager._input_probe import install as _install_input_probe\n"
    b"_install_input_probe(SheetList)\n"
)
_entries: deque[dict[str, Any]] = deque(maxlen=4096)


def instrument_package(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("The investigation must not overwrite the normal package")
    with zipfile.ZipFile(source) as original:
        names = original.namelist()
        if names.count(MEMBER) != 1 or PROBE_MEMBER in names:
            raise ValueError("Expected exactly one uninstrumented sheet-list module")
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as patched:
            patched.comment = original.comment
            for member in original.infolist():
                payload = original.read(member)
                patched.writestr(member, payload + SUFFIX if member.filename == MEMBER else payload)
            patched.writestr(PROBE_MEMBER, Path(__file__).read_bytes())


def _plain(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Flag):
        return value.value
    if isinstance(value, (tuple, list, frozenset)):
        return [_plain(item) for item in value]
    return type(value).__name__


def _list_state(owner):
    selection = getattr(owner, "_selection", None)
    press = getattr(owner, "_press", None)
    monitor = getattr(owner, "_monitor", None)
    events = getattr(monitor, "events", None)
    state: dict[str, Any] = {
        name: _plain(getattr(owner, name, None))
        for name in (
            "_input",
            "_proven",
            "_generation",
            "_pointer_depth",
            "_selection_write_pending",
            "_view_ack_pending",
            "_view_input",
            "_view_generation",
            "_view_state",
            "_shown",
        )
    }
    state["monitor_id"] = id(events)
    state["monitor_generation"] = getattr(events, "generation", None)
    state["rows"] = [row.name for row in getattr(owner, "rows", ())]
    state["picks"] = [ref.name for ref in getattr(selection, "picked", ())]
    state["press"] = (
        None
        if press is None
        else {
            name: _plain(getattr(press, name))
            for name in ("row", "name", "generation", "voided", "modifiers", "clicks")
        }
    )
    return state


def _structure_state(events):
    return {
        name: _plain(getattr(events, name))
        for name in (
            "generation",
            "count",
            "history",
            "undo_notes",
            "explained",
            "epoch",
            "redo_epoch",
        )
    }


def _record(owner, method, phase, state, **values):
    try:
        _entries.append(
            {
                "seconds": time.monotonic(),
                "owner": id(owner),
                "method": method,
                "phase": phase,
                "state": state(owner),
                **values,
            }
        )
    except Exception as error:
        _entries.append({"method": method, "diagnostic_error": type(error).__name__})


def _wrap(owner_type, name, state):
    original = getattr(owner_type, name)

    @functools.wraps(original)
    def traced(owner, *arguments, **keywords):
        # Event arguments may be UNO objects: never inspect or represent them here.
        _record(owner, name, "before", state)
        result = None
        try:
            result = original(owner, *arguments, **keywords)
            return result
        finally:
            value = vars(result) if name == "geometry" and result is not None else _plain(result)
            _record(owner, name, "after", state, result=value)

    setattr(owner_type, name, traced)


def install(sheet_list_type):
    from sheet_manager.structure import StructureEvents

    namespace = vars(sys.modules[sheet_list_type.__module__])

    def wrap_read(name):
        original = namespace[name]

        @functools.wraps(original)
        def observed(value):
            result = original(value)
            # `_current` receives a Python Ref; the other function receives a UNO handle.
            # Preserve the getter's existing result without reading the handle again.
            _entries.append(
                {
                    "seconds": time.monotonic(),
                    "method": name,
                    "phase": "returned",
                    "ref_name": value.name if name == "_current" else None,
                    "proxy_id": id(value.token) if name == "_current" else id(value),
                    "result": result,
                }
            )
            return result

        namespace[name] = observed

    for name in ("_current", "_name_or_none"):
        wrap_read(name)
    for name in (
        "mouse_pressed",
        "mouse_released",
        "geometry",
        "_flush_selection",
        "_refresh",
        "_drop_all_picks",
        "_identities_kept",
        "_apply_selection",
        "_take_tree_selection",
        "_select",
        "_observe_view",
        "_acknowledge_view",
        "active_sheet_changed",
    ):
        _wrap(sheet_list_type, name, _list_state)
    for name in ("_bump", "modified", "action_added", "history_cleared", "check"):
        _wrap(StructureEvents, name, _structure_state)
    dispose = sheet_list_type.dispose

    @functools.wraps(dispose)
    def finish(owner):
        if [row.name for row in getattr(owner, "rows", ())] == ["Alfa", "Bravo", "Charlie"]:
            try:
                print("SHEET_MANAGER_INPUT_PROBE " + json.dumps(list(_entries)), flush=True)
                _entries.clear()
            except Exception as error:
                print("SHEET_MANAGER_INPUT_PROBE_ERROR " + type(error).__name__, flush=True)
        return dispose(owner)

    sheet_list_type.dispose = finish
