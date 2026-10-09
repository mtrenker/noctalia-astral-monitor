"""Read-only Astral power-feed collector: one sensor, one snapshot file (docs/design.md).

    python3 -m astral_monitor.collector              poll once a second, write the snapshot
    python3 -m astral_monitor.collector --identify   report cards and adapters from sysfs only
    python3 -m astral_monitor.collector --once       one sample as JSON on stdout, no file
    python3 -m astral_monitor.collector --udev-rule  print the device-permission rule

It issues no power, clock, fan, or process commands and opens no network sockets.
"""

import argparse
import errno
import json
import os
import secrets
import signal
import sys
import time

from . import i2c
from . import identify
from . import snapshot as snap

DEFAULT_OUT = "/run/astral-monitor/snapshot.json"
INTERVAL_MS = 1000
UNSUPPORTED_RETRY_MS = 30000


def now_ms():
    return int(time.time() * 1000)


class Collector:
    """Turns each poll into exactly one schema-v1 snapshot. All I/O is injectable for tests."""

    def __init__(self, table, *, sysfs="/sys", dev="/dev", clock=now_ms,
                 open_transport=i2c.Transport.open, log=print):
        self.table = tuple(table)
        self.sysfs = sysfs
        self.dev = dev
        self.clock = clock
        self.open_transport = open_transport
        self.log = log
        self.instance = secrets.token_hex(4)
        self.started_at_ms = clock()
        self.sequence = 0
        self.card = None
        self.adapter = None
        self.transport = None
        self.reader = None
        self.next_identify_ms = 0

    def _snapshot(self, status, message="", feeds=None):
        self.sequence += 1
        device = None
        if self.card is not None:
            device = {"model": self.card.model, "pci_subsystem": self.card.subsystem}
        return snap.build_snapshot(
            source="hardware", status=status, message=message, observed_at_ms=self.clock(),
            interval_ms=INTERVAL_MS, device=device, feeds=feeds,
            collector={"instance": self.instance, "started_at_ms": self.started_at_ms,
                       "sequence": self.sequence})

    def starting(self):
        return self._snapshot("starting", "Waiting for the first validated sample.")

    def _drop_device(self):
        if self.transport is not None:
            self.transport.close()
        self.transport = None
        self.adapter = None
        self.reader = None
        self.card = None
        self.next_identify_ms = 0

    def poll(self):
        if self.card is None:
            if self.clock() < self.next_identify_ms:
                return self._snapshot("unsupported", "No supported ASUS ROG Astral card found.")
            self.card = identify.find_card(self.table, self.sysfs)
            if self.card is None:
                self.next_identify_ms = self.clock() + UNSUPPORTED_RETRY_MS
                return self._snapshot("unsupported", "No supported ASUS ROG Astral card found.")
            self.log(f"supported card {self.card.subsystem} at {self.card.pci_address}")

        if self.transport is None:
            try:
                self.adapter = identify.select_adapter(self.card, self.sysfs)
            except identify.NoAdapter as error:
                return self._snapshot("no_adapter", str(error))
            path = os.path.join(self.dev, f"i2c-{self.adapter.number}")
            try:
                self.transport = self.open_transport(path)
            except PermissionError:
                return self._snapshot("permission_denied",
                                      "The collector account cannot open the adapter. Check the install steps.")
            except FileNotFoundError:
                return self._snapshot("no_adapter", "Adapter device node missing. Is i2c-dev loaded?")
            except OSError as error:
                if error.errno == errno.EBUSY:
                    message = "The sensor address is claimed by a kernel driver; not forcing it."
                else:
                    message = f"Opening the adapter failed: {error.strerror or str(error)}"
                return self._snapshot("read_error", message)
            self.reader = i2c.Reader(log=self.log)
            self.log(f"reading i2c-{self.adapter.number} ({self.adapter.name})")

        try:
            raw = self.reader.read(self.transport)
            feeds = snap.decode_block(raw)
        except snap.ReadError as error:
            return self._snapshot("read_error", str(error))
        except OSError as error:
            # A failed transfer may mean the adapter was renumbered; identify again next poll.
            self.log(f"read failed: {error.strerror or str(error)}")
            self._drop_device()
            return self._snapshot("read_error", f"Sensor read failed: {error.strerror or str(error)}")
        return self._snapshot("ok", feeds=feeds)

    def close(self):
        self._drop_device()


