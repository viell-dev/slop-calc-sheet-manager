"""A readable list palette around Calc's document background, without UNO (#141).

Keep a configured text or UI colour when it remains readable on its background. Otherwise use
black/white text and neutral edges. The document background itself is never adjusted. Tab-colour
swatches remain the sheet's own colours, outside this palette.
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


def _edge(background: int, preferred: int | None, foreground: int) -> int:
    if preferred is not None and _valid(preferred) and contrast(background, preferred) >= 3:
        return preferred
    # The first sufficient blend keeps a divider or selection distinct without making every
    # edge as bright as the text. A black/white foreground always supplies a sufficient endpoint.
    for amount in (0.25, 0.4, 0.55, 0.7, 0.85, 1):
        mixed = sum(
            round(
                ((background >> shift) & 255) * (1 - amount)
                + ((foreground >> shift) & 255) * amount
            )
            << shift
            for shift in (16, 8, 0)
        )
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
) -> Palette:
    text = text_color(background, foreground)
    selection = _edge(background, highlight, text)
    return Palette(
        background,
        text,
        selection,
        text_color(selection, highlight_text),
        _edge(background, border, text),
    )
