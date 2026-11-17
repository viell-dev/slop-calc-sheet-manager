"""Research only (#179): resolve this office build's Calc symbols to RVAs on the runner.

Starts a private headless office, loads a blank Calc document so sclo.dll is loaded, then
attaches CDB non-invasively with TDF's symbol server and records the RVAs and member offsets
that probe179.py needs, so its live breakpoints load no symbols during the measured load.
"""
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path.cwd() / "tests/integration"))
from main_thread import close_after  # noqa: E402
from run import office_session  # noqa: E402

CDB = r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"
NAMES = {
    "VIEW-CTOR": "ScTabViewShell::ScTabViewShell", "VIEW-DTOR": "ScTabViewShell::~ScTabViewShell",
    "ACTIVATE": "ScTabViewShell::Activate", "DEACTIVATE": "ScTabViewShell::Deactivate",
    "NOTIFY": "ScInputHandler::NotifyChange", "FORGET": "ScInputHandler::ForgetLastPattern",
    "ENGINE": "ScInputHandler::ImplCreateEditEngine", "HDL-CTOR": "ScInputHandler::ScInputHandler",
    "DELAYTIMER": "ScInputHandler::LinkStubDelayTimer", "SCMOD-CFG": "ScModule::ConfigurationChanged",
}
out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
symbols = sys.argv[2]
program = pathlib.Path(r"C:\Program Files\LibreOffice\program")
record = {}
with office_session(program, None, out, record, headless=True) as (context, desktop, _):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        pids = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='soffice.bin'\").ProcessId"],
            capture_output=True, text=True, timeout=60).stdout.split()
        assert len(pids) == 1, pids
        commands = ["lm m sclo"] + [f"x sclo!{name}" for name in NAMES.values()] + [
            "dt sclo!ScInputHandler mpEditEngine pActiveViewSh pLastState",
            "dt sclo!ScTabViewShell mpInputHandler", "q"]
        result = subprocess.run([CDB, "-pv", "-p", pids[0], "-y", symbols,
                                 "-c", ".reload /f sclo.dll; " + "; ".join(commands)],
                                capture_output=True, text=True, timeout=1800)
        (out / "cdb-resolve.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    finally:
        close_after(context, document)
text = (out / "cdb-resolve.log").read_text(encoding="utf-8")
base = int(re.search(r"^([0-9a-f]{8}`[0-9a-f]{8})\s+[0-9a-f`]+\s+sclo\b", text, re.M)
           .group(1).replace("`", ""), 16)
rvas = {}
for key, name in NAMES.items():
    pattern = re.compile(r"^([0-9a-f]{8}`[0-9a-f]{8}) sclo!" + re.escape(name) + r" \(", re.M)
    found = [m for m in pattern.finditer(text)]
    assert found, name
    rvas[key] = int(found[0].group(1).replace("`", ""), 16) - base
offsets = {name: int(value, 16) for value, name in
           re.findall(r"\+0x([0-9a-f]+) (mpEditEngine|pActiveViewSh|pLastState|mpInputHandler)\b",
                      text)}
config = {"sclo": rvas, "offsets": offsets}
(out / "rvas.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"sclo": {k: hex(v) for k, v in rvas.items()},
                  "offsets": {k: hex(v) for k, v in offsets.items()}}, indent=2))