def udev_rule(table):
    """The rule granting the collector's group access to each table row's adapter only."""
    lines = ["# Generated by: python3 -m astral_monitor.collector --udev-rule",
             "# Grants the astral-monitor group access to the Astral sensor adapter only."]
    for row in table:
        lines.append(
            'SUBSYSTEM=="i2c-dev", KERNEL=="i2c-[0-9]*", '
            f'ATTR{{name}}=="{row.adapter_name}", '
            f'ATTRS{{vendor}}=="0x{identify.NVIDIA_VENDOR:04x}", '
            f'ATTRS{{subsystem_vendor}}=="0x{identify.ASUS_VENDOR:04x}", '
            f'ATTRS{{subsystem_device}}=="0x{row.subsystem_device:04x}", '
            'GROUP="astral-monitor", MODE="0660"')
    return "\n".join(lines) + "\n"


def identify_report(table, sysfs="/sys"):
    """Human-readable sysfs-only report for the controlled trial."""
    lines = []
    cards = identify.asus_nvidia_cards(sysfs)
    if not cards:
        lines.append("No ASUS-built NVIDIA display device found.")
    supported = {row.subsystem_device for row in table}
    for address, subsystem_device in cards:
        listed = "listed" if subsystem_device in supported else "not in the supported table"
        lines.append(f"Card {address}  subsystem 1043:{subsystem_device:04x}  ({listed})")
        for adapter in identify.card_adapters(address, sysfs):
            exposed = "/dev node available" if identify.has_dev_interface(address, adapter, sysfs) \
                else "no /dev node (i2c-dev not loaded?)"
            lines.append(f"  i2c-{adapter.number}  {adapter.name!r}  {exposed}")
    lines.append("No device was opened.")
    return "\n".join(lines)


def table_from_args(args):
    if args.card is None:
        return identify.SUPPORTED_CARDS
    if not args.adapter_name:
        raise SystemExit("--card needs --adapter-name")
    row = identify.CardType(subsystem_device=identify.parse_subsystem(args.card),
                            model=args.model or "Unvalidated card (trial)",
                            adapter_name=args.adapter_name)
    return (row,)


def run(collector, out, interval_s):
    snap.write_snapshot(out, collector.starting())
    next_tick = time.monotonic()
    while True:
        snap.write_snapshot(out, collector.poll())
        next_tick += interval_s
        time.sleep(max(0.0, next_tick - time.monotonic()))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Astral power-feed collector.")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"snapshot path (default {DEFAULT_OUT})")
    parser.add_argument("--identify", action="store_true", help="report cards and adapters from sysfs only")
    parser.add_argument("--once", action="store_true", help="print one sample as JSON; write no file")
    parser.add_argument("--udev-rule", action="store_true", help="print the udev rule for the table")
    parser.add_argument("--card", metavar="1043:XXXX", help="trial only: treat this subsystem as supported")
    parser.add_argument("--adapter-name", metavar="PATTERN", help="trial only: adapter sysfs name pattern")
    parser.add_argument("--model", help="trial only: model label for --card")
    args = parser.parse_args(argv)
    table = table_from_args(args)

    if args.identify:
        print(identify_report(table))
        return 0
    if args.udev_rule:
        if not table:
            print("The supported-card table is empty; pass --card and --adapter-name.", file=sys.stderr)
            return 1
        sys.stdout.write(udev_rule(table))
        return 0
    if os.geteuid() == 0:
        print("Refusing to run as root. Run as the astral-monitor account or with a narrow ACL; "
              "see docs/live-trial.md.", file=sys.stderr)
        return 1

    collector = Collector(table, log=lambda message: print(message, file=sys.stderr, flush=True))
    if args.once:
        value = collector.poll()
        collector.close()
        print(json.dumps(value, indent=2))
        return 0 if value["status"] == "ok" else 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), mode=0o755, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        run(collector, args.out, INTERVAL_MS / 1000)
    except KeyboardInterrupt:
        pass
    finally:
        collector.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
