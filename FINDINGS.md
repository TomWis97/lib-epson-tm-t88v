# TM-T88V capability investigation — raw findings

Everything in this file was measured against the physical printer on 2026-10-03,
not taken from a datasheet. Where something is an interpretation rather than an
observation it is marked **(inferred)**.

Probing was done over the USB printer-class device node, which the host exposes
at `/dev/usb/lp0` (udev `DEVNAME=usb/lp0`). It was bind-mounted into the
development container as `/workspace/lp0`; that container path appears in the
raw logs below but **must never appear in shipped code** — the library defaults
to `/dev/usb/lp0` and auto-discovers `/dev/usb/lp*` and `/dev/usblp*`.

---

## 1. Hardware identity

| Property | Value | Source |
|---|---|---|
| Maker | `EPSON` | `GS I 66` → `5F 45 50 53 4F 4E 00` |
| Model | `TM-T88V` | `GS I 67` → `5F 54 4D 2D 54 38 38 56 00` |
| Firmware | `30.13 ESC/POS` | `GS I 65` → `5F 33 30 2E 31 33 20 45 53 43 2F 50 4F 53 00` |
| Serial (command) | `MQAF009470` | `GS I 68` |
| Serial (USB descriptor) | `405141460094700000` | sysfs |
| USB ID | `04b8:0202` | sysfs |
| Printer model ID | `0x20` | `GS I 1` |
| Type ID | `0x02` | `GS I 2` |
| Firmware ID | `0x64` (100) | `GS I 3` |
| `GS I 69` (font of language) | empty (`5F 00`) | — |
| `GS I 112` / `GS I 113` | `0` / `1` | undocumented, recorded for completeness |

`GS I 33..37` (the alternate numbering for the same strings) return **nothing** —
this firmware only answers the `65..69` form.

**Type ID `0x02` decoded (inferred from the standard ESC/POS bit layout):**
bit0 = 0 → no multi-byte character support (ANK model);
bit1 = 1 → **autocutter installed**; bit2 = 0 → no DM-D customer display.

Paper confirmed by the owner: **80 mm roll**. At this printer's **180 dpi**
that is **512 printable dots = 72.2 mm**, giving 42 columns in Font A (12×24)
and 56 in Font B (9×17) — 42×12 = 504 and 56×9 = 504, both just inside 512.

⚠ **Do not use 576 dots for this printer.** 576 is the figure for 203 dpi
80 mm printers (TM-T20/T82 and most generic ones); at 180 dpi it would be
81.3 mm, wider than the paper. An over-wide raster is clipped or wrapped by the
printer and ruins the print. 58 mm paper on this model gives 360 dots (30/40
columns). The ruler band in `tools/calibrate.py` measures this directly — it is
the single most important number to confirm.

---

## 2. Status reporting — all verified working

The device node is **bidirectional**: it opens `O_RDWR` and the printer answers
queries on the same file descriptor. This is the basis for all status handling.

### 2.1 Real-time status, `DLE EOT n` (`10 04 n`)

Observed on a healthy, idle printer:

| Query | Response | Meaning |
|---|---|---|
| `DLE EOT 1` printer status | `0x16` | online, drawer pin 3 high |
| `DLE EOT 2` offline cause | `0x12` | cover closed, no paper-end stop, no error |
| `DLE EOT 3` error cause | `0x12` | no cutter / recoverable / unrecoverable error |
| `DLE EOT 4` paper sensor | `0x1E` then `0x12` | see note below |

`DLE EOT 7 m` and `DLE EOT 8 3` return **nothing** — not supported on this model.

**Note on the paper sensor:** the first read returned `0x1E` (near-end bits 2+3
set → "roll near end"), a later read returned `0x12` (adequate). The owner had
physically checked the roll in between. The roll-end sensor read "paper present"
throughout. Treat the **near-end sensor on this unit as borderline/twitchy** —
the library exposes it but should not be used as a hard gate.

Bit layouts used by `status.py`, consistent with every reading taken:

