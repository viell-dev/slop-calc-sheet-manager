"""Retain existing public-UNO observations at a failed input poll (#160).

Record scalars from existing fixture reads/posts or native event callbacks: never make a UNO
call, add a wait or retry input here. The bounded trace is diagnostic evidence, not a history of
sheet identities. Detailed failure-only state is supplied by the caller after its poll fails.
Failure to write diagnostics must preserve the original assertion.
Proxy IDs distinguish retained test proxies only; they are not native window identities.
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
            {
                "seconds": time.monotonic() - _started,
                "kind": kind,
                "window_proxy_id": window,
                **values,
            }
        )


def events_for(window: int) -> list[dict[str, Any]]:
    return [entry for entry in list(_entries) if entry["window_proxy_id"] == window]


def retain(failure: BaseException, details: object = None) -> None:
    if _path is None:
        return
    try:
        _path.write_text(
            json.dumps(
                {
                    "failure": str(failure),
                    "failure_notes": getattr(failure, "__notes__", []),
                    "events": list(_entries),
                    "details": details,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        failure.add_note(f"Retaining input observations also failed: {error!r}")
