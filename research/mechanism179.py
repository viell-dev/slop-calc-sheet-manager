"""Research only (#179): is ScInputHandler::DelayTimer's null-engine crash reachable without
Sheet Manager, through public UNO alone?

Mechanism read from the pinned source (sc/source/ui/app/inputhdl.cxx): a view's ScInputHandler
creates its EditEngine only in NotifyChange when a Calc view is current or supplied. NotifyChange
without one (ScModule::ConfigurationChanged -> ForgetLastPattern, or ScTabViewShell::Deactivate)
starts the 500 ms DelayTimer; when it fires with no last state, DelayTimer calls
mpEditEngine->SetTextCurrentDefaults with no presence check. A view that was never activated
has no engine, so the timer would dereference null.

Each case runs in a fresh private headless office with NO extension installed and loads a copy
of the synthetic FODS. Orders:
  hidden-scheme   load with Hidden=True, then switch the colour scheme (ColorConfig broadcast)
  visible-scheme  same with a visible load (control: the view was activated)
  hidden-idle     load with Hidden=True and change nothing (control: the trigger matters)
With :cdb, probe179's non-invasive trace records NotifyChange, engine creation and every
DelayTimer firing with the receiver's engine pointer; an access violation writes a full dump that
the workflow analyses on the runner and deletes. Run from the repository root with LibreOffice's
bundled Python.
"""

import argparse
import json
import pathlib
import re
import shutil
import sys
import tempfile
import time
import traceback

root = pathlib.Path.cwd()
sys.path.insert(0, str(root / "tests/integration"))
sys.path.insert(0, str(root / "research"))
import uno  # noqa: E402
from com.sun.star.beans import PropertyValue  # noqa: E402
from main_thread import close_after  # noqa: E402
from run import office_session  # noqa: E402
import probe179  # noqa: E402

program = pathlib.Path(r"C:\Program Files\LibreOffice\program")
SCHEMES = ("COLOR_SCHEME_LIBREOFFICE_LIGHT", "COLOR_SCHEME_LIBREOFFICE_DARK")


def prop(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


def switch_scheme(context, scheme):
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", context)
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess",
        (prop("nodepath", "/org.openoffice.Office.UI/ColorScheme"),))
    before = access.getPropertyValue("CurrentColorScheme")
    access.setPropertyValue("CurrentColorScheme", scheme)
    access.commitChanges()
    return before


def alive(desktop):
    desktop.getComponents().hasElements()  # Any remote call fails once the office crashed.
    return True


def run_case(out, order, use_cdb, fixture_source):
    record = {"order": order, "cdb": use_cdb, "phases": [], "load_at_start": probe179.machine_load()}
    phases = record["phases"]
    fixture = out / f"fixture-{out.name}.fods"
    shutil.copyfile(fixture_source, fixture)
    cdb = None
    debugger: list = []
    watchdog = None
    try:
        with tempfile.TemporaryDirectory(prefix="sheet-manager-mechanism-") as directory:
            profile = pathlib.Path(directory) / "profile"
            watchdog = probe179.start_watchdog(profile, record, debugger)
            (out / "office").mkdir()
            record["office"] = {}
            with office_session(program, None, out / "office", record["office"], headless=True,
                                profile_directory=profile, startup_attempts=3) as session:
                context, desktop, _ = session
                if use_cdb:
                    cdb = probe179.attach(profile, out, record)
                    debugger.append(cdb)
                hidden = order.startswith("hidden")
                phases.append(("load-start", time.time()))
                doc = desktop.loadComponentFromURL(
                    fixture.resolve().as_uri(), "_blank", 0, (prop("Hidden", hidden),))
                phases.append(("load-returned", time.time()))
                try:
                    assert len(doc.Sheets.ElementNames) == 60
                    if order.endswith("-scheme"):
                        record["scheme_before"] = switch_scheme(context, SCHEMES[0])
                        phases.append(("scheme-switched", time.time()))
                    # DelayTimer fires 500 ms after it is started; wait well past it.
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        alive(desktop)
                        time.sleep(0.25)
                    phases.append(("alive-after-5s", time.time()))
                    if order.endswith("-scheme"):
                        switch_scheme(context, record["scheme_before"])
                        time.sleep(2)
                        alive(desktop)
                        phases.append(("scheme-restored-alive", time.time()))
                except BaseException as error:
                    close_after(context, doc, error)
                    raise
                close_after(context, doc)
                phases.append(("closed", time.time()))
        record["assertions_passed"] = True
    except BaseException:
        record["failure"] = traceback.format_exc()
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if cdb is not None:
            try:
                cdb.wait(timeout=60)
            except Exception:
                cdb.kill()
            record["cdb_exit"] = cdb.returncode
            for dump in pathlib.Path(record["cdb_work"]).glob("*.dmp"):
                shutil.move(str(dump), str(out / dump.name))
        (out / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=pathlib.Path, required=True)
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
        record = run_case(out, order, mode == "cdb", a.fixture.resolve())
        dumps = record.get("office", {}).get("office_crash_dumps", [])
        trace = ((out / "cdb.log").read_text(encoding="utf-8", errors="replace")
                 if (out / "cdb.log").exists() else "")
        line = {"case": out.name, "passed": bool(record.get("assertions_passed")),
                "crash": bool(dumps) or "FIRST-CHANCE-AV" in trace,
                "seconds": round(time.time() - started, 1),
                "delaytimer_engines": re.findall(r"^DELAYTIMER hdl=\S+ engine=(\S+)", trace, re.M),
                "traced": {key: len(re.findall(rf"^{key}", trace, re.M)) for key in (
                    "VIEW-CTOR", "ACTIVATE", "DEACTIVATE", "NOTIFY", "FORGET", "DELAYTIMER",
                    "ENGINE-CREATE", "SCMOD-CONFIGURATION-CHANGED")} if trace else None}
        summary.append(line)
        print(json.dumps(line), flush=True)
        (base / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
