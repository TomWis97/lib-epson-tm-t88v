#!/usr/bin/env python3
"""Print one calibration receipt that settles everything a query cannot.

What it resolves, in order:

  1  width    printable width in dots and columns per font
  2  text     every text decoration, including double-height
  3  size     the full GS ! magnification grid
  4  align    fonts, justification, margins
  5  barcode  every 1-D symbology this driver knows about
  6  code2d   QR, PDF417, MaxiCode
  7  image    both raster paths, dithering, and the column-0 guard
  8  color    two-colour output (needs two-colour thermal paper)
  9  cut      partial then full cut

Usage::

    python3 tools/calibrate.py                     # everything
    python3 tools/calibrate.py --sections width,image
    python3 tools/calibrate.py --list
    python3 tools/calibrate.py --dry-run out.bin   # no printer needed

The whole run is roughly 30 cm of paper. It refuses to start if the printer
reports a fault, so a paper-out or open cover does not silently eat the job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import (  # noqa: E402
    Barcode,
    CutMode,
    FileTransport,
    Font,
    HriPosition,
    ImageCommand,
    Justification,
    MaxiCodeMode,
    Printer,
    QrErrorCorrection,
    Raster,
    TM_T88V_80MM,
    Underline,
    from_grayscale,
)
from epson_tm_t88v import commands as cmd  # noqa: E402
from epson_tm_t88v.enums import Color  # noqa: E402
from epson_tm_t88v.exceptions import PrinterError  # noqa: E402
from epson_tm_t88v.imaging import pack_bits  # noqa: E402

PROFILE = TM_T88V_80MM


# ---------------------------------------------------------------- helpers

def heading(p: Printer, number: str, title: str) -> None:
    p.feed(1)
    with p.style(reverse=True, bold=True):
        p.textln(f" {number}  {title} ".ljust(PROFILE.columns(Font.A)))
    p.feed(1)


def ruler_raster(width: int) -> Raster:
    """A measuring bar: solid top, a tick every 32 dots, a tall one every 128."""
    height = 20
    dark: List[int] = []
    for y in range(height):
        for x in range(width):
            if y < 6 or x >= width - 2:
                dark.append(1)
            elif x % 128 < 2:
                dark.append(1)
            elif y < 13 and x % 32 < 2:
                dark.append(1)
            else:
                dark.append(0)
    return Raster(width, height, pack_bits(dark, width, height))


def test_pattern(width: int = 240, height: int = 120) -> List[int]:
    """Grayscale test image: a hard border, diagonals, and a gradient strip.

    The border proves exact placement and that nothing is clipped; the
    diagonals show aliasing; the gradient shows how dithering behaves.
    """
    px: List[int] = []
    for y in range(height):
        for x in range(width):
            if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
                px.append(0)                       # black frame
            elif y > height - 34:
                px.append(int(255 * x / (width - 1)))   # gradient strip
            elif abs(x * (height - 40) // max(1, width) - y) < 2:
                px.append(0)                       # diagonal
            elif abs((width - 1 - x) * (height - 40) // max(1, width) - y) < 2:
                px.append(0)                       # other diagonal
            else:
                px.append(255)
    return px


BARCODES = [
    (Barcode.UPC_A, "01234567890"),
    (Barcode.UPC_E, "01234500005"),
    (Barcode.EAN13, "123456789012"),
    (Barcode.EAN8, "1234567"),
    (Barcode.CODE39, "CODE39"),
    (Barcode.ITF, "12345678"),
    (Barcode.CODABAR, "A12345B"),
    (Barcode.CODE93, "CODE93"),
    (Barcode.CODE128, "{BCODE128"),
    (Barcode.GS1_128, "{B012345678901231"),
    (Barcode.GS1_DATABAR_OMNIDIRECTIONAL, "0123456789012"),
    (Barcode.GS1_DATABAR_TRUNCATED, "0123456789012"),
    (Barcode.GS1_DATABAR_LIMITED, "0123456789012"),
    (Barcode.GS1_DATABAR_EXPANDED, "{B0112345678901231"),
]


# --------------------------------------------------------------- sections

def section_width(p: Printer, notes: List[str]) -> None:
    heading(p, "1", "PRINT WIDTH")
    p.textln("Count where each ruler WRAPS to a second line.")
    p.textln("Expect Font A 42, Font B 56 on an 80 mm roll.")
    p.feed(1)

    scale = "----+----1----+----2----+----3----+----4----+----5----+----6----+----7"
    p.textln("Font A:")
    p.set_style(font=Font.A)
    p.textln(scale)
    p.feed(1)
    p.textln("Font B:")
    p.set_style(font=Font.B)
    p.textln(scale)
    p.set_style(font=Font.A)
    p.feed(1)

    p.textln("Dot rulers. Tall ticks are 128 dots apart.")
    p.textln("The 576 bar is sent deliberately over-wide,")
    p.textln("bypassing the driver, to see where the printer")
    p.textln("itself clips. If 512 and 576 end at the same")
    p.textln("place, the print area really is 512 dots.")
    p.feed(1)
    for width in (360, 512, 576):
        p.textln(f"{width} dots:")
        bar = ruler_raster(width)
        if width <= PROFILE.print_width_dots:
            p.image(bar, align=Justification.LEFT)
        else:
            # Past the configured print area on purpose: emit GS v 0 directly
            # so the driver's own width check does not trim it. Whatever comes
            # out is the printer's true clipping behaviour.
            p.ensure_line_start()
            p.write_raw(cmd.justify(Justification.LEFT))
            p.write_raw(cmd.raster_image(bar.data, bar.row_bytes, bar.height))
            p.write_raw(b"\n")
        p.feed(1)
    notes.append(
        "measure the three bars: 360 and 512 should differ by ~21 mm; if the "
        "576 bar is no longer than the 512 bar, the print area is 512 dots"
    )


def section_text(p: Printer, notes: List[str]) -> None:
    heading(p, "2", "TEXT DECORATION")
    p.textln("normal")
    with p.style(bold=True):
        p.textln("bold / emphasized (ESC E)")
    with p.style(double_strike=True):
        p.textln("double-strike (ESC G)")
    with p.style(underline=Underline.SINGLE):
        p.textln("underline 1 dot (ESC - 1)")
    with p.style(underline=Underline.DOUBLE):
        p.textln("underline 2 dot (ESC - 2)")
    with p.style(height=2):
        p.textln("DOUBLE HEIGHT")
    with p.style(width=2):
        p.textln("DOUBLE WIDTH")
    with p.style(width=2, height=2):
        p.textln("DOUBLE BOTH")
    with p.style(reverse=True):
        p.textln("reverse: white on black (GS B)")
    with p.style(bold=True, underline=Underline.SINGLE, height=2):
        p.textln("BOLD+UNDERLINE+TALL")
    with p.style(upside_down=True):
        p.textln("upside down (ESC {)")
    with p.style(rotate_90=True):
        p.textln("rotated 90 (ESC V)")
    p.feed(1)
    with p.style(width=3, height=3, smoothing=False):
        p.textln("3x NO SMOOTH")
    with p.style(width=3, height=3, smoothing=True):
        p.textln("3x SMOOTHED")
    notes.append("check: does smoothing visibly round the 3x glyph edges?")


def section_size(p: Printer, notes: List[str]) -> None:
    heading(p, "3", "CHARACTER SIZE GRID (GS !)")
    for n in range(1, 9):
        with p.style(width=n, height=n):
            p.textln(f"{n}x")
    p.feed(1)
    p.textln("mixed width/height:")
    for w, h in ((1, 2), (2, 1), (1, 4), (4, 1), (2, 4)):
        with p.style(width=w, height=h):
            p.textln(f"w{w} h{h}")
    notes.append("check: does 8x still fit the line, or is it clipped?")


def section_align(p: Printer, notes: List[str]) -> None:
    heading(p, "4", "FONTS, JUSTIFY, MARGINS")
    for font in (Font.A, Font.B):
        with p.style(font=font):
            p.textln(f"Font {font.name}: the quick brown fox 0123456789")
    p.feed(1)
    for just in (Justification.LEFT, Justification.CENTER, Justification.RIGHT):
        with p.style(justify=just):
            p.textln(f"[{just.name.lower()}]")
    p.feed(1)
    p.textln("left margin 100 dots, width 300:")
    p.set_margins(left=100, width=300)
    p.textln("this block is indented and narrowed")
    p.textln("and should wrap inside 300 dots only")
    p.set_margins(left=0)
    p.textln("back to full width")
    notes.append("check: is the indented block exactly 100 dots from the left?")


def section_barcode(p: Printer, notes: List[str]) -> None:
    heading(p, "5", "1-D BARCODES")
    p.textln("Any missing block = unsupported symbology.")
    p.feed(1)
    for symbology, data in BARCODES:
        with p.style(font=Font.B):
            p.textln(f"{symbology.name}  ({data})")
        try:
            p.barcode(symbology, data, height=50, module_width=2, hri=HriPosition.BELOW)
        except (ValueError, PrinterError) as exc:
            with p.style(font=Font.B, bold=True):
                p.textln(f"  !! rejected by driver: {exc}")
            notes.append(f"{symbology.name}: driver rejected the sample data - {exc}")
        p.feed(1)
    notes.append("record which of the 14 barcode blocks actually printed")


def section_code2d(p: Printer, notes: List[str]) -> None:
    heading(p, "6", "2-D CODES")
    for module in (3, 5, 8):
        with p.style(font=Font.B):
            p.textln(f"QR module={module} EC=M")
        p.qr("https://example.com/tm-t88v", module=module)
        p.feed(1)
    with p.style(font=Font.B):
        p.textln("QR EC=H, 200 chars")
    p.qr("X" * 200, module=3, error_correction=QrErrorCorrection.H)
    p.feed(1)
    with p.style(font=Font.B):
        p.textln("PDF417 auto")
    p.pdf417("PDF417 CALIBRATION 1234567890")
    p.feed(1)
    with p.style(font=Font.B):
        p.textln("MaxiCode mode 4")
    p.maxicode("MAXICODE CALIBRATION 123456", mode=MaxiCodeMode.MODE_4)
    p.feed(1)
    notes.append("scan each 2-D symbol with a phone and confirm the payload")


def section_image(p: Printer, notes: List[str]) -> None:
    heading(p, "7", "IMAGES")
    px = test_pattern(240, 120)
    dithered = from_grayscale(px, 240, 120, dither=True)
    thresholded = from_grayscale(px, 240, 120, dither=False)

    with p.style(font=Font.B):
        p.textln("GS ( L graphics path, dithered")
    p.image(dithered, command=ImageCommand.GRAPHICS)
    p.feed(1)

    with p.style(font=Font.B):
        p.textln("GS v 0 raster path, dithered")
    p.image(dithered, command=ImageCommand.RASTER)
    p.feed(1)

    with p.style(font=Font.B):
        p.textln("threshold instead of dither")
    p.image(thresholded, command=ImageCommand.GRAPHICS)
    p.feed(1)

    with p.style(font=Font.B):
        p.textln("full-width bar, should touch both edges")
    p.image(ruler_raster(PROFILE.print_width_dots), align=Justification.LEFT)
    p.feed(1)

    # The column-0 guard: text is left pending on the line, then an image is
    # sent. Without the guard the image starts mid-line and wraps.
    with p.style(font=Font.B):
        p.textln("column-0 guard (text then image, no newline):")
    p.text("PENDING TEXT")
    p.image(dithered, command=ImageCommand.GRAPHICS)
    notes.append(
        "check: 'PENDING TEXT' sits on its own line and the image below it "
        "starts hard against the left margin, not offset"
    )
    p.feed(1)


def section_color(p: Printer, notes: List[str]) -> None:
    heading(p, "8", "TWO-COLOUR")
    p.textln("Only differs on two-colour thermal paper.")
    with p.style(color=Color.BLACK):
        p.textln("colour 1 (black)")
    with p.style(color=Color.RED):
        p.textln("colour 2 (red on two-colour paper)")
    p.set_style(color=Color.BLACK)
    notes.append("check: did 'colour 2' print red, black, or not at all?")


def section_cut(p: Printer, notes: List[str]) -> None:
    heading(p, "9", "CUT")
    p.textln("partial cut below this line")
    p.cut(CutMode.PARTIAL, feed=4)
    p.textln("full cut below this line")
    p.cut(CutMode.FULL, feed=4)
    notes.append("check: partial cut leaves a small tab, full cut separates")


SECTIONS = {
    "width": section_width,
    "text": section_text,
    "size": section_size,
    "align": section_align,
    "barcode": section_barcode,
    "code2d": section_code2d,
    "image": section_image,
    "color": section_color,
    "cut": section_cut,
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--device", default=None, help="device node (default: auto-discover)")
    ap.add_argument("--sections", default="all", help="comma-separated, or 'all'")
    ap.add_argument("--list", action="store_true", help="list section names and exit")
    ap.add_argument("--dry-run", metavar="FILE", default=None,
                    help="write the byte stream to FILE instead of printing")
    ap.add_argument("--no-status-check", action="store_true",
                    help="print even if the printer reports a fault")
    args = ap.parse_args()

    if args.list:
        for name in SECTIONS:
            print(name)
        return 0

    chosen = list(SECTIONS) if args.sections == "all" else [
        s.strip() for s in args.sections.split(",") if s.strip()
    ]
    unknown = [s for s in chosen if s not in SECTIONS]
    if unknown:
        print(f"unknown section(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(SECTIONS)}", file=sys.stderr)
        return 2

    if args.dry_run:
        printer = Printer(FileTransport(args.dry_run), profile=PROFILE)
    else:
        printer = Printer(args.device, profile=PROFILE)
        status = printer.status()
        print(f"printer: {printer.identity()}")
        print(f"status:  {status}")
        if not status.ok and not args.no_status_check:
            print("\nrefusing to print - fix the above, or pass --no-status-check",
                  file=sys.stderr)
            printer.close()
            return 1

    notes: List[str] = []
    with printer as p:
        p.set_style(justify=Justification.LEFT, font=Font.A)
        with p.style(bold=True, width=2, height=2, justify=Justification.CENTER):
            p.textln("TM-T88V")
        with p.style(justify=Justification.CENTER):
            p.textln("calibration print")
        p.rule("=")
        for name in chosen:
            SECTIONS[name](p, notes)
        if "cut" not in chosen:
            p.feed(4)

        if not args.dry_run:
            p.wait_for_completion(timeout=120.0)

    print("\nWhat to check on the paper:")
    for i, note in enumerate(notes, 1):
        print(f"  {i:2d}. {note}")
    print("\nPhotograph the receipt and record the answers in FINDINGS.md section 7.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
