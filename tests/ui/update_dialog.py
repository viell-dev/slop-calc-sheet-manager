"""Check real update offers, installation and restart on a private painted gen desktop.

GTK's weld manager is not exposed through Toolkit top windows. gen exposes the same
deployment dialogs through public UNO accessibility; input still uses real XTEST events.
Only the selected test extension is checked, keeping bundled extensions off the network.
"""

import argparse
import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
import traceback
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "integration"), str(HERE.parents[1] / "tools")]

import uno  # noqa: E402
import unohelper  # noqa: E402
from com.sun.star.ui.dialogs import XDialogClosedListener  # noqa: E402
from release_data import (  # noqa: E402
    DESCRIPTION,
    IDENTIFIER,
    LO,
    XLINK,
    PublishedBuild,
    feed,
    package_metadata,
)
from run import assert_deck, office_session, wait_for  # noqa: E402
from run_ui import Lab  # noqa: E402
from xinput import RIGHT, Pointer  # noqa: E402

ENABLED = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.ENABLED")
CHECKED = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.CHECKED")
SHOWING = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.SHOWING")
BUTTON = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.PUSH_BUTTON")
CHECKBOX = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.CHECK_BOX")
TEXT = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.TEXT")
PANEL = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.PANEL")


class Closed(unohelper.Base, XDialogClosedListener):
    def dialogClosed(self, event):
        pass

    def disposing(self, event):
        pass


class Server(http.server.SimpleHTTPRequestHandler):
    requests: list[tuple[str, str]] = []

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.requests.append(("GET", self.path))
        super().do_GET()

    def log_message(self, format, *args):
        pass


def fixture(source, destination, version, minimum, url):
    """Keep the complete built payload, changing only test deployment metadata."""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as target:
        for name in original.namelist():
            data = original.read(name)
            if name == "description.xml":
                root = ET.fromstring(data)
                number = root.find(f"{{{DESCRIPTION}}}version")
                floor = root.find(
                    f"{{{DESCRIPTION}}}dependencies/{{{LO}}}LibreOffice-minimal-version"
                )
                source_url = root.find(f"{{{DESCRIPTION}}}update-information/{{{DESCRIPTION}}}src")
                assert number is not None and floor is not None and source_url is not None
                number.set("value", version)
                floor.set("value", minimum)
                source_url.set(f"{{{XLINK}}}href", url)
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(name, data)


def dialog_nodes(context, title):
    toolkit = context.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", context)
    roots = []
    for index in range(toolkit.getTopWindowCount()):
        window = toolkit.getTopWindow(index)
        accessible = window.getProperty("XAccessible")
        root = accessible.getAccessibleContext()
        if root.getAccessibleName() == title and root.getAccessibleStateSet() & SHOWING:
            roots.append(root)
    assert len(roots) <= 1, (title, len(roots))
    if not roots:
        return None
    nodes = []

    def visit(node, depth):
        assert depth <= 12 and len(nodes) < 300, "Unexpectedly large deployment dialog"
        point, size = node.getLocationOnScreen(), node.getSize()
        children = node.getAccessibleChildCount()
        item = {
            "name": node.getAccessibleName(),
            "role": node.getAccessibleRole(),
            "states": node.getAccessibleStateSet(),
            "bounds": [point.X, point.Y, size.Width, size.Height],
            "children": children,
        }
        if hasattr(node, "getText"):
            item["text"] = node.getText()
        nodes.append(item)
        for index in range(children):
            visit(node.getAccessibleChild(index).getAccessibleContext(), depth + 1)

    visit(roots[0], 0)
    return nodes


def named(nodes, name, role=BUTTON):
    found = [item for item in nodes if item["name"] == name and item["role"] == role]
    assert len(found) == 1, (name, found)
    return found[0]


