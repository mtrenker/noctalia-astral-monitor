"""Hardware-free stand-ins: a fake sysfs tree and a fake i2c-dev ioctl."""

import os
import pathlib

from astral_monitor import i2c
from astral_monitor import snapshot as snap

# Real ASUS ROG Astral RTX 5090 capture from astral-watch tests (MIT, Copyright (c) 2026 Matt Beaman).
ASTRAL_WATCH_SAMPLE = bytes([
    0x2E, 0x98, 0x21, 0xD4, 0x2E, 0x90, 0x21, 0xD4, 0x2E, 0x90, 0x20, 0x80, 0x2E, 0xA0, 0x20,
    0x58, 0x2E, 0xA0, 0x21, 0x5C, 0x2E, 0xA0, 0x1F, 0xE0,
])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")


def add_pci(root, address, *, vendor=0x10DE, klass=0x030000, sub_vendor=0x1043, sub_device=0x89ED,
            adapters=(), dev_interface=True):
    """adapters: iterable of (number, name)."""
    base = pathlib.Path(root) / "bus" / "pci" / "devices" / address
    write(base / "vendor", f"0x{vendor:04x}")
    write(base / "class", f"0x{klass:06x}")
    write(base / "subsystem_vendor", f"0x{sub_vendor:04x}")
    write(base / "subsystem_device", f"0x{sub_device:04x}")
    for number, name in adapters:
        write(base / f"i2c-{number}" / "name", name)
        if dev_interface:
            (base / f"i2c-{number}" / "i2c-dev" / f"i2c-{number}").mkdir(parents=True)
    return base


class FakeBus:
    """Answers the telemetry registers from a 24-byte image and records every ioctl."""

    def __init__(self, image=ASTRAL_WATCH_SAMPLE, block=None, block_error=None):
        self.image = bytearray(image)
        self.block = block  # bytes returned by the block read; default: the image
        self.block_error = block_error
        self.calls = []
        self.address = None

    def ioctl(self, fd, request, arg):
        if request == i2c.I2C_SLAVE:
            self.calls.append(("slave", arg))
            self.address = arg
            return 0
        self.calls.append(("smbus", arg.read_write, arg.command, arg.size))
        data = arg.data.contents
        if arg.size == i2c.I2C_SMBUS_BYTE_DATA:
            data.byte = self.image[arg.command - i2c.REG_FIRST]
        elif arg.size == i2c.I2C_SMBUS_I2C_BLOCK_DATA:
            if self.block_error is not None:
                raise OSError(self.block_error, os.strerror(self.block_error))
            payload = self.image if self.block is None else self.block
            data.block[0] = len(payload)
            for index, value in enumerate(payload):
                data.block[1 + index] = value
        return 0

    def transport(self):
        return i2c.Transport(fd=99, ioctl=self.ioctl, close=lambda fd: None)

    def opener(self, error=None):
        opened = []

        def open_transport(path):
            opened.append(path)
            if error is not None:
                raise error
            return self.transport()

        open_transport.opened = opened
        return open_transport


def feeds_of(raw):
    return snap.decode_block(raw)
