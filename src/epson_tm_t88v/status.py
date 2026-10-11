"""Decoding of every status byte the TM-T88V produces.

The bit layouts here are not copied from a datasheet - each one is consistent
with readings taken from the physical printer (see FINDINGS.md section 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .exceptions import PrinterFault, PrinterOffline


def _bit(value: int, n: int) -> bool:
    return bool(value & (1 << n))


@dataclass(frozen=True)
class PrinterStatus:
    """``DLE EOT 1``. Observed ``0x16`` on a healthy idle printer."""

    raw: int
    online: bool
    drawer_pin_high: bool

    @classmethod
    def decode(cls, b: int) -> "PrinterStatus":
        return cls(raw=b, online=not _bit(b, 3), drawer_pin_high=_bit(b, 2))


@dataclass(frozen=True)
class OfflineStatus:
    """``DLE EOT 2``. Observed ``0x12`` on a healthy idle printer."""

    raw: int
    cover_open: bool
    feeding_by_button: bool
    stopped_paper_end: bool
    error: bool

    @classmethod
    def decode(cls, b: int) -> "OfflineStatus":
        return cls(
            raw=b,
            cover_open=_bit(b, 2),
            feeding_by_button=_bit(b, 3),
            stopped_paper_end=_bit(b, 5),
            error=_bit(b, 6),
        )


@dataclass(frozen=True)
class ErrorStatus:
    """``DLE EOT 3``. Observed ``0x12`` on a healthy idle printer."""

    raw: int
    recoverable_error: bool
    autocutter_error: bool
    unrecoverable_error: bool
    auto_recoverable_error: bool

    @classmethod
    def decode(cls, b: int) -> "ErrorStatus":
        return cls(
            raw=b,
            recoverable_error=_bit(b, 2),
            autocutter_error=_bit(b, 3),
            unrecoverable_error=_bit(b, 5),
            auto_recoverable_error=_bit(b, 6),
        )


@dataclass(frozen=True)
class PaperStatus:
    """``DLE EOT 4``.

    On the development unit the near-end sensor was observed flipping between
    "near end" (``0x1E``) and "adequate" (``0x12``) with the roll untouched, so
    treat :attr:`near_end` as advisory. :attr:`present` is the reliable one.
    """

    raw: int
    near_end: bool
    present: bool

    @classmethod
    def decode(cls, b: int) -> "PaperStatus":
        return cls(raw=b, near_end=_bit(b, 2) and _bit(b, 3), present=not (_bit(b, 5) and _bit(b, 6)))


@dataclass(frozen=True)
class FullStatus:
    """Everything the four real-time queries report, in one object."""

    printer: PrinterStatus
    offline: OfflineStatus
    errors: ErrorStatus
    paper: PaperStatus

    @property
    def ok(self) -> bool:
        """True when the printer is ready to print right now."""
        return (
            self.printer.online
            and not self.offline.cover_open
            and not self.offline.error
            and not self.offline.stopped_paper_end
            and not self.errors.recoverable_error
            and not self.errors.autocutter_error
            and not self.errors.unrecoverable_error
            and not self.errors.auto_recoverable_error
            and self.paper.present
        )

    @property
    def problems(self) -> List[str]:
        """Human-readable list of everything currently wrong. Empty when fine."""
        out: List[str] = []
        if not self.printer.online:
            out.append("printer is offline")
        if self.offline.cover_open:
            out.append("cover is open")
        if not self.paper.present:
            out.append("out of paper")
        elif self.paper.near_end:
            out.append("paper roll near end")
        if self.offline.stopped_paper_end:
            out.append("printing stopped at paper end")
        if self.errors.autocutter_error:
            out.append("autocutter error (paper jam in the cutter?)")
        if self.errors.unrecoverable_error:
            out.append("unrecoverable error - power cycle required")
        if self.errors.auto_recoverable_error:
            out.append("auto-recoverable error (print head overheated?)")
        if self.errors.recoverable_error:
            out.append("recoverable error")
        return out

    def raise_for_status(self) -> None:
        """Raise if the printer cannot print. ``near end`` alone does not raise."""
        if not self.printer.online:
            raise PrinterOffline("; ".join(self.problems) or "printer is offline")
        blocking = [p for p in self.problems if p != "paper roll near end"]
        if blocking:
            raise PrinterFault("; ".join(blocking), status=self)

    def __str__(self) -> str:
        problems = self.problems
        if not self.ok:
            return "; ".join(problems)
        # ``ok`` deliberately ignores the near-end warning, but it should still
        # be visible rather than being reported as a clean "ready".
        return f"ready ({'; '.join(problems)})" if problems else "ready"


@dataclass(frozen=True)
class AsbStatus:
    """A 4-byte Automatic Status Back block pushed by ``GS a``.

    Confirmed against hardware 2026-10-03 by opening and closing the cover
    with a listener attached. Observed ``14 00 00 0f`` idle and
    ``3c 00 00 0f`` with the cover open, which decodes correctly through the
    layout below. The fourth byte was ``0f`` in every block seen, in both
    states, so nothing is decoded from it - paper status comes from the third
    byte, which the cover test and the idle baseline agree on.
    """

    raw: bytes
    drawer_pin_high: bool
    online: bool
    cover_open: bool
    feeding_by_button: bool
    wait_for_online_recovery: bool
    paper_feed_button_pressed: bool
    autocutter_error: bool
    unrecoverable_error: bool
    auto_recoverable_error: bool
    paper_near_end: bool
    paper_present: bool

    @classmethod
    def decode(cls, data: bytes) -> "AsbStatus":
        if len(data) != 4:
            raise ValueError(f"an ASB block is 4 bytes, got {len(data)}")
        b1, b2, b3, b4 = data
        return cls(
            raw=bytes(data),
            drawer_pin_high=_bit(b1, 2),
            online=not _bit(b1, 3),
            cover_open=_bit(b1, 5),
            feeding_by_button=_bit(b1, 6),
            wait_for_online_recovery=_bit(b2, 0),
            paper_feed_button_pressed=_bit(b2, 1),
            autocutter_error=_bit(b2, 3),
            unrecoverable_error=_bit(b2, 5),
            auto_recoverable_error=_bit(b2, 6),
            paper_near_end=_bit(b3, 0) and _bit(b3, 1),
            paper_present=not (_bit(b3, 2) and _bit(b3, 3)),
        )


@dataclass(frozen=True)
class SymbolSize:
    """Reply to ``GS ( k fn=82`` - the dot dimensions of a stored 2-D symbol."""

    width: int
    height: int
    flag: int
    error_code: int

    @property
    def encoded(self) -> bool:
        """False when the printer rejected the payload for this symbology."""
        return self.error_code == 0 and self.width > 0 and self.height > 0

    @classmethod
    def decode(cls, reply: bytes) -> "SymbolSize":
        # 37 <id> <w> 1F <h> 1F <flag> 1F <err> 00
        if len(reply) < 4 or reply[0] != 0x37:
            raise ValueError(f"not a symbol-size reply: {reply!r}")
        body = reply[2:-1] if reply.endswith(b"\x00") else reply[2:]
        parts = body.split(b"\x1f")
        if len(parts) < 4:
            raise ValueError(f"malformed symbol-size reply: {reply!r}")
        return cls(
            width=int(parts[0] or 0),
            height=int(parts[1] or 0),
            flag=int(parts[2] or 0),
            error_code=int(parts[3] or 0),
        )


@dataclass(frozen=True)
class PrinterIdentity:
    """Everything ``GS I`` reports about the attached printer."""

    maker: str = ""
    model: str = ""
    firmware: str = ""
    serial: str = ""
    model_id: Optional[int] = None
    type_id: Optional[int] = None
    firmware_id: Optional[int] = None
    extra: dict = field(default_factory=dict)

    @property
    def has_autocutter(self) -> bool:
        """Type ID bit 1. ``0x02`` on the development unit."""
        return bool(self.type_id is not None and self.type_id & 0x02)

    @property
    def has_multibyte_font(self) -> bool:
        """Type ID bit 0. Clear on the ANK (single-byte) TM-T88V."""
        return bool(self.type_id is not None and self.type_id & 0x01)

    @property
    def has_customer_display(self) -> bool:
        """Type ID bit 2 - a DM-D attached to the printer."""
        return bool(self.type_id is not None and self.type_id & 0x04)

    def __str__(self) -> str:
        return f"{self.maker} {self.model} firmware {self.firmware} serial {self.serial}".strip()


def parse_id_string(reply: bytes) -> str:
    """Strip the ``5F`` header and trailing NUL from a ``GS I 65..69`` reply."""
    if not reply:
        return ""
    body = reply[1:] if reply[0] == 0x5F else reply
    return body.split(b"\x00", 1)[0].decode("ascii", "replace")