```
DLE EOT 1 (printer status)
  bit0 0   bit1 1(fixed)   bit2 drawer kick pin3 (1=high)
  bit3 1=offline           bit4 1(fixed)   bit7 0

DLE EOT 2 (offline cause)
  bit2 1=cover open        bit3 1=feeding by FEED button
  bit5 1=stopped, paper end                bit6 1=error occurred

DLE EOT 3 (error cause)
  bit2 1=recoverable error bit3 1=autocutter error
  bit5 1=unrecoverable error               bit6 1=auto-recoverable error

DLE EOT 4 (paper sensor)
  bits2+3 = 11 -> roll paper near end
  bits5+6 = 11 -> roll paper NOT present (paper out)
```

### 2.2 Legacy status commands — all working, all consistent

| Command | Response | Meaning |
|---|---|---|
| `ESC u 0` (`1B 75 00`) | `0x01` | drawer kick pin 3 high |
| `ESC v` (`1B 76`) | `0x03` | near-end set, paper present |
| `GS r 1` (`1D 72 01`) | `0x03` | paper sensor, same as `ESC v` |
| `GS r 2` (`1D 72 02`) | `0x01` | drawer kick status |

### 2.3 `GS ( H` — job completion barrier (**important**)

`GS ( H pL pH fn=48 m=48 <id bytes>` echoes the id back **only after the printer
has consumed everything queued before it**:

```
send: 1D 28 48 06 00 30 30 54 45 53 54      ("TEST")
recv: 37 22 54 45 53 54 00                  header 0x37, id 0x22, "TEST", NUL
```

This is a genuine synchronisation primitive — the library uses it for
`Printer.wait_for_completion()`. `GS ( H fn=49` (offline response) returns
nothing and is not supported.

### 2.4 `DLE DC4 fn=8` — real-time buffer clear

```
send: 10 14 08 01 03 14 01 06 02 08
recv: 37 25 00
```

Acknowledged. This aborts a stuck job without power-cycling, and is exposed as
`Printer.abort()`.

### 2.5 Automatic Status Back (ASB), `GS a n` — verified working

Confirmed on hardware 2026-10-03 with `tools/asb_watch.py`, by opening and
closing the cover twice while listening:

```
[   0.0s] push 14 00 00 0f  ->  drawer pin high          <- on enable
[  80.5s] push 3c 00 00 0f  ->  cover open, offline
[  87.0s] push 14 00 00 0f  ->  back to normal
[ 135.5s] push 3c 00 00 0f  ->  cover open, offline
[ 138.1s] push 14 00 00 0f  ->  back to normal
```

Two things to note.

**A block *is* sent the moment ASB is enabled**, carrying the current state.
An earlier note here said no immediate push arrived with `n=0xFF` or `n=0x0F`;
that is contradicted by the timestamped capture above, and was most likely a
read that did not wait long enough. The first `read_status_push()` after
enabling therefore returns a baseline rather than blocking until something
happens, which is the more useful behaviour.

**The fourth byte is not decoded.** It read `0f` in every block observed, in
both the idle and cover-open states, so nothing can be inferred from it. Paper
status is decoded from the *third* byte, which reads `00` while paper is
loaded — consistent with both the idle baseline and the cover test. If the
fourth byte were the paper byte, its `0f` would decode as "out of paper" on a
printer that was demonstrably printing, so the third byte is the right one.

### 2.6 Maintenance counters — NOT supported

`GS g 2 pL pH n m` was swept across **all 128 values of `m`** (and retried with a
1.2 s timeout on the documented set 10–13, 20–22, 50–53, 70–73, 80). Every single
one returned nothing. This firmware does not implement maintenance counters.

---

## 3. 2D symbologies — measured, not assumed

Method: store a payload with `GS ( k cn 80 48 <data>`, then ask the printer for
the resulting symbol dimensions with `GS ( k 3 0 cn 82 48`. The reply is
`37 <id> <width> US <height> US <f3> US <errcode> NUL`. **No paper used.**

| Symbology | `cn` | Result | Verdict |
|---|---|---|---|
| PDF417 | 48 | `462 × 27` for `"HELLO"` | **supported, fully parameterised** |
| QR Code | 49 | `63 × 63` for `"1234"` | **supported** |
| MaxiCode | 50 | `180 × 167` modes 4/5/6 | **supported** |
| GS1 DataBar (2D) | 51 | `0 × 0`, errcode 1, every payload | recognised but rejected — see note |
| Composite | 52 | `0 × 0`, errcode 11006 | recognised but rejected |
| Aztec | 53 | **no response at all** | **not supported** |
| DataMatrix | 54 | **no response at all** | **not supported** |

