"""#179 reproduction attempts: public 0.0.9 -> 0.0.10 upgrade in a private profile, then the
first Calc load with Help queried before (help-first) or after (calc-first) it.

Run from the repository root with LibreOffice's bundled Python. Local evidence only: raw dumps
and traces stay under test-results/. With --cdb, a non-invasive trace is attached to the
upgraded office's soffice.bin before the first Calc load: breakpoints by RVA (no symbol loads
during the load) record Calc view construction/activation, every ScInputHandler::NotifyChange,
ForgetLastPattern, colour-configuration broadcasts and every DelayTimer firing with the
receiver's engine/state pointers; an access violation writes a full dump.
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile

root = pathlib.Path.cwd()
sys.path.insert(0, str(root / "tests/integration"))
import uno  # noqa: E402
from main_thread import close_after  # noqa: E402
from run import office_session  # noqa: E402
from sheet_list_view import names, open_list, poll  # noqa: E402
import test_help  # noqa: E402

CDB = r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"
program = pathlib.Path(r"C:\Program Files\LibreOffice\program")
identifier = "dev.viell.sheetmanager"
site = "https://viell-dev.github.io/slop-calc-sheet-manager"

# RVAs for LibreOffice 26.8.1.1 (bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1), from TDF's PDBs.
SC = {
    "VIEW-CTOR": 0xDD8250, "VIEW-DTOR": 0xDD8D40, "ACTIVATE": 0xDD0B40, "DEACTIVATE": 0xDD10C0,
    "NOTIFY": 0x804E40, "FORGET": 0x7FF370, "ENGINE": 0x7FA030, "HDL-CTOR": 0x7F99B0,
    "DELAYTIMER": 0x8059D0, "SCMOD-CFG": 0x827650,
}
MERGED = {"CC-SETTINGS-STUB": 0x1F2F6E0, "CC-NOTIFY": 0x1F2EB10}
# ScInputHandler: mpEditEngine +0x8, pActiveViewSh +0xe0, pLastState +0xf8.
# ScTabViewShell: mpInputHandler +0xa30.
OFF = {"mpEditEngine": 0x8, "pActiveViewSh": 0xE0, "pLastState": 0xF8, "mpInputHandler": 0xA30}
if os.environ.get("PROBE_RVAS"):  # Another build: RVAs and offsets resolved on this machine.
    _config = json.loads(pathlib.Path(os.environ["PROBE_RVAS"]).read_text(encoding="utf-8"))
    SC, OFF, MERGED = _config["sclo"], _config["offsets"], {}

# No spaces: cdb's $$< and .dump paths are not quoted inside command strings.
SCRATCH = pathlib.Path(os.environ["PROBE_CDB_WORK"])


def cdb_script(work: pathlib.Path) -> str:
    def bp(module, rva, text):
        return f'bp {module}+0x{rva:x} "{text}"'

    hdl = r"hdl=%p engine=%p last=%p active=%p"
    hdl_args = (
        f"@rcx, poi(@rcx+0x{OFF['mpEditEngine']:x}), poi(@rcx+0x{OFF['pLastState']:x}), "
        f"poi(@rcx+0x{OFF['pActiveViewSh']:x})"
    )
    engine = f"poi(@rcx+0x{OFF['mpEditEngine']:x})"
    view_hdl = f"poi(@rcx+0x{OFF['mpInputHandler']:x})"
    sc = [
        bp("sclo", SC["VIEW-CTOR"], r'.echotime; .printf \"VIEW-CTOR view=%p\", @rcx; .echo; gc'),
        bp("sclo", SC["VIEW-DTOR"], r'.echotime; .printf \"VIEW-DTOR view=%p\", @rcx; .echo; gc'),
        bp("sclo", SC["ACTIVATE"], r'.echotime; .printf \"ACTIVATE view=%p mdi=%x hdl=%p\", @rcx, @dl, ' + view_hdl + '; .echo; gc'),
        bp("sclo", SC["DEACTIVATE"], r'.echotime; .printf \"DEACTIVATE view=%p mdi=%x hdl=%p\", @rcx, @dl, ' + view_hdl + '; .echo; kc 14; gc'),
        # Stack for a call without a state or on a handler that has no edit engine yet: the
        # latter is the call that can arm DelayTimer before the engine exists.
        bp("sclo", SC["NOTIFY"], r'.echotime; .printf \"NOTIFY ' + hdl + r' state=%p force=%x src=%p\", ' + hdl_args + r', @rdx, @r8b, @r9; .echo; .if ((@rdx == 0) | (' + engine + r' == 0)) { kc 14 }; gc'),
        bp("sclo", SC["FORGET"], r'.echotime; .printf \"FORGET ' + hdl + r'\", ' + hdl_args + r'; .echo; kc 14; gc'),
        bp("sclo", SC["ENGINE"], r'.echotime; .printf \"ENGINE-CREATE ' + hdl + r'\", ' + hdl_args + r'; .echo; gc'),
        bp("sclo", SC["HDL-CTOR"], r'.echotime; .printf \"HDL-CTOR hdl=%p\", @rcx; .echo; gc'),
        bp("sclo", SC["DELAYTIMER"], r'.echotime; .printf \"DELAYTIMER ' + hdl + r'\", ' + hdl_args + r'; .echo; kc 14; gc'),
        bp("sclo", SC["SCMOD-CFG"], r'.echotime; .printf \"SCMOD-CONFIGURATION-CHANGED broadcaster=%p hints=%x\", @rdx, @r8d; .echo; kc 14; gc'),
    ]
    merged = [] if not MERGED else [
        bp("mergedlo", MERGED["CC-SETTINGS-STUB"], r'.echotime; .printf \"COLORCONFIG-DATACHANGED-EVENT\"; .echo; kc 10; gc'),
        bp("mergedlo", MERGED["CC-NOTIFY"], r'.echotime; .printf \"COLORCONFIG-NOTIFY\"; .echo; kc 10; gc'),
    ]
    # Forward slashes: CDB reads backslashes in quoted command strings as escapes. Run
    # 44212422194 lost its sclo.dll command file that way (D:\a\_temp) and CDB then held the
    # office stopped until the job's time limit.
    dump = (work / "cdb-av-full.dmp").as_posix()
    dump2 = (work / "cdb-av2-full.dmp").as_posix()
    lines = [
        "sxi eh", "sxi ct", "sxi et", "sxi ld", "sxi ud", "sxi out",
        f'sxe -c ".echotime; .echo FIRST-CHANCE-AV; r; kn 40; .dump /ma {dump}; gn" '
        f'-c2 ".echotime; .echo SECOND-CHANCE-AV; kn 40; .dump /ma {dump2}; q" av',
        "lm m mergedlo",
        *(merged if MERGED else []),
    ]
    # sclo.dll is loaded by the first Calc document; its breakpoints are set on its load event.
    (work / "sclo-breakpoints.txt").write_text(
        "lm m sclo\n" + "\n".join(sc) + "\n", encoding="utf-8"
    )
    (work / "sclo-load.txt").write_text(
        (work / "sclo-breakpoints.txt").read_text(encoding="utf-8") + "gc\n", encoding="utf-8"
    )
    lines.append(f'sxe -c "$$< {(work / "sclo-load.txt").as_posix()}" ld:sclo.dll')
    lines += [".echo READY", ".echotime", "g"]
    return "\n".join(lines) + "\n"


def soffice_bin_pid(profile: pathlib.Path) -> int:
    marker = profile.as_uri()
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='soffice.bin'\" | "
        "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
    )
    output = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60
    ).stdout
    matches = [line.split("|", 1)[0] for line in output.splitlines() if marker in line]
    assert len(matches) == 1, (marker, output)
    return int(matches[0])


def sclo_loaded(pid: int) -> bool:
    command = f"(Get-Process -Id {pid}).Modules | Where-Object ModuleName -eq 'sclo.dll' | Measure-Object | ForEach-Object Count"
    output = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60
    ).stdout.strip()
    return output not in ("", "0")


def attach(profile: pathlib.Path, directory: pathlib.Path, record: dict) -> subprocess.Popen:
    pid = soffice_bin_pid(profile)
    record["soffice_bin_pid"] = pid
    loaded = sclo_loaded(pid)
    record["sclo_loaded_before_attach"] = loaded
    work = SCRATCH / f"{directory.parent.name}-{directory.name}"
    work.mkdir(parents=True)
    record["cdb_work"] = str(work)
    script = cdb_script(work)
    if loaded:
        script = script.replace(
            ".echo READY", f"$< {(work / 'sclo-breakpoints.txt').as_posix()}\n.echo READY", 1)
    (directory / "cdb-script.txt").write_text(script, encoding="utf-8")
    log = directory / "cdb.log"
    process = subprocess.Popen(
        [CDB, "-p", str(pid), "-G", "-y", "", "-cf", str(directory / "cdb-script.txt"),
         "-logo", str(log)],
        # No input: at an unexpected break CDB reads end of input and exits instead of holding
        # the office stopped.
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if log.exists() and "READY" in log.read_text(encoding="utf-8", errors="replace"):
            record["cdb_ready_at"] = time.time()
            return process
        if process.poll() is not None:
            raise RuntimeError("cdb exited before READY")
        time.sleep(0.2)
    raise TimeoutError("cdb did not become ready")


def machine_load() -> dict:
    command = (
        "$os = Get-CimInstance Win32_OperatingSystem; "
        r"$cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1)"
        ".CounterSamples.CookedValue; "
        "'{0} {1}' -f [int]($os.FreePhysicalMemory/1024), [int]$cpu"
    )
    output = subprocess.run(["pwsh", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=60).stdout.split()
    return {"free_mb": int(output[0]), "cpu_percent": int(output[1])} if len(output) == 2 else {}


def installed(context):
    manager = context.getValueByName("/singletons/com.sun.star.deployment.ExtensionManager")
    found = [x for x in manager.getDeployedExtensions("user", None, None)
             if x.getIdentifier().Value == identifier]
    assert len(found) == 1
    return found[0]


def panel(context, desktop, url, expected, phases):
    phases.append(("load-start", time.time()))
    doc = desktop.loadComponentFromURL(url, "_blank", 0, ())
    phases.append(("load-returned", time.time()))
    try:
        _, tree = open_list(context, doc)
        poll(lambda: len(names(tree)) == expected, "the installed public package's rows")
        assert len(doc.Sheets.ElementNames) == expected
        phases.append(("rows-shown", time.time()))
    except BaseException as error:
        close_after(context, doc, error)
        raise
    close_after(context, doc)
    phases.append(("closed", time.time()))


CASE_LIMIT = 600  # Seconds; a healthy case takes a few minutes on the hosted runner.


def start_watchdog(profile: pathlib.Path, record: dict, debugger: list) -> threading.Timer:
    """Stop a stuck case's own processes so the next case runs; the record says it happened."""

    def fire():
        record["watchdog_fired_at"] = time.time()
        for process in debugger:
            process.kill()
        marker = profile.as_uri().replace("'", "''")
        command = (
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
            f"'*{marker}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force; $_.Name }}"
        )
        record["watchdog_stopped"] = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60
        ).stdout.split()

    timer = threading.Timer(CASE_LIMIT, fire)
    timer.daemon = True
    timer.start()
    return timer


