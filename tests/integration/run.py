"""Install into a fresh profile and assert the live sidebar through bundled PyUNO.

Run with LibreOffice's program/python[.exe], never the development venv interpreter.
The default run is headless; --screenshot adds a separate painted gtk3/Xvfb run.
"""

import argparse
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
from com.sun.star.beans import PropertyValue

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


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@contextmanager
def office_session(program, package, output, *, headless):
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
        log = (output / f"soffice-{headless}-{attempt}.log").open("w", encoding="utf-8")
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
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
            stop_process(process)
            log.close()
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
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stop_process(process)
            log.close()
            temporary.cleanup()
        return


def assert_panel(context, document, factory):
    frame = document.getCurrentController().getFrame()
    frame.activate()
    dispatch = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", context
    )
    dispatch.executeDispatch(frame, ".uno:SidebarDeck." + DECK, "", 0, ())

    def matching_panel():
        for name in factory.getElementNames():
            panel = factory.getByName(name)
            if panel.Frame == frame:
                return panel
        return None

    panel = wait_for(matching_panel, "the installed factory's panel in this Calc frame")
    assert panel.ResourceURL == "private:resource/toolpanel/SheetManager/Panel"
    assert panel.Type == uno.getConstantByName("com.sun.star.ui.UIElementType.TOOLPANEL")
    assert panel.createAccessible(None) is None
    peer_types = [item.typeName for item in panel.Window.getTypes()]
    assert "com.sun.star.awt.XSimpleTabController" in peer_types, peer_types
    wait_for(lambda: panel.Window.getPosSize().Height > 100, "a full-height panel")
    assert panel.Window.getPosSize().Width >= 150
    sidebar = document.getCurrentController().getSidebar()
    deck = sidebar.getDecks().getByName(DECK)
    assert deck.getTitle() == "Sheet Manager"
    assert deck.isActive()
    panels = deck.getPanels()
    assert panels.getElementNames() == ("SheetManagerPanel",)
    return panel


def exercise(context, desktop, directory, output, *, screenshot):
    factory = context.ServiceManager.createInstanceWithContext(FACTORY, context)
    assert factory is not None, "Passive registration did not activate the Python factory"
    assert factory.getImplementationName() == FACTORY
    assert not factory.hasElements(), "Factory activation must not eagerly create a panel"
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    assert document is not None
    assert not document.getArgs() or not any(
        item.Name == "Hidden" and item.Value for item in document.getArgs()
    )
    panel = assert_panel(context, document, factory)
    window = document.getCurrentController().getFrame().getContainerWindow()
    before = panel.Window.getPosSize()
    bounds = window.getPosSize()
    window.setPosSize(bounds.X, bounds.Y, 1100, 700, 12)
    wait_for(lambda: panel.Window.getPosSize().Height != before.Height, "panel resize")
    resized = panel.Window.getPosSize()
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
    wait_for(lambda: not factory.hasElements(), "panel disposal after document close")
    document = desktop.loadComponentFromURL(
        workbook.as_uri(), "_blank", 0, (property_value("ReadOnly", True),)
    )
    assert document.isReadonly()
    assert_panel(context, document, factory)
    document.close(True)
    wait_for(lambda: not factory.hasElements(), "read-only panel disposal")
    writer = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    assert writer is not None
    decks = writer.getCurrentController().getSidebar().getDecks()
    assert not decks.hasByName(DECK), "Sheet Manager must be Calc-only"
    assert not factory.hasElements()
    writer.close(True)
    return {
        "factory": FACTORY,
        "panel": "VCLXTabControl",
        "resize": True,
        "read_only": True,
        "writer_excluded": True,
        "svg_decoded": True,
        "python": sys.version,
        "screenshot": screenshot,
    }


def check_refusal(program, package, output):
    with tempfile.TemporaryDirectory(prefix="sheet-manager-refusal-") as directory:
        profile = "-env:UserInstallation=" + Path(directory).as_uri()
        result = subprocess.run(
            [str(program / "unopkg"), profile, "add", str(package)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        combined = result.stdout + result.stderr
        (output / "refusal.log").write_text(combined, encoding="utf-8")
        assert result.returncode != 0, "Unsupported LibreOffice accepted the package"
        assert "dependenc" in combined.lower(), combined
        listing = subprocess.run(
            [str(program / "unopkg"), profile, "list"],
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
    package = arguments.oxt.resolve()
    program = arguments.program.resolve()
    if arguments.expect_refusal:
        results = [check_refusal(program, package, output)]
    else:
        results = []
        for headless in [True, False] if arguments.screenshot else [True]:
            with office_session(program, package, output, headless=headless) as session:
                context, desktop, directory = session
                results.append(
                    exercise(context, desktop, directory, output, screenshot=not headless)
                )
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
