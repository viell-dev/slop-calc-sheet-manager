"""Translation boundary shared by generated metadata and future UI controls."""


def tr(message: str) -> str:
    """Return the English source text until packaged translations are available.

    Keep messages literal at call sites so a future catalogue extractor can find them.
    Configuration templates use {{message}} and are rendered through this same helper.
    """
    return message
