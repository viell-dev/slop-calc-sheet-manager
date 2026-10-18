"""Tab colour swatches as small PNG images; a tree row's image can only come from a URL."""

import struct
import zlib

SIZE = 14
BORDER = (110, 110, 110, 255)


def _chunk(tag: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)


def swatch_png(color: int | None, size: int = SIZE) -> bytes:
    """A size x size RGBA PNG: a grey frame filled with color, or transparent when None."""
    fill = (0, 0, 0, 0) if color is None else ((color >> 16) & 255, (color >> 8) & 255, color & 255, 255)
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter type "none" for this scanline.
        for x in range(size):
            edge = color is not None and (x in (0, size - 1) or y in (0, size - 1))
            rows.extend(BORDER if edge else fill)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )
