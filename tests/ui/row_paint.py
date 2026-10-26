"""Check screenshot pixels against independently captured native row bounds.

Run with the lab's system Python/Pillow, outside LibreOffice's Python environment.
The PNG and adjacent JSON remain useful failure evidence in the UI artifacts.
"""

import importlib
import json
import sys
from pathlib import Path

Image = importlib.import_module("PIL.Image")


def check(image_path: Path, metadata_path: Path) -> None:
    data = json.loads(metadata_path.read_text())
    image = Image.open(image_path).convert("RGB")
    left, top = data["offset"]
    width, height, viewport = data["width"], data["height"], data["viewport"]
    bottom = min(height - 1, data.get("content_height", height))
    shadow = tuple((data["shadow"] >> shift) & 255 for shift in (16, 8, 0))
    expected = sorted(
        row["Y"] + row["Height"] - 1
        for row in data["rows"]
        if 0 < row["Y"] + row["Height"] - 1 < bottom
    )
    column = left + viewport - 6  # Beyond these synthetic labels, inside the row viewport.
    actual = [y for y in range(1, bottom) if image.getpixel((column, top + y)) == shadow]
    # The native hit test includes its bottom boundary. A fully visible last row can
    # share that pixel with a horizontal scrollbar, so the painter excludes it safely.
    final = data["rows"][-1]
    last_omitted = bool(
        width > viewport
        and expected
        and expected[-1] == final["Y"] + final["Height"] - 1
        and actual == expected[:-1]
    )
    assert actual == expected or last_omitted, {
        "expected_dividers": expected,
        "actual_shadow_pixels": actual,
    }
    missing_left = [
        y
        for y in actual
        if not any(image.getpixel((left + x, top + y)) == shadow for x in range(min(3, viewport)))
    ]
    assert not missing_left, {"dividers_missing_left_edge": missing_left}
    short = [
        y
        for y in actual
        if not any(
            image.getpixel((left + x, top + y)) == shadow
            for x in range(max(0, viewport - 3), viewport)
        )
    ]
    assert not short, {"dividers_stopping_short": short, "viewport": viewport}
    if width - viewport > 6:
        # A native gen thumb bevel can span the track interior at a divider's Y.
        # Extension overpaint is continuous through the content/scrollbar boundary too.
        crossed = [
            y
            for y in expected
            if 25 < y < height - 25
            and all(
                image.getpixel((left + x, top + y)) == shadow
                for x in range(viewport - 1, width - 2)
            )
        ]
        assert not crossed, {"dividers_crossing_scrollbar": crossed}
    print(
        json.dumps(
            {
                "native_dividers": len(actual),
                "last_divider_omitted": last_omitted,
                "scrollbar_clear": True,
            }
        )
    )


if __name__ == "__main__":
    check(Path(sys.argv[1]), Path(sys.argv[2]))
