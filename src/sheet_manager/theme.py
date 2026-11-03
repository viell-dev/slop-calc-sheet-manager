"""A readable list palette around Calc's document background, without UNO (#141).

Keep the native selection/text pair together when it remains distinct or the document uses the
host's field background. Only synthesise selection text when replacing the selection colour.
Adapt a faint selection from its native colour, retaining its tint rather than starting at the
document background (#167). Keep configured ordinary text when readable; otherwise use black/white
text. Borders retain their separate neutral fallback.
The document background and sheet-tab colour swatches are never adjusted.
"""

from dataclasses import dataclass


def luminance(color: int) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sum(
        linear((color >> shift) & 255) * weight
        for shift, weight in ((16, 0.2126), (8, 0.7152), (0, 0.0722))
    )


def contrast(first: int, second: int) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _valid(color: int | None) -> bool:
    return color is not None and 0 <= color <= 0xFFFFFF


def text_color(background: int, preferred: int | None) -> int:
    if preferred is not None and _valid(preferred) and contrast(background, preferred) >= 4.5:
        return preferred
    return max((0, 0xFFFFFF), key=lambda color: contrast(background, color))


def _blend(first: int, second: int, amount: float) -> int:
    return sum(
        round(((first >> shift) & 255) * (1 - amount) + ((second >> shift) & 255) * amount) << shift
        for shift in (16, 8, 0)
    )


def _edge(background: int, preferred: int | None, foreground: int) -> int:
    if preferred is not None and _valid(preferred) and contrast(background, preferred) >= 3:
        return preferred
    # The first sufficient blend keeps a divider distinct without making every
    # edge as bright as the text. The readable foreground supplies a sufficient endpoint.
    for amount in (0.25, 0.4, 0.55, 0.7, 0.85, 1):
        mixed = _blend(background, foreground, amount)
        if contrast(background, mixed) >= 3:
            return mixed
    return foreground


def _selection(background: int, preferred: int) -> int:
    # Blending toward black or white retains a native hue until the neutral endpoint is
    # necessary. Pick the readable endpoint independently of configured ordinary text.
    foreground = text_color(background, None)
    for amount in (0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1):
        mixed = _blend(preferred, foreground, amount)
        if contrast(background, mixed) >= 3:
            return mixed
    return foreground


@dataclass(frozen=True)
class Palette:
    background: int
    foreground: int
    highlight: int
    highlight_text: int
    border: int


def palette(
    background: int,
    foreground: int | None,
    highlight: int,
    highlight_text: int,
    border: int | None,
    native_background: int | None = None,
) -> Palette:
    text = text_color(background, foreground)
    keep_selection = background == native_background or contrast(background, highlight) >= 3
    selection = highlight if keep_selection else _selection(background, highlight)
    return Palette(
        background,
        text,
        selection,
        highlight_text if keep_selection else text_color(selection, highlight_text),
        _edge(background, border, text),
    )
