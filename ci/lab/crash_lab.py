"""Investigation lab for issue #8: repeat composable office lifecycles in fresh gtk3 profiles.

Parent mode interleaves arms round by round; each session is a separate child process with a
fresh profile, using tests/integration/run.py's office_session (mounted read-only at /work).

Arm syntax: NAME=ext:STEP,STEP,...  or  NAME=noext:STEP,...
Steps: calc | writer | deck=<DeckId> | resize | svg | shot | save | close | ro | wquery | wvis
       | idle | sleep=<seconds> | cell | quit
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.environ.get("LAB_INTEGRATION_DIR", "/work/tests/integration"))


def child(arguments):
    import shutil
    import tempfile

    output = arguments.output
    output.mkdir(parents=True, exist_ok=True)

    class KeepCrashDumps(tempfile.TemporaryDirectory):
        """Preserve LibreOffice's own crash dumps (Windows) before the profile is deleted."""

        def cleanup(self):
            for dump in Path(self.name).rglob("*.dmp"):
                (output / "crash").mkdir(exist_ok=True)
                shutil.copy2(dump, output / "crash" / dump.name)
            super().cleanup()

    tempfile.TemporaryDirectory = KeepCrashDumps
    if os.environ.get("LAB_CLEAN_PYTHON_ENV"):
        # The bundled interpreter's PYTHONHOME/PYTHONPATH would break gdb's embedded Python.
        # A desktop launch has neither, so the office itself is unaffected.
        os.environ.pop("PYTHONHOME", None)
        os.environ.pop("PYTHONPATH", None)

    import uno  # noqa: F401
    from run import DECK, DisposalListener, office_session, property_value, wait_for

    result = {"arm": arguments.arm, "steps": arguments.steps, "extension": arguments.extension}
    steps_log = (output / "steps.log").open("w", encoding="utf-8")
    start = time.monotonic()

    def note(text):
        steps_log.write(f"{time.monotonic() - start:8.3f} {text}\n")
        steps_log.flush()

    try:
        with office_session(
            arguments.program,
            arguments.oxt if arguments.extension else None,
            output,
            result,
            headless=False,
            backtrace=arguments.backtrace,
            startup_attempts=1,
        ) as (context, desktop, directory):
            smgr = context.ServiceManager
            helper = smgr.createInstanceWithContext("com.sun.star.frame.DispatchHelper", context)
            toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", context)
            workbook = directory / "synthetic.ods"
            def xdotool(*words):
                return subprocess.run(
                    ["xdotool", *words], check=True, capture_output=True, text=True, timeout=30
                ).stdout.split()

            def activate(title):
                window = xdotool("search", "--sync", "--onlyvisible", "--name", title)[-1]
                xdotool("windowactivate", "--sync", window)
                time.sleep(0.3)

            def text_documents():
                found = []
                enumeration = desktop.getComponents().createEnumeration()
                while enumeration.hasMoreElements():
                    component = enumeration.nextElement()
                    if component.supportsService("com.sun.star.text.TextDocument"):
                        found.append(component)
                return found

            # Open documents form a stack: steps act on the newest; close pops it.
            state = {"docs": [], "frame": None}
            observations = {}
            for step in arguments.steps.split(","):
                name, _, value = step.partition("=")
                note(f"begin {step}")
                entry = state["docs"][-1] if state["docs"] else None
                document = entry["doc"] if entry else None
                if name == "calc":
                    state["docs"].append(
                        {
                            "doc": desktop.loadComponentFromURL(
                                "private:factory/scalc", "_blank", 0, ()
                            ),
                            "listeners": [],
                        }
                    )
                elif name == "writer":
                    state["docs"].append(
                        {
                            "doc": desktop.loadComponentFromURL(
                                "private:factory/swriter", "_blank", 0, ()
                            ),
                            "listeners": [],
                        }
                    )
                elif name == "kbactivate":
                    activate("LibreOffice " + value)
                elif name == "key":
                    xdotool("key", "--clearmodifiers", value)
                    time.sleep(0.3)
                elif name == "alive":
                    # One cheap remote call: fails if the office has died.
                    observations.setdefault("alive", []).append(desktop.getFrames().getCount())
                elif name == "kbnewwriter":
                    # A person's File > New > Text Document, handled on the office's main thread.
                    activate("LibreOffice Calc")
                    for key in ("alt+f", "n", "t"):
                        xdotool("key", "--clearmodifiers", key)
                        time.sleep(0.3)
                    writer = wait_for(lambda: text_documents(), "a keyboard-created Writer document")
                    state["docs"].append({"doc": writer[0], "listeners": []})
                elif name == "kbclose":
                    # Ctrl+W on the frontmost Writer window, handled on the office's main thread.
                    activate("LibreOffice Writer")
                    xdotool("key", "--clearmodifiers", "ctrl+w")
                    wait_for(lambda: not text_documents(), "the keyboard-closed Writer document")
                    state["docs"].pop()
                elif name == "ro":
                    state["docs"].append(
                        {
                            "doc": desktop.loadComponentFromURL(
                                workbook.as_uri(),
                                "_blank",
                                0,
                                (property_value("ReadOnly", True),),
                            ),
                            "listeners": [],
                        }
                    )
                elif name == "deck":
                    frame = document.getCurrentController().getFrame()
                    frame.activate()
                    sidebar = document.getCurrentController().getSidebar()
                    # The sidebar reopens a remembered deck; dispatching it again toggles it shut.
                    # Keep the integration test's unconditional dispatch for the extension deck.
                    if value == DECK or not (
                        sidebar.getDecks().hasByName(value)
                        and sidebar.getDecks().getByName(value).isActive()
                    ):
                        helper.executeDispatch(frame, ".uno:SidebarDeck." + value, "", 0, ())
                    deck = wait_for(
                        lambda: sidebar.getDecks().hasByName(value)
                        and sidebar.getDecks().getByName(value),
                        f"deck {value}",
                    )
                    wait_for(deck.isActive, f"active deck {value}")
                    if value == DECK:
                        panels = deck.getPanels()
                        window = wait_for(
                            lambda: panels.getByName("SheetManagerPanel").getDialog(),
                            "the public panel dialog",
                        )
                        listener = DisposalListener()
                        window.addEventListener(listener)
                        entry["listeners"].append(listener)
                elif name == "resize":
                    window = document.getCurrentController().getFrame().getContainerWindow()
                    window.IsMaximized = False
                    for height in (500, 650):
                        window.setPosSize(0, 0, 1000, height, 15)
                        time.sleep(0.75)
                elif name == "svg":
                    provider = smgr.createInstanceWithContext(
                        "com.sun.star.graphic.GraphicProvider", context
                    )
                    info = context.getValueByName(
                        "/singletons/com.sun.star.deployment.PackageInformationProvider"
                    )
                    location = info.getPackageLocation("dev.viell.sheetmanager")
                    graphic = provider.queryGraphic(
                        (property_value("URL", location + "/icons/deck.svg"),)
                    )
                    assert graphic is not None
                elif name == "shot":
                    time.sleep(1)
                    subprocess.run(
                        [
                            "/usr/bin/python3",
                            "-I",
                            "-c",
                            "from PIL import ImageGrab; import sys; "
                            "ImageGrab.grab().save(sys.argv[1])",
                            str(output / "screen.png"),
                        ],
                        check=True,
                    )
                elif name == "save":
                    document.storeAsURL(workbook.as_uri(), ())
                elif name == "close":
                    state["docs"].pop()
                    document.close(True)
                    for listener in entry["listeners"]:
                        wait_for(lambda: listener.disposed, "panel disposal")
                elif name == "wquery":
                    decks = document.getCurrentController().getSidebar().getDecks()
                    observations.setdefault("wquery", []).append(decks.hasByName(DECK))
                elif name == "keepframe":
                    state["frame"] = document.getCurrentController().getFrame()
                elif name == "framecheck":
                    check = {"desktop_frames": desktop.getFrames().getCount()}
                    try:
                        controller = state["frame"].getController()
                        check["frame_disposed"] = False
                        check["frame_has_controller"] = controller is not None
                    except Exception as error:  # noqa: BLE001 - DisposedException expected
                        check["frame_disposed"] = type(error).__name__
                    observations.setdefault("framecheck", []).append(check)
                elif name == "factory":
                    factory = smgr.createInstanceWithContext(
                        "dev.viell.sheetmanager.PanelFactory", context
                    )
                    assert factory is not None
                elif name == "decknames":
                    decks = document.getCurrentController().getSidebar().getDecks()
                    observations["decks"] = list(decks.getElementNames())
                elif name == "wvis":
                    visible = document.getCurrentController().getSidebar().isVisible()
                    observations.setdefault("sidebar_visible", []).append(visible)
                elif name == "idle":
                    toolkit.processEventsToIdle()
                elif name == "sleep":
                    time.sleep(float(value))
                elif name == "cell":
                    sheet = document.getSheets().getByIndex(0)
                    sheet.getCellByPosition(0, 0).setString("synthetic")
                elif name == "quit":
                    # File > Exit: the office quits from its own main loop, not via terminate().
                    target = document.getCurrentController().getFrame() if document else desktop
                    try:
                        helper.executeDispatch(target, ".uno:Quit", "", 0, ())
                    except Exception as error:  # noqa: BLE001 - the bridge may close first
                        note(f"quit dispatch ended with {type(error).__name__}")
                    state["docs"] = []
                else:
                    raise SystemExit(f"Unknown step {step}")
                note(f"end {step}")
            note("terminate")
            result.update(observations)
            result["assertions_passed"] = True
    except BaseException as error:  # noqa: BLE001 - record every failure for the lab
        result["error"] = "".join(traceback.format_exception_only(type(error), error)).strip()
        note(f"error {result['error']}")
    finally:
        note("finished")
        steps_log.close()
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if "error" not in result else 1)


