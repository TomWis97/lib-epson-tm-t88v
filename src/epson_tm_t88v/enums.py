"""Enumerations for every TM-T88V setting the driver exposes.

Values are the raw ESC/POS parameter bytes, so an enum member can be dropped
straight into a command builder.
"""

from __future__ import annotations

from enum import Enum, IntEnum, IntFlag


class Justification(IntEnum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2


class Font(IntEnum):
    """Built-in fonts. On 80 mm paper (576 dots) A gives 42 columns, B gives 56."""

    A = 0  # 12 x 24 dots
    B = 1  # 9 x 17 dots


class Underline(IntEnum):
    NONE = 0
    SINGLE = 1  # 1-dot thick
    DOUBLE = 2  # 2-dot thick


class CutMode(IntEnum):
    FULL = 0
    PARTIAL = 1


class Color(IntEnum):
    """Only meaningful with two-colour thermal paper."""

    BLACK = 1  # colour 1
    RED = 2  # colour 2


class PrintDirection(IntEnum):
    """Page-mode print direction (``ESC T``)."""

    LEFT_TO_RIGHT = 0
    BOTTOM_TO_TOP = 1
    RIGHT_TO_LEFT = 2
    TOP_TO_BOTTOM = 3


class Barcode(IntEnum):
    """1-D symbologies for ``GS k`` (the length-prefixed ``m`` = 65..78 form).

    ``GS k`` has no query form, so this was settled on paper: **all fourteen
    print** on this unit. ``GS1_128`` and ``GS1_DATABAR_EXPANDED`` need a real
    GS1 element string - handed a CODE128 ``{B`` code-set prefix they emit the
    HRI text and no bars at all, silently, which is why the driver rejects that
    prefix for them. See FINDINGS.md section 7.
    """

    UPC_A = 65
    UPC_E = 66
    EAN13 = 67
    EAN8 = 68
    CODE39 = 69
    ITF = 70
    CODABAR = 71
    CODE93 = 72
    CODE128 = 73
    GS1_128 = 74
    GS1_DATABAR_OMNIDIRECTIONAL = 75
    GS1_DATABAR_TRUNCATED = 76
    GS1_DATABAR_LIMITED = 77
    GS1_DATABAR_EXPANDED = 78


class HriPosition(IntEnum):
    """Where the human-readable interpretation is printed (``GS H``)."""

    NONE = 0
    ABOVE = 1
    BELOW = 2
    BOTH = 3


class QrErrorCorrection(IntEnum):
    """``GS ( k`` cn=49 fn=69."""

    L = 48  # ~7%
    M = 49  # ~15%
    Q = 50  # ~25%
    H = 51  # ~30%


class Pdf417Type(IntEnum):
    STANDARD = 0
    TRUNCATED = 1


class MaxiCodeMode(IntEnum):
    """Modes 4-6 are verified working; 2 and 3 need a structured carrier message."""

    MODE_2 = 50
    MODE_3 = 51
    MODE_4 = 52
    MODE_5 = 53
    MODE_6 = 54


class ImageCommand(Enum):
    """Which raster command to use for images.

    ``GRAPHICS`` is the modern ``GS ( L`` / ``GS 8 L`` fn=112 path: it supports
    scaling and two-colour output. ``RASTER`` is the legacy ``GS v 0`` path,
    kept because it is the most widely supported command in the family.
    """

    GRAPHICS = "graphics"
    RASTER = "raster"


class CharacterSet(IntEnum):
    """``ESC t n`` character code tables.

    Which of these the firmware actually carries is confirmed by
    ``tools/charsets.py``, which prints the high half of every table so they can
    be compared; a table the printer does not have falls back to PC437.
    """

    PC437_USA_STANDARD_EUROPE = 0
    KATAKANA = 1
    PC850_MULTILINGUAL = 2
    PC860_PORTUGUESE = 3
    PC863_CANADIAN_FRENCH = 4
    PC865_NORDIC = 5
    WPC1252 = 16
    PC866_CYRILLIC2 = 17
    PC852_LATIN2 = 18
    PC858_EURO = 19
    ISO8859_15 = 40
    #: ``ESC t 48`` is **Windows-1254**, not the DOS PC857 code page. Confirmed
    #: on paper 2026-10-03: its glyphs differ from WPC1252 at exactly 0x8E,
    #: 0x9E, 0xD0, 0xDD, 0xDE, 0xF0, 0xFD and 0xFE - the six Turkish letters
    #: and the two slots Windows-1254 drops - and it uses a Windows layout at
    #: 0xC0-0xFF rather than DOS box drawing. It was originally named
    #: ``PC857_TURKISH`` and paired with the ``cp857`` codec, which silently
    #: mangled every Turkish character.
    WPC1254_TURKISH = 48


class InternationalCharset(IntEnum):
    """``ESC R n`` - overlays a dozen code points with national variants."""

    USA = 0
    FRANCE = 1
    GERMANY = 2
    UK = 3
    DENMARK_I = 4
    SWEDEN = 5
    ITALY = 6
    SPAIN_I = 7
    JAPAN = 8
    NORWAY = 9
    DENMARK_II = 10
    SPAIN_II = 11
    LATIN_AMERICA = 12
    KOREA = 13


class DrawerPin(IntEnum):
    PIN_2 = 0
    PIN_5 = 1


class StatusClass(IntFlag):
    """Bit mask for ``GS a`` (Automatic Status Back)."""

    DRAWER = 0x01
    ONLINE_OFFLINE = 0x02
    ERROR = 0x04
    PAPER_ROLL = 0x08
    ALL = 0x0F
