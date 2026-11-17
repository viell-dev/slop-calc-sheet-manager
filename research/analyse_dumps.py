"""Research only: print every retained dump's stacks with TDF's symbols, then delete the dump.

Raw dumps never leave the runner. For the probe's CDB full dumps, the last DelayTimer receiver
recorded in the neighbouring cdb.log is also expanded.
"""
import pathlib
import re
import subprocess
import sys

root, symbols, cdb = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
for dump in sorted(root.rglob("*.dmp")):
    commands = [".ecxr", "kvn 40", "~*kc 40"]
    log = dump.parent / "cdb.log"
    if log.exists():
        found = re.findall(r"DELAYTIMER hdl=([0-9a-f`]+)", log.read_text("utf-8", "replace"))
        if found:
            address = found[-1].replace("`", "")
            commands += [f"dx -r1 ((sclo!ScInputHandler*)0x{address})",
                         f"dx -r1 ((sclo!ScInputHandler*)0x{address})->pActiveViewSh"]
    result = subprocess.run([cdb, "-z", str(dump), "-y", symbols, "-c", "; ".join(commands + ["q"])],
                            capture_output=True, text=True, timeout=3000)
    dump.with_suffix(".stacks.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    dump.unlink()
    print("analysed and removed", dump)
