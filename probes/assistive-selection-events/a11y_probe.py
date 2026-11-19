"""In-process probe for #294: which events the sheet list's tree delivers for a selection, and when.

Measurement only; never shipped. `runner.py` installs this file into a private profile's user
Python scripts and calls its functions through the script provider, so that its listeners and
wrappers run inside soffice, in the interpreter that runs the extension. Each record notes its
native thread, whether that is the process's main thread (on Linux the main thread's id is the
process id), and, for the first few records of each kind in a phase, whether another thread
could take LibreOffice's solar mutex meanwhile: a helper thread calls the guarded
`VCLXWindow::getPosSize` and the callback waits for it, as the #269 probe did.

Channels, each added to the live list's own objects:

- `tree`: an `XAccessibleEventListener` on the tree's accessible context, the very context
  (`SheetList._cursor_context`) the list listens to for the keyboard cursor.
- `row`: the same listener on each row's accessible context, re-added at every phase.
- `selection`: an `XSelectionChangeListener` on the tree's peer, the toolkit's own selection
  notification (`TreeControlPeer::onSelectionChanged`). Not an accessibility event; recorded
  because the list could also listen to it.

The live `SheetList` is found through the garbage collector. Its methods that write or read the
tree's selection, its mouse and key handlers and its main-thread posting are wrapped on the
instance to record when they run and with which picks; the wrappers change nothing they wrap.
`mouse_pressed`'s wrapper also reads the tree's selection with `getSelection()` before the list's
own listener runs, which is direction 2 on #294 (reading the tree in the press listener).

`arm` makes the next selection event that neither the list's own write nor the probe's
assistive call explains, which is a native press handled inside VCL's button handling, post work
ahead of that press's queued mouse listener: the list's coalesced selection write (`flush`), a
rebuild of the same rows (`rebuild`), or the list's disposal (`dispose`).
"""

import _thread
import gc
import json
import os
import sys
import threading
import time
import traceback

import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from com.sun.star.awt import XCallback
from com.sun.star.view import XSelectionChangeListener

EVENT_IDS = (
    "ACTION_CHANGED",
    "ACTIVE_DESCENDANT_CHANGED",
    "ACTIVE_DESCENDANT_CHANGED_NOFOCUS",
    "BOUNDRECT_CHANGED",
    "CARET_CHANGED",
    "CHILD",
    "COLUMN_CHANGED",
    "DESCRIPTION_CHANGED",
    "HYPERTEXT_CHANGED",
    "INVALIDATE_ALL_CHILDREN",
    "LISTBOX_ENTRY_COLLAPSED",
    "LISTBOX_ENTRY_EXPANDED",
    "NAME_CHANGED",
    "PAGE_CHANGED",
    "ROLE_CHANGED",
    "SECTION_CHANGED",
    "SELECTION_CHANGED",
    "SELECTION_CHANGED_ADD",
    "SELECTION_CHANGED_REMOVE",
    "SELECTION_CHANGED_WITHIN",
    "STATE_CHANGED",
    "SUB_WINDOW_OF_RELATION_CHANGED",
    "TABLE_MODEL_CHANGED",
    "TEXT_ATTRIBUTE_CHANGED",
    "TEXT_CHANGED",
    "TEXT_SELECTION_CHANGED",
    "VALUE_CHANGED",
    "VISIBLE_DATA_CHANGED",
)
STATE_TYPES = (
    "ACTIVE",
    "CHECKED",
    "COLLAPSE",
    "DEFUNC",
    "ENABLED",
    "EXPANDABLE",
    "EXPANDED",
    "FOCUSABLE",
    "FOCUSED",
    "MANAGES_DESCENDANTS",
    "MULTI_SELECTABLE",
    "OPAQUE",
    "SELECTABLE",
    "SELECTED",
    "SENSITIVE",
    "SHOWING",
    "TRANSIENT",
    "VISIBLE",
)


def _constants(group, names):
    found = {}
    for name in names:
        try:
            found[uno.getConstantByName(f"com.sun.star.accessibility.{group}.{name}")] = name
        except Exception:
            pass
    return found


EVENT_NAMES = _constants("AccessibleEventId", EVENT_IDS)
STATE_NAMES = _constants("AccessibleStateType", STATE_TYPES)
FOCUSED = next(value for value, name in STATE_NAMES.items() if name == "FOCUSED")

