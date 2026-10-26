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
    shadow = tuple((data["shadow"] >> shift) & 255 for shift in (16, 8, 0))
    expected = sorted(
        row["Y"] + row["Height"] - 1
        for row in data["rows"]
        if 0 < row["Y"] + row["Height"] - 1 < height - 1
    )
    column = left + viewport - 6  # Beyond these synthetic labels, inside the row viewport.
    actual = [y for y in range(1, height - 1) if image.getpixel((column, top + y)) == shadow]
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
    if width - viewport > 6:
        # Native grips can contain shadow-coloured pixels, but do not span the track interior.
        crossed = [
            y
            for y in expected
            if 25 < y < height - 25
            and all(
                image.getpixel((left + x, top + y)) == shadow
                for x in range(viewport + 2, width - 2)
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
