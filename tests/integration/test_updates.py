"""Exercise generated feeds through LibreOffice's headless parser and dependency checker.

The enabled/disabled update list belongs to a modal VCL dialog, not a UNO API. The
public UpdateInformationProvider parses descriptions without filtering versions or
dependencies. Test that boundary honestly, and check candidate dependencies through
deployment's real XPackage API rather than duplicating LibreOffice's floor check. Keep the parser
and dependency assertions distinct.
"""

import argparse
import functools
import http.server
import json
import sys
import threading
import zipfile
from pathlib import Path

import uno
from com.sun.star.deployment import DeploymentException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from release_data import (  # noqa: E402
    DESCRIPTION,
    IDENTIFIER,
    LO,
    SITE,
    UPDATE,
    XLINK,
    PublishedBuild,
    compare_versions,
    feed,
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def candidate_package(path: Path, version: str, minimum: str) -> Path:
    description = (
        f'<description xmlns="{DESCRIPTION}" xmlns:lo="{LO}">'
        f'<identifier value="{IDENTIFIER}"/><version value="{version}"/>'
        '<display-name><name lang="en">Sheet Manager update test</name></display-name>'
        f'<dependencies><lo:LibreOffice-minimal-version value="{minimum}"/></dependencies>'
        "</description>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("description.xml", description)
        archive.writestr(
            "META-INF/manifest.xml",
            '<manifest:manifest xmlns:manifest="http://openoffice.org/2001/manifest"/>',
        )
    return path


def exercise(context, desktop, directory, output):
    manager = context.getValueByName("/singletons/com.sun.star.deployment.ExtensionManager")
    installed = [
        package
        for package in manager.getDeployedExtensions("user", None, None)
        if package.getIdentifier().Value == IDENTIFIER
    ]
    assert len(installed) == 1
    older = installed[0]
    assert tuple(older.getUpdateInformationURLs()) == (f"{SITE}/updates/stable.xml",)
    current = older.getVersion()
    # Pick larger synthetic versions without constraining the source version in future releases.
    major = int(current.split(".")[0]) + 1
    newer, future = f"{major}.0.0", f"{major}.1.0"
    compatible = PublishedBuild(newer, False, "26.2.1", "2026-10-19T00:00:00Z")
    incompatible = PublishedBuild(future, False, "999.0.0", "2026-10-20T00:00:00Z")
    root = directory / "update-server"
    root.mkdir()
    for name, builds in (
        ("empty", []),
        ("compatible", [compatible]),
        ("incompatible", [incompatible]),
        ("history", [compatible, incompatible]),
    ):
        (root / f"{name}.xml").write_bytes(feed(builds, stable=False))
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.deployment.UpdateInformationProvider", context
    )
    xpath = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.xml.xpath.XPathAPI", context
    )
    xpath.registerNS("u", UPDATE)
    xpath.registerNS("lo", LO)
    xpath.registerNS("xlink", XLINK)
    results = {}
    try:
        for name, expected in (
            ("empty", []),
            ("compatible", [compatible]),
            ("incompatible", [incompatible]),
            ("history", [incompatible, compatible]),
        ):
            url = f"http://127.0.0.1:{server.server_port}/{name}.xml"
            nodes = provider.getUpdateInformation((url,), IDENTIFIER)
            assert len(nodes) == len(expected), (name, len(nodes))
            for node, item in zip(nodes, expected, strict=True):

                def value(expression, node=node):
                    return xpath.selectSingleNode(node, expression).getNodeValue()

                assert value("/u:description/u:identifier/@value") == older.getIdentifier().Value
                number = value("/u:description/u:version/@value")
                assert number == item.version and compare_versions(number, current) > 0
                assert (
                    value("/u:description/u:dependencies/lo:LibreOffice-minimal-version/@value")
                    == item.minimum
                )
                assert value("/u:description/u:update-download/u:src/@xlink:href") == item.download
                assert value("/u:description/u:release-notes/u:src/@xlink:href") == item.notes
            results[name] = len(nodes)
        # Deployment reads the same dependency element from an OXT description. Stage
        # candidates in the private temporary repository; never replace the installed one.
        factory = context.getValueByName(
            "/singletons/com.sun.star.deployment.thePackageManagerFactory"
        )
        temporary = factory.getPackageManager("tmp")
        for item, expected in ((compatible, True), (incompatible, False)):
            package = candidate_package(
                root / f"candidate-{item.version}.oxt", item.version, item.minimum
            )
            staged = temporary.addPackage(uno.systemPathToFileUrl(str(package)), (), "", None, None)
            try:
                satisfied = staged.checkDependencies(None)
            except DeploymentException as error:
                assert error.Message == "unsatisfied dependencies"
                satisfied = False
            assert satisfied == expected
            results[f"dependencies-{item.minimum}"] = expected
        assert older.getVersion() == current
        assert compare_versions("0.1.0-rc.1", "0.1.0") > 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return {"parser_and_deployment": results, "installed_older_version": current}


if __name__ == "__main__":
    from run import office_session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {}
    with office_session(
        arguments.program, arguments.oxt, arguments.output, result, headless=True
    ) as session:
        context, desktop, directory = session
        result.update(exercise(context, desktop, directory, arguments.output))
    (arguments.output / "updates.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
