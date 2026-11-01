"""Fixed paired investigation of the initial theme pick (#160), never release evidence.

Each case has a fresh office/profile and repeats the normal panel/accessibility/adapter prefix.
ABBA twice compares the original path with scalar mouse/selection observers. Retain every
outcome; an expected initial-pick assertion allows the remaining measurements, then fails the
whole command. Unexpected failures or unclean shutdowns stop the experiment. No input is retried.
"""

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import run as integration
from extension_input_trace import instrument_package
from input_trace import configure

MODES = (False, True, True, False, False, True, True, False)
INITIAL_PICK_FAILURE = "Timed out waiting for the independent Bravo pick"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", required=True, type=Path)
    parser.add_argument("--oxt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    package = arguments.oxt.resolve()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_checksum = hashlib.sha256(package.read_bytes()).hexdigest()
    diagnostic_package = output / "extension-input-probe.oxt"
    instrument_package(package, diagnostic_package)
    package = diagnostic_package
    sys.path.insert(0, str(package) + "/pythonpath")
    import test_accessibility
    import test_adapter_failures
    import test_document_theme

    cases: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "investigation_only": True,
        "run_complete": False,
        "assertions_passed": False,
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "source_package_sha256": source_checksum,
        "diagnostic_package": package.name,
        "planned_observer_modes": MODES,
        "cases": cases,
    }

    def save():
        (output / "probe-results.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    save()
    for index, observed in enumerate(MODES, 1):
        directory = output / f"case-{index}-{'observed' if observed else 'original'}"
        directory.mkdir(parents=True, exist_ok=True)
        case: dict[str, Any] = {"case": index, "observed": observed, "assertions_passed": False}
        cases.append(case)
        print(f"theme-pick investigation: case {index}, observed={observed}", flush=True)
        configure(directory / "input-observations.json")
        try:
            with integration.office_session(
                arguments.program.resolve(), package, directory, case, headless=True
            ) as (context, desktop, profile):
                case["panel"] = integration.exercise(
                    context, desktop, profile, directory, screenshot=False
                )
                case["accessibility"] = test_accessibility.exercise(
                    context, desktop, profile, directory, headless=True
                )
                case["adapter_failures"] = test_adapter_failures.exercise(
                    context, desktop, profile, directory
                )
                # Keep this case's theme events even if the earlier control filled the buffer.
                configure(directory / "input-observations.json")
                try:
                    case["theme"] = test_document_theme.check_document_colors(
                        context, desktop, trace_input=observed
                    )
                except AssertionError as failure:
                    if str(failure) != INITIAL_PICK_FAILURE:
                        raise
                    case["failure"] = traceback.format_exc()
                else:
                    case["assertions_passed"] = True
        except BaseException:
            case["assertions_passed"] = False
            case["unexpected_failure"] = traceback.format_exc()
            raise
        finally:
            save()
    result["run_complete"] = True
    result["assertions_passed"] = all(case["assertions_passed"] for case in cases)
    save()
    if not result["assertions_passed"]:
        raise AssertionError("Initial theme pick failed; all eight case outcomes are retained")
    print("All eight theme-pick cases passed; the older failure remains unclassified", flush=True)


if __name__ == "__main__":
    main()
