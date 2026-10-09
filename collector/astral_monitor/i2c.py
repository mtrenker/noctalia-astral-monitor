"""Read-only access to the IT8915FN telemetry registers over /dev/i2c-*.

Only two ioctl requests are ever issued: I2C_SLAVE (select address 0x2B, never the
FORCE variant) and I2C_SMBUS with read_write=READ for either one register in
0x80-0x97 or the 24-byte block at 0x80. The SMBus read protocol transmits the
register number; no data byte is ever written.

The read strategy is ported from astral-watch src/i2c.rs
(https://github.com/mbeaman/astral-watch/blob/dce7eee77676268c66b3624c7a2870ed9d84eb9c/src/i2c.rs):

    Copyright (c) 2026 Matt Beaman, MIT License. The full notice is in
    LICENSES/astral-watch-MIT.txt and must travel with this file.

In short: a per-register read is the reference. The single-transaction block read is
used only after it has matched that reference on this device; a block that answers
wrongly falls back to per-register reads for good, and repeated block errors do too.
Per-register 16-bit values are read high, low, high and re-read while the high byte
moves, so a value updated mid-read is not published as a phantom spike.
"""

import ctypes
import fcntl
import os

from . import snapshot as snap

ADDRESS = 0x2B
REG_FIRST = 0x80
REG_LAST = REG_FIRST + snap.BLOCK_LEN - 1

# linux/i2c-dev.h and linux/i2c.h
I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
I2C_SMBUS_READ = 1
I2C_SMBUS_BYTE_DATA = 2
I2C_SMBUS_I2C_BLOCK_DATA = 8
I2C_SMBUS_BLOCK_MAX = 32
ALLOWED_REQUESTS = (I2C_SLAVE, I2C_SMBUS)

BLOCK_PROBE_ATTEMPTS = 3
BLOCK_PROBE_TOLERANCE_MV = 500
TEAR_RETRIES = 3


class SmbusData(ctypes.Union):
    _fields_ = [("byte", ctypes.c_uint8), ("word", ctypes.c_uint16),
                ("block", ctypes.c_uint8 * (I2C_SMBUS_BLOCK_MAX + 2))]


class SmbusIoctlData(ctypes.Structure):
    _fields_ = [("read_write", ctypes.c_uint8), ("command", ctypes.c_uint8),
                ("size", ctypes.c_uint32), ("data", ctypes.POINTER(SmbusData))]


class Transport:
    """One open adapter, restricted to read transfers from the telemetry registers."""

    def __init__(self, fd, ioctl=fcntl.ioctl, close=os.close):
        self._fd = fd
        self._ioctl_fn = ioctl
        self._close_fn = close
        self._ioctl(I2C_SLAVE, ADDRESS)

    @classmethod
    def open(cls, path, opener=os.open, **kwargs):
        # i2c-dev needs a read-write descriptor for its ioctls; read-only use is enforced here.
        fd = opener(path, os.O_RDWR | os.O_CLOEXEC)
        try:
            return cls(fd, **kwargs)
        except BaseException:
            kwargs.get("close", os.close)(fd)
            raise

    def _ioctl(self, request, arg):
        if request not in ALLOWED_REQUESTS:
            raise PermissionError(f"ioctl {request:#06x} is not allowed")
        if request == I2C_SMBUS and arg.read_write != I2C_SMBUS_READ:
            raise PermissionError("only SMBus read transfers are allowed")
        return self._ioctl_fn(self._fd, request, arg)

    def _smbus_read(self, command, size, length=0):
        data = SmbusData()
        if size == I2C_SMBUS_I2C_BLOCK_DATA:
            data.block[0] = length
        args = SmbusIoctlData(read_write=I2C_SMBUS_READ, command=command, size=size,
                              data=ctypes.pointer(data))
        self._ioctl(I2C_SMBUS, args)
        return data

    def read_register(self, register):
        if not REG_FIRST <= register <= REG_LAST:
            raise ValueError(f"register {register:#04x} is outside the telemetry range")
        return self._smbus_read(register, I2C_SMBUS_BYTE_DATA).byte

    def read_block(self):
        data = self._smbus_read(REG_FIRST, I2C_SMBUS_I2C_BLOCK_DATA, snap.BLOCK_LEN)
        count = data.block[0]
        if count != snap.BLOCK_LEN:
            raise snap.ReadError(f"short read: {count} of {snap.BLOCK_LEN} bytes")
        return bytes(data.block[1 : 1 + count])

    def close(self):
        if self._fd is not None:
            self._close_fn(self._fd)
            self._fd = None


def read_bytewise(transport):
    """The reference read: 12 tear-checked 16-bit values, one register at a time."""
    raw = bytearray()
    for register in range(REG_FIRST, REG_LAST + 1, 2):
        high = transport.read_register(register)
        low = transport.read_register(register + 1)
        for _ in range(TEAR_RETRIES):
            again = transport.read_register(register)
            if again == high:
                break
            high = again
            low = transport.read_register(register + 1)
        raw += bytes((high, low))
    return bytes(raw)


def _plausible(raw):
    try:
        return snap.decode_block(raw)
    except snap.ReadError:
        return None


def _agrees(block, reference_feeds):
    feeds = _plausible(block)
    return feeds is not None and all(
        abs(a["voltage_mv"] - b["voltage_mv"]) <= BLOCK_PROBE_TOLERANCE_MV
        for a, b in zip(feeds, reference_feeds))


class Reader:
    """Chooses block or per-register reads for one device and returns raw 24-byte blocks."""

    def __init__(self, log=print):
        self.mode = "unprobed"
        self.block_errors = 0
        self._log = log

    def _latch(self, mode):
        self.mode = mode
        how = "block read (1 transaction per sample)" if mode == "block" else "per-register reads"
        self._log(f"telemetry access: {how}")

    def read(self, transport):
        if self.mode == "block":
            raw = transport.read_block()
            if _plausible(raw) is None:
                self.mode, self.block_errors = "unprobed", 0
            return raw
        if self.mode == "bytewise":
            return read_bytewise(transport)
        reference = read_bytewise(transport)
        reference_feeds = _plausible(reference)
        if reference_feeds is None:
            return reference
        try:
            block = transport.read_block()
        except (OSError, snap.ReadError):
            self.block_errors += 1
            if self.block_errors >= BLOCK_PROBE_ATTEMPTS:
                self._latch("bytewise")
            return reference
        self._latch("block" if _agrees(block, reference_feeds) else "bytewise")
        return reference