# The list's methods recorded on entry and exit. Writes of the tree's selection first, then its
# readers, then the handlers and the holds.
WRAPPED = (
    "_apply_selection",
    "_move_tree_cursor",
    "_show_native",
    "_rebuild",
    "_take_tree_selection",
    "_settle_shown",
    "_flush_selection",
    "_refresh",
    "mouse_pressed",
    "mouse_released",
    "tree_key",
    "cursor_changed",
    "follow_tabs",
    "_drop_all_picks",
    "_drop_picks",
    "_hold_toggles",
    "_toggles_shown",
    "_toggle_held_off",
)
WRITES = {"_apply_selection", "_move_tree_cursor", "_show_native", "_rebuild"}
SOLAR_PROBES_PER_KIND = 2
SOLAR_WAIT = 0.3

PID = os.getpid()
LOCK = _thread.allocate_lock()
STATE = {
    "events": [],
    "phase": None,
    "t0": time.monotonic(),
    "list": None,
    "stacks": {},
    "solar": {},
    "armed": None,
    "posts": 0,
    "listeners": [],
    "rows": [],
    "saved": None,
}


def _stack():
    return STATE["stacks"].setdefault(threading.get_native_id(), [])


def _mark(kind, **extra):
    tid = threading.get_native_id()
    with LOCK:
        entry = {
            "seq": len(STATE["events"]) + 1,
            "ms": round((time.monotonic() - STATE["t0"]) * 1000, 1),
            "kind": kind,
            "tid": tid,
            "main": tid == PID,
            "inside": list(STATE["stacks"].get(tid, ())),
        }
        entry.update(extra)
        STATE["events"].append(entry)
    return entry


def _solar_free(timeout):
    """Whether another thread took the solar mutex while this thread waited `timeout` seconds."""
    sheet_list = STATE["list"]
    done = _thread.allocate_lock()
    done.acquire()

    def helper():
        try:
            sheet_list.peer.getPosSize()  # VCLXWindow::getPosSize takes SolarMutexGuard.
        except Exception:
            pass
        finally:
            done.release()

    start = time.monotonic()
    _thread.start_new_thread(helper, ())
    free = done.acquire(True, timeout)
    return {"solar_free": free, "waited": round(time.monotonic() - start, 3)}


def _solar(kind):
    """A mutex probe for the first records of each kind in a phase; empty after that."""
    with LOCK:
        if "*" in STATE["solar"]:
            return {}
        count = STATE["solar"].get(kind, 0)
        if count >= SOLAR_PROBES_PER_KIND:
            return {}
        STATE["solar"][kind] = count + 1
    return _solar_free(SOLAR_WAIT)


class _Callback(unohelper.Base, XCallback):
    def __init__(self, function):
        self._function = function

    def notify(self, data):
        try:
            self._function()
        except Exception:
            _mark("probe-error", where="posted", error=traceback.format_exc())


def _post(function):
    context = uno.getComponentContext()
    callback = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.AsyncCallback", context
    )
    callback.addCallback(_Callback(function), None)


def _tree_names():
    """The tree's selected rows, read as the list reads them; or the exception that raised."""
    sheet_list = STATE["list"]
    try:
        selection = sheet_list.tree.getSelection()
    except Exception as error:
        return {"error": type(error).__name__, "message": str(error)[:200]}
    if selection is None:
        return {"names": []}
    nodes = selection if isinstance(selection, tuple) else (selection,)
    try:
        values = {node.DataValue for node in nodes}
    except Exception as error:
        return {"error": type(error).__name__, "message": str(error)[:200]}
    order = [row.name for row in sheet_list.rows]
    return {"names": [name for name in order if name in values]}


def _list_state():
    sheet_list = STATE["list"]
    try:
        cursor = sheet_list._selection.cursor
        return {
            "picks": sheet_list._selection.names(),
            "cursor": cursor.name if cursor is not None else None,
            "shown": list(sheet_list._shown) if sheet_list._shown is not None else None,
            "held": sheet_list._toggles_held is not None,
            "input": sheet_list._input,
            "press": sheet_list._press.name if sheet_list._press is not None else None,
        }
    except Exception as error:
        return {"state_error": type(error).__name__}


def _explained():
    """What explains a native selection change on this thread: the list's write or the probe."""
    stack = _stack()
    if any(name in WRITES for name in stack):
        return "list-write"
    if "probe:assistive" in stack:
        return "assistive"
    if stack:
        return "list:" + stack[-1]
    return None