Aztec and DataMatrix arrived with the TM-T88VI; this model genuinely lacks them.

**GS1 DataBar note:** `cn=51` *is* parsed (it answers the size query with
identifier `0x4F`), but rejected `1234567890123` as Stacked, Stacked
Omnidirectional and Limited, and rejected both `0112345678901231` and
`{0112345678901231` as Expanded Stacked. **(inferred)** On this model GS1 DataBar
is reached through the 1-D `GS k` command (`m` = 75–78) instead. `GS k` has no
query form, so this can only be settled by printing — see §7.

### 3.1 QR Code — detailed behaviour

* **The printer encodes QR itself.** 7089 digits → `177 × 177` dots, which is
  QR **version 40, the maximum the QR standard defines**. Full capacity is
  available; no Python QR encoder is needed.
* Module size (`fn=67`): **1–16 valid** and linear (`n` → `21n` dots for a
  version-1 symbol). `n=17` silently falls back to the default of 3.
* Error correction (`fn=69`): all four levels work. For
  `"HELLO WORLD 1234567890"`: L and M → 63×63 (version 1), Q and H → 75×75
  (version 2).
* **Model selection (`fn=65`) is silently ignored.** Model 1, Model 2 and Micro
  QR all produce identical dimensions — `"AB"` as "Micro QR" still returns
  21×21, which is a full-size QR version 1, not any Micro QR size (M1–M4 are
  11/13/15/17 modules). **Treat QR on this printer as Model 2 only.**

Capacity ladder measured at module size 1, EC level L:

| digits | symbol | QR version |
|---|---|---|
| 100 | 29×29 | 3 |
| 500 | 53×53 | 9 |
| 1000 | 69×69 | 13 |
| 2000 | 97×97 | 20 |
| 3000 | 117×117 | 25 |
| 4000 | 137×137 | 30 |
| 5000 | 153×153 | 34 |
| 7089 | 177×177 | 40 (max) |

### 3.2 PDF417 — every parameter verified to take effect

Baseline `"HELLO"` → `462 × 27`.

| Setting | Command | Result |
|---|---|---|
| columns = 4 | `fn=65` | 462 → **411** wide |
| rows = 8 | `fn=66` | 27 → **72** tall |
| module width = 3 | `fn=67` | unchanged → 3 is already the default |
| row height = 4 | `fn=68` | 27 → **36** tall |
| EC level 2 | `fn=69` | unchanged (likely already the default) |
| truncated | `fn=70` | unchanged — parameter encoding needs rechecking |

### 3.3 MaxiCode

Modes 4, 5 and 6 encode a 30-digit payload to `180 × 167` dots. Modes 2 and 3
returned errcode 1 because they require a structured carrier message (postal
code / country code / service class), not free text. Mode 7 does not exist.

---

## 4. Graphics memory

| Query | Response | Value |
|---|---|---|
| `GS ( L fn=48` | `37 30 "262144" 00` | NV graphics capacity **262144 B (256 KB)** |
| `GS ( L fn=51` | `37 31 "262144" 00` | NV graphics remaining — **entirely free** |
| `GS ( L fn=52` | `37 32 "212992" 00` | **(inferred)** download-graphics area, 212992 B |
| `GS ( L fn=50`, `fn=64` | nothing | not supported |

The identical `GS 8 L` (32-bit length) forms return the same values, confirming
**both the `GS ( L` and `GS 8 L` graphics command families are implemented**.
`GS 8 L` is what the library uses for images taller than a single chunk.

---

## 5. Stored configuration (`GS ( E` user setting mode)

Read with the owner's explicit permission, using only the **read** functions
(`fn=1` enter, `fn=4` read memory switch, `fn=6` read customize value, `fn=2`
exit). The write functions `fn=3` and `fn=5` were deliberately never sent.

