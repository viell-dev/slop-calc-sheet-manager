"""Generate the populated synthetic performance workbooks with a private office session."""

import argparse
import json
import sys
from pathlib import Path

from main_thread import close_after
from run import office_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/workbooks"))
    parser.add_argument("--sheets", type=int, choices=(200, 1000), nargs="+", default=[200, 1000])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = args.oxt.resolve()
    sys.path.insert(0, str(package) + "/pythonpath")
    from test_reorder import assert_references, populated_workbook

    result = {}
    try:
        with office_session(
            args.program.resolve(), package, output, result, headless=True
        ) as session:
            context, desktop, _ = session
            for count in args.sheets:
                document = populated_workbook(desktop, count)
                try:
                    assert_references(document, count)
                    destination = output / f"synthetic-{count}.ods"
                    document.storeAsURL(destination.as_uri(), ())
                    print(destination, flush=True)
                except BaseException as failure:
                    close_after(context, document, failure)
                    raise
                close_after(context, document)
    finally:
        (output / "generator-session.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
