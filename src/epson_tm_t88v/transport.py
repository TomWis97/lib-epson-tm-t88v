"""Byte channels to the printer.

The USB transport deliberately does its own ``select()``-driven write loop
rather than relying on blocking ``write``. During development the printer
stopped accepting data part-way through a write and returned ``EAGAIN``
indefinitely; a naive write either raises ``BlockingIOError`` or silently
truncates the command stream, which on a receipt printer means garbage on
paper. See FINDINGS.md section 6.
"""

from __future__ import annotations

import errno
import glob
import os
import select
import time
from abc import ABC, abstractmethod
from typing import List, Optional

from .exceptions import DeviceNotFound, ReadTimeout, TransportError, WriteTimeout

#: Where the Linux ``usblp`` driver puts USB printer-class devices. The modern
#: udev location is ``/dev/usb/lp0``; older setups use ``/dev/usblp0``.
DEVICE_GLOBS = ("/dev/usb/lp*", "/dev/usblp*")

#: Set this to point the driver at a node outside the usual locations - a
#: different name, or a path the node has been bind-mounted to.
DEVICE_ENV_VAR = "EPSON_TM_T88V_DEVICE"


def find_devices() -> List[str]:
    """Return every candidate printer device node, best guess first.

    ``EPSON_TM_T88V_DEVICE`` wins if it is set and exists, so the node can
    live somewhere other than the two standard locations without any code or
    command line knowing where.
    """
    found: List[str] = []
    override = os.environ.get(DEVICE_ENV_VAR)
    if override and os.path.exists(override):
        found.append(override)
    for pattern in DEVICE_GLOBS:
        found.extend(path for path in sorted(glob.glob(pattern)) if path not in found)
    return found


