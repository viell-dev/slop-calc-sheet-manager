"""Install into a fresh profile and assert the live sidebar through bundled PyUNO.

Run with LibreOffice's program/python[.exe], never the development venv interpreter.
Choose headless, gtk3, or both with --sessions; gtk3 saves a screenshot.
"""

import argparse
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, cast

import uno
import unohelper
from com.sun.star.beans import PropertyValue
from com.sun.star.lang import XEventListener
from main_thread import close_document
from office_process import (
    assert_clean_shutdown,
    finish_process,
    normal_startup_restart,
    retain_crash_dumps,
)

FACTORY = "dev.viell.sheetmanager.PanelFactory"
DECK = "SheetManagerDeck"
# LibreOffice defect #30: on gtk3, a new Writer window reads the clipboard within milliseconds
# and releases LibreOffice's lock while it waits; closing the document from this process during
# that wait crashes the office (#8). Closing 100 ms or more after loading never crashed.
WRITER_SETTLE_SECONDS = 1.0


def property_value(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


def close_writer(writer):
    """Close a Writer document after its start-up toolbar update has had time to finish."""
    time.sleep(WRITER_SETTLE_SECONDS)
    writer.close(True)


def wait_for(function, description, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


@contextmanager
def office_session(
    program,
    package,
    output,
    result,
    *,
    headless,
    backtrace=False,
    startup_attempts=3,
    vcl="gtk3",
):
    # Retry only startup, before opening documents or making test assertions. Windows
    # occasionally loses soffice.bin just after a successful UNO connection. Such an attempt's
    # crash dumps are kept and listed, but do not fail a session whose retry starts cleanly.
    startup_dumps: list[str] = []
    for attempt in range(startup_attempts):
        temporary = tempfile.TemporaryDirectory(prefix="sheet-manager-integration-")
        directory = Path(temporary.name)
        profile = "-env:UserInstallation=" + (directory / "profile").as_uri()
        pipe = "sheet_manager_" + uuid.uuid4().hex
        environment = os.environ.copy()
        environment.pop("WAYLAND_DISPLAY", None)
        runtime = directory / "runtime"
        runtime.mkdir(mode=0o700)
        environment["XDG_RUNTIME_DIR"] = str(runtime)
        environment["SAL_USE_VCLPLUGIN"] = "svp" if headless else vcl
        environment["GDK_BACKEND"] = "x11"
        if headless:
            environment.pop("DISPLAY", None)
        suffix = ".exe" if os.name == "nt" else ""
        installer = program / ("unopkg" + suffix)
        # Do not suppress the license here: installation must be noninteractive by metadata.
        install = (
            subprocess.run(
                [str(installer), profile, "add", str(package)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            if package is not None
            else None
        )
        (output / f"install-{headless}-{attempt}.log").write_text(
            install.stdout + install.stderr if install is not None else "Extension not installed\n",
            encoding="utf-8",
        )
        if install is not None and install.returncode:
            temporary.cleanup()
            raise AssertionError(f"Installation failed: {install.stdout}\n{install.stderr}")
        command = [
            str(program / ("soffice" + suffix)),
            profile,
            "--invisible",
            "--norestore",
            "--nologo",
            "--nolockcheck",
            "--nodefault",
            f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext",
        ]
        if headless:
            command.append("--headless")
        if backtrace:
            command.append("--backtrace")
            # The bundled Python launcher exports paths incompatible with gdb's Python.
            environment.pop("PYTHONHOME", None)
            environment.pop("PYTHONPATH", None)
        trace_path = output / f"gdbtrace-{headless}-{attempt}.log" if backtrace else None
        log_path = output / f"soffice-{headless}-{attempt}.log"
        log = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=directory,
        )
        try:
            # The stub calls this UNO "Any"; the actual value is a dynamic XComponentContext.
            local = cast(Any, uno.getComponentContext())
            resolver = local.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", local
            )
            deadline = time.monotonic() + 30
            context = None
            restarted = False
            while time.monotonic() < deadline:
                try:
                    context = resolver.resolve(
                        f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext"
                    )
                    break
                except Exception:
                    if process.poll() is not None:
                        generated_trace = directory / "gdbtrace.log"
                        if backtrace and not restarted and generated_trace.exists():
                            trace = generated_trace.read_text(encoding="utf-8", errors="replace")
                            if normal_startup_restart(trace):
                                # Match the normal launcher's profile bootstrap, only before UNO.
                                (output / f"startup-restart-{headless}-{attempt}.log").write_text(
                                    trace,
                                    encoding="utf-8",
                                )
                                result["office_startup_restart"] = 81
                                restarted = True
                                # gdbtrace enables logging before setting overwrite on;
                                # otherwise gdb appends the bootstrap exit to the final trace.
                                generated_trace.unlink()
                                process = subprocess.Popen(
                                    command,
                                    env=environment,
                                    stdin=subprocess.DEVNULL,
                                    stdout=log,
                                    stderr=subprocess.STDOUT,
                                    text=True,
                                    cwd=directory,
                                )
                                continue
                        raise RuntimeError("Private soffice exited during startup") from None
                    time.sleep(0.1)
            if context is None:
                raise TimeoutError("Private soffice did not expose its unique UNO pipe")
            time.sleep(0.75)
            desktop = context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", context
            )
            desktop.getComponents().hasElements()  # Detect the post-connect startup crash.
        except Exception:
            generated_trace = directory / "gdbtrace.log"
            startup = finish_process(
                process,
                log_path,
                timeout=0,
                backtrace_path=generated_trace if backtrace else None,
            )
            if trace_path is not None and generated_trace.exists():
                trace_path.write_bytes(generated_trace.read_bytes())
                startup["office_backtrace"] = trace_path.name
            dumps = retain_crash_dumps(
                directory / "profile" / "crash", output, f"crash-{headless}-{attempt}"
            )
            startup["office_crash_dumps"] = dumps
            startup_dumps.extend(dumps)
            log.close()
            (output / f"startup-{headless}-{attempt}.json").write_text(
                json.dumps(startup, indent=2) + "\n", encoding="utf-8"
            )
            temporary.cleanup()
            if attempt == startup_attempts - 1:
                result.update(startup)
                result["failure_stage"] = "startup"
                raise
            continue
        result["office_startup_crash_dumps"] = startup_dumps
        try:
            yield context, desktop, directory
        finally:
            # The bridge is normally disposed during successful termination.
            with suppress(Exception):
                desktop.terminate()
            try:
                generated_trace = directory / "gdbtrace.log"
                # finish_process must wait before copying the debugger's final output.
                result.update(
                    finish_process(
                        process,
                        log_path,
                        backtrace_path=generated_trace if backtrace else None,
                    )
                )
                if trace_path is not None:
                    if generated_trace.exists():
                        trace_path.write_bytes(generated_trace.read_bytes())
                    result["office_backtrace"] = trace_path.name
                result["office_crash_dumps"] = retain_crash_dumps(
                    directory / "profile" / "crash", output, f"crash-{headless}-{attempt}"
                )
            finally:
                log.close()
                temporary.cleanup()
            # #8 tracks the intermittent gtk3 abort previously hidden at termination.
            assert_clean_shutdown(result)
        return


class DisposalListener(unohelper.Base, XEventListener):
    def __init__(self):
        self.disposed = False

    def disposing(self, Source):
        self.disposed = True


def assert_panel(context, document):
    frame = document.getCurrentController().getFrame()
    frame.activate()
    dispatch = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", context
    )
    dispatch.executeDispatch(frame, ".uno:SidebarDeck." + DECK, "", 0, ())

    sidebar = document.getCurrentController().getSidebar()
    deck = sidebar.getDecks().getByName(DECK)
    assert deck.getTitle() == "Sheet Manager"
    assert deck.isActive()
    panels = deck.getPanels()
    assert panels.getElementNames() == ("SheetManagerPanel",)
    window = wait_for(
        lambda: panels.getByName("SheetManagerPanel").getDialog(), "the public panel dialog"
    )
    peer_types = [item.typeName for item in window.getTypes()]
    assert "com.sun.star.awt.XSimpleTabController" in peer_types, peer_types
    wait_for(lambda: window.getPosSize().Height > 100, "a full-height panel")
    assert window.getPosSize().Width >= 150
    listener = DisposalListener()
    window.addEventListener(listener)
    return window, listener, peer_types


