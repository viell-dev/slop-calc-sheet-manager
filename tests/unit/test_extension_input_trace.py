"""The investigation's patched package cannot overwrite or silently alter the normal OXT."""

import zipfile
from pathlib import Path

import pytest

from tests.integration import extension_input_trace as probe


def test_private_instrumentation_preserves_normal_bytes_and_unrelated_members(
    tmp_path: Path,
) -> None:
    original = tmp_path / "normal.oxt"
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr(probe.MEMBER, "class SheetList:\n    pass\n")
        archive.writestr("description.xml", b"normal release metadata")
    before = original.read_bytes()
    diagnostic = tmp_path / "diagnostic.oxt"
    probe.instrument_package(original, diagnostic)
    assert original.read_bytes() == before
    with zipfile.ZipFile(diagnostic) as archive:
        assert set(archive.namelist()) == {probe.MEMBER, probe.PROBE_MEMBER, "description.xml"}
        assert archive.read("description.xml") == b"normal release metadata"
        source = archive.read(probe.MEMBER)
        assert source.endswith(probe.SUFFIX)
        compile(source, probe.MEMBER, "exec")
        compile(archive.read(probe.PROBE_MEMBER), probe.PROBE_MEMBER, "exec")
    with pytest.raises(ValueError, match="must not overwrite"):
        probe.instrument_package(original, original)
    with pytest.raises(FileExistsError):
        probe.instrument_package(original, diagnostic)
    with pytest.raises(ValueError, match="exactly one uninstrumented"):
        probe.instrument_package(diagnostic, tmp_path / "twice.oxt")
    assert not (tmp_path / "twice.oxt").exists()


def test_unexpected_or_already_instrumented_packages_fail_closed(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.oxt"
    with zipfile.ZipFile(wrong, "w") as archive:
        archive.writestr("unrelated.py", b"unrelated")
    with pytest.raises(ValueError, match="exactly one uninstrumented"):
        probe.instrument_package(wrong, tmp_path / "result.oxt")
    assert not (tmp_path / "result.oxt").exists()
