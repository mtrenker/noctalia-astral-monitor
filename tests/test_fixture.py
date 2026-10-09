import json
import pathlib
import re
import unittest

from astral_monitor import fixture
from astral_monitor import snapshot as snap

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FixtureTest(unittest.TestCase):
    def test_every_scenario_is_labelled_and_matches_the_schema(self):
        collector = fixture.Collector(1000)
        for scenario in fixture.STEADY:
            value = fixture.snapshot_for(scenario, collector, 5000, t=1.0)
            if scenario == "invalid":
                with self.assertRaises(json.JSONDecodeError):
                    json.loads(value)
                continue
            self.assertEqual(value["schema_version"], 1, scenario)
            self.assertEqual(value["source"], "fixture", scenario)
            self.assertIn(value["status"], snap.STATUSES, scenario)
            self.assertEqual(value["observed_at_ms"], 5000, scenario)
            self.assertEqual("feeds" in value, value["status"] == "ok", scenario)
            json.dumps(value)

    def test_warning_scenario_puts_one_feed_over_9_2_a(self):
        value = fixture.snapshot_for("warning", fixture.Collector(0), 0, t=2.0)
        over = [f["pin"] for f in value["feeds"] if f["current_ma"] >= 9200]
        self.assertEqual(over, [fixture.WARNING_PIN])

    def test_short_block_goes_through_the_decoder_to_read_error(self):
        value = fixture.snapshot_for("read_error", fixture.Collector(0), 0)
        self.assertEqual(value["status"], "read_error")
        self.assertNotIn("feeds", value)
        self.assertIn("short read", value["message"])

    def test_restart_is_a_new_instance_with_sequence_from_one(self):
        first = fixture.Collector(0)
        fixture.snapshot_for("normal", first, 0)
        fixture.snapshot_for("normal", first, 1)
        second = fixture.Collector(10)
        value = fixture.snapshot_for("starting", second, 10)
        self.assertNotEqual(second.instance, first.instance)
        self.assertEqual(value["collector"]["sequence"], 1)
        self.assertEqual(value["collector"]["started_at_ms"], 10)

    def test_fixture_and_shared_code_never_open_devices(self):
        for name in ("fixture.py", "snapshot.py"):
            path = ROOT / "collector" / "astral_monitor" / name
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("/dev/", source, path.name)
            self.assertIsNone(re.search(r"^\s*(import|from)\s+(fcntl|smbus|ctypes)", source, re.M), path.name)


if __name__ == "__main__":
    unittest.main()
