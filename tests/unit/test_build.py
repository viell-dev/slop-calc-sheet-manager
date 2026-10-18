"""Validate the actual package, including its deployment and localization contracts."""

import hashlib
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tools.build import DESCRIPTION_NS, ROOT, build, render, version

OOR = "{http://openoffice.org/2001/registry}"


def test_two_builds_are_identical_and_allowlisted(tmp_path: Path) -> None:
    first = build(tmp_path / "first")
    second = build(tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()
    assert first.with_suffix(".oxt.sha256").read_text() == (
        f"{hashlib.sha256(first.read_bytes()).hexdigest()}  {first.name}\n"
    )
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert set(names) == {
            "description.xml",
            "description-en.txt",
            "META-INF/manifest.xml",
            "Factories.xcu",
            "Sidebar.xcu",
            "sheet-manager.components",
            "registration.py",
            "icons/deck.svg",
            "LICENSE.txt",
            "pythonpath/sheet_manager/__init__.py",
            "pythonpath/sheet_manager/i18n.py",
            "pythonpath/sheet_manager/reorder.py",
            "pythonpath/sheet_manager/uno_panel.py",
            "pythonpath/sheet_manager/uno_reorder.py",
        }
        for member in archive.infolist():
            assert member.date_time == (2000, 1, 1, 0, 0, 0)
            assert member.external_attr >> 16 == 0o100644
            assert member.compress_type == zipfile.ZIP_STORED
            if member.filename.endswith((".xml", ".xcu", ".txt")):
                assert b"{{" not in archive.read(member)
        assert archive.read("LICENSE.txt") == (ROOT / "LICENSE").read_bytes()


def test_metadata_and_registration_agree(tmp_path: Path) -> None:
    with zipfile.ZipFile(build(tmp_path)) as archive:
        description = ET.fromstring(archive.read("description.xml"))
        identifier = description.find(f"{DESCRIPTION_NS}identifier")
        assert identifier is not None and identifier.attrib["value"] == "dev.viell.sheetmanager"
        dependency = description.find(
            f"{DESCRIPTION_NS}dependencies/"
            "{http://libreoffice.org/extensions/description/2011}LibreOffice-minimal-version"
        )
        assert dependency is not None and dependency.attrib["value"] == "26.2.1"
        assert version() == "0.0.1"
        assert description.findtext(f"{DESCRIPTION_NS}display-name/{DESCRIPTION_NS}name") == (
            "Sheet Manager"
        )
        manifest = ET.fromstring(archive.read("META-INF/manifest.xml"))
        manifest_ns = "{http://openoffice.org/2001/manifest}"
        entries = {
            n.attrib[f"{manifest_ns}full-path"]: n.attrib[f"{manifest_ns}media-type"]
            for n in manifest
        }
        assert entries["sheet-manager.components"] == "application/vnd.sun.star.uno-components"
        assert "registration.py" not in entries  # Passive registration, not executable discovery.
        assert set(entries) <= set(archive.namelist())
        components = ET.fromstring(archive.read("sheet-manager.components"))
        namespace = "{http://openoffice.org/2010/uno-components}"
        component = components.find(f"{namespace}component")
        assert component is not None
        assert component.attrib == {
            "loader": "com.sun.star.loader.Python",
            "uri": "registration.py",
        }
        implementation = component.find(f"{namespace}implementation")
        assert implementation is not None
        factory_name = implementation.attrib["name"]
        factories = ET.fromstring(archive.read("Factories.xcu"))
        assert (
            factories.findtext(f".//prop[@{OOR}name='FactoryImplementation']/value") == factory_name
        )
        sidebar = ET.fromstring(archive.read("Sidebar.xcu"))
        assert sidebar.findtext(f".//prop[@{OOR}name='TitleBarIsOptional']/value") == "true"
        assert sidebar.findtext(f".//prop[@{OOR}name='ShowForReadOnlyDocument']/value") == "true"
        assert {n.text for n in sidebar.findall(f".//prop[@{OOR}name='ContextList']/value")} == {
            "Calc, any, visible ;"
        }


def test_translation_rendering_escapes_xml() -> None:
    assert render("{{Sheets & panels}}", xml=True) == "Sheets &amp; panels"
    assert render("{{Sheets & panels}}", xml=False) == "Sheets & panels"


def test_pure_package_does_not_import_uno() -> None:
    code = (
        "import sys; sys.path.insert(0, 'src'); "
        "from sheet_manager.i18n import tr; assert tr('Sheet Manager') == 'Sheet Manager'; "
        "from sheet_manager import reorder; assert reorder.Sheet('A').name == 'A'; "
        "assert 'uno' not in sys.modules; assert 'unohelper' not in sys.modules"
    )
    subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, check=True)
