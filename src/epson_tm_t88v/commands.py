"""Pure ESC/POS command builders for the Epson TM-T88V.

Every function here is side-effect free: it validates its arguments and returns
``bytes``. Nothing in this module performs I/O, so the whole command layer is
testable without a printer attached.

Byte-level references in the docstrings are the literal sequences that were
exercised against the hardware; see FINDINGS.md.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from .enums import (
    Barcode,
    CharacterSet,
    Color,
    CutMode,
    DrawerPin,
    Font,
    HriPosition,
    InternationalCharset,
    Justification,
    MaxiCodeMode,
    Pdf417Type,
    PrintDirection,
    QrErrorCorrection,
    StatusClass,
    Underline,
)
from .exceptions import DataTooLarge

ESC = 0x1B
GS = 0x1D
DLE = 0x10
EOT = 0x04
DC4 = 0x14
FS = 0x1C

LF = b"\x0a"
CR = b"\x0d"
FF = b"\x0c"
HT = b"\x09"
CAN = b"\x18"


def _check(name: str, value: int, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in {low}..{high}, got {value}")
    return value


def _u16(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _u32(value: int) -> bytes:
    return bytes(
        (
            value & 0xFF,
            (value >> 8) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 24) & 0xFF,
        )
    )


def _flag(value: bool) -> int:
    return 1 if value else 0


# --------------------------------------------------------------------------
# Printer state
# --------------------------------------------------------------------------

def initialize() -> bytes:
    """``ESC @`` - clear the print buffer and reset modes.

    Verified safe: does not feed paper and does not print. Good recovery step.
    """
    return bytes((ESC, 0x40))


def enable_panel_buttons(enabled: bool) -> bytes:
    """``ESC c 5 n`` - enable/disable the FEED button."""
    return bytes((ESC, 0x63, 0x35, _flag(not enabled)))


def paper_sensor_stop_printing(near_end: bool, end: bool) -> bytes:
    """``ESC c 4 n`` - which sensors halt printing when they trigger."""
    return bytes((ESC, 0x63, 0x34, (1 if near_end else 0) | (2 if end else 0)))


# --------------------------------------------------------------------------
# Feeding and cutting
# --------------------------------------------------------------------------

def feed_lines(lines: int = 1) -> bytes:
    """``ESC d n`` - feed n lines (0-255)."""
    return bytes((ESC, 0x64, _check("lines", lines, 0, 255)))


def feed_dots(units: int) -> bytes:
    """``ESC J n`` - feed n vertical motion units (0-255).

    The TM-T88V's vertical unit is 1/360 in, **half a dot**; see
    ``Profile.vertical_units_per_dot``. ``Printer.feed_dots`` converts.
    """
    return bytes((ESC, 0x4A, _check("units", units, 0, 255)))


def cut(mode: CutMode = CutMode.PARTIAL, feed: Optional[int] = None) -> bytes:
    """``GS V`` - cut the paper.

    With ``feed`` set, uses the ``GS V 65/66 n`` form, which feeds ``n`` dots to
    the cut position first. Without it, uses ``GS V 0/1``; the caller is then
    responsible for feeding enough paper clear of the print head, otherwise the
    cut lands in the middle of the last few lines.
    """
    mode = CutMode(mode)
    if feed is None:
        return bytes((GS, 0x56, 0 if mode is CutMode.FULL else 1))
    _check("feed", feed, 0, 255)
    return bytes((GS, 0x56, 65 if mode is CutMode.FULL else 66, feed))


# --------------------------------------------------------------------------
# Text styling
# --------------------------------------------------------------------------

def justify(mode: Justification) -> bytes:
    """``ESC a n``. Only takes effect at the start of a line."""
    return bytes((ESC, 0x61, int(Justification(mode))))


def select_font(font: Font) -> bytes:
    """``ESC M n`` - Font A (12x24) or Font B (9x17)."""
    return bytes((ESC, 0x4D, int(Font(font))))


def emphasize(on: bool) -> bytes:
    """``ESC E n`` - bold."""
    return bytes((ESC, 0x45, _flag(on)))


def double_strike(on: bool) -> bytes:
    """``ESC G n`` - prints each dot twice; visually close to emphasize."""
    return bytes((ESC, 0x47, _flag(on)))


def underline(mode: Underline) -> bytes:
    """``ESC - n`` - 0 off, 1 one-dot, 2 two-dot."""
    return bytes((ESC, 0x2D, int(Underline(mode))))


def upside_down(on: bool) -> bytes:
    """``ESC { n`` - rotates the whole line 180 degrees.

    Only takes effect at the start of a line.
    """
    return bytes((ESC, 0x7B, _flag(on)))


def reverse(on: bool) -> bytes:
    """``GS B n`` - white characters on a black background."""
    return bytes((GS, 0x42, _flag(on)))


def rotate_90(on: bool) -> bytes:
    """``ESC V n`` - rotate characters 90 degrees clockwise."""
    return bytes((ESC, 0x56, _flag(on)))


def smoothing(on: bool) -> bytes:
    """``GS b n`` - edge smoothing for magnified characters."""
    return bytes((GS, 0x62, _flag(on)))


def char_size(width: int = 1, height: int = 1) -> bytes:
    """``GS !`` - independent magnification, 1x to 8x on each axis.

    ``height=2`` is the "double height" the TM-T88V is usually asked for.
    """
    _check("width", width, 1, 8)
    _check("height", height, 1, 8)
    return bytes((GS, 0x21, ((width - 1) << 4) | (height - 1)))


def print_mode(
    font: Font = Font.A,
    emphasized: bool = False,
    double_height: bool = False,
    double_width: bool = False,
    underlined: bool = False,
) -> bytes:
    """``ESC !`` - set several attributes in one byte.

    Note this *overwrites* font, emphasis, size and underline together, so it
    will clear anything previously set with the individual commands.
    """
    n = int(Font(font))
    if emphasized:
        n |= 0x08
    if double_height:
        n |= 0x10
    if double_width:
        n |= 0x20
    if underlined:
        n |= 0x80
    return bytes((ESC, 0x21, n))


def char_spacing(dots: int) -> bytes:
    """``ESC SP n`` - extra space to the right of each character."""
    return bytes((ESC, 0x20, _check("dots", dots, 0, 255)))


def line_spacing(units: Optional[int] = None) -> bytes:
    """``ESC 3 n`` to set, in vertical motion units (half dots on the
    TM-T88V); ``ESC 2`` restores the default of 1/6 in (30 dots)."""
    if units is None:
        return bytes((ESC, 0x32))
    return bytes((ESC, 0x33, _check("units", units, 0, 255)))


def character_set(table: CharacterSet) -> bytes:
    """``ESC t n`` - select the character code table."""
    return bytes((ESC, 0x74, int(CharacterSet(table))))


def international_charset(charset: InternationalCharset) -> bytes:
    """``ESC R n`` - national variants for a handful of code points."""
    return bytes((ESC, 0x52, int(InternationalCharset(charset))))


def color(value: Color) -> bytes:
    """``GS ( N fn=48`` - select character colour (two-colour paper only)."""
    return bytes((GS, 0x28, 0x4E, 0x02, 0x00, 0x30, 48 + int(Color(value))))


# --------------------------------------------------------------------------
# Positioning
# --------------------------------------------------------------------------

def absolute_position(dots: int) -> bytes:
    """``ESC $`` - set the horizontal print position from the left margin."""
    return bytes((ESC, 0x24)) + _u16(_check("dots", dots, 0, 65535))


def relative_position(dots: int) -> bytes:
    """``ESC \\`` - move the print position relative to the current one."""
    _check("dots", dots, -32768, 32767)
    return bytes((ESC, 0x5C)) + _u16(dots & 0xFFFF)


def left_margin(dots: int) -> bytes:
    """``GS L`` - only takes effect at the start of a line."""
    return bytes((GS, 0x4C)) + _u16(_check("dots", dots, 0, 65535))


def print_area_width(dots: int) -> bytes:
    """``GS W`` - only takes effect at the start of a line."""
    return bytes((GS, 0x57)) + _u16(_check("dots", dots, 0, 65535))


def set_tabs(positions: Sequence[int]) -> bytes:
    """``ESC D ... NUL`` - horizontal tab stops, in character columns."""
    if len(positions) > 32:
        raise DataTooLarge("at most 32 tab stops are supported")
    last = 0
    for p in positions:
        _check("tab position", p, 1, 255)
        if p <= last:
            raise ValueError("tab positions must be strictly increasing")
        last = p
    return bytes((ESC, 0x44)) + bytes(positions) + b"\x00"


# --------------------------------------------------------------------------
# Page mode
# --------------------------------------------------------------------------

def page_mode() -> bytes:
    """``ESC L`` - switch to page mode, where output is composed in a 2-D area."""
    return bytes((ESC, 0x4C))


def standard_mode() -> bytes:
    """``ESC S`` - back to the normal line-at-a-time mode."""
    return bytes((ESC, 0x53))


def page_area(x: int, y: int, width: int, height: int) -> bytes:
    """``ESC W`` - define the page-mode print area.

    ``x`` and ``width`` are horizontal motion units (dots on the TM-T88V);
    ``y`` and ``height`` are vertical motion units (half dots).
    """
    for name, v in (("x", x), ("y", y), ("width", width), ("height", height)):
        _check(name, v, 0, 65535)
    if width == 0 or height == 0:
        raise ValueError("page area width and height must be non-zero")
    return bytes((ESC, 0x57)) + _u16(x) + _u16(y) + _u16(width) + _u16(height)


def page_direction(direction: PrintDirection) -> bytes:
    """``ESC T`` - which corner of the page area output starts from."""
    return bytes((ESC, 0x54, int(PrintDirection(direction))))


def print_page() -> bytes:
    """``ESC FF`` - print the composed page and stay in page mode."""
    return bytes((ESC, 0x0C))


def cancel_page_data() -> bytes:
    """``CAN`` - discard everything composed in the current page area."""
    return CAN


# --------------------------------------------------------------------------
# Cash drawer
# --------------------------------------------------------------------------

def pulse(pin: DrawerPin = DrawerPin.PIN_2, on_ms: int = 100, off_ms: int = 100) -> bytes:
    """``ESC p`` - buffered drawer-kick pulse. Timings round to 2 ms units."""
    on = _check("on_ms", on_ms, 0, 510) // 2
    off = _check("off_ms", off_ms, 0, 510) // 2
    return bytes((ESC, 0x70, int(DrawerPin(pin)), on, off))


def pulse_realtime(pin: DrawerPin = DrawerPin.PIN_2, on_ms: int = 100) -> bytes:
    """``DLE DC4 1`` - real-time drawer kick, executed ahead of the queue."""
    t = _check("on_ms", on_ms, 100, 800) // 100
    return bytes((DLE, DC4, 0x01, int(DrawerPin(pin)), t))


# --------------------------------------------------------------------------
# Status and synchronisation
# --------------------------------------------------------------------------

def realtime_status(kind: int) -> bytes:
    """``DLE EOT n`` - n is 1 printer, 2 offline cause, 3 error cause, 4 paper.

    Answered immediately even while the printer is busy or offline. ``n`` of 7
    and 8 are not implemented on the TM-T88V.
    """
    return bytes((DLE, EOT, _check("kind", kind, 1, 4)))


def transmit_printer_id(n: int) -> bytes:
    """``GS I n`` - 1/2/3 give single-byte IDs, 65..69 give NUL-terminated strings."""
    return bytes((GS, 0x49, _check("n", n, 1, 255)))


def automatic_status_back(classes: StatusClass) -> bytes:
    """``GS a n`` - push a 4-byte status block whenever the status changes.

    Pass ``StatusClass(0)`` to disable. Confirmed on hardware 2026-10-03: this
    firmware sends one block **immediately** when ASB is switched on, giving
    the current state, and then one on every subsequent change. An earlier note
    here claimed nothing was sent on enable; that was wrong.
    """
    return bytes((GS, 0x61, int(classes) & 0xFF))


def clear_buffer() -> bytes:
    """``DLE DC4 fn=8`` - real-time buffer clear. Acknowledged with ``37 25 00``."""
    return bytes((DLE, DC4, 0x08, 0x01, 0x03, 0x14, 0x01, 0x06, 0x02, 0x08))


def response_to_host(token: bytes) -> bytes:
    """``GS ( H fn=48`` - echo ``token`` back once everything queued is consumed.

    The reply is ``37 22 <token> 00``. This is the only reliable way to know the
    printer has finished processing a job.
    """
    if not 1 <= len(token) <= 80:
        raise DataTooLarge("token must be 1..80 bytes")
    if any(b in (0, 0x1F) for b in token):
        raise ValueError("token must not contain NUL or US bytes")
    body = b"\x30\x30" + token
    return bytes((GS, 0x28, 0x48)) + _u16(len(body)) + body


# --------------------------------------------------------------------------
# User setting mode (GS ( E)
# --------------------------------------------------------------------------

def enter_user_setting_mode() -> bytes:
    """``GS ( E fn=1`` - acknowledged with ``37 20 00``."""
    return bytes((GS, 0x28, 0x45, 0x03, 0x00, 0x01, 0x49, 0x4E))


def exit_user_setting_mode() -> bytes:
    """``GS ( E fn=2`` - leaves user setting mode and **software-resets** the printer.

    On USB this causes the printer to re-enumerate. See FINDINGS.md section 5.1:
    a re-enumeration invalidates a bind-mounted device node inside a container.
    """
    return bytes((GS, 0x28, 0x45, 0x04, 0x00, 0x02, 0x4F, 0x55, 0x54))


def transmit_memory_switch(switch: int) -> bytes:
    """``GS ( E fn=4`` - returned nothing on firmware 30.13."""
    return bytes((GS, 0x28, 0x45, 0x02, 0x00, 0x04, _check("switch", switch, 49, 56)))


def transmit_customize_value(address: int) -> bytes:
    """``GS ( E fn=6`` - reply is ``37 27 <addr> 1F <value> 00``."""
    return bytes((GS, 0x28, 0x45, 0x02, 0x00, 0x06, _check("address", address, 1, 255)))


# --------------------------------------------------------------------------
# 1-D barcodes
# --------------------------------------------------------------------------

def barcode_height(dots: int) -> bytes:
    """``GS h n`` - 1..255 dots."""
    return bytes((GS, 0x68, _check("dots", dots, 1, 255)))


def barcode_width(module: int) -> bytes:
    """``GS w n`` - module width 2..6 dots."""
    return bytes((GS, 0x77, _check("module", module, 2, 6)))


def hri_position(position: HriPosition) -> bytes:
    """``GS H n``."""
    return bytes((GS, 0x48, int(HriPosition(position))))


def hri_font(font: Font) -> bytes:
    """``GS f n``."""
    return bytes((GS, 0x66, int(Font(font))))


def barcode(symbology: Barcode, data: bytes) -> bytes:
    """``GS k m n d1..dn`` - the length-prefixed form, so data may contain NUL."""
    symbology = Barcode(symbology)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("barcode data must be bytes")
    if not 1 <= len(data) <= 255:
        raise DataTooLarge("barcode data must be 1..255 bytes")
    return bytes((GS, 0x6B, int(symbology), len(data))) + bytes(data)


# --------------------------------------------------------------------------
# 2-D symbols (GS ( k). The printer does the encoding itself.
# --------------------------------------------------------------------------

def _gs_k(cn: int, fn: int, params: bytes = b"") -> bytes:
    body = bytes((cn, fn)) + params
    if len(body) > 65535:
        raise DataTooLarge("GS ( k payload exceeds 65535 bytes")
    return bytes((GS, 0x28, 0x6B)) + _u16(len(body)) + body


def _store_symbol_data(cn: int, data: bytes) -> bytes:
    body = bytes((cn, 80, 48)) + data
    if len(body) > 65535:
        raise DataTooLarge("symbol data exceeds what GS ( k can carry")
    return bytes((GS, 0x28, 0x6B)) + _u16(len(body)) + body


def print_stored_symbol(cn: int) -> bytes:
    """``GS ( k fn=81`` - print whatever is in the symbol storage area."""
    return _gs_k(cn, 81, b"\x30")


def transmit_symbol_size(cn: int) -> bytes:
    """``GS ( k fn=82`` - ask for the symbol's dot dimensions without printing.

    Reply: ``37 <id> <width> US <height> US <f3> US <errcode> NUL``. This is how
    the whole 2-D support matrix in FINDINGS.md was established on zero paper.
    """
    return _gs_k(cn, 82, b"\x30")


QR_CN = 49
PDF417_CN = 48
MAXICODE_CN = 50


def qr_module_size(size: int) -> bytes:
    """``GS ( k cn=49 fn=67`` - 1..16 dots per module. 17+ silently reverts to 3."""
    return _gs_k(QR_CN, 67, bytes((_check("size", size, 1, 16),)))


def qr_error_correction(level: QrErrorCorrection) -> bytes:
    """``GS ( k cn=49 fn=69``."""
    return _gs_k(QR_CN, 69, bytes((int(QrErrorCorrection(level)),)))


def qr_store(data: bytes) -> bytes:
    """``GS ( k cn=49 fn=80`` - hand the payload to the printer's QR encoder.

    Capacity is the full QR specification: 7089 digits encodes to a version 40
    (177x177) symbol, measured on hardware.
    """
    return _store_symbol_data(QR_CN, data)


def pdf417_columns(columns: int) -> bytes:
    """``GS ( k cn=48 fn=65`` - 0 selects automatic, else 1..30."""
    return _gs_k(PDF417_CN, 65, bytes((_check("columns", columns, 0, 30),)))


def pdf417_rows(rows: int) -> bytes:
    """``GS ( k cn=48 fn=66`` - 0 selects automatic, else 3..90."""
    rows = _check("rows", rows, 0, 90)
    if rows and rows < 3:
        raise ValueError("PDF417 rows must be 0 (auto) or 3..90")
    return _gs_k(PDF417_CN, 66, bytes((rows,)))


def pdf417_module_width(width: int) -> bytes:
    """``GS ( k cn=48 fn=67`` - 2..8 dots. Default measured as 3."""
    return _gs_k(PDF417_CN, 67, bytes((_check("width", width, 2, 8),)))


def pdf417_row_height(height: int) -> bytes:
    """``GS ( k cn=48 fn=68`` - 2..8 times the module width."""
    return _gs_k(PDF417_CN, 68, bytes((_check("height", height, 2, 8),)))


def pdf417_error_correction(level: int) -> bytes:
    """``GS ( k cn=48 fn=69`` - error correction level 0..8."""
    return _gs_k(PDF417_CN, 69, bytes((0x30, _check("level", level, 0, 8))))


def pdf417_type(kind: Pdf417Type) -> bytes:
    """``GS ( k cn=48 fn=70`` - standard or truncated."""
    return _gs_k(PDF417_CN, 70, bytes((int(Pdf417Type(kind)),)))


def pdf417_store(data: bytes) -> bytes:
    """``GS ( k cn=48 fn=80``."""
    return _store_symbol_data(PDF417_CN, data)


def maxicode_mode(mode: MaxiCodeMode) -> bytes:
    """``GS ( k cn=50 fn=65`` - modes 4..6 verified; 2 and 3 need carrier data."""
    return _gs_k(MAXICODE_CN, 65, bytes((int(MaxiCodeMode(mode)),)))


def maxicode_store(data: bytes) -> bytes:
    """``GS ( k cn=50 fn=80``."""
    return _store_symbol_data(MAXICODE_CN, data)


# --------------------------------------------------------------------------
# Raster graphics
# --------------------------------------------------------------------------

def raster_image(
    data: bytes,
    width_bytes: int,
    height: int,
    double_width: bool = False,
    double_height: bool = False,
) -> bytes:
    """``GS v 0`` - the legacy raster bit image command.

    ``data`` is packed 1-bit-per-pixel, MSB first, ``width_bytes`` per row, rows
    top to bottom. A set bit prints a black dot.
    """
    _check("width_bytes", width_bytes, 1, 0xFFFF)
    _check("height", height, 1, 0xFFFF)
    if len(data) != width_bytes * height:
        raise ValueError(
            f"data is {len(data)} bytes, expected {width_bytes * height}"
        )
    m = (1 if double_width else 0) | (2 if double_height else 0)
    return bytes((GS, 0x76, 0x30, m)) + _u16(width_bytes) + _u16(height) + data


def graphics_store(
    data: bytes,
    width: int,
    height: int,
    scale_x: int = 1,
    scale_y: int = 1,
    ink: Color = Color.BLACK,
) -> bytes:
    """``GS ( L`` / ``GS 8 L`` fn=112 - buffer a raster image for printing.

    ``width`` and ``height`` are in dots (not bytes). The short ``GS ( L`` form
    is used when it fits in its 16-bit length field, otherwise the 32-bit
    ``GS 8 L`` form. Follow with :func:`graphics_print`.
    """
    _check("width", width, 1, 0xFFFF)
    _check("height", height, 1, 0xFFFF)
    _check("scale_x", scale_x, 1, 2)
    _check("scale_y", scale_y, 1, 2)
    expected = ((width + 7) // 8) * height
    if len(data) != expected:
        raise ValueError(f"data is {len(data)} bytes, expected {expected}")

    params = (
        bytes((0x30, 112, 0x30, scale_x, scale_y, 48 + int(Color(ink))))
        + _u16(width)
        + _u16(height)
        + data
    )
    if len(params) <= 0xFFFF:
        return bytes((GS, 0x28, 0x4C)) + _u16(len(params)) + params
    return bytes((GS, 0x38, 0x4C)) + _u32(len(params)) + params


def graphics_print() -> bytes:
    """``GS ( L fn=50`` - print the buffered graphics data."""
    return bytes((GS, 0x28, 0x4C, 0x02, 0x00, 0x30, 0x32))


def nv_graphics_capacity() -> bytes:
    """``GS ( L fn=48`` - measured 262144 bytes on this unit."""
    return bytes((GS, 0x28, 0x4C, 0x02, 0x00, 0x30, 48))


def nv_graphics_remaining() -> bytes:
    """``GS ( L fn=51``."""
    return bytes((GS, 0x28, 0x4C, 0x02, 0x00, 0x30, 51))


def download_graphics_remaining() -> bytes:
    """``GS ( L fn=52`` - measured 212992 bytes on this unit."""
    return bytes((GS, 0x28, 0x4C, 0x02, 0x00, 0x30, 52))
