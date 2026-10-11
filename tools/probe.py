#!/usr/bin/env python3
"""Interrogate a TM-T88V and report everything it will tell you. Uses no paper.

Re-run this after any firmware or configuration change, or to re-establish the
capability map on a different unit. It reproduces the investigation recorded in
FINDINGS.md.

    python3 tools/probe.py                     # default device
    python3 tools/probe.py --device /dev/usb/lp0
    python3 tools/probe.py --json report.json

By default it does NOT enter user setting mode, because leaving that mode
software-resets the printer and forces a USB re-enumeration. Pass
--customize-values to include it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import Printer, UsbTransport, commands as cmd  # noqa: E402
from epson_tm_t88v.exceptions import PrinterError  # noqa: E402
from epson_tm_t88v.status import SymbolSize  # noqa: E402

SYMBOLOGIES = {
    48: "PDF417",
    49: "QR Code",
    50: "MaxiCode",
    51: "GS1 DataBar (2D)",
    52: "Composite",
    53: "Aztec",
    54: "DataMatrix",
}


def hx(b: bytes) -> str:
    return b.hex(" ") if b else "(no reply)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=None, help="device node (default: auto-discover)")
    ap.add_argument("--json", default=None, help="also write the report as JSON")
    ap.add_argument(
        "--customize-values",
        action="store_true",
        help="read stored settings; this RESETS the printer on exit",
    )
    args = ap.parse_args()

    report: dict = {}
    transport = UsbTransport(args.device)
    printer = Printer(transport)
    print(f"device: {transport.device}\n")

    ident = printer.identity()
    report["identity"] = {
        "maker": ident.maker, "model": ident.model, "firmware": ident.firmware,
        "serial": ident.serial, "model_id": ident.model_id,
        "type_id": ident.type_id, "firmware_id": ident.firmware_id,
        "has_autocutter": ident.has_autocutter,
        "has_multibyte_font": ident.has_multibyte_font,
        "has_customer_display": ident.has_customer_display,
    }
    print("== identity ==")
    print(f"  {ident}")
    print(f"  model id 0x{ident.model_id:02X}  type id 0x{ident.type_id:02X}"
          f"  firmware id 0x{ident.firmware_id:02X}")
    print(f"  autocutter: {ident.has_autocutter}   multibyte font: "
          f"{ident.has_multibyte_font}   customer display: {ident.has_customer_display}")

    status = printer.status()
    report["status"] = {
        "ok": status.ok, "problems": status.problems,
        "raw": {
            "printer": status.printer.raw, "offline": status.offline.raw,
            "errors": status.errors.raw, "paper": status.paper.raw,
        },
    }
    print("\n== status ==")
    print(f"  {status}")
    print(f"  DLE EOT 1..4 = 0x{status.printer.raw:02X} 0x{status.offline.raw:02X} "
          f"0x{status.errors.raw:02X} 0x{status.paper.raw:02X}")

    mem = printer.graphics_memory()
    report["graphics_memory"] = mem
    print("\n== graphics memory ==")
    for k, v in mem.items():
        print(f"  {k:22s} {v}")

    print("\n== legacy status commands ==")
    legacy = {}
    for label, command in (
        ("ESC u 0", b"\x1b\x75\x00"), ("ESC v", b"\x1b\x76"),
        ("GS r 1", b"\x1d\x72\x01"), ("GS r 2", b"\x1d\x72\x02"),
    ):
        reply = transport.query(command, expect=1, timeout=0.5)
        legacy[label] = reply.hex()
        print(f"  {label:10s} -> {hx(reply)}")
    report["legacy_status"] = legacy

    print("\n== synchronisation ==")
    ack = transport.query(cmd.response_to_host(b"PROBE"), terminator=b"\x00", timeout=2.0)
    print(f"  GS ( H job barrier -> {hx(ack)}")
    clr = transport.query(cmd.clear_buffer(), terminator=b"\x00", timeout=1.0)
    print(f"  DLE DC4 8 buffer clear -> {hx(clr)}")
    report["sync"] = {"response_to_host": ack.hex(), "clear_buffer": clr.hex()}

    print("\n== maintenance counters (GS g 2) ==")
    counters = {}
    for m in (10, 11, 12, 13, 20, 21, 22, 50, 51, 52, 53, 70, 71, 72, 73, 80):
        reply = transport.query(
            bytes((0x1D, 0x67, 0x32, 0x02, 0x00, 0x00, m)), terminator=b"\x00", timeout=0.3
        )
        if reply:
            counters[m] = reply.hex()
    report["maintenance_counters"] = counters
    print(f"  {len(counters)} of 16 documented counters answered"
          f"{'' if counters else '  -> not supported on this firmware'}")

    print("\n== 2-D symbologies (store a payload, ask for its size) ==")
    symbols = {}
    probes = {
        48: b"HELLO", 49: b"HELLO", 50: b"123456789012345678901234567890",
        51: b"1234567890123", 52: b"1234567890123", 53: b"HELLO", 54: b"HELLO",
    }
    for cn, name in SYMBOLOGIES.items():
        transport.write(cmd.initialize())
        if cn == 50:
            transport.write(cmd.maxicode_mode(52))
        data = probes[cn]
        body = bytes((cn, 80, 48)) + data
        transport.write(bytes((0x1D, 0x28, 0x6B, len(body) & 0xFF, len(body) >> 8)) + body)
        reply = transport.query(cmd.transmit_symbol_size(cn), terminator=b"\x00", timeout=1.0)
        if not reply:
            symbols[name] = {"supported": False, "reason": "no reply"}
            print(f"  {name:18s} NOT SUPPORTED (no reply)")
            continue
        size = SymbolSize.decode(reply)
        symbols[name] = {
            "supported": size.encoded, "width": size.width,
            "height": size.height, "error_code": size.error_code,
        }
        if size.encoded:
            print(f"  {name:18s} OK   {size.width} x {size.height} dots")
        else:
            print(f"  {name:18s} recognised but payload rejected (error {size.error_code})")
    report["symbologies"] = symbols

    print("\n== QR capacity ==")
    qr_caps = {}
    for n in (100, 1000, 7089):
        try:
            size = printer.qr_size(b"1" * n, module=1)
            qr_caps[n] = [size.width, size.height]
            print(f"  {n:5d} digits -> {size.width} x {size.height} dots")
        except PrinterError as exc:
            qr_caps[n] = None
            print(f"  {n:5d} digits -> failed: {exc}")
    report["qr_capacity"] = qr_caps

    if args.customize_values:
        print("\n== stored customize values ==")
        print("  (entering user setting mode; the printer will RESET on exit)")
        values = printer.read_customize_values()
        report["customize_values"] = values
        for a in sorted(values):
            print(f"  a={a:<4d} {values[a]}")
        printer.exit_user_setting_mode()
        print("  printer reset issued - it will re-enumerate on USB")

    transport.write(cmd.initialize())
    printer.close()

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
