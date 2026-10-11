# Verbatim probe output, 2026-10-03

Unedited console output from the capability investigation, kept so the
conclusions in FINDINGS.md can be re-checked against the actual bytes.
Device was the bind-mounted node at `/workspace/lp0` (host `/dev/usb/lp0`).

## Device node

```
crw-rw-rw- 1 nobody nobody 180, 0 /workspace/lp0
rw OK fd 3        # opens O_RDWR  -> bidirectional
ro OK fd 3
wo OK fd 3
```

USB identity from sysfs:
```
5-4: EPSON / TM-T88V / 04b8:0202 serial=405141460094700000
/sys/class/usbmisc/lp0/uevent -> MAJOR=180 MINOR=0 DEVNAME=usb/lp0
```

## Real-time status

```
unsolicited data on open: (nothing)

DLE EOT 1  (printer status    ) -> 16
DLE EOT 2  (offline cause     ) -> 12
DLE EOT 3  (error cause       ) -> 12
DLE EOT 4  (roll paper sensor ) -> 1E
```

Later in the session, after the owner physically checked the roll:

```
  DLE EOT 1 (printer)        16
  DLE EOT 2 (offline cause)  12
  DLE EOT 3 (error cause)    12
  DLE EOT 4 (paper sensor)   12      <- near-end flag had cleared
```

## Printer ID

```
GS I 1    20        GS I 49   20
GS I 2    02        GS I 50   02
GS I 3    64        GS I 51   64

GS I 33..37  (nothing)

GS I 65 (firmware version) 5F 33 30 2E 31 33 20 45 53 43 2F 50 4F 53 00  |_30.13 ESC/POS.|
GS I 66 (maker name)       5F 45 50 53 4F 4E 00                          |_EPSON.|
GS I 67 (model name)       5F 54 4D 2D 54 38 38 56 00                    |_TM-T88V.|
GS I 68 (serial number)    5F 4D 51 41 46 30 30 39 34 37 30 00           |_MQAF009470.|
GS I 69 (font of language) 5F 00                                         |_.|
GS I 110 (nothing)
GS I 112                   5F 30 00                                      |_0.|
GS I 113                   5F 31 00                                      |_1.|
```

## Maintenance counters, extended status, legacy status

```
=== GS g 2 : maintenance counters (sweep m=0..127) ===
  (0 counters responded)
  retry with 1.2 s timeout on m=10,11,12,13,20,21,22,50,51,52,53,70,71,72,73,80
  -> all (nothing)

=== DLE EOT extended ===
DLE EOT 7 1   (nothing)
DLE EOT 7 2   (nothing)
DLE EOT 8 3   (nothing)

=== legacy status commands ===
ESC u 0 (peripheral device)  01
ESC v   (paper sensor)       03
GS r 1  (paper sensor)       03
GS r 2  (drawer kick)        01

=== GS ( H : response to host ===
GS ( H fn=48 'ABCD'          37 22 41 42 43 44 00    |7"ABCD.|
GS ( H fn=48 'TEST'          37 22 54 45 53 54 00    |7"TEST.|
GS ( H fn=49 (offline)       (nothing)

=== DLE DC4 fn=8 : clear buffer ===
10 14 08 01 03 14 01 06 02 08  ->  37 25 00          |7%.|

=== ASB ===
GS a 0xFF then wait -> (nothing)
GS a 0x0F then wait -> (nothing)
```

## Graphics memory

```
GS ( L fn=48   37 30 32 36 32 31 34 34 00   |70262144.|
GS ( L fn=50   (nothing)
GS ( L fn=51   37 31 32 36 32 31 34 34 00   |71262144.|
GS ( L fn=52   37 32 32 31 32 39 39 32 00   |72212992.|
GS ( L fn=64   (nothing)

GS 8 L fn=48   37 30 32 36 32 31 34 34 00   (same values via the 32-bit form)
GS 8 L fn=51   37 31 32 36 32 31 34 34 00
GS 8 L fn=52   37 32 32 31 32 39 39 32 00
GS 8 L fn=64   (nothing)
```

## 2-D symbologies

Store `1234`, then `GS ( k fn=82` for the symbol size:

