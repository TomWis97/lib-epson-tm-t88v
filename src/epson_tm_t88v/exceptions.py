"""Exception hierarchy for the TM-T88V driver."""

from __future__ import annotations


class PrinterError(Exception):
    """Base class for every error raised by this package."""


class TransportError(PrinterError):
    """The underlying byte channel to the printer failed."""


class DeviceNotFound(TransportError):
    """No usable printer device node could be opened."""


class WriteTimeout(TransportError):
    """The printer stopped accepting data within the allotted time.

    Seen in practice when the printer's receive buffer fills up, e.g. after a
    burst of commands the firmware does not implement. The device returns
    EAGAIN and never becomes writable again until it drains.
    """


class ReadTimeout(TransportError):
    """The printer did not answer a query within the allotted time."""


class PrinterOffline(PrinterError):
    """The printer reported itself offline."""


class PrinterFault(PrinterError):
    """The printer reported an error condition (cover, paper, cutter, ...)."""

    def __init__(self, message: str, status: object = None) -> None:
        super().__init__(message)
        self.status = status


class EncodingError(PrinterError):
    """Text could not be encoded in the selected character code table."""


class DataTooLarge(PrinterError):
    """A payload exceeds what the command (or the printer) can carry."""


class UnsupportedFeature(PrinterError):
    """The requested feature is not available on the TM-T88V."""
