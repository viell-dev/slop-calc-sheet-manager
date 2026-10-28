"""Translation boundary shared by generated metadata and future UI controls.

Python UI strings go through `tr`. Metadata templates use `{{message}}`, which `tools/build.py`
renders as English through it. That renderer supports only English: adding the first translation
catalogue must also replace it with locale-aware XML/XCU element generation and per-locale
description files. Keep English as the fallback.
"""


def tr(message: str) -> str:
    """Return the English source text until packaged translations are available.

    Keep messages literal at call sites so a future catalogue extractor can find them.
    Configuration templates currently render English only. Translated metadata will
    need per-locale XML/XCU elements and description files, not single-string replacement.
    """
    return message
