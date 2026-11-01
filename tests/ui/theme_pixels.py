"""Check independently captured native label and empty-space pixels for #141.

Run with the test display's system Python/Pillow, never in LibreOffice's Python environment.
The fixture has three short rows with the second picked, so label glyphs, full-width backgrounds,
row dividers and unused space can be checked independently of the extension's painter.
"""

import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def foreground_pixel(
    pixel: Sequence[int], foreground: Sequence[int], background: Sequence[int]
) -> bool:
    """A glyph's strong antialiased coverage of its foreground over this background."""
    direction = [f - b for f, b in zip(foreground, background, strict=True)]
    length = sum(value * value for value in direction)
    if not length:
        return False
    amount = (
        sum((p - b) * delta for p, b, delta in zip(pixel, background, direction, strict=True))
        / length
    )
    return 0.5 <= amount <= 1.01 and all(
        abs(p - (b + amount * delta)) <= 3
        for p, b, delta in zip(pixel, background, direction, strict=True)
    )


def check(path: Path) -> dict[str, int]:
    Image = importlib.import_module("PIL.Image")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["foreground"] == data["expected_foreground"], "configured or readable text colour"
    image = Image.open(path.with_suffix(".png")).convert("RGB")
    left, top = data["offset"]

    def rgb(color):
        return tuple((color >> shift) & 255 for shift in (16, 8, 0))

    def pixel(x, y):
        return image.getpixel((left + x, top + y))

    glyphs = []
    for index, row in enumerate(data["rows"]):
        picked = index == 1
        background = rgb(data["highlight"] if picked else data["background"])
        foreground = rgb(data["highlight_text"] if picked else data["foreground"])
        y = row["y"] + row["height"] // 2
        # Beyond the short label, still well inside the native content area.
        assert pixel(data["width"] - 30, y) == background, ("full-width background", index)
        x1, x2 = max(35, row["x"]), min(data["width"] - 35, row["x"] + row["width"])
        pixels = [
            pixel(x, y)
            for y in range(row["y"] + 2, row["y"] + row["height"] - 2)
            for x in range(x1, x2)
        ]
        # GTK's thin font strokes may contain no opaque foreground pixel. Require strong
        # coverage along the expected foreground/background blend, within rounding tolerance.
        # The arrow and swatch lie before x=35, so they cannot satisfy the glyph assertion.
        count = sum(foreground_pixel(pixel, foreground, background) for pixel in pixels)
        assert count >= 2, ("native label colour", index, foreground, count)
        assert pixels.count(background) > len(pixels) // 2, ("native label background", index)
        glyphs.append(count)
        assert pixel(data["width"] - 30, row["y"] + row["height"] - 1) == rgb(data["border"])
    empty_y = data["rows"][-1]["y"] + data["rows"][-1]["height"] + 20
    assert empty_y < data["height"] - 20, "The fixture has no unused list space"
    assert pixel(data["width"] // 2, empty_y) == rgb(data["background"]), "unused list space"
    return {"native_glyph_pixels": sum(glyphs), "rows": len(glyphs), "empty_space_checked": 1}


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]))))
