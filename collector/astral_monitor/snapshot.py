"""Snapshot schema v1, telemetry decoding, and atomic publication.

Shared by the hardware-free fixture source and the future collector. Nothing here
opens a device; see docs/design.md for the contract.
"""

import json
import os
import tempfile

SCHEMA_VERSION = 1
SOURCES = ("hardware", "fixture")
STATUSES = ("ok", "starting", "unsupported", "no_adapter", "permission_denied", "read_error")

PIN_COUNT = 6
BLOCK_LEN = PIN_COUNT * 4
PLAUSIBLE_MAX_MV = (5000, 20000)


class ReadError(Exception):
    """A telemetry block that must be published as read_error, never as readings."""


def decode_block(raw):
    """Decode the 24-byte IT8915FN telemetry block into feeds ordered pin 1..6.

    The sensor stores six big-endian (u16 mV, u16 mA) groups with pin 6 first.
    Short, all-zero, and implausible blocks raise ReadError.
    """
    raw = bytes(raw)
    if len(raw) != BLOCK_LEN:
        raise ReadError(f"short read: {len(raw)} of {BLOCK_LEN} bytes")
    if not any(raw):
        raise ReadError("all-zero telemetry block")
    groups = []
    for offset in range(0, BLOCK_LEN, 4):
        voltage_mv = int.from_bytes(raw[offset : offset + 2], "big")
        current_ma = int.from_bytes(raw[offset + 2 : offset + 4], "big")
        groups.append((voltage_mv, current_ma))
    groups.reverse()
    max_mv = max(mv for mv, _ in groups)
    if not PLAUSIBLE_MAX_MV[0] <= max_mv <= PLAUSIBLE_MAX_MV[1]:
        raise ReadError(f"implausible voltage: max {max_mv} mV")
    return [
        {"pin": pin, "voltage_mv": mv, "current_ma": ma}
        for pin, (mv, ma) in enumerate(groups, start=1)
    ]


def encode_block(feeds):
    """Inverse of decode_block, for fixtures and tests: feeds pin 1..6 -> raw bytes."""
    raw = bytearray()
    for feed in reversed(feeds):
        raw += feed["voltage_mv"].to_bytes(2, "big") + feed["current_ma"].to_bytes(2, "big")
    return bytes(raw)


def build_snapshot(*, source, status, observed_at_ms, collector, interval_ms=1000,
                   message="", device=None, feeds=None):
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if (status == "ok") != (feeds is not None):
        raise ValueError("feeds must be present exactly when status is ok")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "status": status,
        "message": message,
        "observed_at_ms": int(observed_at_ms),
        "interval_ms": int(interval_ms),
        "collector": dict(collector),
    }
    if device is not None:
        snapshot["device"] = dict(device)
    if feeds is not None:
        if [f["pin"] for f in feeds] != list(range(1, PIN_COUNT + 1)):
            raise ValueError("feeds must be pins 1..6 in order")
        snapshot["feeds"] = [dict(f) for f in feeds]
    return snapshot


def write_atomic(path, content):
    """Replace path with content so readers see the old or new file, never a partial one."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_snapshot(path, snapshot):
    write_atomic(path, json.dumps(snapshot, separators=(",", ":")) + "\n")
