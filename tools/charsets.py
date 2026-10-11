#!/usr/bin/env python3
"""Print every ``ESC t`` character code table and every ``ESC R`` variant.

There is no query for either, so the only way to find out which tables this
firmware actually carries is to print them and look. A table the printer does
not have falls back to PC437, so **two blocks that look identical to PC437 mean
that table is absent**; that is the thing to look for when reading the result.

    python3 tools/charsets.py
    python3 tools/charsets.py --dry-run out.bin

Roughly 25 cm of paper. The high half of each table (0x80-0xFF) is printed as
raw bytes, deliberately bypassing the driver's text encoding, so that what
lands on paper is the printer's own glyph for each code point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import (  # noqa: E402
    CharacterSet,
    CutMode,
    FileTransport,
    Font,
    InternationalCharset,
    Justification,
    Printer,
    TM_T88V_80MM,
)
from epson_tm_t88v import commands as cmd  # noqa: E402

PROFILE = TM_T88V_80MM

#: The twelve code points ``ESC R`` overlays with national variants.
NATIONAL_POINTS = bytes((0x23, 0x24, 0x40, 0x5B, 0x5C, 0x5D, 0x5E,
                         0x60, 0x7B, 0x7C, 0x7D, 0x7E))


def raw_line(p: Printer, label: str, payload: bytes) -> None:
    """Emit ``label`` then ``payload`` verbatim, with no encoding applied."""
    p.write_raw(label.encode("ascii") + payload + b"\n")


def section_tables(p: Printer) -> None:
    with p.style(reverse=True, bold=True):
        p.textln(" ESC t  CHARACTER CODE TABLES ".ljust(PROFILE.columns(Font.A)))
    with p.style(font=Font.B):
        p.textln("High half of each table, 0x80-0xFF, 32 per row.")
        p.textln("A table identical to PC437 below is NOT installed.")
    p.feed(1)

    for table in CharacterSet:
        with p.style(font=Font.B, bold=True):
            p.textln(f"ESC t {int(table):<3d}  {table.name}")
        p.write_raw(cmd.character_set(table))
        p.set_style(font=Font.B)
        for start in range(0x80, 0x100, 32):
            raw_line(p, f"{start:02X} ", bytes(range(start, start + 32)))
        p.set_style(font=Font.A)
        p.feed(1)

    # Leave the printer on the driver's default, not whatever was last selected.
    p.write_raw(cmd.character_set(CharacterSet.PC437_USA_STANDARD_EUROPE))


def section_national(p: Printer) -> None:
    with p.style(reverse=True, bold=True):
        p.textln(" ESC R  INTERNATIONAL VARIANTS ".ljust(PROFILE.columns(Font.A)))
    with p.style(font=Font.B):
        p.textln("The 12 code points ESC R overlays:")
        p.textln("  23 24 40 5B 5C 5D 5E 60 7B 7C 7D 7E")
        p.textln("Rows that differ from USA are installed.")
    p.feed(1)

    for variant in InternationalCharset:
        p.write_raw(cmd.international_charset(variant))
        p.set_style(font=Font.B)
        raw_line(p, f"{variant.name:<14s} ", NATIONAL_POINTS)
    p.set_style(font=Font.A)
    p.write_raw(cmd.international_charset(InternationalCharset.USA))
    p.feed(1)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--device", default=None, help="device node (default: auto-discover)")
    ap.add_argument("--dry-run", metavar="FILE", default=None,
                    help="write the byte stream to FILE instead of printing")
    args = ap.parse_args()

    if args.dry_run:
        printer = Printer(FileTransport(args.dry_run), profile=PROFILE)
    else:
        printer = Printer(args.device, profile=PROFILE)
        status = printer.status()
        print(f"printer: {printer.identity()}")
        print(f"status:  {status}")
        if not status.ok:
            print("\nrefusing to print - fix the above first", file=sys.stderr)
            printer.close()
            return 1

    with printer as p:
        p.set_style(justify=Justification.LEFT, font=Font.A)
        with p.style(bold=True, width=2, height=2, justify=Justification.CENTER):
            p.textln("CHARSETS")
        p.rule("=")
        section_tables(p)
        section_national(p)
        p.rule("=")
        p.cut(CutMode.FULL, feed=4)
        if not args.dry_run:
            p.wait_for_completion(timeout=180.0)

    print("\nWhat to check:")
    print("  1. which ESC t blocks differ from PC437 (those are installed)")
    print("  2. which ESC R rows differ from USA (those are installed)")
    print("\nRecord the answers in FINDINGS.md section 7.7.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