def click(lab, node, *, inset=None, button=1):
    x, y, width, height = node["bounds"]
    assert width > 1 and height > 1, node
    Pointer(lab.input, (0, 0)).click(
        x + (inset if inset is not None else width // 2), y + height // 2, button=button
    )


def installed(context):
    manager = context.getValueByName("/singletons/com.sun.star.deployment.ExtensionManager")
    packages = [
        package
        for package in manager.getDeployedExtensions("user", None, None)
        if package.getIdentifier().Value == IDENTIFIER
    ]
    assert len(packages) == 1
    return packages[0]


def snapshot(lab, title, name):
    nodes = dialog_nodes(lab.context, title)
    assert nodes, title
    (lab.output / f"{name}.json").write_text(json.dumps(nodes, indent=2) + "\n", "utf-8")
    lab.screenshot(name)
    return nodes


def offers(lab, version, enabled):
    nodes = dialog_nodes(lab.context, "Extensions")
    assert nodes
    # The manager's custom extension cards have no accessible children. Its search
    # narrows the list to the one known installed package; use the observed canvas bounds.
    canvases = [
        node
        for node in nodes
        if node["role"] == PANEL
        and not node["children"]
        and node["bounds"][2] > 400
        and node["bounds"][3] > 150
    ]
    assert len(canvases) == 1, canvases
    x, y, _, _ = canvases[0]["bounds"]
    before = len(Server.requests)
    Pointer(lab.input, (0, 0)).click(x + 60, y + 20, button=RIGHT)
    # LibreOffice's ExtensionBoxWithButtons appends CMD_UPDATE first on every pinned
    # build. The resulting dialog and loopback request independently verify the command.
    lab.input.tap("Home")
    lab.input.tap("Return")

    def complete():
        nodes = dialog_nodes(lab.context, "Extension Update")
        return (
            nodes
            if nodes
            and ("GET", "/updates.xml") in Server.requests[before:]
            and not any(node["name"] == "Checking..." for node in nodes)
            else None
        )

    wait_for(complete, "the selected extension's completed update check", timeout=30)
    nodes = snapshot(lab, "Extension Update", version)
    rows = [node for node in nodes if node["role"] == CHECKBOX and " Version " in node["name"]]
    assert [node["name"] for node in rows] == (
        [f"Sheet Manager Version {version}"] if enabled else []
    ), rows
    assert bool(named(nodes, "Install")["states"] & ENABLED) is enabled
    if enabled:
        assert rows[0]["states"] & CHECKED, rows
    return nodes


def exercise(program, package, output, result, backtrace):
    root = output / "server"
    root.mkdir()
    with zipfile.ZipFile(package) as archive:
        current, minimum = package_metadata(archive.read("description.xml"))
    major = int(current.split(".")[0]) + 1
    newer, future = f"{major}.0.0", f"{major}.1.0"
    Server.requests = []
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Server, directory=str(root))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    older = output / "older.oxt"
    fixture(package, older, current, minimum, url + "/updates.xml")
    fixture(package, root / "newer.oxt", newer, minimum, url + "/updates.xml")

    def serve(builds):
        # Feed generation owns all metadata; substitute only the test download URL.
        data = feed(builds, stable=True)
        for build in builds:
            data = data.replace(build.download.encode(), (url + "/newer.oxt").encode())
        (root / "updates.xml").write_bytes(data)

    profile = output / "profile"
    try:
        result["dialog"] = session = {}
        with office_session(
            program,
            older,
            output,
            session,
            headless=False,
            vcl="gen",
            backtrace=backtrace,
            profile_directory=profile,
        ) as (context, desktop, directory):
            document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
            lab = Lab(context, desktop, directory, output)
            try:
                assert installed(context).getVersion() == current
                service = context.ServiceManager.createInstanceWithContext(
                    "com.sun.star.deployment.ui.PackageManagerDialog", context
                )
                listener = Closed()
                service.startExecuteModal(listener)
                nodes = wait_for(lambda: dialog_nodes(context, "Extensions"), "Extensions dialog")
                search = [node for node in nodes if node["role"] == TEXT]
                assert len(search) == 1, search
                click(lab, search[0])
                for character in "sheet manager":
                    lab.input.tap("space" if character == " " else character, pause=0.01)
                for label, builds in (
                    ("empty", []),
                    ("same", [PublishedBuild(current, False, minimum, "2026-10-26T00:00:00Z")]),
                    ("older", [PublishedBuild("0.0.0", False, minimum, "2026-10-26T00:00:00Z")]),
                    (
                        "incompatible",
                        [PublishedBuild(future, False, "999.0.0", "2026-10-26T00:00:00Z")],
                    ),
                ):
                    serve(builds)
                    nodes = offers(lab, label, False)
                    if label == "incompatible":
                        click(lab, named(nodes, "Show all updates", CHECKBOX), inset=5)
                        wait_for(
                            lambda: (
                                named(
                                    dialog_nodes(context, "Extension Update"),
                                    "Show all updates",
                                    CHECKBOX,
                                )["states"]
                                & CHECKED
                            ),
                            "disabled updates to be shown",
                        )
                        nodes = snapshot(lab, "Extension Update", "incompatible-all")
                        row = named(nodes, f"Sheet Manager Version {future}", CHECKBOX)
                        assert not row["states"] & CHECKED
                        click(lab, row, inset=80)
                        nodes = snapshot(lab, "Extension Update", "incompatible-reason")
                        assert "999.0.0" in " ".join(node.get("text", "") for node in nodes)
                        assert not named(nodes, "Install")["states"] & ENABLED
                    click(lab, named(nodes, "Close"))
                    assert installed(context).getVersion() == current
                    assert not any(path.endswith(".oxt") for _, path in Server.requests)
                    result[label] = True
                serve([PublishedBuild(newer, False, minimum, "2026-10-26T00:00:00Z")])
                nodes = offers(lab, newer, True)
                click(lab, named(nodes, "Install"))

                def finished():
                    nodes = dialog_nodes(context, "Download and Installation")
                    return nodes if nodes and named(nodes, "OK")["states"] & ENABLED else None

                wait_for(finished, "successful update installation to finish", timeout=60)
                nodes = snapshot(lab, "Download and Installation", "installation-complete")
                assert ("GET", "/newer.oxt") in Server.requests
                assert installed(context).getVersion() == newer
                result["installed"] = newer
                result["installation_text"] = [node["text"] for node in nodes if "text" in node]
                assert "No errors." in result["installation_text"], result["installation_text"]
                click(lab, named(nodes, "OK"))
            finally:
                for _ in range(4):
                    lab.input.tap("Escape", pause=0.3)
                document.close(True)
        restart = output / "restart"
        restart.mkdir()
        result["restart"] = restarted = {}
        with office_session(
            program,
            None,
            restart,
            restarted,
            headless=False,
            vcl="gen",
            backtrace=backtrace,
            profile_directory=profile,
        ) as (context, desktop, directory):
            registered = installed(context)
            assert registered.getVersion() == newer
            assert tuple(registered.getUpdateInformationURLs()) == (url + "/updates.xml",)
            assert_deck(context, desktop, installed=True)
            restarted["version"] = newer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        result["requests"] = Server.requests
    logs = "".join(path.read_text("utf-8", "replace") for path in output.rglob("soffice-*.log"))
    result["extension_errors"] = logs.count("Sheet Manager: ")
    assert not result["extension_errors"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ui", action="store_true", help="Accepted from the container session")
    parser.add_argument("--backtrace", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {"vcl": "gen"}
    try:
        # Deployment state survives our controlled restart, then the profile is removed.
        with tempfile.TemporaryDirectory(prefix="sheet-manager-updates-") as directory:
            output = Path(directory)
            try:
                exercise(arguments.program, arguments.oxt, output, result, arguments.backtrace)
            finally:
                shutil.copytree(
                    output,
                    arguments.output,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("profile", "*.oxt"),
                )
    except Exception:
        result["error"] = traceback.format_exc()
    (arguments.output / "results.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()
