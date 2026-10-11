#!/usr/bin/env python3
"""Watch Automatic Status Back pushes. Uses no paper.

The printer sends a 4-byte block only when something *changes*, never when ASB
is switched on, so this needs someone to physically change something while it
is listening. Opening and closing the cover is the easiest trigger, and on this
unit it is harmless - it is also the fix for the false paper-out.

    python3 tools/asb_watch.py                 # listen for 120 s
    python3 tools/asb_watch.py --seconds 300

Every block that arrives is decoded and timestamped. ASB is switched off again
on the way out, including if you interrupt it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epson_tm_t88v import Printer, StatusClass  # noqa: E402
from epson_tm_t88v.status import AsbStatus  # noqa: E402
from epson_tm_t88v import commands as cmd  # noqa: E402


#: Every flag an ASB block carries, in the order worth reading them.
FLAGS = (
    ("cover_open", "cover open"),
    ("paper_present", "out of paper"),                 # inverted below
    ("paper_near_end", "paper near end"),
    ("online", "offline"),                             # inverted below
    ("wait_for_online_recovery", "waiting for online recovery"),
    ("paper_feed_button_pressed", "feed button pressed"),
    ("feeding_by_button", "feeding by button"),
    ("autocutter_error", "autocutter error"),
    ("unrecoverable_error", "unrecoverable error"),
    ("auto_recoverable_error", "auto-recoverable error"),
    ("drawer_pin_high", "drawer pin high"),
)
#: These read true when healthy, so they are reported when false.
INVERTED = {"paper_present", "online"}


def describe(block: AsbStatus) -> str:
    """One line naming only what is actually true of this push."""
    flags = []
    for attr, label in FLAGS:
        value = getattr(block, attr)
        if attr in INVERTED:
            value = not value
        if value:
            flags.append(label)
    return ", ".join(flags) if flags else "nothing flagged (back to normal)"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--device", default=None, help="device node (default: auto-discover)")
    ap.add_argument("--seconds", type=float, default=120.0, help="how long to listen")
    args = ap.parse_args()

    printer = Printer(args.device)
    print(f"printer: {printer.identity()}")
    print(f"status:  {printer.status()}")
    print()
    print(f"ASB on. Listening for {args.seconds:g}s.")
    print(">>> Open the printer cover, wait a second, then close it. <<<")
    print(flush=True)

    received = []
    try:
        printer.enable_status_push(StatusClass.ALL)
        deadline = time.monotonic() + args.seconds
        started = time.monotonic()
        while time.monotonic() < deadline:
            block = printer.read_status_push(timeout=0.5)
            if block is None:
                continue
            elapsed = time.monotonic() - started
            received.append(block)
            raw = getattr(block, "raw", b"")
            raw_hex = raw.hex(" ") if isinstance(raw, (bytes, bytearray)) else str(raw)
            # Flushed explicitly: stdout is block-buffered when redirected to
            # a file, and a listener whose output only appears when it exits
            # is useless for watching a live test.
            print(f"  [{elapsed:6.1f}s] push {raw_hex}  ->  {describe(block)}",
                  flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        # Leave the printer as it was found, whatever happened above.
        try:
            printer.write_raw(cmd.automatic_status_back(StatusClass(0)))
        except Exception as exc:                      # noqa: BLE001
            print(f"warning: could not switch ASB off: {exc}", file=sys.stderr)
        printer.close()

    print()
    if received:
        print(f"{len(received)} push(es) received - ASB works on this unit.")
        return 0
    print("No pushes arrived. Either nothing changed, or ASB does not push on "
          "this firmware. Re-run and make sure the cover actually opens.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