* Entering (`GS ( E 3 0 1 'I' 'N'`) → `37 20 00`, accepted.
* **Memory switches (`fn=4`, `a` = '1'..'8') returned nothing** — not readable
  on this firmware.
* **Customize values (`fn=6`) — 28 of 127 addresses responded.** Response format
  is `37 27 <a in ASCII> 1F <value in ASCII> 00`.

| `a` | value | | `a` | value | | `a` | value |
|---|---|---|---|---|---|---|---|
| 3 | 6 | | 100 | 1 | | 118 | 85 |
| 5 | 0 | | 101 | 0 | | 119 | 0 |
| 6 | 1 | | 102 | 0 | | 120 | 65535 |
| 8 | 0 | | 103 | 0 | | 121 | 1 |
| 9 | 0 | | 104 | 0 | | 122 | 1 |
| 10 | 1 | | 105 | 0 | | 123 | 1 |
| 97 | 1 | | 111 | 0 | | 124 | 1 |
| 98 | 2 | | 112 | 1 | | 125 | 2 |
| | | | 116 | 1 | | 126 | 1 |
| | | | 117 | 0 | | 127 | 0 |

**These are raw readings with no verified meaning.** Epson's ESC/POS reference
(`reference.epson-biz.com`) was shut down on 2024-06-16 and its replacement at
`support.epson.net/publist/reference_en` returns HTTP 403 to scripted clients,
so the `a`-number → setting-name table could not be obtained. Do not act on
guesses here; re-read them against the official PDF reference guide when
available. The numbers are recorded so a future session need not re-enter user
setting mode to get them.

### 5.1 ⚠ Exiting user setting mode resets the printer over USB

`GS ( E 4 0 2 'O' 'U' 'T'` performs a **software reset**. The printer
disconnected and re-enumerated on USB. The host's udev deleted and recreated
`/dev/usb/lp0` as a **new inode**, which severed the container's bind mount:

```
# /proc/self/mountinfo after the reset
1194 1332 0:6 /usb/lp0//deleted /workspace/lp0 rw,nosuid,relatime - devtmpfs dev ...
                        ^^^^^^^^
# ls -la /workspace/lp0
c--------- 0 nobody nobody 180, 0 ...      <- mode stripped to 0000, Links: 0
```

Recovery from inside the container was impossible: `mknod` is denied in the
rootless user namespace, remounting devtmpfs is denied, and `/dev/bus/usb` is
not mounted so there is no libusb fallback route.

**Two consequences, both important:**

1. **Container fix (host-side):** bind-mount the *directory* `/dev/usb` rather
   than the single node `/dev/usb/lp0`. A node recreated inside a bind-mounted
   directory is visible to the container; a bind-mounted node is pinned to one
   inode and dies with it. This change has to be made to the `claude-container`
   invocation on the host — it cannot be done from inside.
2. **Library policy:** any operation that resets the printer is marked as such
   and never issued implicitly. See `Printer.exit_user_setting_mode()`.

---

## 6. Behaviour notes that shaped the library

* **Writes can block with `EAGAIN`.** A burst of unsupported commands filled the
  receive buffer and the device stopped accepting data mid-write, raising
  `BlockingIOError` from a naive `os.write`. Every write in `transport.py` goes
  through a `select()` loop and raises `WriteTimeout` rather than silently
  truncating. The budget is an **idle** one, restarted on every byte the printer
  accepts — an early version used a fixed total deadline and aborted a perfectly
  healthy image hand-over simply because the printer was still busy (§9).
* **Images must start at column 0.** This is the owner's known paper-waster: if
  anything is pending in the line buffer when a raster image is sent, the image
  is offset and wraps, ruining the print. The library tracks whether the current
  line is dirty and emits a `LF` before any image, barcode or 2D symbol. This is
  automatic and on by default (`Printer(auto_line_start=True)`).
* `ESC @` (initialize) clears the print buffer **without** feeding or printing,
  so it is safe to use liberally as a recovery/reset-state step.

---

## 7. Settled on paper — calibration print read back 2026-10-03

The full nine-section calibration print was run, scanned on a flatbed at
600 dpi and measured. Every open question is now closed.