def press_modifiers(document):
    """Press and release real Shift, Ctrl, and Alt keys in the document's window (painted only).

    Each modifier change makes VCL walk the window tree to show or hide access keys (#18).
    """
    title = document.getCurrentController().getFrame().getTitle()
    windows = subprocess.run(
        ["xdotool", "search", "--sync", "--onlyvisible", "--name", re.escape(title)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.split()
    assert windows, f"No visible window titled {title!r}"
    subprocess.run(["xdotool", "windowactivate", "--sync", windows[-1]], check=True, timeout=30)
    for key in ("shift", "ctrl", "alt"):
        subprocess.run(["xdotool", "key", "--clearmodifiers", key], check=True, timeout=30)
        time.sleep(0.3)


def exercise(context, desktop, directory, output, *, screenshot):
    factory = context.ServiceManager.createInstanceWithContext(FACTORY, context)
    assert factory is not None, "Passive registration did not activate the Python factory"
    assert factory.getImplementationName() == FACTORY
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    assert document is not None
    assert not document.getArgs() or not any(
        item.Name == "Hidden" and item.Value for item in document.getArgs()
    )
    panel, disposal, peer_types = assert_panel(context, document)
    window = document.getCurrentController().getFrame().getContainerWindow()
    window.IsMaximized = False
    window.setPosSize(0, 0, 1000, 500, 15)
    # gtk3 can report a 475px frame height for a 500px native request (#9).
    # Establish the actual baseline, then require both frame and panel to grow by 150px.
    previous: tuple[int, ...] | None = None
    measurements = []

    def stable_geometry():
        nonlocal previous
        frame, panel_size = window.getPosSize(), panel.getPosSize()
        measured = (
            frame.X,
            frame.Y,
            frame.Width,
            frame.Height,
            panel_size.Width,
            panel_size.Height,
        )
        measurements.append(measured)
        stable = measured == previous and frame.Width == 1000 and 100 < frame.Height <= 500
        previous = measured
        if stable:
            return frame, panel_size
        time.sleep(0.25)
        return None

    try:
        frame_before, before = wait_for(
            stable_geometry, "two matching initial frame/panel measurements"
        )
    finally:
        (output / f"resize-initial-{not screenshot}.json").write_text(
            json.dumps(measurements, indent=2) + "\n",
            encoding="utf-8",
        )
    window.setPosSize(0, 0, 1000, 650, 15)
    wait_for(
        lambda: window.getPosSize().Height == frame_before.Height + 150, "frame resize by 150px"
    )
    frame_after = window.getPosSize()
    wait_for(lambda: panel.getPosSize().Height == before.Height + 150, "panel resize by 150px")
    resized = panel.getPosSize()
    assert resized.Height > 100 and resized.Width >= 150

    # Decode the packaged SVG using this minimum-version GraphicProvider, not a browser.
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", context
    )
    package_info = context.getValueByName(
        "/singletons/com.sun.star.deployment.PackageInformationProvider"
    )
    location = package_info.getPackageLocation("dev.viell.sheetmanager")
    graphic = provider.queryGraphic((property_value("URL", location + "/icons/deck.svg"),))
    assert graphic is not None
    assert graphic.SizePixel.Width > 0 and graphic.SizePixel.Height > 0

    if screenshot:
        time.sleep(1)
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",  # Ignore the bundled launcher's PYTHONHOME/PYTHONPATH.
                "-c",
                "from PIL import ImageGrab; import sys; ImageGrab.grab().save(sys.argv[1])",
                str(output / "deck.png"),
            ],
            check=True,
        )
        assert (output / "deck.png").stat().st_size > 1000
        press_modifiers(document)
        # Any remote call fails if the office crashed handling the keys.
        assert panel.getPosSize().Height == resized.Height, "The panel must survive modifier keys"

    # Read-only documents still have a panel, and closing a frame releases it.
    workbook = directory / "synthetic.ods"
    document.storeAsURL(workbook.as_uri(), ())
    close_document(context, document)
    wait_for(lambda: disposal.disposed, "panel dialog disposal after document close")
    document = desktop.loadComponentFromURL(
        workbook.as_uri(), "_blank", 0, (property_value("ReadOnly", True),)
    )
    assert document.isReadonly()
    _, readonly_disposal, _ = assert_panel(context, document)
    close_document(context, document)
    wait_for(lambda: readonly_disposal.disposed, "read-only panel dialog disposal")
    writer = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    assert writer is not None
    decks = writer.getCurrentController().getSidebar().getDecks()
    assert not decks.hasByName(DECK), "Sheet Manager must be Calc-only"
    close_writer(writer)
    return {
        "factory": FACTORY,
        "panel_types": peer_types,
        "resize": True,
        "requested_frame_heights": [500, 650],
        "frame_heights": [frame_before.Height, frame_after.Height],
        "panel_heights": [before.Height, resized.Height],
        "read_only": True,
        "writer_excluded": True,
        "svg_decoded": True,
        "python": sys.version,
        "screenshot": screenshot,
        "modifier_keys": screenshot,
    }