def run_case(out: pathlib.Path, order: str, use_cdb: bool, assets: pathlib.Path) -> dict:
    record: dict = {"order": order, "cdb": use_cdb, "phases": [], "load_at_start": machine_load()}
    phases = record["phases"]
    old, new = assets / "sheet-manager-0.0.9.oxt", assets / "sheet-manager-0.0.10.oxt"
    fixture = out / f"fixture-{out.name}.fods"
    shutil.copyfile(assets / "manual.fods", fixture)
    cdb = None
    debugger: list = []
    watchdog = None
    try:
        with tempfile.TemporaryDirectory(prefix="sheet-manager-public-upgrade-") as directory:
            profile = pathlib.Path(directory) / "profile"
            watchdog = start_watchdog(profile, record, debugger)
            for name in ("before", "after"):
                (out / name).mkdir()
                record[name] = {}
            # Same command as office_session's own install, with a longer limit: on this
            # loaded laptop a fresh-profile `unopkg add` has exceeded office_session's 90 s.
            started = time.time()
            result = subprocess.run([str(program / "unopkg.exe"),
                                     "-env:UserInstallation=" + profile.as_uri(),
                                     "add", str(old)],
                                    capture_output=True, text=True, timeout=600)
            record["old_install_seconds"] = round(time.time() - started, 1)
            (out / "old-install.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            assert result.returncode == 0, result.stdout + result.stderr
            with office_session(program, None, out / "before", record["before"], headless=True,
                                profile_directory=profile, startup_attempts=3) as session:
                context, desktop, _ = session
                package = installed(context)
                assert package.getVersion() == "0.0.9"
                panel(context, desktop, "private:factory/scalc", 1, phases)
            started = time.time()
            result = subprocess.run([str(program / "unopkg.exe"),
                                     "-env:UserInstallation=" + profile.as_uri(),
                                     "add", "--force", str(new)],
                                    capture_output=True, text=True, timeout=600)
            record["upgrade_seconds"] = round(time.time() - started, 1)
            (out / "upgrade-install.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            assert result.returncode == 0, result.stdout + result.stderr
            with office_session(program, None, out / "after", record["after"], headless=True,
                                profile_directory=profile, startup_attempts=3) as session:
                context, desktop, temporary = session
                if use_cdb:
                    cdb = attach(profile, out, record)
                    debugger.append(cdb)
                package = installed(context)
                assert package.getVersion() == "0.0.10" and package.checkDependencies(None)
                location_service = context.getValueByName(
                    "/singletons/com.sun.star.deployment.PackageInformationProvider")
                location = pathlib.Path(uno.fileUrlToSystemPath(
                    location_service.getPackageLocation(identifier))).resolve()
                with zipfile.ZipFile(new) as archive:
                    for name in archive.namelist():
                        assert (location / name).read_bytes() == archive.read(name), name
                    record["after"]["verified_payload_files"] = len(archive.namelist())
                if order == "help-first":
                    phases.append(("help-start", time.time()))
                    record["after"]["help"] = test_help.exercise(context, desktop, temporary, out / "after")
                    phases.append(("help-done", time.time()))
                panel(context, desktop, fixture.resolve().as_uri(), 60, phases)
                if order == "calc-first":
                    phases.append(("help-start", time.time()))
                    record["after"]["help"] = test_help.exercise(context, desktop, temporary, out / "after")
                    phases.append(("help-done", time.time()))
        record["assertions_passed"] = True
    except BaseException:
        record["failure"] = traceback.format_exc()
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if cdb is not None:
            try:
                cdb.wait(timeout=60)
            except subprocess.TimeoutExpired:
                cdb.kill()
            record["cdb_exit"] = cdb.returncode
            work = pathlib.Path(record["cdb_work"])
            for dump in work.glob("*.dmp"):
                shutil.move(str(dump), str(out / dump.name))
        (out / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--plan", required=True, help="comma list of order[:cdb]")
    a = parser.parse_args()
    base = a.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    summary = []
    for index, item in enumerate(a.plan.split(",")):
        order, _, mode = item.partition(":")
        out = base / f"{index:02d}-{order}{'-cdb' if mode == 'cdb' else ''}"
        out.mkdir()
        started = time.time()
        record = run_case(out, order, mode == "cdb", a.assets.resolve())
        dumps = record.get("after", {}).get("office_crash_dumps", [])
        trace = ((out / "cdb.log").read_text(encoding="utf-8", errors="replace")
                 if (out / "cdb.log").exists() else "")
        crashed = bool(dumps) or "FIRST-CHANCE-AV" in trace
        line = {"case": out.name, "passed": bool(record.get("assertions_passed")),
                "crash": crashed, "seconds": round(time.time() - started, 1),
                "traced": {key: len(re.findall(rf"^{key}", trace, re.M)) for key in (
                    "VIEW-CTOR", "ACTIVATE", "DEACTIVATE", "NOTIFY", "FORGET", "DELAYTIMER",
                    "ENGINE-CREATE", "SCMOD-CONFIGURATION-CHANGED")} if trace else None}
        summary.append(line)
        print(json.dumps(line), flush=True)
        (base / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