| # | Question | Answer | How |
|---|---|---|---|
| 1 | Printable width | **512 dots = 72.2 mm** | measured, three ways |
| 2 | 1-D symbologies | **all 14** print | one of each, plus a retest |
| 3 | Text decorations | **all render**, incl. double-height | visual |
| 4 | Character code tables (`ESC t`) | **all 12 installed**; one mislabelled | `tools/charsets.py` |
| 5 | Two-colour output | colour 2 **prints, in black** | mono paper loaded |
| 6 | Both image paths | **both work** | visual |
| 7 | ASB push on a real status change | **works**, plus one on enable | `tools/asb_watch.py` |
| 8 | Full vs partial cut | **not distinguishable** | owner observed |

### 7.1 Printable width is 512 dots — confirmed three independent ways

The scan resolves to 3.3203 scan px per printer dot, i.e. an effective
597.7 dpi against a 180 dpi printer — self-consistent, so the measurement below
is trustworthy.

| Bar as sent | Predicted px | Measured px | Dots actually printed |
|---|---|---|---|
| 360 dots | 1195 | 1196 | **360.2** |
| 512 dots | 1700 | 1700 | **512.0** |
| 576 dots (sent raw, bypassing the driver) | 1912 | 1699 | **511.7** |

The 576-dot bar was emitted with `GS v 0` directly so the driver's own width
check could not trim it. It came out **one pixel shorter than the 512 bar**:
the printer itself clips at 512 dots. 512 dots measures 72.2 mm on the paper,
exactly as predicted for 180 dpi.

Two further confirmations from the same print, using nothing but character
counts — the 70-character ruler string wrapped at:

* **Font A: 42 columns** (`----+----1…----+----4--` then `--+----5…----7`), and
  512 ÷ 12 = 42;
* **Font B: 56 columns** (`…----+----5----+-` then `---6----+----7`), and
  512 ÷ 9 = 56.

The full-width bar in section 7 of the print touches both paper edges.

**The earlier 576 estimate was wrong and 512 is now measured, not inferred.**
`Profile.print_width_dots` is correct as it stands.

### 7.2 All fourteen 1-D symbologies print

Printed a scannable symbol with HRI: **UPC-A, UPC-E, EAN13, EAN8, CODE39, ITF,
CODABAR, CODE93, CODE128, GS1 DataBar Omnidirectional, GS1 DataBar Truncated,
GS1 DataBar Limited.**

The three GS1 DataBar variants were given plain 13 digits and the printer
supplied the AI and check digit itself, printing HRI `(01)01234567890128`.
CODE93's HRI carries the usual start/stop guard glyphs.

**Printed HRI text but no bars at all: `GS1_128` and `GS1_DATABAR_EXPANDED`.**
The bar zone is literally blank — zero dark pixels where a 50-dot-high symbol
should be, with the HRI printed underneath as if nothing were wrong.

That was the **test data**, not the printer. Both payloads began with `{B`, a
CODE128 code-set selector:

```
CODE128                "{BCODE128"            -> printed fine
GS1_128                "{B012345678901231"    -> HRI only, no bars
GS1_DATABAR_EXPANDED   "{B0112345678901231"   -> HRI only, no bars
```

`{B` is correct for CODE128 and meaningless as the lead-in to a GS1 element
string, which must start with an application identifier.

`tools/gs1_retest.py` then printed six properly-formed payloads, three per
symbology, and the owner confirmed **all six produced barcodes**:

| Symbology | Payload | |
|---|---|---|
| GS1-128 | `(01)12345678901231` | ✅ |
| GS1-128 | `0112345678901231` | ✅ |
| GS1-128 | `12345678901231` | ✅ |
| GS1 DataBar Expanded | `(01)12345678901231` | ✅ |
| GS1 DataBar Expanded | `0112345678901231` | ✅ |
| GS1 DataBar Expanded | `(10)ABC123` | ✅ |

So both symbologies are fully supported, with or without parentheses around the
application identifier, and DataBar Expanded handles alphanumeric AI 10 as
well. **All fourteen symbologies the driver offers now print.**

The real defect was in the driver: it had no validation for these two and
passed bad data through to a silent non-result — a barcode call that "succeeds"
and produces nothing but text is the worst possible failure mode. It now
rejects a CODE128 code-set selector on both, naming the correct format.

