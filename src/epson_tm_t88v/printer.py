"""High-level driver for the Epson TM-T88V."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, replace
from typing import Iterator, List, Optional, Sequence, Union

from . import commands as cmd
from .enums import (
    Barcode,
    CharacterSet,
    Color,
    CutMode,
    DrawerPin,
    Font,
    HriPosition,
    ImageCommand,
    InternationalCharset,
    Justification,
    MaxiCodeMode,
    Pdf417Type,
    PrintDirection,
    QrErrorCorrection,
    StatusClass,
    Underline,
)
from .exceptions import (
    DataTooLarge,
    EncodingError,
    PrinterError,
    ReadTimeout,
    UnsupportedFeature,
)
from .imaging import Raster, from_image
from .profile import TM_T88V_80MM, Profile
from .status import (
    AsbStatus,
    ErrorStatus,
    FullStatus,
    OfflineStatus,
    PaperStatus,
    PrinterIdentity,
    PrinterStatus,
    SymbolSize,
    parse_id_string,
)
from .transport import BufferTransport, Transport, UsbTransport

#: Python codecs matching the printer's character code tables.
CODEC_FOR_TABLE = {
    CharacterSet.PC437_USA_STANDARD_EUROPE: "cp437",
    CharacterSet.PC850_MULTILINGUAL: "cp850",
    CharacterSet.PC860_PORTUGUESE: "cp860",
    CharacterSet.PC863_CANADIAN_FRENCH: "cp863",
    CharacterSet.PC865_NORDIC: "cp865",
    CharacterSet.WPC1252: "cp1252",
    CharacterSet.PC866_CYRILLIC2: "cp866",
    CharacterSet.PC852_LATIN2: "cp852",
    CharacterSet.PC858_EURO: "cp858",
    CharacterSet.ISO8859_15: "iso8859-15",
    CharacterSet.WPC1254_TURKISH: "cp1254",
}


@dataclass(frozen=True)
class Style:
    """The text attributes the driver tracks so they can be restored."""

    font: Font = Font.A
    bold: bool = False
    underline: Underline = Underline.NONE
    width: int = 1
    height: int = 1
    reverse: bool = False
    upside_down: bool = False
    rotate_90: bool = False
    double_strike: bool = False
    smoothing: bool = False
    justify: Justification = Justification.LEFT
    color: Color = Color.BLACK


class Printer:
    """Driver for a TM-T88V.

    Typical use::

        with Printer() as p:
            p.status().raise_for_status()
            with p.style(bold=True, height=2):
                p.textln("TOTAL  12.50")
            p.qr("https://example.com")
            p.cut()

    The driver keeps track of whether anything has been written to the current
    line. Before any image, barcode or 2-D symbol it emits a line feed if
    needed, because raster output that does not start at column 0 is printed
    offset and wraps - the classic way to waste a lot of paper. Disable with
    ``auto_line_start=False`` only if you are managing position yourself.
    """

    def __init__(
        self,
        device: Optional[Union[str, Transport]] = None,
        profile: Profile = TM_T88V_80MM,
        auto_line_start: bool = True,
        charset: CharacterSet = CharacterSet.PC437_USA_STANDARD_EUROPE,
        initialize: bool = True,
    ) -> None:
        if isinstance(device, Transport):
            self.transport: Transport = device
        else:
            self.transport = UsbTransport(device)
        self.profile = profile
        self.auto_line_start = auto_line_start
        self._charset = CharacterSet(charset)
        self._style = Style()
        self._line_dirty = False
        self._page_mode = False
        if initialize:
            self.reset()

    # -- plumbing ---------------------------------------------------------

    def write_raw(self, data: bytes) -> "Printer":
        """Send bytes straight to the printer, bypassing all tracking.

        After using this the driver can no longer know whether the current
        line is dirty, so it conservatively assumes it is.
        """
        self.transport.write(data)
        if data:
            self._line_dirty = not data.endswith((b"\n", b"\r"))
        return self

    def _send(self, data: bytes) -> "Printer":
        self.transport.write(data)
        return self

    def resync(self) -> bool:
        """Recover a printer left waiting for the payload of a failed write.

        After a :class:`~epson_tm_t88v.exceptions.WriteTimeout` part-way
        through a command the printer answers nothing at all, because it is
        reading every further byte as that command's data. This satisfies the
        outstanding payload, clears the buffer and restores the driver's idea
        of the current style. Returns False if the printer is stuck on
        something else.
        """
        if not self.transport.resync():
            return False
        self._send(cmd.character_set(self._charset))
        self._style = Style()
        self._line_dirty = False
        self._page_mode = False
        return True

    def reset(self) -> "Printer":
        """``ESC @`` - clear the buffer and return to defaults. Prints nothing."""
        self._send(cmd.initialize())
        self._send(cmd.character_set(self._charset))
        self._style = Style()
        self._line_dirty = False
        self._page_mode = False
        return self

    def ensure_line_start(self) -> "Printer":
        """Emit a line feed if anything is pending on the current line."""
        if self._line_dirty:
            self._send(cmd.LF)
            self._line_dirty = False
        return self

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "Printer":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- text -------------------------------------------------------------

    def encode(self, text: str, errors: str = "strict") -> bytes:
        """Encode text in the currently selected character code table.

        Defaults to ``errors="strict"``: a character the table cannot express
        raises rather than being silently dropped, because a receipt quietly
        missing a character is worse than a loud failure.
        """
        codec = CODEC_FOR_TABLE.get(self._charset)
        if codec is None:
            raise EncodingError(
                f"no Python codec for character table {self._charset.name}; "
                f"use write_raw() with bytes you have encoded yourself"
            )
        try:
            return text.encode(codec, errors)
        except UnicodeEncodeError as exc:
            raise EncodingError(
                f"{text[exc.start:exc.end]!r} cannot be represented in "
                f"{self._charset.name}. Select another table with "
                f"set_charset(), or pass errors='replace'."
            ) from exc

    def text(self, text: str, errors: str = "strict") -> "Printer":
        """Write text without a trailing newline."""
        data = self.encode(text, errors)
        self.transport.write(data)
        if data:
            self._line_dirty = not data.endswith((b"\n", b"\r"))
        return self

    def textln(self, text: str = "", errors: str = "strict") -> "Printer":
        """Write text followed by a line feed."""
        self.text(text, errors)
        self._send(cmd.LF)
        self._line_dirty = False
        return self

    def rule(self, char: str = "-", font: Optional[Font] = None) -> "Printer":
        """Print a full-width horizontal rule in the current (or given) font."""
        f = self._style.font if font is None else Font(font)
        width = self.profile.columns(f) // max(1, self._style.width)
        return self.textln(char * width)

    def columns(self, *cells: str, widths: Optional[Sequence[int]] = None) -> "Printer":
        """Lay out cells across the line; the last cell is right-aligned.

        Useful for the ``item .......... price`` shape receipts are made of.
        """
        total = self.profile.columns(self._style.font) // max(1, self._style.width)
        if widths is None:
            if len(cells) < 2:
                return self.textln("".join(cells))
            first = total - sum(len(c) for c in cells[1:])
            widths = [max(0, first)] + [len(c) for c in cells[1:]]
        if len(widths) != len(cells):
            raise ValueError("widths must have one entry per cell")
        out = "".join(c[:w].ljust(w) for c, w in zip(cells, widths))
        return self.textln(out[:total])

    # -- styling ----------------------------------------------------------

    def _apply(self, old: Style, new: Style) -> None:
        # ESC a and ESC { are ignored unless they arrive at the start of a
        # line, so a change sent mid-line silently does nothing: proven on
        # paper 2026-10-07, where leaving upside-down mode before the line
        # feed left every following line upside down. End the line first.
        line_level = new.justify != old.justify or new.upside_down != old.upside_down
        if line_level and not self._page_mode:
            self.ensure_line_start()
        if new.font != old.font:
            self._send(cmd.select_font(new.font))
        if new.bold != old.bold:
            self._send(cmd.emphasize(new.bold))
        if new.double_strike != old.double_strike:
            self._send(cmd.double_strike(new.double_strike))
        if new.underline != old.underline:
            self._send(cmd.underline(new.underline))
        if (new.width, new.height) != (old.width, old.height):
            self._send(cmd.char_size(new.width, new.height))
        if new.reverse != old.reverse:
            self._send(cmd.reverse(new.reverse))
        if new.upside_down != old.upside_down:
            self._send(cmd.upside_down(new.upside_down))
        if new.rotate_90 != old.rotate_90:
            self._send(cmd.rotate_90(new.rotate_90))
        if new.smoothing != old.smoothing:
            self._send(cmd.smoothing(new.smoothing))
        if new.justify != old.justify:
            self._send(cmd.justify(new.justify))
        if new.color != old.color:
            self._send(cmd.color(new.color))

    def set_style(self, **kwargs: object) -> "Printer":
        """Change text attributes permanently. See :class:`Style` for names."""
        unknown = set(kwargs) - set(Style.__dataclass_fields__)
        if unknown:
            raise TypeError(f"unknown style attributes: {sorted(unknown)}")
        new = replace(self._style, **kwargs)  # type: ignore[arg-type]
        self._apply(self._style, new)
        self._style = new
        return self

    @contextlib.contextmanager
    def style(self, **kwargs: object) -> Iterator["Printer"]:
        """Temporarily change text attributes, restoring them on exit."""
        previous = self._style
        self.set_style(**kwargs)
        try:
            yield self
        finally:
            self._apply(self._style, previous)
            self._style = previous

    @property
    def current_style(self) -> Style:
        return self._style

    def set_charset(self, table: CharacterSet) -> "Printer":
        self._charset = CharacterSet(table)
        return self._send(cmd.character_set(self._charset))

    def set_international_charset(self, charset: InternationalCharset) -> "Printer":
        return self._send(cmd.international_charset(charset))

    def set_line_spacing(self, dots: Optional[int] = None) -> "Printer":
        """Line spacing in dots (at most 127), or None for the default 30."""
        if dots is None:
            return self._send(cmd.line_spacing(None))
        return self._send(cmd.line_spacing(self._vertical_units(dots)))

    def set_char_spacing(self, dots: int) -> "Printer":
        return self._send(cmd.char_spacing(dots))

    def set_margins(self, left: int = 0, width: Optional[int] = None) -> "Printer":
        """Set the left margin and print area width, in dots.

        Both only take effect at the start of a line, so this forces one.
        """
        self.ensure_line_start()
        self._send(cmd.left_margin(left))
        if width is None:
            width = self.profile.print_width_dots - left
        if left + width > self.profile.print_width_dots:
            raise DataTooLarge(
                f"left margin {left} + width {width} exceeds the "
                f"{self.profile.print_width_dots}-dot print area"
            )
        return self._send(cmd.print_area_width(width))

    # -- paper ------------------------------------------------------------

    def feed(self, lines: int = 1) -> "Printer":
        self._line_dirty = False
        return self._send(cmd.feed_lines(lines))

    def feed_dots(self, dots: int) -> "Printer":
        self._line_dirty = False
        units = self._vertical_units(dots, limit=None)
        # ESC J takes at most 255 units, so feed further in steps.
        while units > 255:
            self._send(cmd.feed_dots(255))
            units -= 255
        return self._send(cmd.feed_dots(units))

    def _vertical_units(self, dots: int, limit: Optional[int] = 255) -> int:
        """Convert dots to the printer's vertical motion units."""
        if dots < 0:
            raise ValueError(f"dots must not be negative, got {dots}")
        units = dots * self.profile.vertical_units_per_dot
        if limit is not None and units > limit:
            raise ValueError(
                f"{dots} dots is more than this command can take "
                f"({limit // self.profile.vertical_units_per_dot} dots)"
            )
        return units

    def cut(self, mode: CutMode = CutMode.PARTIAL, feed: int = 5) -> "Printer":
        """Feed clear of the print head, then cut.

        ``feed`` is in *lines*. Without it the cut lands a couple of
        centimetres above the last printed line, because the cutter sits well
        above the head.
        """
        self.ensure_line_start()
        if feed:
            self._send(cmd.feed_lines(feed))
        return self._send(cmd.cut(mode))

    def open_drawer(self, pin: DrawerPin = DrawerPin.PIN_2, on_ms: int = 100) -> "Printer":
        return self._send(cmd.pulse(pin, on_ms))

    # -- images -----------------------------------------------------------

    def image(
        self,
        source: Union[Raster, str, object],
        align: Optional[Justification] = Justification.CENTER,
        command: ImageCommand = ImageCommand.GRAPHICS,
        scale_x: int = 1,
        scale_y: int = 1,
        ink: Color = Color.BLACK,
        dither: bool = True,
        band_rows: int = 256,
        pace: Optional[bool] = None,
    ) -> "Printer":
        """Print an image.

        ``source`` may be a :class:`~epson_tm_t88v.imaging.Raster`, a path, or
        a PIL image (the latter two need Pillow). Images are banded into
        horizontal strips so no single command overruns the printer.

        The print position is always moved to column 0 first - an image sent
        mid-line is offset and wraps.

        ``pace`` waits for the printer to catch up between bands so no single
        command meets a full receive buffer. It defaults to on for real
        hardware and off for the write-only transports, which cannot reply.
        """
        raster = (
            source
            if isinstance(source, Raster)
            else from_image(source, max_width=self.profile.print_width_dots, dither=dither)
        )
        if raster.width > self.profile.print_width_dots:
            raise DataTooLarge(
                f"image is {raster.width} dots wide, print area is "
                f"{self.profile.print_width_dots}"
            )

        if self.auto_line_start:
            self.ensure_line_start()
        if align is not None:
            self._send(cmd.justify(align))

        # The receive buffer is only a few KB, so band by bytes as well as by
        # rows: a command larger than the buffer cannot be handed over in one
        # go while the printer is busy, and a write that stalls part-way
        # through one leaves the printer waiting for the rest of its payload,
        # silently swallowing everything sent afterwards. Half the buffer per
        # band leaves room for the commands around it.
        budget = max(1, self.profile.receive_buffer_bytes // 2 - 32)
        rows_that_fit = max(1, budget // max(1, raster.row_bytes))
        rows_per_band = max(1, min(band_rows, rows_that_fit))

        should_pace = self.transport.supports_status if pace is None else pace
        bands = list(raster.bands(rows_per_band))
        for index, band in enumerate(bands):
            if should_pace and index:
                # Let the printer work through the previous band so this one
                # meets a buffer with room in it.
                self.wait_for_completion(timeout=60.0)
            if command is ImageCommand.GRAPHICS:
                self._send(cmd.graphics_store(band.data, band.width, band.height, scale_x, scale_y, ink))
                self._send(cmd.graphics_print())
            else:
                self._send(
                    cmd.raster_image(
                        band.data,
                        band.row_bytes,
                        band.height,
                        double_width=scale_x > 1,
                        double_height=scale_y > 1,
                    )
                )

        if align is not None:
            self._send(cmd.justify(self._style.justify))
        self._line_dirty = False
        return self

    # -- 1-D barcodes -----------------------------------------------------

    def barcode(
        self,
        symbology: Barcode,
        data: Union[str, bytes],
        height: int = 64,
        module_width: int = 3,
        hri: HriPosition = HriPosition.BELOW,
        hri_font: Font = Font.B,
        align: Optional[Justification] = Justification.CENTER,
    ) -> "Printer":
        """Print a 1-D barcode using the printer's own encoder.

        Which symbologies this model actually accepts has not been confirmed on
        hardware - ``GS k`` has no query form. ``tools/calibrate.py`` prints one
        of each to settle it; see FINDINGS.md section 7.
        """
        symbology = Barcode(symbology)
        payload = data.encode("ascii") if isinstance(data, str) else bytes(data)
        _validate_barcode(symbology, payload)

        if self.auto_line_start:
            self.ensure_line_start()
        if align is not None:
            self._send(cmd.justify(align))
        self._send(cmd.barcode_height(height))
        self._send(cmd.barcode_width(module_width))
        self._send(cmd.hri_position(hri))
        self._send(cmd.hri_font(hri_font))
        self._send(cmd.barcode(symbology, payload))
        if align is not None:
            self._send(cmd.justify(self._style.justify))
        self._line_dirty = False
        return self

    # -- 2-D symbols ------------------------------------------------------

    def qr(
        self,
        data: Union[str, bytes],
        module: int = 4,
        error_correction: QrErrorCorrection = QrErrorCorrection.M,
        align: Optional[Justification] = Justification.CENTER,
    ) -> "Printer":
        """Print a QR code. The printer encodes it; no Python QR library needed.

        Capacity is the full QR specification (7089 digits, version 40,
        measured). Note that QR *model* selection is ignored by this firmware -
        everything comes out as Model 2.
        """
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._store_qr(payload, module, error_correction)
        return self._print_symbol(cmd.QR_CN, align)

    def qr_size(
        self,
        data: Union[str, bytes],
        module: int = 4,
        error_correction: QrErrorCorrection = QrErrorCorrection.M,
    ) -> SymbolSize:
        """Ask the printer how big this QR would be, without printing it.

        Use it to check a symbol will fit before committing paper.
        """
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._store_qr(payload, module, error_correction)
        return self._symbol_size(cmd.QR_CN)

    def _store_qr(self, payload: bytes, module: int, ec: QrErrorCorrection) -> None:
        self._send(cmd.qr_module_size(module))
        self._send(cmd.qr_error_correction(ec))
        self._send(cmd.qr_store(payload))

    def pdf417(
        self,
        data: Union[str, bytes],
        columns: int = 0,
        rows: int = 0,
        module_width: int = 3,
        row_height: int = 3,
        error_correction: int = 1,
        kind: Pdf417Type = Pdf417Type.STANDARD,
        align: Optional[Justification] = Justification.CENTER,
    ) -> "Printer":
        """Print a PDF417 symbol. ``columns``/``rows`` of 0 mean automatic."""
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._send(cmd.pdf417_columns(columns))
        self._send(cmd.pdf417_rows(rows))
        self._send(cmd.pdf417_module_width(module_width))
        self._send(cmd.pdf417_row_height(row_height))
        self._send(cmd.pdf417_error_correction(error_correction))
        self._send(cmd.pdf417_type(kind))
        self._send(cmd.pdf417_store(payload))
        return self._print_symbol(cmd.PDF417_CN, align)

    def maxicode(
        self,
        data: Union[str, bytes],
        mode: MaxiCodeMode = MaxiCodeMode.MODE_4,
        align: Optional[Justification] = Justification.CENTER,
    ) -> "Printer":
        """Print a MaxiCode symbol. Modes 4-6 are verified; 2 and 3 need a
        structured carrier message (postal code, country code, service class)."""
        payload = data.encode("ascii") if isinstance(data, str) else bytes(data)
        self._send(cmd.maxicode_mode(mode))
        self._send(cmd.maxicode_store(payload))
        return self._print_symbol(cmd.MAXICODE_CN, align)

    def _print_symbol(self, cn: int, align: Optional[Justification]) -> "Printer":
        if self.auto_line_start:
            self.ensure_line_start()
        if align is not None:
            self._send(cmd.justify(align))
        self._send(cmd.print_stored_symbol(cn))
        if align is not None:
            self._send(cmd.justify(self._style.justify))
        self._line_dirty = False
        return self

    def _symbol_size(self, cn: int) -> SymbolSize:
        reply = self._query(cmd.transmit_symbol_size(cn), terminator=b"\x00", timeout=1.0)
        if not reply:
            raise UnsupportedFeature(
                f"the printer did not answer a symbol-size query for cn={cn}; "
                f"this symbology is not supported"
            )
        return SymbolSize.decode(reply)

    # -- status -----------------------------------------------------------

    def _query(self, command: bytes, **kwargs: object) -> bytes:
        query = getattr(self.transport, "query", None)
        if query is None:
            raise PrinterError("this transport cannot read from the printer")
        return query(command, **kwargs)

    def status(self) -> FullStatus:
        """Read all four real-time status registers.

        Answered even while the printer is busy printing or is offline.
        """
        def one(kind: int) -> int:
            reply = self._query(cmd.realtime_status(kind), expect=1, timeout=1.0)
            if not reply:
                raise ReadTimeout(f"no reply to DLE EOT {kind}")
            return reply[0]

        return FullStatus(
            printer=PrinterStatus.decode(one(1)),
            offline=OfflineStatus.decode(one(2)),
            errors=ErrorStatus.decode(one(3)),
            paper=PaperStatus.decode(one(4)),
        )

    def identity(self) -> PrinterIdentity:
        """Read everything ``GS I`` reports."""
        def string(n: int) -> str:
            return parse_id_string(
                self._query(cmd.transmit_printer_id(n), terminator=b"\x00", timeout=1.0)
            )

        def byte(n: int) -> Optional[int]:
            reply = self._query(cmd.transmit_printer_id(n), expect=1, timeout=1.0)
            return reply[0] if reply else None

        return PrinterIdentity(
            firmware=string(65),
            maker=string(66),
            model=string(67),
            serial=string(68),
            model_id=byte(1),
            type_id=byte(2),
            firmware_id=byte(3),
        )

    def graphics_memory(self) -> dict:
        """NV and download graphics capacity, in bytes."""
        def number(command: bytes) -> Optional[int]:
            reply = self._query(command, terminator=b"\x00", timeout=1.0)
            if not reply or len(reply) < 3:
                return None
            return int(reply[2:].split(b"\x00", 1)[0] or 0)

        return {
            "nv_capacity": number(cmd.nv_graphics_capacity()),
            "nv_remaining": number(cmd.nv_graphics_remaining()),
            "download_remaining": number(cmd.download_graphics_remaining()),
        }

    def wait_for_completion(self, timeout: float = 30.0, token: bytes = b"DONE") -> bool:
        """Block until the printer has consumed everything queued so far.

        Uses ``GS ( H``, which echoes a token back only once the printer has
        worked through the preceding data. Returns True on acknowledgement.
        """
        reply = self._query(
            cmd.response_to_host(token), terminator=b"\x00", timeout=timeout
        )
        if token not in reply:
            raise ReadTimeout(
                f"printer did not acknowledge completion within {timeout}s "
                f"(got {reply!r})"
            )
        return True

    def abort(self) -> bool:
        """Real-time buffer clear - discards queued data without a power cycle."""
        reply = self._query(cmd.clear_buffer(), terminator=b"\x00", timeout=2.0)
        self._line_dirty = False
        return reply.startswith(b"\x37\x25")

    def enable_status_push(self, classes: StatusClass = StatusClass.ALL) -> "Printer":
        """Turn on Automatic Status Back.

        The printer then pushes a 4-byte block whenever the status changes;
        read them with :meth:`read_status_push`. The printer sends one block
        immediately on enable, carrying the current state, then one on every
        change after that - so the first read gives a baseline rather than
        blocking until something happens.
        """
        return self._send(cmd.automatic_status_back(classes))

    def disable_status_push(self) -> "Printer":
        return self._send(cmd.automatic_status_back(StatusClass(0)))

    def read_status_push(self, timeout: float = 1.0) -> Optional[AsbStatus]:
        """Collect one pushed ASB block, or None if nothing arrived in time."""
        data = self.transport.read(4, timeout=timeout)
        if len(data) < 4:
            return None
        return AsbStatus.decode(data[:4])

    # -- page mode --------------------------------------------------------

    @contextlib.contextmanager
    def page(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        direction: PrintDirection = PrintDirection.LEFT_TO_RIGHT,
    ) -> Iterator["Printer"]:
        """Compose freely inside a 2-D area, then print it all at once.

        Inside the block, :meth:`at` moves anywhere in the area; on exit the
        page is printed and the printer returns to standard mode.
        """
        self.ensure_line_start()
        self._send(cmd.page_mode())
        self._send(
            cmd.page_area(
                x,
                self._vertical_units(y, limit=65535),
                width,
                self._vertical_units(height, limit=65535),
            )
        )
        self._send(cmd.page_direction(direction))
        self._page_mode = True
        try:
            yield self
        finally:
            self._send(cmd.print_page())
            self._send(cmd.standard_mode())
            self._page_mode = False
            self._line_dirty = False

    def at(self, x: int, y: Optional[int] = None) -> "Printer":
        """Move the print position, in dots. ``y`` is only meaningful in page
        mode, and is where the bottom of the text goes: text at ``y=0`` is
        above the area. Use at least the font height (24 dots for Font A)."""
        self._send(cmd.absolute_position(x))
        if y is not None:
            if not self._page_mode:
                raise PrinterError("vertical positioning requires page mode")
            units = self._vertical_units(y, limit=65535)
            self._send(bytes((cmd.GS, 0x24)) + cmd._u16(units))
        return self

    # -- user setting mode ------------------------------------------------

    def read_customize_values(self, addresses: Sequence[int] = range(1, 128)) -> dict:
        """Read stored customize values. **Enters user setting mode.**

        You must call :meth:`exit_user_setting_mode` afterwards, which
        software-resets the printer. On USB that causes a re-enumeration; if
        the device node is bind-mounted into a container the mount is severed.
        Read FINDINGS.md section 5.1 before using this.
        """
        self._query(cmd.enter_user_setting_mode(), terminator=b"\x00", timeout=2.0)
        values = {}
        for a in addresses:
            reply = self._query(
                cmd.transmit_customize_value(a), terminator=b"\x00", timeout=0.35
            )
            if reply and len(reply) > 2:
                body = reply[2:].split(b"\x00", 1)[0]
                parts = body.split(b"\x1f")
                if len(parts) == 2:
                    values[int(parts[0])] = int(parts[1])
        return values

    def exit_user_setting_mode(self) -> "Printer":
        """Leave user setting mode. **This software-resets the printer.**"""
        return self._send(cmd.exit_user_setting_mode())


def _validate_barcode(symbology: Barcode, data: bytes) -> None:
    """Catch the obvious mistakes before they reach paper."""
    digits_only = {
        Barcode.UPC_A: (11, 12),
        Barcode.UPC_E: (11, 12),
        Barcode.EAN13: (12, 13),
        Barcode.EAN8: (7, 8),
        Barcode.GS1_DATABAR_OMNIDIRECTIONAL: (13,),
        Barcode.GS1_DATABAR_TRUNCATED: (13,),
        Barcode.GS1_DATABAR_LIMITED: (13,),
    }
    if symbology in digits_only:
        allowed = digits_only[symbology]
        if not data.isdigit():
            raise ValueError(f"{symbology.name} accepts digits only, got {data!r}")
        if len(data) not in allowed:
            raise ValueError(
                f"{symbology.name} needs {' or '.join(map(str, allowed))} digits, "
                f"got {len(data)}"
            )
    if symbology is Barcode.ITF:
        if not data.isdigit():
            raise ValueError(f"ITF accepts digits only, got {data!r}")
        if len(data) % 2:
            raise ValueError(f"ITF needs an even number of digits, got {len(data)}")
    if symbology is Barcode.CODABAR:
        if not (data[:1].upper() in b"ABCD" and data[-1:].upper() in b"ABCD"):
            raise ValueError("CODABAR data must start and end with A, B, C or D")
    if symbology in (Barcode.GS1_128, Barcode.GS1_DATABAR_EXPANDED):
        # Proven on paper 2026-10-03: a CODE128 code-set selector at the start
        # of a GS1 payload makes the printer emit the HRI text and no bars at
        # all, silently. It is valid for CODE128 itself, never for these.
        if data[:1] == b"{" and data[1:2].upper() in b"ABC":
            raise ValueError(
                f"{symbology.name} data must be a GS1 element string, not a "
                f"CODE128 code-set selector: {data[:2]!r} produces human-"
                f"readable text with no barcode. Use an application "
                f"identifier instead, e.g. b'(01)12345678901231'."
            )
        if not data:
            raise ValueError(f"{symbology.name} needs data")
