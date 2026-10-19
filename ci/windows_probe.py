"""Branch-only issue #45 runner experiment; never packaged in the extension."""

import argparse
import faulthandler
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "integration"))
import run


def mark(message):
    print(f"{time.monotonic():.6f} {message}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["list", "main", "absent"], required=True)
    parser.add_argument("--experiment", choices=["baseline", "close"], required=True)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--painted", action="store_true")
    args = parser.parse_args()
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    class RetainedLogs(run.tempfile.TemporaryDirectory):
        def cleanup(self):
            root = Path(self.name)
            for pattern in ("*.log", "*.dmp", "*.json"):
                for source in root.rglob(pattern):
                    target = output / "private-profile-logs" / source.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            super().cleanup()

    run.tempfile.TemporaryDirectory = RetainedLogs
    sys.path.insert(0, str(args.oxt.resolve()) + "/pythonpath")
    import test_reorder as reorder

    result = {"mode": args.mode, "experiment": args.experiment, "completed": []}
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
            if args.experiment == "baseline":
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
                                    ".uno:SidebarDeck.PropertyDeck", "", 0, (),
                                )
                        for change, delay in ((False, 0), (True, 0), (True, 0.05), (True, 1)):
                            label = [iteration, shown, change, delay]
                            mark(f"opening second workbook {label}")
                            other = reorder.workbook(desktop, 2)
                            other.CurrentController.Frame.activate()
                            if shown and args.mode != "absent":
                                run.assert_panel(context, other)
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