### 7.3 Text decoration — everything renders

Confirmed on paper: normal, bold (`ESC E`), double-strike (`ESC G`), underline
1-dot and 2-dot (`ESC -`), double height, double width, double both, reverse
white-on-black (`GS B`), upside-down (`ESC {`), 90° rotation (`ESC V`), and
combined attributes (bold + underline + double-height together). The `GS !`
magnification grid prints every step from 1× to 8×, and **8× still fits the
line**. Mixed width/height combinations (w1h2, w2h1, w1h4, w4h1, w2h4) all
render.

Smoothing (`GS b`) is **clearly visible** at 3×: unsmoothed glyphs show hard
stair-stepping on every curve, smoothed ones are visibly rounded.

Fonts, justification and margins all behave: left/centre/right place correctly,
and a 100-dot left margin with a 300-dot width indents and wraps exactly as
asked.

### 7.4 Images — both paths, both renderings, and the column-0 guard

`GS ( L` fn=112 and the legacy `GS v 0` both produce identical, correctly
placed images. Floyd–Steinberg dithering renders the gradient strip as a smooth
tonal ramp; thresholding renders it as a hard black/white split, as it should.
Image borders come out as complete unbroken rectangles — nothing is clipped or
offset.

The column-0 guard works: text left pending on the line is flushed with a line
feed first, and the image below it prints as a clean rectangle rather than
offset and wrapped. **The owner's original paper-waster is fixed.**

### 7.5 The partial cut is not a partial cut on this unit

The owner's observation: *"Partial cut no worky, it cuts just like the full cut
after it."*

The driver emits the two distinct, textbook-correct commands — `GS V 1`
(0x1D 0x56 0x01) for partial and `GS V 0` for full — so this is the cutter
mechanism, not a mapping bug. On this unit both separate the paper completely
and no holding tab is left. Recorded as `Profile.partial_cut_leaves_tab =
False`. Do not build anything that depends on a partial cut holding the receipt
in place.

### 7.6 Two-colour

Colour 2 (`GS ( N`) is **accepted and prints** — in black, because the loaded
roll is single-colour thermal paper. Nothing is lost or skipped when colour 2
is selected on mono paper, which is the useful thing to know. Whether it comes
out red still depends on loading two-colour stock.

### 7.7 Character code tables — all twelve installed, one mislabelled

`tools/charsets.py` printed the high half (0x80–0xFF) of all twelve `ESC t`
tables; the strip was scanned and compared numerically rather than by eye,
because several of these tables differ from one another at only one or two code
points and the printer falls back to PC437 for a table it does not carry.

Method, and why a naive diff is not enough: comparing whole rows has an
alignment noise floor of roughly 4% on a 600 dpi scan, which is the same order
as a genuine one-character difference. The reliable discriminator is *where*
the differences fall. Normalising the per-character difference profile, a pair
that genuinely differs shows sharp peaks and a low mean (~0.20); a pair with
identical glyphs shows flat noise and a high mean (~0.36–0.51). Rows that must
be identical — the shared DOS box-drawing block of PC437/PC860/PC863/PC865 —
were used as the control and behaved exactly as predicted.

Results, with the differences landing on precisely the expected code points:

| Table | Verdict | Evidence |
|---|---|---|
| PC437, Katakana, PC850, PC860, PC863, PC866, PC852 | installed | large, obvious differences |
| **PC865** | installed | differs from PC437 at exactly **0x9B, 0x9D** (80 row) and 0xAF (A0 row) — the ¢→ø, ¥→Ø, »→¤ substitutions |
| **PC858** | installed | differs from PC850 at exactly **0xD5** — the ı→€ substitution, its only difference |
| **ISO8859-15** | installed | 0x80–0x9F prints **blank** (that range is undefined in Latin-9, where PC437 would print glyphs), and it differs from WPC1252 at exactly 0xA4, 0xA6, 0xA8, 0xB4, 0xB8, 0xBC, 0xBD, 0xBE — the eight Latin-9 substitutions |
| **`ESC t 48`** | installed, **but it is not PC857** | see below |

#### `ESC t 48` is Windows-1254, not PC857