```
  cn=48 PDF417          37 2F 34 36 32 1F 32 37 1F 31 1F 30 00    |7/462.27.1.0.|
  cn=49 QR Code         37 36 36 33 1F 36 33 1F 31 1F 30 00       |7663.63.1.0.|
  cn=50 MaxiCode        37 37 30 1F 30 1F 31 1F 31 00             |770.0.1.1.|
  cn=51 GS1 DataBar 2D  37 4F 30 1F 30 1F 31 1F 31 00             |7O0.0.1.1.|
  cn=52 Composite       37 50 30 1F 30 1F 31 1F 31 31 30 30 36 00 |7P0.0.1.11006.|
  cn=53 Aztec           (nothing)
  cn=54 DataMatrix      (nothing)
```

MaxiCode with a valid 30-digit payload:

```
  mode 2   37 37 30 1F 30 1F 31 1F 31 00             0 x 0, error 1
  mode 3   37 37 30 1F 30 1F 31 1F 31 00             0 x 0, error 1
  mode 4   37 37 31 38 30 1F 31 36 37 1F 31 1F 30 00 180 x 167, OK
  mode 5   37 37 31 38 30 1F 31 36 37 1F 31 1F 30 00 180 x 167, OK
  mode 6   37 37 31 38 30 1F 31 36 37 1F 31 1F 30 00 180 x 167, OK
  mode 7   37 37 30 1F 30 1F 31 1F 31 00             0 x 0, error 1 (no such mode)
```

GS1 DataBar 2-D, every payload shape tried:

```
  Stacked / 13 digits          ['0', '0', '1', '1']
  Stacked Omni / 13 digits     ['0', '0', '1', '1']
  Limited / 13 digits          ['0', '0', '1', '1']
  Expanded / AI+GTIN           ['0', '0', '1', '1']
  Expanded / {01 escaped       ['0', '0', '1', '1']
```

### QR parameter sweeps

```
  Model 1    'HELLO'      63 x 63
  Model 2    'HELLO'      63 x 63
  Micro QR   'HELLO'      63 x 63      <- model setting has no effect
  Model 1    1000 digits  69 x 69
  Model 2    1000 digits  69 x 69
  Micro QR   1000 digits  69 x 69
  Model 1    'AB'         21 x 21
  Micro QR   'AB'         21 x 21      <- a real Micro QR would be <= 17 modules

  module size sweep (model 2, 'HELLO'):
    module=1   -> ['21', '21', '1', '0']
    module=2   -> ['42', '42', '1', '0']
    module=3   -> ['63', '63', '1', '0']
    module=4   -> ['84', '84', '1', '0']
    module=8   -> ['168', '168', '1', '0']
    module=15  -> ['315', '315', '1', '0']
    module=16  -> ['336', '336', '1', '0']
    module=17  -> ['63', '63', '1', '0']     <- falls back to the default of 3

  error correction (model 2, module 3, 'HELLO WORLD 1234567890'):
    EC L 7%    -> 63 x 63
    EC M 15%   -> 63 x 63
    EC Q 25%   -> 75 x 75
    EC H 30%   -> 75 x 75

  capacity (model 2, EC L, module 1):
      100 digits -> 29 x 29        3000 digits -> 117 x 117
      500 digits -> 53 x 53        4000 digits -> 137 x 137
     1000 digits -> 69 x 69        5000 digits -> 153 x 153
     2000 digits -> 97 x 97        7089 digits -> 177 x 177   (QR version 40)
```

### PDF417 parameters

```
  default            -> 462 x 27
  columns=4          -> 411 x 27
  rows=8             -> 462 x 72
  module width=3     -> 462 x 27   (already the default)
  row height=4       -> 462 x 36
  EC level 2         -> 462 x 27
  truncated          -> 462 x 27   (parameter encoding needs rechecking)
```

## User setting mode

```
status before: 16
enter user setting mode (fn=1)     37 20 00

=== memory switches (fn=4) ===
  msw1 .. msw8                     (nothing)       <- not readable

=== customize values (fn=6), sweep a=1..127 ===
  a=3     37 27 33 1F 36 00                |7'3.6.|
  a=5     37 27 35 1F 30 00                |7'5.0.|
  a=6     37 27 36 1F 31 00                |7'6.1.|
  a=8     37 27 38 1F 30 00                |7'8.0.|
  a=9     37 27 39 1F 30 00                |7'9.0.|
  a=10    37 27 31 30 1F 31 00             |7'10.1.|
  a=97    37 27 39 37 1F 31 00             |7'97.1.|
  a=98    37 27 39 38 1F 32 00             |7'98.2.|
  a=100   37 27 31 30 30 1F 31 00          |7'100.1.|
  a=101   |7'101.0.|      a=102 |7'102.0.|      a=103 |7'103.0.|
  a=104   |7'104.0.|      a=105 |7'105.0.|      a=111 |7'111.0.|
  a=112   |7'112.1.|      a=116 |7'116.1.|      a=117 |7'117.0.|
  a=118   |7'118.85.|     a=119 |7'119.0.|      a=120 |7'120.65535.|
  a=121   |7'121.1.|      a=122 |7'122.1.|      a=123 |7'123.1.|
  a=124   |7'124.1.|      a=125 |7'125.2.|      a=126 |7'126.1.|
  a=127   |7'127.0.|
  (28 customize values responded)

exiting user setting mode (printer will software-reset)...
PermissionError: [Errno 13] Permission denied: '/workspace/lp0'
```

