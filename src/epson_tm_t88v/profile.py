"""Measured capabilities of the Epson TM-T88V.

Numbers here are either measured on hardware or determined by the paper the
owner has loaded; nothing is aspirational. See FINDINGS.md for provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet

from .enums import Barcode, Font


@dataclass(frozen=True)
class Profile:
    model: str = "TM-T88V"
    dpi: int = 180
    #: Printable width in dots: 512 (72.2 mm) on an 80 mm roll, 360 (50.8 mm)
    #: on a 58 mm roll. At this printer's 180 dpi, 512 dots is what makes the
    #: documented 42 (Font A) / 56 (Font B) columns come out right.
    #: NOTE: 576 is the figure for 203 dpi printers and is wrong here - it
    #: would be 81.3 mm, wider than the paper. Confirm with tools/calibrate.py.
    print_width_dots: int = 512
    #: Dots per character cell, keyed by font.
    font_width: Dict[Font, int] = field(
        default_factory=lambda: {Font.A: 12, Font.B: 9}
    )
    font_height: Dict[Font, int] = field(
        default_factory=lambda: {Font.A: 24, Font.B: 17}
    )
    #: Receive buffer, per the TM-T88V specification. Small enough that a
    #: single full-width image band can fill it, which is why image data is
    #: banded by bytes and paced against the printer's progress.
    receive_buffer_bytes: int = 4096
    #: Vertical motion units per dot. ``ESC J``, ``ESC 3``, ``GS $`` and the
    #: y/height of ``ESC W`` count in vertical motion units, which default to
    #: 1/360 in on this printer - half a 180 dpi dot. Horizontal units are
    #: 1/180 in, one dot. Shown on paper 2026-10-07: page-mode text at "y=30"
    #: landed 15 dots down and had its top clipped. ``Printer`` converts, so
    #: its methods take dots. The driver never changes the units (``GS P``).
    vertical_units_per_dot: int = 2
    #: Measured with ``GS ( L fn=48`` / ``fn=52``.
    nv_graphics_bytes: int = 262144
    download_graphics_bytes: int = 212992
    has_autocutter: bool = True
    #: Measured on paper 2026-10-03: ``GS V 1`` (partial) separates the paper
    #: exactly as ``GS V 0`` (full) does on this unit. The driver emits the two
    #: distinct commands correctly; the cutter mechanism does not distinguish
    #: them. Do not rely on a partial cut leaving a holding tab.
    partial_cut_leaves_tab: bool = False
    #: Verified by querying symbol sizes; Aztec and DataMatrix are absent.
    supports_qr: bool = True
    supports_pdf417: bool = True
    supports_maxicode: bool = True
    supports_aztec: bool = False
    supports_datamatrix: bool = False
    #: ``GS ( k`` model selection is accepted but has no effect; everything
    #: encodes as QR Model 2.
    qr_model_selectable: bool = False
    #: ``GS g 2`` returned nothing for any counter on firmware 30.13.
    supports_maintenance_counters: bool = False
    #: Confirmed on paper 2026-10-03 by printing one of each and reading the
    #: receipt back. All fourteen print. GS1-128 and GS1 DataBar Expanded
    #: needed a second pass with well-formed GS1 data (``tools/gs1_retest.py``)
    #: because the first attempt used a CODE128 ``{B`` code-set prefix, which
    #: makes the printer emit HRI text and no bars at all.
    barcodes_verified: bool = True
    verified_barcodes: FrozenSet[Barcode] = field(
        default_factory=lambda: frozenset(
            {
                Barcode.UPC_A,
                Barcode.UPC_E,
                Barcode.EAN13,
                Barcode.EAN8,
                Barcode.CODE39,
                Barcode.ITF,
                Barcode.CODABAR,
                Barcode.CODE93,
                Barcode.CODE128,
                Barcode.GS1_128,
                Barcode.GS1_DATABAR_OMNIDIRECTIONAL,
                Barcode.GS1_DATABAR_TRUNCATED,
                Barcode.GS1_DATABAR_LIMITED,
                Barcode.GS1_DATABAR_EXPANDED,
            }
        )
    )
    #: Nothing outstanding: every symbology the driver offers has printed.
    unverified_barcodes: FrozenSet[Barcode] = field(default_factory=frozenset)

    def columns(self, font: Font = Font.A) -> int:
        """How many characters fit on a line in the given font."""
        return self.print_width_dots // self.font_width[Font(font)]

    def dots_to_mm(self, dots: float) -> float:
        return dots * 25.4 / self.dpi

    def mm_to_dots(self, mm: float) -> int:
        return round(mm * self.dpi / 25.4)


#: Standard 80 mm configuration - what this driver was developed against.
TM_T88V_80MM = Profile()

#: 58 mm roll using the narrow-paper guide: 360 dots, 30/40 columns.
TM_T88V_58MM = Profile(print_width_dots=360)