The driver called `ESC t 48` `PC857_TURKISH` and encoded text for it with
Python's `cp857`. The paper says otherwise. `ESC t 48` uses a **Windows**
layout at 0xC0–0xFF (accented Latin letters, not DOS box drawing) and differs
from WPC1252 at exactly:

```
0x8E  0x9E  0xD0  0xDD  0xDE  0xF0  0xFD  0xFE
```

Those are the six Turkish letters of Windows-1254 (Ğ ğ İ ı Ş ş) plus the two
slots 1254 drops relative to 1252 (Ž ž). That is **code page 1254**, not 857.

This mattered, because the two code pages place the Turkish letters in
completely different slots:

| | cp857 (what the driver sent) | cp1254 (what the printer draws) | rendered as |
|---|---|---|---|
| ğ | 0xA7 | 0xF0 | `§` |
| Ğ | 0xA6 | 0xD0 | `¦` |
| İ | 0x98 | 0xDD | `˜` |
| ı | 0x8D | 0xFD | (undefined) |
| Ş | 0x9E | 0xDE | (undefined) |
| ş | 0x9F | 0xFE | `Ÿ` |

Every Turkish character would have printed as something else, silently. The
enum member is now `WPC1254_TURKISH` and the codec is `cp1254`, with a
regression test pinning each of the six letters to the byte the printer
actually draws.

**Katakana has no Python codec** and is the only table without one. The driver
raises `EncodingError` naming `write_raw()` rather than guessing, which is the
right behaviour; a test pins Katakana as the *only* such table, so a future
table added without a codec is caught.

### 7.8 International character sets — all fourteen installed

