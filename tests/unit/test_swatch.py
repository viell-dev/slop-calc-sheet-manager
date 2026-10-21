"""Tab colour swatches are valid PNG images with the expected pixels."""

import struct
import zlib

from sheet_manager.swatch import BORDER, SIZE, swatch_png


def pixels(png: bytes) -> tuple[int, int, list[bytes]]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    offset, data, width, height = 8, b"", 0, 0
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        tag = png[offset + 4 : offset + 8]
        body = png[offset + 8 : offset + 8 + length]
        (checksum,) = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])
        assert checksum == zlib.crc32(tag + body) & 0xFFFFFFFF
        if tag == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
            assert body[8:] == bytes((8, 6, 0, 0, 0))
        elif tag == b"IDAT":
            data += body
        offset += 12 + length
    raw = zlib.decompress(data)
    stride = 1 + 4 * width
    rows = [raw[y * stride : (y + 1) * stride] for y in range(height)]
    assert all(row[0] == 0 for row in rows)
    return width, height, [row[1:] for row in rows]


def test_coloured_swatch_has_a_frame() -> None:
    width, height, rows = pixels(swatch_png(0x336699))
    assert (width, height) == (SIZE, SIZE)
    assert rows[0][:4] == bytes(BORDER)
    middle = rows[SIZE // 2][4 * (SIZE // 2) : 4 * (SIZE // 2) + 4]
    assert middle == bytes((0x33, 0x66, 0x99, 255))


def test_default_colour_is_transparent() -> None:
    _, _, rows = pixels(swatch_png(None))
    assert all(set(row[3::4]) == {0} for row in rows)