def exercise_without_extension(context, desktop, directory):
    """Match the document lifecycle, omitting only extension-specific operations."""
    assert context.ServiceManager.createInstanceWithContext(FACTORY, context) is None
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    sidebar = document.getCurrentController().getSidebar()
    assert not sidebar.getDecks().hasByName(DECK)
    window = document.getCurrentController().getFrame().getContainerWindow()
    window.IsMaximized = False
    for height in (500, 650):
        window.setPosSize(0, 0, 1000, height, 15)
        time.sleep(0.5)
    workbook = directory / "synthetic.ods"
    document.storeAsURL(workbook.as_uri(), ())
    close_document(context, document)
    document = desktop.loadComponentFromURL(
        workbook.as_uri(), "_blank", 0, (property_value("ReadOnly", True),)
    )
    assert document.isReadonly()
    close_document(context, document)
    writer = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    assert writer is not None
    close_writer(writer)
    return {"extension_absent": True, "document_lifecycle": True, "python": sys.version}


def check_refusal(program, package, output) -> dict[str, object]:
    installer = program / ("unopkg.exe" if os.name == "nt" else "unopkg")
    with tempfile.TemporaryDirectory(prefix="sheet-manager-refusal-") as directory:
        profile = "-env:UserInstallation=" + Path(directory).as_uri()
        result = subprocess.run(
            [str(installer), profile, "add", str(package)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        combined = result.stdout + result.stderr
        (output / "refusal.log").write_text(combined, encoding="utf-8")
        assert result.returncode != 0, "Unsupported LibreOffice accepted the package"
        assert "dependenc" in combined.lower(), combined
        listing = subprocess.run(
            [str(installer), profile, "list"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        assert "dev.viell.sheetmanager" not in listing.stdout
        return {"refused": True, "dependency_error": True, "not_installed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/integration"))
    parser.add_argument("--expect-refusal", action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--sessions", choices=["headless", "gtk3", "both"])
    parser.add_argument("--without-extension", action="store_true")
    parser.add_argument("--suites", choices=["all", "none"], default="all")
    parser.add_argument("--startup-attempts", type=int, choices=[1, 3], default=3)
    parser.add_argument(
        "--backtrace", action="store_true", help="Linux only: use LibreOffice's gdb wrapper"
    )
    arguments = parser.parse_args()
    if arguments.backtrace and os.name == "nt":
        parser.error("--backtrace requires the Linux test image with gdb")
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for pattern in (
        "results.json",
        "deck.png",
        "refusal.log",
        "resize-initial*.json",
        "install-*.log",
        "soffice-*.log",
        "gdbtrace-*.log",
        "startup-*.json",
        "startup-restart-*.log",
        "crash-*.dmp",
        "crash-*-dump.ini",
        "reorder-performance*.json",
    ):
        for artifact in output.glob(pattern):
            artifact.unlink()
    package = arguments.oxt.resolve()
    program = arguments.program.resolve()
    # Add once for all sessions; feature suites exercise packaged modules, not src/.
    sys.path.insert(0, str(package) + "/pythonpath")
    results: list[dict[str, object]] = []
    try:
        if arguments.expect_refusal:
            results.append(check_refusal(program, package, output))
        else:
            sessions = arguments.sessions or ("both" if arguments.screenshot else "headless")
            for headless in {"headless": [True], "gtk3": [False], "both": [True, False]}[sessions]:
                result: dict[str, object] = {
                    "headless": headless,
                    "extension_installed": not arguments.without_extension,
                }
                results.append(result)
                with office_session(
                    program,
                    None if arguments.without_extension else package,
                    output,
                    result,
                    headless=headless,
                    backtrace=arguments.backtrace,
                    startup_attempts=arguments.startup_attempts,
                ) as session:
                    context, desktop, directory = session
                    if arguments.without_extension:
                        result.update(exercise_without_extension(context, desktop, directory))
                    else:
                        result.update(
                            exercise(context, desktop, directory, output, screenshot=not headless)
                        )
                        if arguments.suites == "all":
                            for suite_path in sorted(Path(__file__).parent.glob("test_*.py")):
                                spec = importlib.util.spec_from_file_location(
                                    suite_path.stem, suite_path
                                )
                                assert spec is not None and spec.loader is not None
                                suite = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(suite)
                                # A suite may take the session kind, for steps that need it.
                                options = (
                                    {"headless": headless}
                                    if "headless" in inspect.signature(suite.exercise).parameters
                                    else {}
                                )
                                suite_result = suite.exercise(
                                    context, desktop, directory, output, **options
                                )
                                result[suite_path.stem] = suite_result
                                if "performance" in suite_result:
                                    mode = "headless" if headless else "gtk3"
                                    (output / f"reorder-performance-{mode}.json").write_text(
                                        json.dumps(suite_result["performance"], indent=2) + "\n",
                                        encoding="utf-8",
                                    )
                    result["assertions_passed"] = True
    finally:
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
