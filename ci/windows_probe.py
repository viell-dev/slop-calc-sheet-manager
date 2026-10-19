"""Branch-only issue #45 runner experiment; never packaged in the extension."""

import argparse
import faulthandler
import json
import shutil
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "integration"))
import run
import unohelper
from com.sun.star.awt import XCallback


def mark(message):
    print(f"{time.monotonic():.6f} {message}", flush=True)


class MainThreadCall(unohelper.Base, XCallback):
    """Run work inside an AsyncCallback notification, on LibreOffice's main thread.

    The office calls notify() from its main thread. URP keeps thread identity, so every UNO
    call that work() makes from inside notify() runs nested on that main thread, as calls
    made by the user interface do; calls from any other client thread run on a bridge thread.
    """

    def __init__(self, work, armed=None):
        self.work = work
        self.armed = armed
        self.started = threading.Event()
        self.done = threading.Event()
        self.error = None

    def notify(self, data):
        try:
            if self.armed is not None:
                self.armed()
            self.started.set()
            self.work()
        except BaseException as error:  # Reported to the waiting client thread.
            self.error = error
        finally:
            self.started.set()
            self.done.set()


def post_main(context, work, armed=None):
    call = MainThreadCall(work, armed)
    callback = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.AsyncCallback", context
    )
    callback.addCallback(call, None)
    return call


def wait_call(call, label):
    if not call.done.wait(60):
        raise TimeoutError(f"main-thread call did not finish: {label}")
    if call.error is not None:
        raise call.error


ARMED_SECONDS = 0.15  # Three times ToolBarManager's 50 ms update timeout.


def thread_experiment(context, desktop, args, result, output):
    """Close freshly opened workbooks on the main thread, then on a bridge thread.

    Variants:
    - natural: open, activate, show the deck (extension modes), close at once.
    - armed: as natural, then on the main thread call XFrame.contextChanged(), which starts
      each toolbar's 50 ms controller update timer, and keep the main thread busy for 150 ms
      so that the timer is overdue when the close starts.
    Main-thread closes run first (they are expected to survive); then one bridge-thread
    variant repeats until the office fails or the iterations end.
    """
    import test_reorder as reorder

    document = reorder.workbook(desktop)
    if args.mode != "absent":
        run.assert_panel(context, document)

    def open_second():
        other = reorder.workbook(desktop, 2)
        other.CurrentController.Frame.activate()
        if args.mode != "absent":
            run.assert_panel(context, other)
        return other

    def record(label):
        result["completed"].append(label)
        (output / "progress.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    for iteration in range(args.iterations):
        for variant in ("natural", "armed"):
            label = [iteration, "main", variant]
            other = open_second()
            frame = other.CurrentController.Frame
            mark(f"closing second workbook {label}")
            if variant == "natural":
                call = post_main(context, lambda: other.close(True))
            else:
                call = post_main(
                    context,
                    lambda: (time.sleep(ARMED_SECONDS), other.close(True)),
                    frame.contextChanged,
                )
            wait_call(call, label)
            mark(f"closed second workbook {label}")
            document.CurrentController.Frame.activate()
            record(label)
    variant = "natural" if args.session % 2 else "armed"
    result["bridge_variant"] = variant
    for iteration in range(args.iterations):
        label = [iteration, "bridge", variant]
        other = open_second()
        frame = other.CurrentController.Frame
        call = None
        if variant == "armed":
            call = post_main(context, lambda: time.sleep(ARMED_SECONDS), frame.contextChanged)
            if not call.started.wait(30):
                raise TimeoutError(f"main-thread call did not start: {label}")
        mark(f"closing second workbook {label}")
        other.close(True)  # From this client's main thread: a bridge thread in the office.
        mark(f"closed second workbook {label}")
        if call is not None:
            wait_call(call, label)
        document.CurrentController.Frame.activate()
        record(label)
    document.close(True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["list", "main", "absent"], required=True)
    parser.add_argument("--experiment", choices=["baseline", "close", "thread"], required=True)
    parser.add_argument("--session", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--painted", action="store_true")
    parser.add_argument("--settle", type=float, default=0)
    args = parser.parse_args()
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    class RetainedLogs(run.tempfile.TemporaryDirectory):
        def cleanup(self):
            root = Path(self.name)
            for pattern in ("*.log", "*.dmp", "*.json", "*.ini"):
                for source in root.rglob(pattern):
                    target = output / "private-profile-logs" / source.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            super().cleanup()

    run.tempfile.TemporaryDirectory = RetainedLogs
    sys.path.insert(0, str(args.oxt.resolve()) + "/pythonpath")
    import test_reorder as reorder

    result = {
        "mode": args.mode,
        "experiment": args.experiment,
        "painted": args.painted,
        "settle": args.settle,
        "completed": [],
    }
    try:
        with run.office_session(
            args.program.resolve(),
            None if args.mode == "absent" else args.oxt.resolve(),
            output,
            result,
            headless=not args.painted,
            startup_attempts=1,
        ) as (context, desktop, directory):
            mark("session connected; original lifecycle starts")
            if args.mode == "absent":
                run.exercise_without_extension(context, desktop, directory)
            else:
                run.exercise(context, desktop, directory, output, screenshot=False)
            mark("original lifecycle complete")
            if args.experiment == "thread":
                thread_experiment(context, desktop, args, result, output)
            elif args.experiment == "baseline":
                # Unmodified reorder suite, including failure injection and performance.
                mark("original reorder suite starts")
                result["reorder"] = reorder.exercise(context, desktop, directory, output)
                mark("original reorder suite complete")
            else:
                document = reorder.workbook(desktop)
                dispatch = context.ServiceManager.createInstanceWithContext(
                    "com.sun.star.frame.DispatchHelper", context
                )
                # Alternate variants within a session; record every completed close.
                for iteration in range(args.iterations):
                    for shown in (False, True):
                        if args.mode != "absent":
                            if shown:
                                run.assert_panel(context, document)
                            else:
                                dispatch.executeDispatch(
                                    document.CurrentController.Frame,
                                    ".uno:SidebarDeck.PropertyDeck",
                                    "",
                                    0,
                                    (),
                                )
                        for change, delay in ((False, 0), (True, 0), (True, 0.05), (True, 1)):
                            label = [iteration, shown, change, delay]
                            mark(f"opening second workbook {label}")
                            other = reorder.workbook(desktop, 2)
                            other.CurrentController.Frame.activate()
                            if shown and args.mode != "absent":
                                run.assert_panel(context, other)
                            if args.settle:
                                time.sleep(args.settle)
                                if args.mode != "absent":
                                    deck = (
                                        other.CurrentController.getSidebar()
                                        .getDecks()
                                        .getByName(run.DECK)
                                    )
                                    assert deck.isActive() == shown, (label, deck.isActive())
                            if change:
                                other.Sheets.insertNewByName("PendingRefresh", 2)
                                other.CurrentController.setActiveSheet(
                                    other.Sheets.getByName("PendingRefresh")
                                )
                            if delay:
                                time.sleep(delay)
                            mark(f"closing second workbook {label}")
                            other.close(True)
                            mark(f"closed second workbook {label}")
                            document.CurrentController.Frame.activate()
                            result["completed"].append(label)
                            (output / "progress.json").write_text(
                                json.dumps(result, indent=2), encoding="utf-8"
                            )
                mark("closing primary workbook")
                document.close(True)
            result["assertions_passed"] = True
    finally:
        (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    mark("session cleanly finished")


if __name__ == "__main__":
    main()