def _value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return STATE_NAMES.get(value, value)
    try:
        context = value.getAccessibleContext()
    except Exception:
        return type(value).__name__
    try:
        return {
            "index": context.getAccessibleIndexInParent(),
            "name": context.getAccessibleName(),
        }
    except Exception as error:
        return {"error": type(error).__name__}


def _after_unexplained(entry):
    """For a change nothing explains: post a marker, and run an armed injection, once."""
    _post(lambda: _mark("posted-from-event", after=entry["seq"]))
    armed = STATE["armed"]
    if armed is None:
        return
    STATE["armed"] = None
    sheet_list = STATE["list"]
    _mark("inject", what=armed, after=entry["seq"])
    if armed == "flush":
        sheet_list._queue_selection()  # Posts the list's coalesced write, as a key's change does.
    elif armed == "rebuild":
        sheet_list.post(
            lambda: sheet_list._rebuild(
                list(sheet_list.rows), sheet_list._observed, sheet_list._proven
            ),
            "probe: rebuild the same rows ahead of the press's listener",
        )
    elif armed == "dispose":

        def dispose():
            _mark("dispose-start")
            sheet_list.dispose()
            _mark("dispose-end", disposed=sheet_list._disposed)

        _post(dispose)


class _Accessible(unohelper.Base, XAccessibleEventListener):
    def __init__(self, channel, row=None):
        self.channel = channel
        self.row = row

    def notifyEvent(self, event):
        try:
            name = EVENT_NAMES.get(event.EventId, event.EventId)
            extra = {"channel": self.channel, "id": name, "why": _explained()}
            if self.row is not None:
                extra["row"] = self.row
            extra["old"] = _value(event.OldValue)
            extra["new"] = _value(event.NewValue)
            extra.update(_solar(f"{self.channel}:{name}"))
            entry = _mark("a11y", **extra)
            if extra["why"] is None and str(name).startswith("SELECTION"):
                _after_unexplained(entry)
        except Exception:
            _mark("probe-error", where=self.channel, error=traceback.format_exc())

    def disposing(self, source):
        pass


class _Selection(unohelper.Base, XSelectionChangeListener):
    def selectionChanged(self, event):
        try:
            extra = {"channel": "selection", "why": _explained(), "tree": _tree_names()}
            extra.update(_solar("selection"))
            entry = _mark("selection", **extra)
            if extra["why"] is None:
                _after_unexplained(entry)
        except Exception:
            _mark("probe-error", where="selection", error=traceback.format_exc())

    def disposing(self, source):
        pass


def _wrap(sheet_list, name):
    original = getattr(sheet_list, name)

    def wrapper(*arguments, **keywords):
        extra = {}
        if name in ("mouse_pressed", "mouse_released"):
            event = arguments[0]
            extra.update(
                buttons=event.Buttons, modifiers=event.Modifiers, clicks=event.ClickCount, y=event.Y
            )
            if name == "mouse_pressed":
                extra["tree_at_listener"] = _tree_names()  # Direction 2: read in the listener.
            extra.update(_solar(name))
        elif name == "tree_key":
            extra.update(code=arguments[0], modifiers=arguments[1])
        elif name == "_take_tree_selection":
            extra["defer"] = keywords.get("defer", False)
        _mark("enter", method=name, **extra, **_list_state())
        stack = _stack()
        stack.append(name)
        try:
            result = original(*arguments, **keywords)
        except BaseException as error:
            stack.pop()
            _mark("raise", method=name, error=type(error).__name__)
            raise
        stack.pop()
        result = result if isinstance(result, (bool, type(None))) else type(result).__name__
        _mark("exit", method=name, result=result, **_list_state())
        return result

    setattr(sheet_list, name, wrapper)


def _wrap_posting(sheet_list):
    main = sheet_list._main
    original = main.post

    def post(function, where="a deferred update"):
        with LOCK:
            STATE["posts"] += 1
            number = STATE["posts"]
        _mark("post", number=number, where=where)

        def run():
            extra = _solar("posted")
            _mark("run", number=number, where=where, **extra)
            function()

        original(run, where)

    main.post = post


def _find_list():
    module = sys.modules.get("sheet_manager.uno_list")
    if module is None:
        raise RuntimeError("The extension's uno_list module is not loaded")
    lists = [
        item for item in gc.get_objects() if isinstance(item, module.SheetList) and not item._disposed
    ]
    if len(lists) != 1:
        raise RuntimeError(f"Expected one live sheet list, found {len(lists)}")
    return lists[0]


