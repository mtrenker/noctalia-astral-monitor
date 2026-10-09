"""Supported-card identification and adapter selection from sysfs (docs/design.md).

Reads sysfs attributes only. Nothing here opens a device node, so an unsupported
machine sees no I2C transaction at all.
"""

import fnmatch
import os
from dataclasses import dataclass

NVIDIA_VENDOR = 0x10DE
ASUS_VENDOR = 0x1043
DISPLAY_CLASS_PREFIX = 0x03


@dataclass(frozen=True)
class CardType:
    """One row of the supported-card table."""

    subsystem_device: int
    model: str
    adapter_name: str  # fnmatch pattern for the adapter's sysfs `name`


# Rows are added only after a controlled live trial records the subsystem ID, adapter
# name, kernel, and driver, and a validation read matches the per-register reference.
# See docs/live-trial.md. astral-watch's card list is a source of candidates, not support.
SUPPORTED_CARDS = (
    # Trial 2026-10-09, docs/hardware.md: kernel 7.2.8, driver 615.71.09, block read validated.
    CardType(subsystem_device=0x89E3, model="ROG Astral RTX 5090",
             adapter_name="NVIDIA i2c adapter 1 at *"),
)


@dataclass(frozen=True)
class Card:
    pci_address: str
    subsystem: str  # "vvvv:dddd"
    model: str
    adapter_name: str


@dataclass(frozen=True)
class Adapter:
    number: int
    name: str


class NoAdapter(Exception):
    """A supported card is present but its adapter cannot be used yet."""


def _read(path):
    try:
        with open(path, encoding="ascii") as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _hex(path):
    text = _read(path)
    try:
        return int(text, 16) if text else None
    except ValueError:
        return None


def _pci_root(sysfs):
    return os.path.join(sysfs, "bus", "pci", "devices")


def asus_nvidia_cards(sysfs="/sys"):
    """(pci_address, subsystem_device) for every ASUS-built NVIDIA display function."""
    root = _pci_root(sysfs)
    try:
        addresses = sorted(os.listdir(root))
    except OSError:
        return []
    found = []
    for address in addresses:
        base = os.path.join(root, address)
        klass = _hex(os.path.join(base, "class"))
        if klass is None or klass >> 16 != DISPLAY_CLASS_PREFIX:
            continue
        if _hex(os.path.join(base, "vendor")) != NVIDIA_VENDOR:
            continue
        if _hex(os.path.join(base, "subsystem_vendor")) != ASUS_VENDOR:
            continue
        subsystem_device = _hex(os.path.join(base, "subsystem_device"))
        if subsystem_device is not None:
            found.append((address, subsystem_device))
    return found


def find_card(table, sysfs="/sys"):
    """The first present card listed in table, or None (unsupported)."""
    by_subsystem = {row.subsystem_device: row for row in table}
    for address, subsystem_device in asus_nvidia_cards(sysfs):
        row = by_subsystem.get(subsystem_device)
        if row is not None:
            return Card(pci_address=address, subsystem=f"{ASUS_VENDOR:04x}:{subsystem_device:04x}",
                        model=row.model, adapter_name=row.adapter_name)
    return None


def card_adapters(pci_address, sysfs="/sys"):
    """I2C adapters that are children of this PCI function, with their sysfs names."""
    base = os.path.join(_pci_root(sysfs), pci_address)
    adapters = []
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return adapters
    for entry in entries:
        if entry.startswith("i2c-") and entry[4:].isdigit():
            name = _read(os.path.join(base, entry, "name")) or ""
            adapters.append(Adapter(number=int(entry[4:]), name=name))
    return adapters


def has_dev_interface(pci_address, adapter, sysfs="/sys"):
    """True when i2c-dev exposes this adapter (otherwise /dev/i2c-N cannot exist)."""
    base = os.path.join(_pci_root(sysfs), pci_address, f"i2c-{adapter.number}", "i2c-dev")
    return os.path.isdir(os.path.join(base, f"i2c-{adapter.number}"))


def select_adapter(card, sysfs="/sys"):
    """The single adapter of this card whose name matches the table row, or NoAdapter."""
    matches = [a for a in card_adapters(card.pci_address, sysfs)
               if fnmatch.fnmatchcase(a.name, card.adapter_name)]
    if not matches:
        raise NoAdapter(f"No adapter named like '{card.adapter_name}' on this card.")
    if len(matches) > 1:
        names = ", ".join(f"i2c-{a.number}" for a in matches)
        raise NoAdapter(f"Several adapters match '{card.adapter_name}' ({names}); not guessing.")
    adapter = matches[0]
    if not has_dev_interface(card.pci_address, adapter, sysfs):
        raise NoAdapter("Sensor adapter found but not exposed to userspace. Is i2c-dev loaded?")
    return adapter


def parse_subsystem(text):
    """'1043:89ed' -> 0x89ed, insisting on the ASUS subsystem vendor."""
    vendor, _, device = text.partition(":")
    if int(vendor, 16) != ASUS_VENDOR or not device:
        raise ValueError("subsystem must be 1043:xxxx (ASUS)")
    return int(device, 16)
