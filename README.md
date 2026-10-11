# epson-tm-t88v

A Python driver for the **Epson TM-T88V** thermal receipt printer, talking
directly to the Linux `usblp` character device (`/dev/usb/lp0`).

That device is **bidirectional**, which is the whole point of this library:
status, errors and job completion are real, queryable facts rather than
fire-and-forget guesses.

* **No required dependencies.** Pillow is optional and only needed to load
  image *files*.
* **The printer does its own barcode encoding** — QR (full spec, up to version
  40), PDF417 and MaxiCode are generated in firmware, so there is no `qrcode`
  or `python-barcode` dependency.
* **Images cannot start mid-line.** The driver tracks this and fixes it for
  you; see [The column-0 rule](#the-column-0-rule).

Everything the driver claims about this printer was measured against real
hardware. See **[FINDINGS.md](FINDINGS.md)** for the raw evidence, and
**[NEXT-SESSION.md](NEXT-SESSION.md)** for what is still unverified.

---

## Install

```bash
pip install -e .            # driver only
pip install -e '.[images]'  # plus Pillow, for loading image files
```

### Device permissions

The device node is usually owned by the `lp` group:

```bash
ls -l /dev/usb/lp0
sudo usermod -aG lp "$USER"   # log out and back in
```

If the node does not exist at all, make sure the `usblp` kernel module is
loaded and that CUPS has not claimed the printer — CUPS binds the device
exclusively and `usblp` will not appear while it holds it.

The driver looks for `/dev/usb/lp*` and `/dev/usblp*`. If the node lives
somewhere else — a different name, or a path it has been bind-mounted to — point
`EPSON_TM_T88V_DEVICE` at it and discovery will prefer it:

```bash
export EPSON_TM_T88V_DEVICE=/some/other/lp0
```

That keeps site-specific paths out of both the code and the command line.

---

## Quick start

```python
from epson_tm_t88v import Printer, Font, Justification, Underline

with Printer() as p:
    p.status().raise_for_status()          # refuse to print into a fault

    with p.style(bold=True, width=2, height=2, justify=Justification.CENTER):
        p.textln("CAFE EXAMPLE")

    p.rule("=")
    p.columns("Espresso", "2.50")
    p.columns("Croissant", "3.20")
    p.rule("-")
    with p.style(bold=True, height=2):
        p.columns("TOTAL", "5.70")

    p.qr("https://example.com/receipt/1234", module=5)
    p.cut()
```

---

## Status and errors

Four real-time registers are readable at any time, **even while the printer is
busy or offline** — with one exception: a printer left waiting for the payload
of a half-sent command reads these queries as data and answers nothing. See
[Recovering from a stuck job](#recovering-from-a-stuck-job).

```python
s = p.status()
print(s)                 # "ready", or "cover is open; out of paper"
s.ok                     # bool
s.problems               # ['paper roll near end']
s.raise_for_status()     # raises PrinterOffline / PrinterFault

s.paper.present          # the reliable one
s.paper.near_end         # advisory - see the note below
s.offline.cover_open
s.errors.autocutter_error
s.errors.unrecoverable_error
```

> **Note on `near_end`.** On the unit this driver was developed against, the
> near-end sensor flipped between "near end" and "adequate" with the roll
> untouched, and reported "near end" on a roll that was plainly full.
> `raise_for_status()` deliberately does **not** treat it as blocking. Use
> `paper.present` to decide whether you can print.
>
> The sensor is not harmless, though. On this unit it has lit the front-panel
> paper LED and taken the printer **offline mid-job** on a full roll, which
> stalls writes and can leave a command half-sent. Opening and closing the
> cover clears it. If a long job dies for no apparent reason, look at the front
> panel before looking at your code.

### Knowing a job actually finished

```python
p.textln("receipt")
p.cut()
p.wait_for_completion()   # blocks until the printer has consumed everything
```

This uses `GS ( H`, which echoes a token back only once the printer has worked
through all preceding data. It is the only reliable completion signal.

### Recovering from a stuck job

There are two different kinds of stuck, and they need different cures.

**Queued work you want to throw away** — the printer is still talking, you just
want the buffer emptied:

```python
p.abort()     # real-time buffer clear; no power cycle needed
```

**A printer that has gone completely silent.** If a write failed part-way
through a command, the printer is still waiting for the rest of that command's
payload, and it consumes everything sent afterwards as data — including
real-time status queries. It looks dead while being perfectly healthy, and
`abort()` will not reach it:

```python
if p.transport.desynced:
    p.resync()        # feeds harmless filler until it answers, then ESC @
```

`resync()` returns `False` if the printer is stuck on something else. The most
common reason for the write to have failed in the first place is the printer
going offline mid-job — **check the front panel for a lit paper LED, and open
and close the cover**, which clears a false paper-out on this unit. The USB
printer-class `LPGETSTATUS` ioctl is not a reliable witness for that condition;
it has reported "ready" with the LED lit. FINDINGS.md section 9 has the whole
story.

### Push notifications

```python
p.enable_status_push()
while True:
    event = p.read_status_push(timeout=5.0)
    if event and not event.paper_present:
        alert("printer is out of paper")
```

The printer sends a block only when something *changes*, not when you enable
it. This path is **not yet verified on hardware** — see NEXT-SESSION.md.

---

## Text

```python
p.textln("plain")

with p.style(bold=True, underline=Underline.SINGLE):
    p.textln("bold and underlined")

with p.style(height=2):            # the classic "double height"
    p.textln("TALL")

with p.style(width=2, height=2):
    p.textln("TALL AND WIDE")

with p.style(width=4, height=4):   # GS ! goes to 8x on each axis
    p.textln("HUGE")
```

Styles nest and restore themselves on exit. Everything available:
`font`, `bold`, `underline`, `width`, `height`, `reverse`, `upside_down`,
`rotate_90`, `double_strike`, `smoothing`, `justify`, `color`.

Text is encoded in the selected character code table with `errors="strict"`,
so a character the table cannot express raises `EncodingError` rather than
silently vanishing from a receipt:

```python
from epson_tm_t88v import CharacterSet

p.set_charset(CharacterSet.WPC1252)
p.textln("€12,50")
```

### Which tables this printer actually has

All twelve `ESC t` tables and all fourteen `ESC R` national variants are
installed — confirmed by printing every one of them and comparing the glyphs
(`tools/charsets.py`). Two things are worth knowing:

* **`ESC t 48` is Windows-1254, not PC857.** It is `CharacterSet.WPC1254_TURKISH`
  and encodes with `cp1254`. The two code pages put the Turkish letters in
  completely different slots, so the earlier `cp857` pairing turned every one of
  them into something else (`ğ` → `§`, `Ğ` → `¦`, `ş` → `Ÿ`…) with no error.
* **Katakana has no Python codec**, and is the only table without one.
  `text()` raises `EncodingError` pointing you at `write_raw()` rather than
  guessing at an encoding.

---

## Images

```python
from epson_tm_t88v import from_image, from_grayscale

p.image("logo.png")                       # needs Pillow; scaled to fit
p.image("photo.jpg", dither=True)         # Floyd-Steinberg, good for photos
p.image("logo.png", dither=False)         # threshold, better for line art

# No Pillow? Build the raster yourself - pure Python, no dependencies.
raster = from_grayscale(pixels, width=320, height=200, dither=True)
p.image(raster)
```

Tall images are automatically split into horizontal bands so no single command
overruns the printer. The receive buffer is only 4 KB
(`Profile.receive_buffer_bytes`), so bands are sized in **bytes**, not rows, and
the driver waits for the printer to work through each band before sending the
next. That is what stops a large image meeting a full buffer and stalling
mid-command:

```python
p.image(raster, band_rows=64)    # an upper bound; the byte budget still wins
p.image(raster, pace=False)      # skip the waits (only if you know the buffer is clear)
```

Pacing needs a transport that can carry replies, so it is on for real hardware
and off for `BufferTransport` and `FileTransport`.

Both raster paths are available:

```python
from epson_tm_t88v import ImageCommand

p.image(raster, command=ImageCommand.GRAPHICS)  # GS ( L / GS 8 L, the default
p.image(raster, command=ImageCommand.RASTER)    # GS v 0, the legacy path
```

### The column-0 rule

A raster image sent while text is still pending on the current line is printed
**offset**, wraps, and ruins the output — a reliable way to waste a lot of
paper. The driver tracks whether the current line is dirty and emits a line
feed before any image, barcode or 2-D symbol:

```python
p.text("no newline here")
p.image(logo)          # driver inserts the line feed for you
```

This is on by default. `Printer(auto_line_start=False)` disables it if you are
managing print position yourself.

---

## Barcodes and 2-D codes

All encoding happens in the printer's firmware.

```python
from epson_tm_t88v import Barcode, HriPosition, QrErrorCorrection

p.barcode(Barcode.EAN13, "123456789012", height=64, hri=HriPosition.BELOW)
p.barcode(Barcode.CODE128, "{BHello")

p.qr("https://example.com", module=5, error_correction=QrErrorCorrection.H)
p.pdf417("payload", columns=0)              # 0 = automatic
p.maxicode("payload", mode=MaxiCodeMode.MODE_4)
```

Obvious data errors are caught before anything reaches paper — wrong digit
counts for UPC/EAN, odd digit counts for ITF, missing CODABAR start/stop
characters.

### Will it fit?

```python
size = p.qr_size("a very long payload...", module=5)
print(size.width, size.height, size.encoded)
if size.width > p.profile.print_width_dots:
    ...   # reduce the module size before committing paper
```

### Support on this model

| | |
|---|---|
| QR Code | ✅ full spec, to version 40 (7089 digits) — but **Model 2 only**, model selection is silently ignored |
| PDF417 | ✅ all parameters verified to take effect |
| MaxiCode | ✅ modes 4–6; modes 2–3 need a structured carrier message |
| Aztec | ❌ not supported by this model |
| DataMatrix | ❌ not supported by this model |
| 1-D symbologies | ✅ all 14 confirmed on paper (below) |

`GS k` has no query form, so the 1-D list was settled by printing one of each
and reading the receipt. All fourteen print:

| Symbology | |
|---|---|
| UPC-A, UPC-E, EAN13, EAN8 | ✅ |
| CODE39, ITF, CODABAR, CODE93, CODE128 | ✅ |
| GS1 DataBar Omnidirectional / Truncated / Limited | ✅ give it 13 plain digits; the printer adds the AI and check digit |
| GS1-128, GS1 DataBar Expanded | ✅ give it a GS1 element string (see below) |

**Mind the payload for the two GS1 ones.** Handed data starting with `{B` —
a CODE128 code-set selector, correct for CODE128 and meaningless at the start
of a GS1 element string — they print **human-readable text and no bars at all**,
silently. The driver now rejects that rather than letting it fail quietly:

```python
p.barcode(Barcode.GS1_128, "{B012345678901231")   # ValueError
p.barcode(Barcode.GS1_128, "(01)12345678901231")  # works
p.barcode(Barcode.GS1_128, "0112345678901231")    # works, parentheses optional
```

Both accept the application identifier with or without parentheses, and
DataBar Expanded also takes alphanumeric data under AI 10 (`"(10)ABC123"`).
`Profile.verified_barcodes` holds the confirmed set programmatically.

---

## Page mode

Compose freely in a 2-D area, then print it in one go:

```python
from epson_tm_t88v import PrintDirection

with p.page(x=0, y=0, width=400, height=200) as page:
    page.at(0, 24).text("top left")
    page.at(200, 100).text("middle")
```

All positions and sizes are in **dots**, vertical ones included; the driver
converts to the printer's half-dot vertical units for you (FINDINGS.md
section 11). `y` is where the **bottom** of the text goes, so text placed at
`y=0` is entirely above the area: give it at least its font height (24 dots
for Font A, 17 for Font B).

---

## Cutting

```python
p.cut()                    # partial, after feeding clear of the head
p.cut(CutMode.FULL)
```

> **On this unit the partial cut is not a partial cut.** `GS V 1` separates the
> paper exactly as `GS V 0` does — no holding tab is left. The driver emits the
> two distinct commands correctly; the cutter mechanism does not distinguish
> them. `Profile.partial_cut_leaves_tab` is `False`, and nothing should be
> built on a partial cut holding the receipt in place.

`cut()` feeds clear of the print head first, because the cutter sits well above
it; without that the cut lands in the middle of the last few lines.

---

## Paper width

| Roll | Dots | Font A | Font B |
|---|---|---|---|
| 80 mm | **512** (72.2 mm) | 42 cols | 56 cols |
| 58 mm | 360 (50.8 mm) | 30 cols | 40 cols |

```python
from epson_tm_t88v import Printer, TM_T88V_58MM
p = Printer(profile=TM_T88V_58MM)
```

> **Do not use 576 dots with this printer.** That figure belongs to 203 dpi
> 80 mm printers. The TM-T88V is **180 dpi**, where 576 dots would be 81.3 mm
> — wider than the paper.
>
> This is measured, not assumed. A 576-dot bar sent raw, bypassing the driver's
> own width check, came out **511.7 dots** — the printer clips at 512. The same
> print measured the 360- and 512-dot bars at 360.2 and 512.0 dots, and the
> Font A / Font B rulers wrapped at exactly 42 and 56 columns. FINDINGS.md
> section 7.1 has the numbers.

---

## Tools

```bash
python3 tools/probe.py                 # interrogate the printer, uses no paper
python3 tools/probe.py --json out.json
python3 tools/calibrate.py             # one ~30 cm calibration receipt
python3 tools/calibrate.py --sections width,image
python3 tools/calibrate.py --dry-run out.bin   # byte stream, no printer needed
python3 tools/gs1_retest.py            # ~12 cm, GS1 payload formats
python3 tools/charsets.py              # ~20 cm, every ESC t table and ESC R variant
python3 tools/asb_watch.py             # no paper; listens for ASB pushes
```

`calibrate.py`, `gs1_retest.py` and `charsets.py` all refuse to start if the
printer reports a fault, take `--dry-run`, and print a checklist of what to
look for on the paper.

`asb_watch.py` needs someone to change something physical while it listens —
ASB only transmits on a change, never when it is switched on. Opening and
closing the cover is the easiest trigger.

Every tool takes `--device`, and all of them honour `EPSON_TM_T88V_DEVICE`.

---

## Testing

```bash
python3 -m pytest tests/ -q
```

55 tests, none of which need a printer. `BufferTransport` captures the byte
stream so command sequences can be asserted exactly; several tests replay
status bytes captured from real hardware.

---

## A caveat for containers

A printer **software reset** (for example leaving user setting mode) makes the
device re-enumerate on USB. udev then deletes and recreates the device node as
a *new inode*. If you bind-mounted the node itself into a container, that mount
is now pinned to a deleted inode and the printer becomes unreachable from
inside — `mknod` and remounting are both denied in a rootless user namespace.

**Bind-mount the directory `/dev/usb`, not the node `/dev/usb/lp0`.**

---

## Licence

MIT.