def _add_rows():
    for context, listener in STATE["rows"]:
        try:
            context.removeAccessibleEventListener(listener)
        except Exception:
            pass
    STATE["rows"] = []
    tree = STATE["list"]._cursor_context
    for index in range(tree.getAccessibleChildCount()):
        context = tree.getAccessibleChild(index).getAccessibleContext()
        listener = _Accessible("row", index)
        context.addAccessibleEventListener(listener)
        STATE["rows"].append((context, listener))


def install():
    """Find the live list, add the listeners and wrap its methods; idempotent per office."""
    if STATE["list"] is not None:
        return json.dumps({"installed": "already"})
    sheet_list = _find_list()
    STATE["list"] = sheet_list
    tree_listener = _Accessible("tree")
    selection_listener = _Selection()
    sheet_list._cursor_context.addAccessibleEventListener(tree_listener)
    sheet_list.peer.addSelectionChangeListener(selection_listener)
    STATE["listeners"] = [tree_listener, selection_listener]
    for name in WRAPPED:
        _wrap(sheet_list, name)
    _wrap_posting(sheet_list)
    return json.dumps({"installed": True, "pid": PID, "rows": [row.name for row in sheet_list.rows]})


def reset(phase, solar=True):
    """Start a phase: no records, row listeners on the rows shown now, and mutex probes unless
    `solar` is false. A probe holds the probing thread for up to `SOLAR_WAIT` seconds, which
    changes the timing of a race, so the race phases run without them."""
    with LOCK:
        STATE["events"] = []
        STATE["phase"] = phase
        STATE["t0"] = time.monotonic()
        STATE["solar"] = {} if solar else {"*": True}
        STATE["armed"] = None
    _add_rows()
    return json.dumps({"phase": phase, "focused": focused(), **_list_state()})


def elapsed():
    """Milliseconds since the phase began, on the records' clock."""
    return json.dumps(round((time.monotonic() - STATE["t0"]) * 1000, 1))


def focused():
    try:
        return bool(STATE["list"]._cursor_context.getAccessibleStateSet() & FOCUSED)
    except Exception as error:
        return type(error).__name__


def arm(what):
    STATE["armed"] = what
    return json.dumps({"armed": what})


def assistive(action, index=-1, where="main", hold=0.0):
    """Select through `XAccessibleSelection`, as assistive technology does.

    `where` "main" runs the call in posted work on the main thread, as a bridge such as ATK's
    runs it; "here" runs it on the calling UNO bridge thread, as a UNO client would. `hold`
    keeps the main thread busy that many seconds after a "main" call, while the caller already
    goes on (for example to press a row).
    """
    context = STATE["list"]._cursor_context
    index = int(index)
    hold = float(hold)

    def call():
        stack = _stack()
        stack.append("probe:assistive")
        _mark("assistive-start", action=action, index=index, where=where, focused=focused())
        try:
            if action == "select":
                context.selectAccessibleChild(index)
            elif action == "deselect":
                context.deselectAccessibleChild(index)
            elif action == "clear":
                context.clearAccessibleSelection()
            elif action == "all":
                context.selectAllAccessibleChildren()
            else:
                raise ValueError(action)
        finally:
            stack.pop()
            _mark("assistive-end", action=action, tree=_tree_names())

    if where == "here":
        call()
        return json.dumps({"done": True})
    done = _thread.allocate_lock()
    done.acquire()
    box = {}

    def work():
        try:
            call()
        except Exception as error:
            box["error"] = repr(error)
        finally:
            done.release()
        if hold:
            time.sleep(hold)
            _mark("hold-end", held=hold)

    _post(work)
    return json.dumps({"done": done.acquire(True, 10), **box})


def assistive_then_refresh(index, sheet):
    """On the main thread: protect `sheet`, select row `index` through accessibility, refresh.

    The refresh defers the intake of that selection and rebuilds the rows for the protection's
    label, so it shows the waiting selection again (`_show_native`), as a refresh does when a
    property change lands between an assistive selection and its intake.
    """
    sheet_list = STATE["list"]
    done = _thread.allocate_lock()
    done.acquire()
    box = {}

    def work():
        try:
            sheet_list.document.getSheets().getByName(sheet).protect("")
            stack = _stack()
            stack.append("probe:assistive")
            try:
                sheet_list._cursor_context.selectAccessibleChild(int(index))
            finally:
                stack.pop()
            _mark("assistive-end", action="select", tree=_tree_names())
            sheet_list.refresh()
        except Exception as error:
            box["error"] = repr(error)
        finally:
            done.release()

    _post(work)
    return json.dumps({"done": done.acquire(True, 10), **box})


