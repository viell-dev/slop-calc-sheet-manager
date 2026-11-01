"""Retain existing public-UNO observations at a failed input poll (#160).

Record only values the fixture already read or posted: never make a UNO call, add a wait or
retry input here. The bounded trace is diagnostic evidence, not a history of sheet identities.
Failure to write diagnostics must preserve the original assertion.
"""

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

_entries: deque[dict[str, Any]] = deque(maxlen=400)
_path: Path | None = None
_started = 0.0


def configure(path: Path) -> None:
    global _path, _started
    _path, _started = path, time.monotonic()
    _entries.clear()


def record(kind: str, window: int, **values: Any) -> None:
    if _path is not None:
        _entries.append(
            {"seconds": time.monotonic() - _started, "kind": kind, "window": window, **values}
        )


def retain(failure: BaseException) -> None:
    if _path is None:
        return
    try:
        _path.write_text(
            json.dumps({"failure": str(failure), "events": list(_entries)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        failure.add_note(f"Retaining input observations also failed: {error!r}")