All fourteen `ESC R` variants differ from USA, each at a sensible set of the
twelve code points it overlays. The two single-character variants came out
exactly right: **JAPAN** changes only `0x5C` (`\` → `¥`) and **KOREA** changes
only `0x5C` (`\` → `₩`). UK changes `0x23` (`#` → `£`), and the rest change
between 6 and 12 points.

---

## 8. Library choice

The owner's requirement was "actively maintained, otherwise something under my
own maintenance".

`python-escpos` was assessed against the GitHub API on 2026-10-03:

* repo is **not** archived, 1321 stars, commits as recent as 2026-09-14;
* but the **last release is v3.1, 2023-12-17** — nearly three years old;
* recent commit traffic is predominantly dependabot bumps plus occasional
  community PRs.

It also talks to USB printers through pyusb/libusb rather than the `/dev/usb/lp*`
printer-class node, and its status support is thin — which is precisely the area
the owner cares most about, and the area where this printer is richest.

**Decision (owner's, 2026-10-03): purpose-built, zero-dependency library.**
Pillow is an optional extra used only to decode image *files*; raw 1-bit and
grayscale buffers work without any dependency at all.

---

## 9. The offline stall and the mute printer (diagnosed 2026-10-03)

The first attempt at the calibration print died part-way through section 7
(images) with:

```
WriteTimeout: printer stopped accepting data after 0 of 7 bytes
```

and afterwards the printer **answered nothing at all** — not `DLE EOT`, not
`GS I`, not even `ESC @`. It still accepted writes, and the USB device was
intact in sysfs (`04b8:0202`, both bulk endpoints, `usblp` bound, bind-mount
not severed). This is worth recording in full because every individual symptom
pointed somewhere misleading.

### What actually happened

1. **The printer went offline on a false paper-out.** The owner saw the paper
   LED lit on the front panel while the roll was plainly full, and clearing it
   took opening and closing the cover. They had seen the same thing during the
   previous session's probing. A later query caught the sensor in the act:
   `status: ready (paper roll near end)` on a full roll.
2. **Offline means the receive buffer stops draining.** With the 4 KB buffer
   full of a 3615-byte `GS ( L` fn=112 image block, the following 7-byte
   `graphics_print` could not be handed over at all — hence "0 of 7".
3. **The abort truncated the image command.** `WriteTimeout` propagated, the
   process exited, and closing the node made `usblp` unlink its in-flight URBs
   mid-payload. The printer was left waiting for the rest of that image.
4. **A printer waiting for a payload is mute by design.** Every subsequent byte
   was consumed as image data, real-time status queries included. That is why
   `DLE EOT` and `ESC @` vanished without trace, and why the printer looked
   dead while being perfectly healthy.

### Two traps for the next person

* **`LPGETSTATUS` lied.** The USB printer-class ioctl on the `usblp` node
  returned `0x18` — paper present, selected, no error — at a moment when the
  paper LED was visibly lit. A clean reading from that ioctl is *not* evidence
  the printer is ready. The ESC/POS `DLE EOT` path and the front panel are the
  trustworthy witnesses.
* **A mute printer is usually not a broken printer.** Before suspecting USB,
  the container mount or the hardware, test whether the command stream is
  simply desynchronised.

### Recovery, and what the library now does about it

Recovery is to satisfy the outstanding payload so the parser reaches a command
boundary again. `0x00` is the only safe filler: a blank pixel inside raster
data, a no-op to the parser outside it. Pour it in until the printer answers
`DLE EOT`, then `ESC @` to discard whatever it became. This restored the
printer with no power cycle and no re-enumeration — important, because a reset
would have severed the bind-mounted node (§5.1).

That procedure is now `Transport.resync()` / `Printer.resync()`, and three
changes make it rarely necessary:

* the write budget is **idle-based**, so a slow-but-progressing hand-over is no
  longer aborted (§6);
* `Printer.image()` bands by **bytes** against `Profile.receive_buffer_bytes`,
  so no single command can exceed the buffer, and waits for the printer to
  catch up between bands on transports that can answer;
* `WriteTimeout` now names both the likely cause (check the front panel for the
  false paper-out) and the cure (`resync()`), instead of a generic
  buffer-full guess.

With those in place the full nine-section print ran straight through.

## 10. An empty read means "nothing yet" (measured 2026-10-07)

On the `usblp` node, `select()` reports the descriptor **readable at all
times**, and `read()` with nothing pending returns **zero bytes** — not
`EAGAIN`, and it does not block. Probed by polling the idle node and after
`DLE EOT 1..4`: every poll returned instantly, mostly with `b''`, and the
one-byte replies showed up a few polls later.

`UsbTransport.read()` used to return after a single `select()`/`read()`, so
it came back empty immediately. `query()` hid this by looping until its own
deadline, but everything that trusted one read was broken:

* `answers()` always reported a mute printer, so **`resync()` never worked**:
  it poured its full 70 000 bytes of `0x00` filler (harmless, the printer
  ignores them) and returned False.
* `drain()` stopped at the first empty read and left late replies queued, so
  the next `status()` decoded stale bytes — it reported "cover is open;
  recoverable error" on a printer that was ready.

`read()` now polls until its timeout and treats a zero-byte read as "nothing
yet". With that, `answers()` replies in about 30 ms and `status()` is
consistent again.

## 11. Vertical distances are half dots (measured 2026-10-07)

The TM-T88V's default motion units (`GS P`) are **1/180 in horizontally (one
dot) and 1/360 in vertically (half a dot)**. Every vertical parameter counts
in half dots: `ESC J` (feed), `ESC 3` (line spacing), `GS $` (page-mode
y position) and the y/height of `ESC W` (page area). The driver used to pass
dots straight through, so all of them came out at half size.

Found on paper: page-mode text at "y=30" had its top clipped. Checked with
a second print after `Printer` started converting (`Profile.vertical_units_per_dot = 2`):

* Page mode: labels at y = 20, 22, 23, 24, 26 and 30 dots all printed whole.
  `y` is the text's baseline; the Font A cell sits above it, and the digits
  do not reach the top rows of their 24-dot cell, which is why y=20 survives.
  At the old 15 dots the tops were cut off.
* Line spacing: three rows of `█` at 24 dots formed one solid block; at
  30 dots they showed gaps of about a quarter of a row (6 of 24 dots).
* Feed: `feed_dots(180)` measured about 1 inch, as it should.

Horizontal values (`ESC $`, `GS L`, `GS W`, x/width of `ESC W`, images)
were always right; the width calibration in section 7 confirms them.
`ESC 3` takes at most 255 units, so line spacing is limited to 127 dots;
`feed_dots()` splits longer feeds into several `ESC J`.
