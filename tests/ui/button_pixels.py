"""Disabled-button labels must paint over the button face, not as a solid grey mask (#166).

Observe public native peers; capture only the lab's private display. Use the caller's calibrated
parent origin: accessible screen coordinates can omit a window decoration (#9). System Python/Pillow
checks interiors independently, excluding the border. Solid foreground cannot count as a label.
Windows keeps native painting and is checked for that property without the Linux pixel oracle.
"""

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from theme_pixels import foreground_pixel  # noqa: E402


def label_pixels(pixels: Sequence[Sequence[int]], background: int, foreground: int) -> int:
    def rgb(color):
        return tuple((color >> shift) & 255 for shift in (16, 8, 0))

    face, text = rgb(background), rgb(foreground)
    assert sum(tuple(pixel) == face for pixel in pixels) > len(pixels) // 2, (
        "The button face is covered instead of showing a label"
    )
    glyphs = sum(foreground_pixel(pixel, text, face) for pixel in pixels)
    assert glyphs >= 2, ("Disabled label glyphs are missing", glyphs)
    return glyphs


def capture(lab, buttons, stem, origin):
    if not sys.platform.startswith("linux"):
        for name, peer in buttons.items():
            assert not peer.isEnabled(), name
            assert peer.getProperty("NativeWidgetLook"), name
        return {"painted": False}
    assert origin is not None, "Button pixels need a calibrated parent origin"
    data = {}
    for name, peer in buttons.items():
        assert not peer.isEnabled(), (name, "The painted control must stay disabled")
        accessible = peer.getProperty("XAccessible").getAccessibleContext()
        bounds = peer.getPosSize()
        data[name] = {
            "name": accessible.getAccessibleName(),
            "bounds": [origin[0] + bounds.X, origin[1] + bounds.Y, bounds.Width, bounds.Height],
            "background": peer.StyleSettings.FaceColor,
            "foreground": peer.StyleSettings.DisableColor,
        }
    path = lab.output / (stem + ".json")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    lab.screenshot(stem)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
    }
    checked = subprocess.run(
        ["/usr/bin/python3", "-I", str(Path(__file__)), str(path)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    for name, peer in buttons.items():
        assert not peer.getProperty("NativeWidgetLook"), name
    return json.loads(checked.stdout)


def check(path: Path) -> dict[str, int]:
    Image = importlib.import_module("PIL.Image")
    image = Image.open(path.with_suffix(".png")).convert("RGB")
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = {}
    for name, item in data.items():
        x, y, width, height = item["bounds"]
        assert width > 10 and height > 10, (name, item["bounds"])
        pixels = [
            image.getpixel((px, py))
            for py in range(y + 4, y + height - 4)
            for px in range(x + 4, x + width - 4)
        ]
        counts[name] = label_pixels(pixels, item["background"], item["foreground"])
    return counts


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]))))
