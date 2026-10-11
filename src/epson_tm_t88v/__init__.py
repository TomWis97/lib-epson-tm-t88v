"""Driver for the Epson TM-T88V thermal receipt printer.

Talks to the printer through the Linux ``usblp`` character device
(``/dev/usb/lp0``), which is bidirectional - so status, errors and job
completion are first-class, not guesswork.

    from epson_tm_t88v import Printer

    with Printer() as p:
        p.status().raise_for_status()
        p.textln("Hello")
        p.qr("https://example.com")
        p.cut()

No required dependencies. Pillow is optional and only needed to load image
*files*; raw and grayscale buffers work without it.
"""

from __future__ import annotations

from . import commands
from .enums import (
    Barcode,
    CharacterSet,
    Color,
    CutMode,
    DrawerPin,
    Font,
    HriPosition,
    ImageCommand,
    InternationalCharset,
    Justification,
    MaxiCodeMode,
    Pdf417Type,
    PrintDirection,
    QrErrorCorrection,
    StatusClass,
    Underline,
)
from .exceptions import (
    DataTooLarge,
    DeviceNotFound,
    EncodingError,
    PrinterError,
    PrinterFault,
    PrinterOffline,
    ReadTimeout,
    TransportError,
    UnsupportedFeature,
    WriteTimeout,
)
from .imaging import HAVE_PILLOW, Raster, from_grayscale, from_image, from_packed
from .printer import Printer, Style
from .profile import TM_T88V_58MM, TM_T88V_80MM, Profile
from .status import (
    AsbStatus,
    ErrorStatus,
    FullStatus,
    OfflineStatus,
    PaperStatus,
    PrinterIdentity,
    PrinterStatus,
    SymbolSize,
)
from .transport import (
    BufferTransport,
    FileTransport,
    Transport,
    UsbTransport,
    find_devices,
)

__version__ = "0.1.0"

__all__ = [
    "Printer", "Style", "Profile", "TM_T88V_80MM", "TM_T88V_58MM",
    "Transport", "UsbTransport", "BufferTransport", "FileTransport", "find_devices",
    "Raster", "from_image", "from_grayscale", "from_packed", "HAVE_PILLOW",
    "FullStatus", "PrinterStatus", "OfflineStatus", "ErrorStatus", "PaperStatus",
    "AsbStatus", "SymbolSize", "PrinterIdentity",
    "Barcode", "CharacterSet", "Color", "CutMode", "DrawerPin", "Font",
    "HriPosition", "ImageCommand", "InternationalCharset", "Justification",
    "MaxiCodeMode", "Pdf417Type", "PrintDirection", "QrErrorCorrection",
    "StatusClass", "Underline",
    "PrinterError", "TransportError", "DeviceNotFound", "WriteTimeout",
    "ReadTimeout", "PrinterOffline", "PrinterFault", "EncodingError",
    "DataTooLarge", "UnsupportedFeature",
    "commands",
]
