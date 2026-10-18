"""Install into a fresh profile and assert the live sidebar through bundled PyUNO.

Run with LibreOffice's program/python[.exe], never the development venv interpreter.
The default run is headless; --screenshot adds a separate painted gtk3/Xvfb run.
"""

import argparse
import importlib.util
import json
import os
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
from office_process import assert_clean_shutdown, finish_process

FACTORY = "dev.viell.sheetmanager.PanelFactory"
DECK = "SheetManagerDeck"


def property_value(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


def wait_for(function, description, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


@contextmanager
def office_session(program, package, output, result, *, headless):
    # Retry only startup, before opening documents or making test assertions. Windows
    # occasionally loses soffice.bin just after a successful UNO connection.
    for attempt in range(3):
        temporary = tempfile.TemporaryDirectory(prefix="sheet-manager-integration-")
        directory = Path(temporary.name)
        profile = "-env:UserInstallation=" + (directory / "profile").as_uri()
        pipe = "sheet_manager_" + uuid.uuid4().hex
        environment = os.environ.copy()
        environment.pop("WAYLAND_DISPLAY", None)
        runtime = directory / "runtime"
        runtime.mkdir(mode=0o700)
        environment["XDG_RUNTIME_DIR"] = str(runtime)
        environment["SAL_USE_VCLPLUGIN"] = "svp" if headless else "gtk3"
        environment["GDK_BACKEND"] = "x11"
        if headless:
            environment.pop("DISPLAY", None)
        suffix = ".exe" if os.name == "nt" else ""
        installer = program / ("unopkg" + suffix)
        # Do not suppress the license here: installation must be noninteractive by metadata.
        install = subprocess.run(
            [str(installer), profile, "add", str(package)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
        (output / f"install-{headless}-{attempt}.log").write_text(
            install.stdout + install.stderr, encoding="utf-8"
        )
        if install.returncode:
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
        log_path = output / f"soffice-{headless}-{attempt}.log"
        log = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command, env=environment, stdout=log, stderr=subprocess.STDOUT, text=True
        )
        try:
            # The stub calls this UNO "Any"; the actual value is a dynamic XComponentContext.
            local = cast(Any, uno.getComponentContext())
            resolver = local.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", local
            )
            deadline = time.monotonic() + 30
            context = None
            while time.monotonic() < deadline:
                try:
                    context = resolver.resolve(
                        f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext"
                    )
                    break
                except Exception:
                    if process.poll() is not None:
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
            startup = finish_process(process, log_path, timeout=0)
            log.close()
            (output / f"startup-{headless}-{attempt}.json").write_text(
                json.dumps(startup, indent=2) + "\n", encoding="utf-8"
            )
            temporary.cleanup()
            if attempt == 2:
                raise
            continue
        try:
            yield context, desktop, directory
        finally:
            # The bridge is normally disposed during successful termination.
            with suppress(Exception):
                desktop.terminate()
            try:
                result.update(finish_process(process, log_path))
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
    wait_for(
        lambda: window.getPosSize().Width == 1000 and 100 < window.getPosSize().Height <= 500,
        "the initial frame geometry",
    )
    time.sleep(0.25)
    frame_before = window.getPosSize()
    before = panel.getPosSize()
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

    # Read-only documents still have a panel, and closing a frame releases it.
    workbook = directory / "synthetic.ods"
    document.storeAsURL(workbook.as_uri(), ())
    document.close(True)
    wait_for(lambda: disposal.disposed, "panel dialog disposal after document close")
    document = desktop.loadComponentFromURL(
        workbook.as_uri(), "_blank", 0, (property_value("ReadOnly", True),)
    )
    assert document.isReadonly()
    _, readonly_disposal, _ = assert_panel(context, document)
    document.close(True)
    wait_for(lambda: readonly_disposal.disposed, "read-only panel dialog disposal")
    writer = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    assert writer is not None
    decks = writer.getCurrentController().getSidebar().getDecks()
    assert not decks.hasByName(DECK), "Sheet Manager must be Calc-only"
    writer.close(True)
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
    }


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
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for artifact in ("results.json", "deck.png"):
        (output / artifact).unlink(missing_ok=True)
    package = arguments.oxt.resolve()
    program = arguments.program.resolve()
    results: list[dict[str, object]] = []
    try:
        if arguments.expect_refusal:
            results.append(check_refusal(program, package, output))
        else:
            for headless in [True, False] if arguments.screenshot else [True]:
                result: dict[str, object] = {"headless": headless}
                results.append(result)
                with office_session(program, package, output, result, headless=headless) as session:
                    context, desktop, directory = session
                    result.update(
                        exercise(context, desktop, directory, output, screenshot=not headless)
                    )
                    # Additive feature suites exercise the packaged modules, not src/.
                    sys.path.insert(0, str(package) + "/pythonpath")
                    for suite_path in sorted(Path(__file__).parent.glob("test_*.py")):
                        spec = importlib.util.spec_from_file_location(suite_path.stem, suite_path)
                        assert spec is not None and spec.loader is not None
                        suite = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(suite)
                        result[suite_path.stem] = suite.exercise(
                            context, desktop, directory, output
                        )
    finally:
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
