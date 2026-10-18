"""Translation boundary shared by generated metadata and future UI controls."""


def tr(message: str) -> str:
    """Return the English source text until packaged translations are available.

    Keep messages literal at call sites so a future catalogue extractor can find them.
    Configuration templates currently render English only. Translated metadata will
    need per-locale XML/XCU elements and description files, not single-string replacement.
    """
    return message
