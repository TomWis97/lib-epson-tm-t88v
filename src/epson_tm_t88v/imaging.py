"""Turning pictures into the 1-bit raster the printer wants.

The packed format used throughout is the ESC/POS one: one bit per pixel, MSB
first, rows padded to a whole number of bytes, a **set bit meaning a black
dot**. That is the inverse of Pillow's ``"1"`` mode, which is handled here.

Pillow is optional. It is needed only to decode image *files*; grayscale and
pre-packed buffers go through a dependency-free path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Union

from .exceptions import DataTooLarge, PrinterError

try:  # pragma: no cover - exercised by whether Pillow is installed
    from PIL import Image as _PILImage

    HAVE_PILLOW = True
except ImportError:  # pragma: no cover
    _PILImage = None
    HAVE_PILLOW = False


@dataclass(frozen=True)
class Raster:
    """A packed 1-bit image ready to hand to the printer."""

    width: int
    height: int
    data: bytes

    def __post_init__(self) -> None:
        expected = self.row_bytes * self.height
        if len(self.data) != expected:
            raise ValueError(
                f"raster data is {len(self.data)} bytes, expected {expected} "
                f"for {self.width}x{self.height}"
            )

    @property
    def row_bytes(self) -> int:
        return (self.width + 7) // 8

    def bands(self, max_rows: int) -> Iterator["Raster"]:
        """Split into horizontal strips of at most ``max_rows`` rows.

        Tall images are sent as several commands so no single command exceeds
        what the printer will accept in one go.
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        stride = self.row_bytes
        for top in range(0, self.height, max_rows):
            rows = min(max_rows, self.height - top)
            yield Raster(
                width=self.width,
                height=rows,
                data=self.data[top * stride : (top + rows) * stride],
            )

    def to_ascii(self, on: str = "#", off: str = " ") -> str:
        """Render as text. Handy for eyeballing output without burning paper."""
        lines: List[str] = []
        for y in range(self.height):
            row = self.data[y * self.row_bytes : (y + 1) * self.row_bytes]
            lines.append(
                "".join(
                    on if row[x >> 3] & (0x80 >> (x & 7)) else off
                    for x in range(self.width)
                )
            )
        return "\n".join(lines)


def pack_bits(dark: Sequence[int], width: int, height: int) -> bytes:
    """Pack a row-major sequence of 0/1 values (1 = black) into ESC/POS bits."""
    if len(dark) != width * height:
        raise ValueError(f"expected {width * height} values, got {len(dark)}")
    row_bytes = (width + 7) // 8
    out = bytearray(row_bytes * height)
    for y in range(height):
        base = y * width
        obase = y * row_bytes
        for x in range(width):
            if dark[base + x]:
                out[obase + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def from_packed(data: bytes, width: int, height: int, invert: bool = False) -> Raster:
    """Wrap an already-packed 1-bit buffer, optionally inverting black/white."""
    if invert:
        data = bytes(b ^ 0xFF for b in data)
    return Raster(width=width, height=height, data=data)


def from_grayscale(
    pixels: Sequence[int],
    width: int,
    height: int,
    dither: bool = True,
    threshold: int = 128,
    invert: bool = False,
) -> Raster:
    """Convert 8-bit grayscale (0 = black, 255 = white) to a printable raster.

    With ``dither`` the conversion uses Floyd-Steinberg error diffusion, which
    is what makes photographs legible on a 1-bit thermal printer. With
    ``dither=False`` it is a plain threshold, which is better for line art,
    text and logos because it keeps edges crisp.

    This is pure Python and needs no Pillow.
    """
    if len(pixels) != width * height:
        raise ValueError(f"expected {width * height} pixels, got {len(pixels)}")
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be 0..255")

    if not dither:
        dark = [1 if (p >= threshold if invert else p < threshold) else 0 for p in pixels]
        return Raster(width, height, pack_bits(dark, width, height))

    # Floyd-Steinberg. Work on a mutable copy so diffused error accumulates.
    buf = [float(255 - p) if invert else float(p) for p in pixels]
    dark = [0] * (width * height)
    for y in range(height):
        base = y * width
        for x in range(width):
            i = base + x
            old = buf[i]
            new = 255.0 if old >= threshold else 0.0
            dark[i] = 0 if new else 1
            err = old - new
            if x + 1 < width:
                buf[i + 1] += err * 7 / 16
            if y + 1 < height:
                below = i + width
                if x > 0:
                    buf[below - 1] += err * 3 / 16
                buf[below] += err * 5 / 16
                if x + 1 < width:
                    buf[below + 1] += err * 1 / 16
    return Raster(width, height, pack_bits(dark, width, height))


def from_image(
    source: Union[str, "object"],
    max_width: int = 576,
    dither: bool = True,
    threshold: int = 128,
    invert: bool = False,
    resize: bool = True,
) -> Raster:
    """Load any image Pillow can read and convert it for the printer.

    ``source`` may be a path or an already-open ``PIL.Image``. Images wider
    than ``max_width`` are scaled down preserving aspect ratio unless
    ``resize=False``, in which case an over-wide image is an error rather than
    something silently clipped by the printer.
    """
    if not HAVE_PILLOW:
        raise PrinterError(
            "Pillow is required to load image files. Install it with "
            "'pip install epson-tm-t88v[images]', or use from_grayscale() / "
            "from_packed(), which need no dependencies."
        )

    img = _PILImage.open(source) if isinstance(source, (str, bytes)) else source

    # Flatten transparency onto white, otherwise alpha turns into black.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        background = _PILImage.new("RGBA", img.size, (255, 255, 255, 255))
        img = _PILImage.alpha_composite(background, img.convert("RGBA"))

    img = img.convert("L")

    if img.width > max_width:
        if not resize:
            raise DataTooLarge(
                f"image is {img.width} dots wide but the print area is "
                f"{max_width}; pass resize=True to scale it down"
            )
        height = max(1, round(img.height * max_width / img.width))
        img = img.resize((max_width, height), _PILImage.LANCZOS)

    if invert:
        img = img.point(lambda p: 255 - p)

    if dither:
        bw = img.convert("1")  # Pillow dithers with Floyd-Steinberg by default
    else:
        bw = img.point(lambda p: 255 if p >= threshold else 0, mode="1")

    # Pillow mode "1" sets a bit for *white*; ESC/POS sets a bit for *black*.
    packed = bytes(b ^ 0xFF for b in bw.tobytes())
    return Raster(width=bw.width, height=bw.height, data=packed)