class _Counter(unohelper.Base, XSelectionChangeListener):
    """The smallest selection listener a fix would add: it only counts."""

    def __init__(self):
        self.count = 0

    def selectionChanged(self, event):
        self.count += 1

    def disposing(self, source):
        pass


PERF = {"counter": None}


def perf_counter(attached):
    """Attach or detach a counting selection listener to the live list's tree peer."""
    sheet_list = _find_list() if STATE["list"] is None else STATE["list"]
    attached = bool(attached)
    if attached and PERF["counter"] is None:
        PERF["counter"] = _Counter()
        sheet_list.peer.addSelectionChangeListener(PERF["counter"])
    elif not attached and PERF["counter"] is not None:
        sheet_list.peer.removeSelectionChangeListener(PERF["counter"])
        PERF["counter"] = None
    return json.dumps({"attached": PERF["counter"] is not None})


def perf_writes(repeats):
    """Time the list's own write of every row picked, then of one, on the main thread.

    Each repeat picks every row and runs `_apply_selection`, which selects the cursor's row and
    adds each other pick, then picks the first row alone and writes again. Returns the times
    in milliseconds and how many notifications the counting listener received, if attached.
    """
    sheet_list = _find_list() if STATE["list"] is None else STATE["list"]
    done = _thread.allocate_lock()
    done.acquire()
    box = {"all": [], "one": []}

    def work():
        try:
            names = [row.name for row in sheet_list.rows]
            for _ in range(int(repeats)):
                sheet_list._selection.take(names, sheet_list._handles, names)
                sheet_list._selection.cursor = sheet_list._selection.picked[0]
                start = time.perf_counter()
                sheet_list._apply_selection()
                box["all"].append(round((time.perf_counter() - start) * 1000, 2))
                sheet_list._selection.take(names[:1], sheet_list._handles, names)
                start = time.perf_counter()
                sheet_list._apply_selection()
                box["one"].append(round((time.perf_counter() - start) * 1000, 2))
            box["rows"] = len(names)
            box["notified"] = PERF["counter"].count if PERF["counter"] is not None else None
        except Exception:
            box["error"] = traceback.format_exc()
        finally:
            done.release()

    _post(work)
    box["done"] = done.acquire(True, 300)
    return json.dumps(box)


def save_handles():
    """Keep the tree, its peer, its accessible context and a node, for calls after disposal."""
    sheet_list = STATE["list"]
    STATE["saved"] = {
        "tree": sheet_list.tree,
        "peer": sheet_list.peer,
        "context": sheet_list._cursor_context,
        "node": sheet_list._nodes[0],
    }
    return json.dumps({"saved": True})


def stale_calls():
    """The calls a press listener could make, on the saved objects, wherever this runs."""
    saved = STATE["saved"]
    results = {}
    calls = {
        "tree.getSelection": lambda: saved["tree"].getSelection(),
        "tree.getSelectionCount": lambda: saved["tree"].getSelectionCount(),
        "tree.getNodeRect": lambda: saved["tree"].getNodeRect(saved["node"]),
        "node.DataValue": lambda: saved["node"].DataValue,
        "peer.getSelection": lambda: saved["peer"].getSelection(),
        "context.getSelectedAccessibleChildCount": lambda: saved[
            "context"
        ].getSelectedAccessibleChildCount(),
    }
    for name, function in calls.items():
        try:
            value = function()
            results[name] = {"returned": value if isinstance(value, (int, str)) else type(value).__name__}
        except Exception as error:
            results[name] = {"raised": type(error).__name__, "message": str(error)[:200]}
    return json.dumps(results)


def state():
    return json.dumps({"tree": _tree_names(), "focused": focused(), **_list_state()})


def report():
    with LOCK:
        return json.dumps({"phase": STATE["phase"], "events": list(STATE["events"])})


g_exportedScripts = (
    install,
    reset,
    elapsed,
    arm,
    assistive,
    assistive_then_refresh,
    save_handles,
    stale_calls,
    perf_counter,
    perf_writes,
    state,
    report,
)
