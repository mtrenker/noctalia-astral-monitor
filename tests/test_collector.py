import errno
import pathlib
import re
import tempfile
import unittest

from astral_monitor import collector as col
from astral_monitor import identify
from astral_monitor import snapshot as snap

from fakes import ASTRAL_WATCH_SAMPLE, FakeBus, add_pci

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADAPTER = "NVIDIA i2c adapter 3 at 1:00.0"
TABLE = (identify.CardType(subsystem_device=0x89ED, model="Test Astral", adapter_name="NVIDIA i2c adapter 3 at *"),)


class Clock:
    def __init__(self):
        self.ms = 1_760_000_000_000

    def __call__(self):
        return self.ms


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sysfs = self._tmp.name
        self.clock = Clock()
        self.bus = FakeBus()

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, opener=None, table=TABLE):
        return col.Collector(table, sysfs=self.sysfs, dev="/dev", clock=self.clock,
                             open_transport=opener or self.bus.opener(), log=lambda _: None)

    def card(self, **kwargs):
        kwargs.setdefault("adapters", [(1, "NVIDIA i2c adapter 1 at 1:00.0"), (3, ADAPTER)])
        add_pci(self.sysfs, "0000:01:00.0", **kwargs)

    def test_supported_card_publishes_validated_feeds(self):
        self.card()
        opener = self.bus.opener()
        collector = self.make(opener)
        self.assertEqual(collector.starting()["status"], "starting")
        value = collector.poll()
        self.assertEqual(value["status"], "ok")
        self.assertEqual(value["source"], "hardware")
        self.assertEqual(value["feeds"], snap.decode_block(ASTRAL_WATCH_SAMPLE))
        self.assertEqual(value["device"], {"model": "Test Astral", "pci_subsystem": "1043:89ed"})
        self.assertEqual(value["collector"]["sequence"], 2)
        self.assertEqual(opener.opened, ["/dev/i2c-3"])

    def test_unsupported_card_causes_no_device_access(self):
        self.card(sub_device=0x1234)
        add_pci(self.sysfs, "0000:02:00.0", sub_vendor=0x1462, adapters=[(5, ADAPTER)])  # non-ASUS
        add_pci(self.sysfs, "0000:00:02.0", vendor=0x8086, adapters=[(0, "i915 gmbus")])
        opener = self.bus.opener()
        collector = self.make(opener)
        for _ in range(3):
            value = collector.poll()
            self.assertEqual(value["status"], "unsupported")
            self.assertNotIn("feeds", value)
            self.assertNotIn("device", value)
        self.assertEqual(opener.opened, [])
        self.assertEqual(self.bus.calls, [])

    def test_shipped_table_ignores_unvalidated_astral_subsystems(self):
        self.card()  # 1043:89ed: an astral-watch candidate, not trialled here
        opener = self.bus.opener()
        value = self.make(opener, table=identify.SUPPORTED_CARDS).poll()
        self.assertEqual(value["status"], "unsupported")
        self.assertEqual(opener.opened, [])

    def test_unsupported_retries_identification_every_30_s(self):
        collector = self.make()
        collector.poll()
        self.card()
        self.clock.ms += 29_000
        self.assertEqual(collector.poll()["status"], "unsupported")
        self.clock.ms += 1_000
        self.assertEqual(collector.poll()["status"], "ok")

    def test_missing_i2c_dev_is_no_adapter(self):
        self.card(dev_interface=False)
        value = self.make().poll()
        self.assertEqual(value["status"], "no_adapter")
        self.assertIn("i2c-dev", value["message"])
        self.assertEqual(self.bus.calls, [])

    def test_ambiguous_or_absent_adapter_is_no_adapter(self):
        self.card(adapters=[(3, ADAPTER), (4, "NVIDIA i2c adapter 3 at 1:00.0 (copy)")])
        table = (identify.CardType(0x89ED, "Test", "NVIDIA i2c adapter 3 at 1:00.0*"),)
        value = self.make(table=table).poll()
        self.assertEqual(value["status"], "no_adapter")
        self.assertIn("not guessing", value["message"])
        table = (identify.CardType(0x89ED, "Test", "Something else"),)
        self.assertEqual(self.make(table=table).poll()["status"], "no_adapter")

    def test_adapters_of_other_cards_are_never_candidates(self):
        self.card(adapters=[(1, "NVIDIA i2c adapter 1 at 1:00.0")])
        add_pci(self.sysfs, "0000:02:00.0", sub_device=0x1234, adapters=[(3, ADAPTER)])
        opener = self.bus.opener()
        self.assertEqual(self.make(opener).poll()["status"], "no_adapter")
        self.assertEqual(opener.opened, [])

    def test_permission_denied(self):
        self.card()
        value = self.make(self.bus.opener(PermissionError(errno.EACCES, "denied"))).poll()
        self.assertEqual(value["status"], "permission_denied")
        self.assertNotIn("feeds", value)

    def test_busy_address_is_not_forced(self):
        self.card()
        value = self.make(self.bus.opener(OSError(errno.EBUSY, "busy"))).poll()
        self.assertEqual(value["status"], "read_error")
        self.assertIn("not forcing", value["message"])

    def test_failed_reads_publish_read_error_without_feeds(self):
        self.card()
        for image in (bytes(24), bytes([0x00, 0x10, 0x10, 0x00] * 6)):
            bus = FakeBus(image=image)
            value = self.make(bus.opener()).poll()
            self.assertEqual(value["status"], "read_error")
            self.assertNotIn("feeds", value)

    def test_transfer_error_triggers_rediscovery(self):
        self.card()
        opener = self.bus.opener()
        collector = self.make(opener)
        self.assertEqual(collector.poll()["status"], "ok")

        def broken(fd, request, arg):
            raise OSError(errno.EIO, "Input/output error")

        collector.transport._ioctl_fn = broken
        value = collector.poll()
        self.assertEqual(value["status"], "read_error")
        self.assertIsNone(collector.card)
        self.assertEqual(collector.poll()["status"], "ok")
        self.assertEqual(opener.opened, ["/dev/i2c-3", "/dev/i2c-3"])

    def test_restart_is_a_new_instance(self):
        first, second = self.make(), self.make()
        self.assertNotEqual(first.instance, second.instance)


