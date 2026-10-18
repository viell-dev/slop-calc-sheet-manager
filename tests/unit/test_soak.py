"""An unreadable session result must fail the soak without losing later measurements."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "posix", reason="The soak runs only inside the Linux test image")
@pytest.mark.parametrize("failure", ["truncated", "unreadable", "missing"])
def test_soak_continues_after_unreadable_results(tmp_path: Path, failure: str) -> None:
    shutil.copyfile(ROOT / "tests/integration/soak.py", tmp_path / "soak.py")
    (tmp_path / "run.py").write_text(
        "import json, pathlib, sys\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "result = output / 'results.json'\n"
        "if output.name == '001' and '--without-extension' not in sys.argv:\n"
        f"    failure = {failure!r}\n"
        "    if failure == 'truncated':\n"
        "        result.write_text('[{')\n"
        "    elif failure == 'unreadable':\n"
        "        result.mkdir()\n"
        "else:\n"
        "    result.write_text(json.dumps([{'assertions_passed': True, 'office_exit_code': 0}]))\n",
        encoding="utf-8",
    )
    output = tmp_path / "results"
    process = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "soak.py"),
            "--program",
            str(tmp_path),
            "--oxt",
            str(tmp_path / "synthetic.oxt"),
            "--output",
            str(output),
            "--soak",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 1, process.stdout + process.stderr
    rows = json.loads((output / "soak-results.json").read_text(encoding="utf-8"))
    assert [(row["mode"], row["session"]) for row in rows] == [
        ("installed", 1),
        ("installed", 2),
        ("absent", 1),
        ("absent", 2),
    ]
    assert rows[0]["runner_exit"] == 0  # A bad result fails even if the runner exited zero.
    assert rows[0]["results"] is None
    assert rows[0]["results_error"]
    assert all(row["results_error"] is None for row in rows[1:])
    assert all(row["results"][0]["assertions_passed"] for row in rows[1:])
    summary = (output / "soak-summary.md").read_text(encoding="utf-8")
    assert rows[0]["results_error"] in summary
    assert "| absent | 2 | 0 |" in summary
