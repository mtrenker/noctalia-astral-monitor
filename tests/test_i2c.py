import errno
import unittest

from astral_monitor import i2c
from astral_monitor import snapshot as snap

from fakes import ASTRAL_WATCH_SAMPLE, FakeBus


class TransportTest(unittest.TestCase):
    def test_only_address_select_and_smbus_reads_are_issued(self):
        bus = FakeBus()
        transport = bus.transport()
        i2c.read_bytewise(transport)
        transport.read_block()
        self.assertEqual(bus.calls[0], ("slave", 0x2B))
        for call in bus.calls[1:]:
            kind, read_write, command, size = call
            self.assertEqual(kind, "smbus")
            self.assertEqual(read_write, i2c.I2C_SMBUS_READ)
            self.assertTrue(0x80 <= command <= 0x97, hex(command))
            self.assertIn(size, (i2c.I2C_SMBUS_BYTE_DATA, i2c.I2C_SMBUS_I2C_BLOCK_DATA))

    def test_block_read_is_one_transfer_returning_the_registers(self):
        bus = FakeBus()
        self.assertEqual(bus.transport().read_block(), ASTRAL_WATCH_SAMPLE)
        self.assertEqual(bus.calls[1:], [("smbus", 1, 0x80, i2c.I2C_SMBUS_I2C_BLOCK_DATA)])

    def test_registers_outside_the_telemetry_window_are_refused(self):
        transport = FakeBus().transport()
        for register in (0x7F, 0x98, 0x00):
            with self.assertRaises(ValueError):
                transport.read_register(register)

    def test_write_transfers_and_other_requests_are_refused(self):
        transport = FakeBus().transport()
        with self.assertRaises(PermissionError):
            transport._ioctl(0x0706, 0x2B)  # I2C_SLAVE_FORCE
        args = i2c.SmbusIoctlData(read_write=0, command=0x80, size=i2c.I2C_SMBUS_BYTE_DATA)
        with self.assertRaises(PermissionError):
            transport._ioctl(i2c.I2C_SMBUS, args)

    def test_short_block_is_a_read_error(self):
        bus = FakeBus(block=ASTRAL_WATCH_SAMPLE[:20])
        with self.assertRaisesRegex(snap.ReadError, "short read: 20 of 24"):
            bus.transport().read_block()


class TearTest(unittest.TestCase):
    def test_moving_high_byte_is_reread(self):
        bus = FakeBus()
        transport = bus.transport()
        reads = {"count": 0}
        original = bus.ioctl

        def tearing(fd, request, arg):
            original(fd, request, arg)
            # The first time register 0x80 is read, report a stale high byte.
            if request == i2c.I2C_SMBUS and arg.command == 0x80 and reads["count"] == 0:
                reads["count"] += 1
                arg.data.contents.byte = 0x2F
            return 0

        transport._ioctl_fn = tearing
        raw = i2c.read_bytewise(transport)
        self.assertEqual(raw, ASTRAL_WATCH_SAMPLE)


class ReaderTest(unittest.TestCase):
    def test_block_path_is_used_after_it_matches_the_reference(self):
        bus = FakeBus()
        reader = i2c.Reader(log=lambda _: None)
        transport = bus.transport()
        self.assertEqual(reader.read(transport), ASTRAL_WATCH_SAMPLE)
        self.assertEqual(reader.mode, "block")
        bus.calls.clear()
        reader.read(transport)
        self.assertEqual(len(bus.calls), 1)

    def test_shifted_block_latches_per_register_reads(self):
        shifted = bytes([24]) + ASTRAL_WATCH_SAMPLE[:-1]  # what a length-prefixed read returns
        reader = i2c.Reader(log=lambda _: None)
        self.assertEqual(reader.read(FakeBus(block=shifted).transport()), ASTRAL_WATCH_SAMPLE)
        self.assertEqual(reader.mode, "bytewise")

    def test_block_errors_latch_per_register_reads_after_three_attempts(self):
        bus = FakeBus(block_error=errno.EIO)
        reader = i2c.Reader(log=lambda _: None)
        transport = bus.transport()
        for attempt in range(1, 4):
            self.assertEqual(reader.read(transport), ASTRAL_WATCH_SAMPLE)
            self.assertEqual(reader.mode, "bytewise" if attempt == 3 else "unprobed")

    def test_implausible_reference_teaches_nothing(self):
        reader = i2c.Reader(log=lambda _: None)
        raw = reader.read(FakeBus(image=bytes(24)).transport())
        self.assertEqual(raw, bytes(24))
        self.assertEqual(reader.mode, "unprobed")

    def test_garbage_on_the_block_path_reopens_the_question(self):
        bus = FakeBus()
        reader = i2c.Reader(log=lambda _: None)
        transport = bus.transport()
        reader.read(transport)
        bus.block = bytes(24)
        self.assertEqual(reader.read(transport), bytes(24))
        self.assertEqual(reader.mode, "unprobed")


if __name__ == "__main__":
    unittest.main()