class CliTest(unittest.TestCase):
    def test_udev_rule_names_one_adapter_on_the_listed_card(self):
        rule = col.udev_rule(TABLE)
        line = [l for l in rule.splitlines() if not l.startswith("#")]
        self.assertEqual(len(line), 1)
        for part in ('SUBSYSTEM=="i2c-dev"', 'ATTR{name}=="NVIDIA i2c adapter 3 at *"',
                     'ATTRS{vendor}=="0x10de"', 'ATTRS{subsystem_vendor}=="0x1043"',
                     'ATTRS{subsystem_device}=="0x89ed"', 'GROUP="astral-monitor"', 'MODE="0660"'):
            self.assertIn(part, line[0])

    def test_identify_report_opens_nothing_and_lists_adapters(self):
        with tempfile.TemporaryDirectory() as sysfs:
            add_pci(sysfs, "0000:01:00.0", adapters=[(3, ADAPTER)], dev_interface=False)
            report = col.identify_report((), sysfs)
        self.assertIn("1043:89ed  (not in the supported table)", report)
        self.assertIn("i2c-3  'NVIDIA i2c adapter 3 at 1:00.0'  no /dev node", report)

    def test_trial_override_requires_an_asus_subsystem(self):
        with self.assertRaises(ValueError):
            identify.parse_subsystem("10de:2b85")
        self.assertEqual(identify.parse_subsystem("1043:89ed"), 0x89ED)

    def test_shipped_support_table_lists_only_trialled_cards(self):
        self.assertEqual([row.subsystem_device for row in identify.SUPPORTED_CARDS], [0x89E3])

    def test_shipped_table_selects_the_trialled_adapter(self):
        with tempfile.TemporaryDirectory() as sysfs:
            add_pci(sysfs, "0000:0a:00.0", sub_device=0x89E3, adapters=[
                (number, f"NVIDIA i2c adapter {number - 2} at a:00.0") for number in range(3, 10)])
            card = identify.find_card(identify.SUPPORTED_CARDS, sysfs)
            self.assertEqual(identify.select_adapter(card, sysfs).number, 3)


class ScopeTest(unittest.TestCase):
    def test_collector_has_no_control_network_or_process_paths(self):
        forbidden = re.compile(
            r"^\s*(import|from)\s+(socket|subprocess|urllib|http|pynvml|smbus)|nvidia-smi|nvml|"
            r"power[_ ]limit|I2C_SLAVE_FORCE|0x0706|I2C_RDWR|os\.kill|signal\.SIGKILL",
            re.M | re.I)
        for name in ("collector.py", "i2c.py", "identify.py"):
            source = (ROOT / "collector" / "astral_monitor" / name).read_text(encoding="utf-8")
            code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
            # The module docstring of i2c.py names I2C_SLAVE_FORCE to say it is never used.
            code = re.sub(r'""".*?"""', "", code, flags=re.S)
            self.assertIsNone(forbidden.search(code), name)


if __name__ == "__main__":
    unittest.main()
