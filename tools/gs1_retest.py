#!/usr/bin/env python3
"""Settle whether GS1-128 and GS1 DataBar Expanded print on this unit.

The 2026-10-03 calibration print produced HRI text but no bars for these two
symbologies. The sample data it used carried a CODE128 ``{B`` code-set prefix,
which is correct for CODE128 but is not a valid lead-in for a GS1 element
string, so that result does not prove the printer lacks them. This tries
several properly-formed payloads instead.

Each block prints its payload as a label and then the barcode. A block with
label text but no bars underneath means the printer rejected that payload.

    python3 tools/gs1_retest.py
    python3 tools/gs1_retest.py --dry-run out.bin

About 12 cm of paper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import (  # noqa: E402
    Barcode,
    CutMode,
    FileTransport,
    Font,
    HriPosition,
    Justification,
    Printer,
    TM_T88V_80MM,
)
from epson_tm_t88v.exceptions import PrinterError  # noqa: E402

PROFILE = TM_T88V_80MM

#: (symbology, payload, what the payload is) - all properly-formed GS1 data.
CANDIDATES: List[Tuple[Barcode, str, str]] = [
    (Barcode.GS1_128, "(01)12345678901231", "AI in parentheses, GTIN-14"),
    (Barcode.GS1_128, "0112345678901231", "AI without parentheses"),
    (Barcode.GS1_128, "12345678901231", "bare digits, no AI"),
    (Barcode.GS1_DATABAR_EXPANDED, "(01)12345678901231", "AI in parentheses"),
    (Barcode.GS1_DATABAR_EXPANDED, "0112345678901231", "AI without parentheses"),
    (Barcode.GS1_DATABAR_EXPANDED, "(10)ABC123", "AI 10, alphanumeric"),
]


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
        with p.style(bold=True, justify=Justification.CENTER):
            p.textln("GS1 RETEST")
        with p.style(font=Font.B, justify=Justification.CENTER):
            p.textln("a label with no bars under it = rejected")
        p.rule("=")
        p.feed(1)

        last = None
        for symbology, payload, description in CANDIDATES:
            if symbology is not last:
                with p.style(reverse=True, bold=True):
                    p.textln(f" {symbology.name} ".ljust(PROFILE.columns(Font.A)))
                last = symbology
            with p.style(font=Font.B):
                p.textln(f"{payload}   [{description}]")
            try:
                p.barcode(symbology, payload, height=40, module_width=2,
                          hri=HriPosition.BELOW)
            except (ValueError, PrinterError) as exc:
                with p.style(font=Font.B, bold=True):
                    p.textln(f"  !! driver rejected: {exc}")
            p.feed(1)

        p.rule("=")
        with p.style(font=Font.B):
            p.textln("Record the answer in FINDINGS.md section 7.")
        p.cut(CutMode.FULL, feed=4)

        if not args.dry_run:
            p.wait_for_completion(timeout=120.0)

    print("\nRead the strip: for each payload, did bars print under the label?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
