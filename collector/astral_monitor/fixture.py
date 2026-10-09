"""Hardware-free fixture source: writes labelled schema-v1 snapshots from canned telemetry.

Run in the foreground and stop with Ctrl-C:

    python3 -m astral_monitor.fixture --scenario cycle

It never opens a device node. Every snapshot carries "source": "fixture".
"""

import argparse
import math
import os
import secrets
import signal
import sys
import time

from . import snapshot as snap

DEVICE = {"model": "Fixture card (no hardware)"}

# Amps per pin at a steady ~600 W load, pin 1..6.
BASE_AMPS = (8.10, 8.30, 8.55, 8.20, 8.40, 8.05)
WARNING_PIN = 3
WARNING_AMPS = 9.65

STEADY = ("normal", "warning", "starting", "unsupported", "no_adapter",
          "permission_denied", "read_error", "invalid")
# (scenario, seconds). "stale" writes nothing; "restart" begins a new collector instance.
CYCLE = (("normal", 10), ("warning", 10), ("permission_denied", 8), ("read_error", 8),
         ("stale", 10), ("restart", 0), ("starting", 3))

MESSAGES = {
    "starting": "Waiting for the first validated sample.",
    "unsupported": "No supported ASUS ROG Astral card found.",
    "no_adapter": "Sensor adapter not found. Is i2c-dev loaded?",
    "permission_denied": "The collector account cannot open the adapter. Check the install steps.",
}


def now_ms():
    return int(time.time() * 1000)


class Collector:
    """The fixture's stand-in for one collector process lifetime."""

    def __init__(self, started_at_ms):
        self.instance = secrets.token_hex(4)
        self.started_at_ms = started_at_ms
        self.sequence = 0

    def next(self):
        self.sequence += 1
        return {"instance": self.instance, "started_at_ms": self.started_at_ms,
                "sequence": self.sequence}


def telemetry_block(scenario, t):
    """Raw register bytes for a moment t (seconds) of a scenario, as the sensor would return them."""
    feeds = []
    for index, amps in enumerate(BASE_AMPS):
        pin = index + 1
        if scenario == "warning" and pin == WARNING_PIN:
            amps = WARNING_AMPS
        amps += 0.12 * math.sin(t * 0.9 + pin)
        volts = 12.05 - 0.04 * math.sin(t * 0.5 + pin * 0.7)
        feeds.append({"pin": pin, "voltage_mv": round(volts * 1000), "current_ma": round(amps * 1000)})
    raw = snap.encode_block(feeds)
    if scenario == "read_error":
        return raw[:17]
    return raw


def snapshot_for(scenario, collector, observed_at_ms, t=0.0):
    """Return a snapshot dict for a steady scenario, or a str for the deliberately corrupt one."""
    if scenario == "invalid":
        return '{"schema_version": 1, "source": "fixture", "status": "ok", "feeds": ['
    common = {"source": "fixture", "observed_at_ms": observed_at_ms, "collector": collector.next()}
    if scenario in ("normal", "warning", "read_error"):
        try:
            feeds = snap.decode_block(telemetry_block(scenario, t))
        except snap.ReadError as error:
            return snap.build_snapshot(status="read_error", message=str(error), device=DEVICE, **common)
        return snap.build_snapshot(status="ok", device=DEVICE, feeds=feeds, **common)
    device = None if scenario == "unsupported" else DEVICE
    return snap.build_snapshot(status=scenario, message=MESSAGES[scenario], device=device, **common)


def publish(path, value):
    if isinstance(value, str):
        snap.write_atomic(path, value)
    else:
        snap.write_snapshot(path, value)


def default_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return None
    return os.path.join(runtime, "astral-monitor-fixture", "snapshot.json")


def describe(value):
    if isinstance(value, str):
        return "invalid (truncated JSON)"
    line = f"{value['status']:<17} seq={value['collector']['sequence']}"
    if "feeds" in value:
        top = max(value["feeds"], key=lambda f: f["current_ma"])
        line += f"  highest pin {top['pin']} {top['current_ma'] / 1000:.2f} A"
    elif value["message"]:
        line += f"  {value['message']}"
    return line


def run(path, scenario, interval_s):
    start = time.monotonic()
    collector = Collector(now_ms())
    plan = CYCLE if scenario == "cycle" else ((scenario, None),)
    step, step_started = 0, start
    # Every process start, like the real collector, reports "starting" first.
    initial = "starting" if scenario != "starting" else None
    initial_until = start + 2 * interval_s

    while True:
        moment = time.monotonic()
        name, seconds = plan[step]
        if seconds is not None and moment - step_started >= seconds:
            step = (step + 1) % len(plan)
            step_started = moment
            name, seconds = plan[step]
            if name == "restart":
                collector = Collector(now_ms())
                print(f"{time.strftime('%H:%M:%S')}  collector restarted (instance {collector.instance})")
                step = (step + 1) % len(plan)
                name, seconds = plan[step]
        if initial is not None and moment < initial_until:
            name = initial
        if name == "stale":
            remaining = seconds - (moment - step_started) if seconds else None
            hint = f", resuming in {remaining:.0f} s" if remaining is not None else ""
            print(f"{time.strftime('%H:%M:%S')}  stale             (not writing{hint})")
        else:
            value = snapshot_for(name, collector, now_ms(), moment - start)
            publish(path, value)
            print(f"{time.strftime('%H:%M:%S')}  {describe(value)}")
        sys.stdout.flush()
        time.sleep(interval_s)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write hardware-free fixture snapshots (schema v1). Never opens a device.")
    parser.add_argument("--out", default=default_path(),
                        help="snapshot path (default: $XDG_RUNTIME_DIR/astral-monitor-fixture/snapshot.json)")
    parser.add_argument("--scenario", default="cycle", choices=("cycle", "stale") + STEADY,
                        help="cycle rotates through states; stale writes normal briefly, then stops")
    parser.add_argument("--interval-ms", type=int, default=1000)
    args = parser.parse_args(argv)
    if not args.out:
        parser.error("XDG_RUNTIME_DIR is not set; pass --out")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), mode=0o755, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("FIXTURE SOURCE - canned data, no hardware is accessed.")
    print(f"Writing {args.out} every {args.interval_ms} ms, scenario {args.scenario}. Ctrl-C stops.")
    scenario = args.scenario
    try:
        if scenario == "stale":
            collector = Collector(now_ms())
            for _ in range(3):
                value = snapshot_for("normal", collector, now_ms())
                publish(args.out, value)
                print(f"{time.strftime('%H:%M:%S')}  {describe(value)}")
                time.sleep(args.interval_ms / 1000)
            print("Stopped writing. The snapshot is now aging; Ctrl-C to exit.")
            while True:
                time.sleep(3600)
        run(args.out, scenario, args.interval_ms / 1000)
    except KeyboardInterrupt:
        print("\nStopped. The last snapshot stays in place and will show as stale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