class Transport(ABC):
    """A bidirectional byte channel."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        ...

    @abstractmethod
    def read(self, max_bytes: int = 4096, timeout: float = 1.0) -> bytes:
        ...

    def drain(self, timeout: float = 0.1) -> bytes:
        """Consume and return anything the printer has already sent."""
        out = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = self.read(4096, timeout=remaining)
            if not chunk:
                break
            out += chunk
        return bytes(out)

    def close(self) -> None:
        ...

    #: Whether this transport can carry status replies back from the printer.
    #: False for the buffer and file transports, which are write-only.
    supports_status: bool = False

    def resync(self) -> bool:
        """Recover a desynchronised command stream. A no-op off real hardware."""
        return True

    @property
    def desynced(self) -> bool:
        return False

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class UsbTransport(Transport):
    """Talks to the printer through a ``usblp`` character device.

    The node is opened ``O_RDWR | O_NONBLOCK``; the TM-T88V answers status
    queries on the same descriptor, which is what makes real status handling
    possible.
    """

    supports_status: bool = True

    def __init__(
        self,
        device: Optional[str] = None,
        write_timeout: float = 10.0,
        read_timeout: float = 2.0,
    ) -> None:
        if device is None:
            candidates = find_devices()
            if not candidates:
                raise DeviceNotFound(
                    "no printer device node found; looked for "
                    + " and ".join(DEVICE_GLOBS)
                )
            device = candidates[0]
        self.device = device
        self.write_timeout = write_timeout
        self.read_timeout = read_timeout
        self._desynced = False
        try:
            self._fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno == errno.EACCES:
                raise DeviceNotFound(
                    f"permission denied opening {device}. Add your user to the "
                    f"'lp' group, or install a udev rule granting access."
                ) from exc
            if exc.errno == errno.ENOENT:
                raise DeviceNotFound(f"{device} does not exist") from exc
            if exc.errno == errno.ENODEV:
                raise DeviceNotFound(
                    f"{device} exists but the printer is not connected"
                ) from exc
            raise TransportError(f"could not open {device}: {exc}") from exc

    def write(self, data: bytes) -> None:
        """Send ``data``, tolerating a printer that drains its buffer slowly.

        ``write_timeout`` is an *idle* budget, not a total one: it restarts
        every time the printer accepts more bytes. The receive buffer is only
        4 KB, so a full-width image queued behind a page of barcodes can take
        far longer to hand over than any fixed deadline would allow, and only a
        complete lack of progress actually indicates a problem.

        A timeout part-way through a command leaves the printer waiting for the
        rest of that command's payload. In that state it silently swallows
        everything sent to it, real-time status queries included, so it looks
        dead while being perfectly healthy. :meth:`resync` undoes it, and the
        error message says so.
        """
        if self._fd < 0:
            raise TransportError("transport is closed")
        sent = 0
        idle_deadline = time.monotonic() + self.write_timeout
        while sent < len(data):
            remaining = idle_deadline - time.monotonic()
            if remaining <= 0:
                self._desynced = sent > 0
                raise WriteTimeout(
                    f"printer accepted no data for {self.write_timeout:g}s, "
                    f"after {sent} of {len(data)} bytes. It has gone offline "
                    f"mid-job: check the front panel, and note that this unit "
                    f"lights its paper LED on a full roll - opening and "
                    f"closing the cover clears that."
                    + (
                        " The write stopped inside a command, so the printer "
                        "is now waiting for the remainder of it; call "
                        "resync() before using it again."
                        if sent > 0
                        else ""
                    )
                )
            _, writable, _ = select.select([], [self._fd], [], min(remaining, 0.25))
            if not writable:
                continue
            try:
                n = os.write(self._fd, data[sent:])
            except BlockingIOError:
                # Reported writable but still not ready; back off and retry.
                time.sleep(0.01)
                continue
            except OSError as exc:
                self._desynced = sent > 0
                raise TransportError(
                    f"write to {self.device} failed after {sent} bytes: {exc}"
                ) from exc
            if n:
                sent += n
                idle_deadline = time.monotonic() + self.write_timeout

    @property
    def desynced(self) -> bool:
        """True when a write failed mid-command and :meth:`resync` is needed."""
        return self._desynced

    def answers(self, timeout: float = 0.6) -> bool:
        """True when the printer replies to ``DLE EOT 1``.

        A printer that is merely busy, offline or out of paper still answers
        this; one that is mid-payload does not. That makes it the test for
        whether the command stream is synchronised.
        """
        self.drain(0.02)
        self.write(b"\x10\x04\x01")
        return bool(self.read(8, timeout=timeout))

    def resync(self, max_filler: int = 70000, chunk: int = 1024) -> bool:
        """Return a printer stuck mid-payload to a command boundary.

        ``0x00`` is the only byte that is safe as filler: it is a blank raster
        pixel inside image data and a no-op to the command parser outside it.
        Filler is poured in until the printer answers again, which means the
        outstanding payload has been satisfied; ``ESC @`` then discards
        whatever that filler became, without feeding or printing.

        Returns False if ``max_filler`` bytes were not enough, which means the
        printer is stuck on something other than a truncated command.
        """
        if self._fd < 0:
            raise TransportError("transport is closed")
        poured = 0
        while not self.answers():
            if poured >= max_filler:
                self._desynced = True
                return False
            step = min(chunk, max_filler - poured)
            self.write(b"\x00" * step)
            poured += step
        self.write(b"\x1b\x40")
        time.sleep(0.2)
        self.drain(0.2)
        self._desynced = False
        return True

    def read(self, max_bytes: int = 4096, timeout: Optional[float] = None) -> bytes:
        if self._fd < 0:
            raise TransportError("transport is closed")
        """Return the bytes that arrive within ``timeout``, or b"" if none do.

        ``usblp`` reports the node readable even when nothing has arrived, and
        ``read()`` then returns zero bytes instead of blocking or raising
        ``EAGAIN`` (measured 2026-10-07, FINDINGS.md section 10). So an empty
        read means "nothing yet", and this keeps polling until the deadline.
        """
        if timeout is None:
            timeout = self.read_timeout
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            readable, _, _ = select.select([self._fd], [], [], max(0.0, remaining))
            if readable:
                try:
                    data = os.read(self._fd, max_bytes)
                except BlockingIOError:
                    data = b""
                except OSError as exc:
                    raise TransportError(f"read from {self.device} failed: {exc}") from exc
                if data:
                    return data
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            time.sleep(min(0.005, remaining))

    def query(
        self,
        command: bytes,
        expect: int = 0,
        timeout: float = 1.0,
        terminator: Optional[bytes] = None,
    ) -> bytes:
        """Send ``command`` and collect the reply.

        Stops as soon as ``expect`` bytes have arrived, or ``terminator`` has
        been seen, or ``timeout`` elapses. Returns whatever did arrive - an
        empty result is how an unsupported command reports itself, so this is
        not treated as an error.
        """
        self.drain(0.02)
        self.write(command)
        out = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            if expect and len(out) >= expect:
                break
            if terminator and out.endswith(terminator):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = self.read(4096, timeout=remaining)
            if chunk:
                out += chunk
        return bytes(out)

    def query_required(self, command: bytes, **kwargs: object) -> bytes:
        """Like :meth:`query`, but raise :class:`ReadTimeout` on an empty reply."""
        reply = self.query(command, **kwargs)  # type: ignore[arg-type]
        if not reply:
            raise ReadTimeout(f"no reply to {command.hex(' ')}")
        return reply

    def close(self) -> None:
        if getattr(self, "_fd", -1) >= 0:
            os.close(self._fd)
            self._fd = -1


class BufferTransport(Transport):
    """Collects bytes in memory instead of printing.

    Useful for tests, for inspecting exactly what would be sent, and for
    building a receipt without a printer attached.
    """

    def __init__(self, replies: Optional[List[bytes]] = None) -> None:
        self.buffer = bytearray()
        self._replies = list(replies or [])

    def write(self, data: bytes) -> None:
        self.buffer += data

    def read(self, max_bytes: int = 4096, timeout: float = 1.0) -> bytes:
        return self._replies.pop(0) if self._replies else b""

    def query(self, command: bytes, **kwargs: object) -> bytes:
        self.write(command)
        return self._replies.pop(0) if self._replies else b""

    @property
    def data(self) -> bytes:
        return bytes(self.buffer)


class FileTransport(Transport):
    """Writes the byte stream to a file. Write-only; reads return nothing."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh = open(path, "wb")

    def write(self, data: bytes) -> None:
        self._fh.write(data)

    def read(self, max_bytes: int = 4096, timeout: float = 1.0) -> bytes:
        return b""

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