def summarize_trace(path):
    if not path.exists():
        return {}
    trace = path.read_text(encoding="utf-8", errors="replace")
    summary = {}
    signal_match = re.search(r"received signal (\w+)", trace)
    if signal_match:
        summary["signal"] = signal_match.group(1)
        crash = trace[signal_match.end() :]
        frame = re.search(r"^#0 .*? in (.+?) \(", crash, re.MULTILINE)
        summary["top_frame"] = frame.group(1) if frame else None
        address = re.search(r"^\$1 = \(void \*\) (0x[0-9a-f]+)", trace, re.MULTILINE)
        summary["fault_address"] = address.group(1) if address else None
    return summary


def parent(arguments):
    output = arguments.output
    output.mkdir(parents=True, exist_ok=True)
    arms = []
    for spec in arguments.arm:
        name, _, rest = spec.partition("=")
        mode, _, steps = rest.partition(":")
        assert mode in ("ext", "noext"), spec
        arms.append((name, mode == "ext", steps))
    rows = []
    jsonl = (output / "lab-results.jsonl").open("a", encoding="utf-8")
    for number in range(1, arguments.rounds + 1):
        for name, extension, steps in arms:
            directory = output / name / f"{number:03d}"
            directory.mkdir(parents=True, exist_ok=True)
            # Windows' bundled Python reports its core directory as sys.executable.
            python = (
                str(arguments.program / "python.exe") if os.name == "nt" else sys.executable
            )
            command = [
                python,
                __file__,
                "--child",
                "--program",
                str(arguments.program),
                "--oxt",
                str(arguments.oxt),
                "--output",
                str(directory),
                "--arm",
                name,
                "--steps",
                steps,
            ]
            if extension:
                command.append("--extension")
            if arguments.backtrace:
                command.append("--backtrace")
            began = time.monotonic()
            with (directory / "runner.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
                try:
                    status = process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                    status = 124
            if os.name == "nt":
                # The Windows launcher can exit while soffice.bin survives; stop only lab offices.
                subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name like 'soffice%'\" | "
                        "Where-Object CommandLine -match 'sheet-manager-integration-' | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
                    ],
                    check=False,
                )
            result_path = directory / "results.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            dumps = sorted(str(path.name) for path in (directory / "crash").glob("*.dmp"))
            row = {
                "arm": name,
                "round": number,
                "runner_exit": status,
                "seconds": round(time.monotonic() - began, 1),
                "markers": result.get("office_fatal_markers"),
                "exit": result.get("office_exit_code"),
                "forced": result.get("office_forced_shutdown"),
                "assertions": result.get("assertions_passed", False),
                "error": result.get("error"),
                "sidebar_visible": result.get("sidebar_visible"),
                "wquery": result.get("wquery"),
                "decks": result.get("decks"),
                "framecheck": result.get("framecheck"),
                "dumps": dumps,
                **summarize_trace(directory / "gdbtrace-False-0.log"),
            }
            rows.append(row)
            jsonl.write(json.dumps(row) + "\n")
            jsonl.flush()
            print(json.dumps(row), flush=True)
    jsonl.close()
    lines = ["| Arm | Sessions | Crashes (signal) | Other failures |", "| --- | ---: | ---: | ---: |"]
    for name, _, _ in arms:
        mine = [row for row in rows if row["arm"] == name]
        crashes = sum(1 for row in mine if row.get("signal"))
        other = sum(1 for row in mine if row["runner_exit"] and not row.get("signal"))
        lines.append(f"| {name} | {len(mine)} | {crashes} | {other} |")
    (output / "lab-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--arm", action="append", required=True)
    parser.add_argument("--steps")
    parser.add_argument("--extension", action="store_true")
    parser.add_argument("--backtrace", action="store_true")
    parser.add_argument("--rounds", type=int, default=1)
    arguments = parser.parse_args()
    if arguments.child:
        arguments.arm = arguments.arm[0]
        child(arguments)
    else:
        parent(arguments)


if __name__ == "__main__":
    main()