## The device node after the reset

```
$ ls -la /workspace/lp0
c--------- 0 nobody nobody 180, 0        <- mode stripped to 0000
$ stat /workspace/lp0
  Links: 0                                <- inode unlinked on the host
$ grep lp0 /proc/self/mountinfo
1194 1332 0:6 /usb/lp0//deleted /workspace/lp0 rw,nosuid,relatime - devtmpfs dev ...

$ sudo mknod /tmp/lp0test c 180 0
mknod: /tmp/lp0test: Operation not permitted
$ sudo mount -t devtmpfs none /mnt/hostdev
mount: /mnt/hostdev: permission denied.
$ grep Cap /proc/self/status
CapEff: 0000000000000000
$ ls /dev/bus
ls: cannot access '/dev/bus': No such file or directory

/sys/class/usbmisc/lp0 still present -> printer alive on the host,
unreachable from inside the container.
```

## python-escpos assessment (GitHub API, 2026-10-03)

```
full_name          python-escpos/python-escpos
stargazers_count   1321
archived           False
pushed_at          2026-09-28
license            MIT

releases:  v3.1  2023-12-17     <- most recent
           v3.0  2023-11-16
           v3.0a9 2023-05-11

recent commits:
  2026-09-14  Bump github/codeql-action from 4.37.9 to 4.38.0 (#771)
  2026-09-06  3 examples (#652)
  2026-09-06  Win32Raw: Add Windows Shared Printer compatibility (#770)
  2026-08-31  Bump github/codeql-action from 4.37.7 to 4.37.9 (#769)
  2026-08-31  docs: Fix capitalisation of openSUSE (#760)
  2026-08-20  Bump github/codeql-action from 4.37.4 to 4.37.7 (#767)
  2026-08-20  Update qrcode requirement from >=8.0 to >=8.2 (#753)
```

---

# Verbatim log, 2026-10-03 (later) — first print, the stall, and recovery

## Probe before printing — matched the earlier run exactly

```
device: /workspace/lp0
== identity ==
  EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
  model id 0x20  type id 0x02  firmware id 0x64
== status ==
  ready
  DLE EOT 1..4 = 0x16 0x12 0x12 0x12
== 2-D symbologies ==
  PDF417             OK   462 x 27 dots
  QR Code            OK   63 x 63 dots
  MaxiCode           OK   180 x 167 dots
  GS1 DataBar (2D)   recognised but payload rejected (error 1)
  Composite          recognised but payload rejected (error 11006)
  Aztec              NOT SUPPORTED (no reply)
  DataMatrix         NOT SUPPORTED (no reply)
```

## First calibration attempt — died in section 7

```
printer: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status:  ready
...
  File "tools/calibrate.py", line 283, in section_image
    p.image(dithered, command=ImageCommand.GRAPHICS)
  File "src/epson_tm_t88v/printer.py", line 374, in image
    self._send(cmd.graphics_print())
epson_tm_t88v.exceptions.WriteTimeout: printer stopped accepting data after
0 of 7 bytes; it may be offline, out of paper, or its receive buffer may be full
```

Sections 1–6 reached the paper. The 3615-byte `GS ( L` fn=112 block had been
handed over; the 7-byte fn=50 print command that follows it could not be.

## Afterwards: writes accepted, nothing answered

```
DLE EOT 1            -> (no reply)
DLE EOT 2            -> (no reply)
GS I 1 (model id)    -> (no reply)
GS r 1 (ink/paper)   -> (no reply)
```

`ESC @` was sent first and made no difference. A blocking `read()` returned a
zero-length packet immediately, i.e. the printer was answering "nothing to
say" rather than failing to answer.

Not a mount or USB problem — the node and the device were both intact:

```
1137 1466 0:6 /usb/lp0 /workspace/lp0 rw,nosuid,relatime - devtmpfs dev ...
(no "//deleted" anywhere in /proc/self/mountinfo)

/sys/devices/.../usb5/5-4:
  idVendor 04b8   idProduct 0202   EPSON / TM-T88V
  serial 405141460094700000   bNumInterfaces 1
  5-4:1.0/ep_01 -> out Bulk
  5-4:1.0/ep_82 -> in  Bulk
```

## The misleading reading

USB printer-class `LPGETSTATUS` ioctl on the node:

```
raw port status: 0x18 (0b00011000)
  Paper Empty (0x20): False
  Selected/Online (0x10): True
  Not Error (0x08): True -> error present: False
```

The owner was looking at the printer at the time and **the paper LED was lit**,
on a full roll. This ioctl is not a trustworthy witness.

## Recovery without a power cycle

Filler poured in until the outstanding image payload was satisfied, then
`ESC @`:

```
filler: sent 4608 of 4608
ESC @: sent 2 of 2
DLE EOT 1    -> 16
GS I 1       -> 20
```

`0x16` and `0x20` are the same ready/model-id values as the clean probe above.
This is now `Transport.resync()`.

The owner independently reported that opening and closing the cover clears the
false paper-out, and had seen the same LED behaviour during the earlier
session. A query taken shortly afterwards caught the sensor misreporting:

```
identity: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status:   ready (paper roll near end)      <- on a full roll
ok: True  problems: ['paper roll near end']
```

## Re-run after the fixes — clean

Remaining sections, then the full nine-section pass, both straight through:

```
printer: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status:  ready
(image, color, cut   — completed)

printer: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status:  ready
(all nine sections   — completed)
```

Printer healthy afterwards, discovery via `EPSON_TM_T88V_DEVICE`:

```
device auto-found via env var: /workspace/lp0
identity: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status: ready | ok: True
desynced: False
```

Largest `GS ( L` block the driver now emits, with byte-based banding against
the 4 KB receive buffer: **2020 bytes** (was 3615).

---

# Measurements from the scanned receipt, 2026-10-03

Source: `calibration print.png`, 6458 x 10057 px RGB, flatbed scan of the full
nine-section calibration print, cut by the owner into three strips to fit an
A3/ledger bed. Strips occupy x 104..1952, 2296..3968 and 4328..6104.

## Ruler bars — the printable-width measurement

Dark-pixel extent of each ruler's solid band, measured on the strip-1 crop:

```
 360 dots: rows 170-198  x  99..1294  width 1196 px
 512 dots: rows 431-473  x  89..1788  width 1700 px
 576 dots: rows 691-733  x  80..1778  width 1699 px

scale from the 512 bar: 3.3203 scan px per printer dot
implied scan resolution against a 180 dpi printer: 597.7 dpi

 360 bar ->   360.2 dots actually printed   (predicted 1195 px, measured 1196)
 512 bar ->   512.0 dots actually printed
 576 bar ->   511.7 dots actually printed   (predicted 1912 px, measured 1699)

576 minus 512 = -1 px (-0.3 dots)
512 bar measures 72.2 mm on paper
```

The 576-dot bar was emitted with `GS v 0` directly, bypassing the driver's
width check, so this is the printer's own clipping behaviour.

## Column counts from the same print

The 70-character ruler string
`----+----1----+----2----+----3----+----4----+----5----+----6----+----7`
wrapped as:

```
Font A line 1: ----+----1----+----2----+----3----+----4--      (42 chars)
Font A line 2: --+----5----+----6----+----7                    (28 chars)
Font B line 1: ----+----1----+----2----+----3----+----4----+----5----+-  (56)
Font B line 2: ---6----+----7                                  (14 chars)
```

512 / 12 = 42 (Font A) and 512 / 9 = 56 (Font B). Both agree with the bars.

## GS1-128 bar zone — blank, not faint

Pixel statistics for the band between the `GS1_128` label and its HRI text,
where a 50-dot-high symbol should be:

```
  label row              min= 17 mean= 237.3 dark_px=10677
  suspected bar zone     min=128 mean= 252.8 dark_px=0
  HRI row                min= 19 mean= 240.9 dark_px=9255
```

Zero dark pixels. The printer emitted the human-readable text and no symbol at
all. `GS1_DATABAR_EXPANDED` behaves identically. Both payloads began with the
CODE128 code-set selector `{B`; `CODE128` itself, given `{BCODE128`, printed
normally.

---

# ASB capture, 2026-10-03

`tools/asb_watch.py`, 540 s window, owner opened and closed the cover twice:

```
printer: EPSON TM-T88V firmware 30.13 ESC/POS serial MQAF009470
status:  ready

  [   0.0s] push 14 00 00 0f  ->  drawer pin high
  [  80.5s] push 3c 00 00 0f  ->  cover open, offline, drawer pin high
  [  87.0s] push 14 00 00 0f  ->  drawer pin high
  [ 135.5s] push 3c 00 00 0f  ->  cover open, offline, drawer pin high
  [ 138.1s] push 14 00 00 0f  ->  drawer pin high

5 push(es) received - ASB works on this unit.
```

The block at 0.0 s arrived on *enable*, contradicting the earlier note in §2.5
that nothing is sent until a change occurs. Byte 4 was `0f` in every block, in
both states, and is not decoded.

---

# Charset chart measurements, 2026-10-03

Source: `CCF03102026_0001.png`, 6458 x 10057 px, flatbed scan of
`tools/charsets.py` output, cut into two strips. `ESC t` tables occupy
x 4112..5960; `ESC R` variants x 1848..3540.

## Why a plain diff is not enough

Whole-row comparison on this scan has an alignment noise floor around 4%, which
is the same magnitude as a genuine one-character difference:

```
  pair                         80       A0       C0       E0
  PC437 vs PC860            14.15     4.04     3.76     4.21
  PC437 vs PC863            10.51     8.73     3.65     3.80
  PC437 vs PC865             5.39     5.47     3.92     4.16
```

The C0/E0 columns are rows that *must* be identical (shared DOS box drawing),
so ~3.7-4.2% is noise, and PC865's 5.39% is not separable from it by magnitude
alone.

## The discriminator that works: where the differences fall

Normalising the per-character difference profile, a pair that genuinely differs
shows sharp peaks and a low mean; identical glyphs give flat noise and a high
mean.

```
CONTROL - genuinely identical rows:
  PC437 vs PC860  C0 row       mean 0.357  (flat)
  PC437 vs PC865  C0 row       mean 0.512  (flat)
  PC850 vs PC858  80 row       mean 0.502  (flat)

GENUINE DIFFERENCES - sharp, and at exactly the right code points:
  PC437 vs PC865  80 row       mean 0.210  peaks: 0x9B, 0x9D
  PC850 vs PC858  C0 row       mean 0.202  peaks: 0xD5
  PC857 vs WPC1252 80 row      mean 0.183  peaks: 0x8E, 0x9E
  PC857 vs WPC1252 A0 row      mean 0.277  peaks: 0xAE, 0xBD, 0xBE
  PC857 vs WPC1252 C0 row      mean 0.243  peaks: 0xD0, 0xDD, 0xDE
  PC857 vs WPC1252 E0 row      mean 0.221  peaks: 0xF0, 0xFD, 0xFE
  WPC1252 vs ISO8859_15 A0 row peaks: 0xA4,0xA6,0xA8,0xB4,0xB8,0xBC,0xBD,0xBE
  WPC1252 vs ISO8859_15 C0/E0  flat (mean 0.787 / 0.640) - identical, correct
```

`0xD0 0xDD 0xDE 0xF0 0xFD 0xFE` are the six Turkish letters of **Windows-1254**,
and `0x8E 0x9E` the two slots 1254 drops relative to 1252. `ESC t 48` is
therefore WPC1254, not PC857. The eight A0-row differences between WPC1252 and
`ESC t 40` are exactly the Latin-9 substitutions, confirming ISO-8859-15.

ISO-8859-15's 0x80 row carried 1042 ink pixels against ~12000-16000 for every
other table: that range is undefined in Latin-9 and prints blank, which is also
proof it is not falling back to PC437.

## ESC R variants vs USA

```
  USA            identical to USA (baseline)
  FRANCE          7 changed   0x40 0x5B 0x5C 0x5D 0x7B 0x7C 0x7D
  GERMANY         8 changed   0x40 0x5B 0x5C 0x5D 0x7B 0x7C 0x7D 0x7E
  UK              3 changed   0x23 0x24 0x40
  DENMARK_I       7 changed   0x40 0x5B 0x5C 0x5D 0x7B 0x7C 0x7D
  SWEDEN         11 changed
  ITALY          11 changed
  SPAIN_I         6 changed   0x23 0x5B 0x5C 0x5D 0x7B 0x7C
  JAPAN           1 changed   0x5C          (backslash -> yen)
  NORWAY         12 changed
  DENMARK_II     12 changed
  SPAIN_II       10 changed
  LATIN_AMERICA  10 changed
  KOREA           1 changed   0x5C          (backslash -> won)
```

All fourteen are installed.
