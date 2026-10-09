import json
import os
import stat
import tempfile
import unittest

from astral_monitor import snapshot as snap

# ASTRAL_WATCH_SAMPLE is a real capture from an ASUS ROG Astral RTX 5090 at ~607 W, published
# in astral-watch's src/decode.rs tests (MIT, Copyright (c) 2026 Matt Beaman, commit dce7eee).
from fakes import ASTRAL_WATCH_SAMPLE

COLLECTOR = {"instance": "abcd1234", "started_at_ms": 1, "sequence": 1}


class DecodeTest(unittest.TestCase):
    def test_known_bytes_decode_to_units_in_pin_order(self):
        feeds = snap.decode_block(ASTRAL_WATCH_SAMPLE)
        self.assertEqual([f["pin"] for f in feeds], [1, 2, 3, 4, 5, 6])
        # The last register group is pin 1; the first is pin 6.
        self.assertEqual(feeds[0], {"pin": 1, "voltage_mv": 11936, "current_ma": 8160})
        self.assertEqual(feeds[5], {"pin": 6, "voltage_mv": 11928, "current_ma": 8660})
        self.assertEqual(sum(f["current_ma"] for f in feeds), 50620)

    def test_short_read_is_an_error(self):
        with self.assertRaisesRegex(snap.ReadError, "short read: 23 of 24"):
            snap.decode_block(ASTRAL_WATCH_SAMPLE[:-1])
        with self.assertRaises(snap.ReadError):
            snap.decode_block(b"")

    def test_all_zero_block_is_an_error_not_zero_current(self):
        with self.assertRaisesRegex(snap.ReadError, "all-zero"):
            snap.decode_block(bytes(24))

    def test_implausible_voltage_is_an_error(self):
        low = bytes([0x00, 0x10, 0x10, 0x00] * 6)
        high = bytes([0xFF, 0xFF, 0x10, 0x00] * 6)
        for raw in (low, high):
            with self.assertRaisesRegex(snap.ReadError, "implausible"):
                snap.decode_block(raw)

    def test_encode_is_the_inverse_of_decode(self):
        feeds = snap.decode_block(ASTRAL_WATCH_SAMPLE)
        self.assertEqual(snap.encode_block(feeds), ASTRAL_WATCH_SAMPLE)


class BuildTest(unittest.TestCase):
    def test_ok_requires_feeds_and_errors_forbid_them(self):
        feeds = snap.decode_block(ASTRAL_WATCH_SAMPLE)
        with self.assertRaises(ValueError):
            snap.build_snapshot(source="fixture", status="ok", observed_at_ms=1, collector=COLLECTOR)
        with self.assertRaises(ValueError):
            snap.build_snapshot(source="fixture", status="read_error", observed_at_ms=1,
                                collector=COLLECTOR, feeds=feeds)

    def test_unknown_source_or_status_is_rejected(self):
        with self.assertRaises(ValueError):
            snap.build_snapshot(source="demo", status="starting", observed_at_ms=1, collector=COLLECTOR)
        with self.assertRaises(ValueError):
            snap.build_snapshot(source="fixture", status="fine", observed_at_ms=1, collector=COLLECTOR)


class WriteTest(unittest.TestCase):
    def test_atomic_write_replaces_file_and_leaves_no_temporaries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "snapshot.json")
            first = snap.build_snapshot(source="fixture", status="starting", observed_at_ms=1,
                                        collector=COLLECTOR)
            snap.write_snapshot(path, first)
            second = dict(first, observed_at_ms=2)
            snap.write_snapshot(path, second)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["observed_at_ms"], 2)
            self.assertEqual(os.listdir(directory), ["snapshot.json"])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)


if __name__ == "__main__":
    unittest.main()
