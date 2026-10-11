"""Tests for the TM-T88V driver.

Everything here runs without a printer. Where a test asserts an exact byte
sequence, that sequence is one that was observed working against the real
hardware - see FINDINGS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import (  # noqa: E402
    Barcode,
    BufferTransport,
    CharacterSet,
    CutMode,
    EncodingError,
    Font,
    Justification,
    Printer,
    QrErrorCorrection,
    Raster,
    TM_T88V_58MM,
    TM_T88V_80MM,
    Underline,
    commands as cmd,
    from_grayscale,
)
from epson_tm_t88v.exceptions import WriteTimeout  # noqa: E402
from epson_tm_t88v.status import (  # noqa: E402
    ErrorStatus,
    FullStatus,
    OfflineStatus,
    PaperStatus,
    PrinterStatus,
    SymbolSize,
    parse_id_string,
)


def mk():
    t = BufferTransport()
    return Printer(t), t


# -- command bytes verified against the hardware --------------------------

def test_response_to_host_matches_hardware():
    assert cmd.response_to_host(b"TEST") == bytes.fromhex("1d28480600303054455354")


def test_clear_buffer_matches_hardware():
    assert cmd.clear_buffer() == bytes.fromhex("10140801031401060208")


def test_symbol_size_query_matches_hardware():
    assert cmd.transmit_symbol_size(49) == bytes.fromhex("1d286b0300315230")


def test_qr_store_matches_hardware():
    assert cmd.qr_store(b"1234") == bytes.fromhex("1d286b0700315030") + b"1234"


def test_initialize():
    assert cmd.initialize() == b"\x1b@"


# -- sizing ---------------------------------------------------------------

def test_char_size_double_height():
    assert cmd.char_size(1, 2) == bytes((0x1D, 0x21, 0x01))


def test_char_size_double_both():
    assert cmd.char_size(2, 2) == bytes((0x1D, 0x21, 0x11))


def test_char_size_max():
    assert cmd.char_size(8, 8) == bytes((0x1D, 0x21, 0x77))


@pytest.mark.parametrize("w,h", [(0, 1), (1, 0), (9, 1), (1, 9)])
def test_char_size_rejects_out_of_range(w, h):
    with pytest.raises(ValueError):
        cmd.char_size(w, h)


def test_profile_columns_are_self_consistent():
    # 42 and 56 are the documented TM-T88V figures; they only come out of a
    # 512-dot print area, never a 576-dot one.
    assert TM_T88V_80MM.print_width_dots == 512
    assert TM_T88V_80MM.columns(Font.A) == 42
    assert TM_T88V_80MM.columns(Font.B) == 56
    assert TM_T88V_58MM.columns(Font.A) == 30
    assert TM_T88V_58MM.columns(Font.B) == 40


def test_print_width_fits_the_paper():
    assert TM_T88V_80MM.dots_to_mm(512) < 80
    assert TM_T88V_58MM.dots_to_mm(360) < 58


# -- the column-0 guard, the thing that wastes paper when it is wrong -----

def test_image_forces_line_start_when_line_is_dirty():
    p, t = mk()
    p.text("pending")
    p.image(Raster(8, 1, b"\xff"))
    body = t.data[t.data.index(b"pending") + 7 :]
    assert body.startswith(b"\x0a"), body[:8]


def test_image_does_not_add_a_feed_when_line_is_clean():
    p, t = mk()
    p.textln("clean")
    before = len(t.data)
    p.image(Raster(8, 1, b"\xff"))
    assert not t.data[before:].startswith(b"\x0a")


def test_barcode_forces_line_start():
    p, t = mk()
    p.text("pending")
    p.barcode(Barcode.CODE39, "ABC")
    assert b"\x0a" in t.data[t.data.index(b"pending") + 7 :]


def test_qr_forces_line_start_before_printing():
    p, t = mk()
    p.text("pending")
    p.qr("X")
    printed = t.data.index(bytes.fromhex("1d286b0300315130"))
    assert b"\x0a" in t.data[t.data.index(b"pending") + 7 : printed]


def test_guard_can_be_disabled():
    t = BufferTransport()
    p = Printer(t, auto_line_start=False)
    p.text("pending")
    before = len(t.data)
    p.image(Raster(8, 1, b"\xff"))
    assert b"\x0a" not in t.data[before : before + 2]


def test_write_raw_marks_line_dirty():
    p, t = mk()
    p.write_raw(b"abc")
    p.image(Raster(8, 1, b"\xff"))
    assert b"\x0a" in t.data[t.data.index(b"abc") + 3 :]


# -- status decoding, replaying real readings -----------------------------

def test_healthy_printer_readings():
    s = FullStatus(
        PrinterStatus.decode(0x16),
        OfflineStatus.decode(0x12),
        ErrorStatus.decode(0x12),
        PaperStatus.decode(0x12),
    )
    assert s.ok and s.problems == [] and str(s) == "ready"


def test_near_end_is_reported_but_not_blocking():
    s = FullStatus(
        PrinterStatus.decode(0x16),
        OfflineStatus.decode(0x12),
        ErrorStatus.decode(0x12),
        PaperStatus.decode(0x1E),
    )
    assert s.ok
    assert s.problems == ["paper roll near end"]
    assert "near end" in str(s)
    s.raise_for_status()  # must not raise


def test_cover_open_is_detected():
    s = OfflineStatus.decode(0x16)
    assert s.cover_open


def test_paper_out_is_detected_and_blocks():
    from epson_tm_t88v import PrinterFault

    s = FullStatus(
        PrinterStatus.decode(0x16),
        OfflineStatus.decode(0x12),
        ErrorStatus.decode(0x12),
        PaperStatus.decode(0x72),
    )
    assert not s.paper.present and not s.ok
    with pytest.raises(PrinterFault):
        s.raise_for_status()


def test_autocutter_error_is_detected():
    assert ErrorStatus.decode(0x1A).autocutter_error


def test_symbol_size_from_real_qr_reply():
    # Exact bytes captured from the printer for QR of "1234".
    s = SymbolSize.decode(bytes.fromhex("373636331f36331f311f3000"))
    assert (s.width, s.height) == (63, 63) and s.encoded


def test_symbol_size_rejected_payload():
    # Exact bytes captured when GS1 DataBar rejected the payload.
    s = SymbolSize.decode(bytes.fromhex("374F301F301F311F3100"))
    assert not s.encoded and s.error_code == 1


def test_parse_id_string_from_real_reply():
    assert parse_id_string(bytes.fromhex("5f544d2d5438385600")) == "TM-T88V"
    assert parse_id_string(bytes.fromhex("5f33302e3133204553432f504f5300")) == "30.13 ESC/POS"


# -- imaging --------------------------------------------------------------

def test_grayscale_threshold_packs_black_as_set_bits():
    r = from_grayscale([0] * 8, 8, 1, dither=False)
    assert r.data == b"\xff"
    r = from_grayscale([255] * 8, 8, 1, dither=False)
    assert r.data == b"\x00"


def test_raster_rejects_wrong_length():
    with pytest.raises(ValueError):
        Raster(16, 2, b"\x00")


def test_raster_rows_are_byte_padded():
    assert Raster(9, 1, b"\x00\x00").row_bytes == 2


def test_bands_cover_every_row_exactly_once():
    r = from_grayscale(list(range(0, 256, 4))[:64], 8, 8, dither=False)
    bands = list(r.bands(3))
    assert [b.height for b in bands] == [3, 3, 2]
    assert b"".join(b.data for b in bands) == r.data


def test_image_wider_than_paper_is_rejected():
    from epson_tm_t88v import DataTooLarge

    p, _ = mk()
    with pytest.raises(DataTooLarge):
        p.image(Raster(600, 1, b"\x00" * 75))


def test_graphics_store_length_is_checked():
    with pytest.raises(ValueError):
        cmd.graphics_store(b"\x00", width=16, height=2)


# -- barcode validation ---------------------------------------------------

@pytest.mark.parametrize(
    "sym,data",
    [
        (Barcode.EAN13, "12345"),          # wrong length
        (Barcode.EAN13, "abcdefghijkl"),   # not digits
        (Barcode.EAN8, "123456789"),
        (Barcode.ITF, "12345"),            # odd digit count
        (Barcode.CODABAR, "12345"),        # missing start/stop
    ],
)
def test_bad_barcode_data_is_rejected_before_printing(sym, data):
    p, _ = mk()
    with pytest.raises(ValueError):
        p.barcode(sym, data)


@pytest.mark.parametrize(
    "sym,data",
    [
        (Barcode.EAN13, "123456789012"),
        (Barcode.EAN8, "1234567"),
        (Barcode.ITF, "123456"),
        (Barcode.CODABAR, "A1234B"),
        (Barcode.CODE39, "HELLO"),
        (Barcode.CODE128, "{BHello"),
    ],
)
def test_valid_barcode_data_is_accepted(sym, data):
    p, _ = mk()
    p.barcode(sym, data)


# -- text encoding --------------------------------------------------------

def test_unencodable_character_raises_rather_than_vanishing():
    p, _ = mk()
    with pytest.raises(EncodingError):
        p.text("snowman ☃")


def test_charset_switch_changes_encoding():
    p, t = mk()
    p.set_charset(CharacterSet.WPC1252)
    p.text("€")  # euro sign exists in cp1252, not in cp437
    assert b"\x80" in t.data


def test_errors_replace_is_available_when_wanted():
    p, t = mk()
    p.text("☃", errors="replace")
    assert b"?" in t.data


# -- styling --------------------------------------------------------------

def test_style_context_restores_previous_state():
    p, t = mk()
    with p.style(bold=True, height=2):
        p.textln("big")
    assert p.current_style.bold is False
    assert p.current_style.height == 1
    assert t.data.count(bytes((0x1B, 0x45, 1))) == 1
    assert t.data.count(bytes((0x1B, 0x45, 0))) == 1


def test_style_rejects_unknown_attribute():
    p, _ = mk()
    with pytest.raises(TypeError):
        p.set_style(blink=True)


def test_nested_styles_restore_correctly():
    p, _ = mk()
    with p.style(bold=True):
        with p.style(underline=Underline.SINGLE):
            pass
        assert p.current_style.bold and p.current_style.underline == Underline.NONE
    assert not p.current_style.bold


# -- cutting --------------------------------------------------------------

def test_cut_feeds_clear_of_the_head_first():
    p, t = mk()
    p.cut(CutMode.PARTIAL, feed=6)
    assert bytes((0x1B, 0x64, 6)) in t.data
    assert t.data.endswith(bytes((0x1D, 0x56, 1)))


def test_full_cut():
    p, t = mk()
    p.cut(CutMode.FULL, feed=0)
    assert t.data.endswith(bytes((0x1D, 0x56, 0)))


# -- margins --------------------------------------------------------------

def test_margins_beyond_the_paper_are_rejected():
    from epson_tm_t88v import DataTooLarge

    p, _ = mk()
    with pytest.raises(DataTooLarge):
        p.set_margins(left=400, width=300)


def test_tabs_must_increase():
    with pytest.raises(ValueError):
        cmd.set_tabs([10, 5])


# --------------------------------------------------------------- buffer safety
#
# The printer's receive buffer is ~4 KB. A command bigger than it cannot be
# handed over in one go while the printer is busy, and a write that stalls
# part-way through one leaves the printer waiting for the rest of the payload,
# swallowing every byte sent afterwards - including real-time status queries.
# These tests pin the two defences: band by bytes, and recover deliberately.


def _gs_l_payload_lengths(stream: bytes) -> list:
    """Lengths declared by every short-form ``GS ( L`` block in ``stream``."""
    lengths = []
    needle = b"\x1d\x28\x4c"
    i = stream.find(needle)
    while i != -1:
        lengths.append(stream[i + 3] | (stream[i + 4] << 8))
        i = stream.find(needle, i + 1)
    return lengths


def test_image_bands_stay_inside_the_receive_buffer():
    transport = BufferTransport()
    p = Printer(transport, profile=TM_T88V_80MM)
    # Tall enough that the old 256-row banding would emit one oversized block.
    raster = from_grayscale([128] * (512 * 300), 512, 300, dither=False)
    p.image(raster)
    for length in _gs_l_payload_lengths(transport.data):
        assert length <= TM_T88V_80MM.receive_buffer_bytes, (
            f"a {length}-byte graphics block exceeds the "
            f"{TM_T88V_80MM.receive_buffer_bytes}-byte receive buffer"
        )


def test_image_is_not_paced_on_a_write_only_transport():
    # BufferTransport cannot answer GS ( H, so pacing must stay off or the
    # call would raise instead of simply producing bytes.
    transport = BufferTransport()
    assert transport.supports_status is False
    p = Printer(transport, profile=TM_T88V_80MM)
    p.image(from_grayscale([0] * (512 * 300), 512, 300, dither=False))
    assert transport.data


def test_write_only_transport_reports_itself_synchronised():
    transport = BufferTransport()
    assert transport.desynced is False
    assert transport.resync() is True


def _fake_usb_transport(fd: int, write_timeout: float):
    """A UsbTransport bound to an arbitrary fd, bypassing device discovery."""
    from epson_tm_t88v.transport import UsbTransport

    t = object.__new__(UsbTransport)
    t._fd = fd
    t.device = "<pipe>"
    t.write_timeout = write_timeout
    t.read_timeout = 0.1
    t._desynced = False
    return t


def test_write_budget_is_idle_not_total():
    """A printer that is slow but still draining must not trip the timeout.

    Handing over a full-width image can easily take longer than any fixed
    deadline when the printer is working through a queue, so the budget has to
    measure a lack of progress rather than elapsed time.
    """
    import os as _os
    import threading
    import time as _time

    read_fd, write_fd = _os.pipe()
    _os.set_blocking(write_fd, False)
    transport = _fake_usb_transport(write_fd, write_timeout=0.5)
    payload = b"\x00" * (512 * 1024)

    stop = threading.Event()

    def drain():
        while not stop.is_set():
            try:
                if not _os.read(read_fd, 8192):
                    return
            except OSError:
                return
            _time.sleep(0.05)      # slower than the 0.5s budget in aggregate

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        started = _time.monotonic()
        transport.write(payload)          # must not raise
        elapsed = _time.monotonic() - started
        assert elapsed > 0.5, "test did not actually outlast the write budget"
        assert transport.desynced is False
    finally:
        stop.set()
        reader.join(timeout=2)
        _os.close(write_fd)
        _os.close(read_fd)


def test_stalled_mid_command_write_demands_a_resync():
    """Nothing draining means a real failure, flagged as needing recovery."""
    import os as _os

    read_fd, write_fd = _os.pipe()
    _os.set_blocking(write_fd, False)
    transport = _fake_usb_transport(write_fd, write_timeout=0.2)
    try:
        with pytest.raises(WriteTimeout) as excinfo:
            transport.write(b"\x00" * (4 * 1024 * 1024))   # far exceeds the pipe
        assert "resync()" in str(excinfo.value)
        assert transport.desynced is True
    finally:
        _os.close(write_fd)
        _os.close(read_fd)


@pytest.mark.parametrize("sym", [Barcode.GS1_128, Barcode.GS1_DATABAR_EXPANDED])
def test_gs1_rejects_a_code128_code_set_selector(sym):
    """Proven on paper: this payload prints HRI text and no bars, silently."""
    p = Printer(BufferTransport())
    with pytest.raises(ValueError, match="GS1 element string"):
        p.barcode(sym, "{B0112345678901231")


def test_code128_still_accepts_its_own_code_set_selector():
    # The same prefix is correct for CODE128, which printed fine.
    transport = BufferTransport()
    p = Printer(transport)
    p.barcode(Barcode.CODE128, "{BCODE128")
    assert transport.data


# ------------------------------------------------------------------ charsets
#
# ESC t 48 is Windows-1254, not the DOS PC857 code page. The two disagree on
# every Turkish letter, so pairing the wrong codec with it produces plausible
# but entirely wrong output. Confirmed against the printed charset chart.


def test_only_katakana_lacks_a_python_codec():
    """Katakana has no Python codec, so text() must refuse it loudly.

    Every other table the printer carries maps to a real codec. Katakana is
    Epson's own arrangement with no stdlib equivalent, so it is raw-only and
    the driver says so rather than guessing.
    """
    from epson_tm_t88v.printer import CODEC_FOR_TABLE
    missing = {t.name for t in CharacterSet if t not in CODEC_FOR_TABLE}
    assert missing == {"KATAKANA"}, f"unexpected tables without a codec: {missing}"

    p = Printer(BufferTransport())
    p.set_charset(CharacterSet.KATAKANA)
    with pytest.raises(EncodingError, match="write_raw"):
        p.encode("abc")


def test_turkish_table_uses_windows_1254_not_cp857():
    from epson_tm_t88v.printer import CODEC_FOR_TABLE
    assert CODEC_FOR_TABLE[CharacterSet.WPC1254_TURKISH] == "cp1254"


@pytest.mark.parametrize(
    "char, expected",
    [("Ğ", 0xD0), ("İ", 0xDD), ("Ş", 0xDE), ("ğ", 0xF0), ("ı", 0xFD), ("ş", 0xFE)],
)
def test_turkish_letters_encode_to_the_bytes_the_printer_draws(char, expected):
    """These are the exact code points the printed chart showed as Turkish."""
    p = Printer(BufferTransport())
    p.set_charset(CharacterSet.WPC1254_TURKISH)
    assert p.encode(char) == bytes([expected])


def test_every_codec_is_importable():
    import codecs
    from epson_tm_t88v.printer import CODEC_FOR_TABLE
    for table, name in CODEC_FOR_TABLE.items():
        codecs.lookup(name)      # raises LookupError if the codec is bogus


def test_usb_read_waits_through_empty_reads():
    """usblp reports readable while returning zero bytes; that is not a reply."""
    import os
    import time

    from epson_tm_t88v.transport import UsbTransport

    read_end, write_end = os.pipe()
    os.close(write_end)  # a closed pipe is always readable and reads b""
    transport = UsbTransport.__new__(UsbTransport)
    transport.device = "pipe"
    transport._fd = read_end
    started = time.monotonic()
    assert transport.read(8, timeout=0.2) == b""
    assert time.monotonic() - started >= 0.2
    transport.close()


def test_line_level_style_change_ends_the_line_first():
    """ESC { and ESC a are ignored mid-line; leaving them must not be lost."""
    from epson_tm_t88v import Justification, commands

    buffer = BufferTransport()
    p = Printer(buffer, initialize=False)
    with p.style(upside_down=True):
        p.text("flipped")
    assert buffer.data.endswith(b"flipped\n" + commands.upside_down(False))

    buffer.buffer.clear()
    p.text("pending")
    with p.style(justify=Justification.CENTER):
        p.textln("centred")
    assert buffer.data.startswith(b"pending\n" + commands.justify(Justification.CENTER))

    buffer.buffer.clear()
    with p.style(bold=True):
        p.text("x")
    assert b"\n" not in buffer.data  # other styles still change mid-line


def test_vertical_values_are_dots_converted_to_half_dot_units():
    """The TM-T88V's vertical motion unit is 1/360 in: two units per dot."""
    from epson_tm_t88v import commands

    buffer = BufferTransport()
    p = Printer(buffer, initialize=False)
    p.set_line_spacing(24)
    assert buffer.data == commands.line_spacing(48)

    buffer.buffer.clear()
    p.feed_dots(200)  # 400 units: more than one ESC J can carry
    assert buffer.data == commands.feed_dots(255) + commands.feed_dots(145)

    buffer.buffer.clear()
    with p.page(x=0, y=0, width=512, height=100):
        p.at(10, 30)
    assert commands.page_area(0, 0, 512, 200) in buffer.data
    assert bytes((commands.GS, 0x24)) + commands._u16(60) in buffer.data

    with pytest.raises(ValueError):
        p.set_line_spacing(128)
