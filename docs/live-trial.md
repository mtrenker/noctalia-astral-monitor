# Controlled live trial

**Status: run once, on subsystem 1043:89e3 (see [hardware](hardware.md)).** No card is supported until a reviewed change adds it to the table. The shipped supported-card table (`SUPPORTED_CARDS` in `collector/astral_monitor/identify.py`) is empty.

The trial answers three questions on one real card:

1. Which of the card's I²C adapters carries the sensor, by its sysfs name.
2. Whether the sensor answers with plausible readings at idle and under normal load.
3. Whether the fast single-transfer block read matches the per-register reference on this card.

Every step below says what it touches and how to undo it. Steps 2 to 4 need the operator's explicit approval, and the operator runs the `sudo` commands. Run from the repository root.

## 0. Identify the card from sysfs (no device access)

```sh
PYTHONPATH=collector python3 -m astral_monitor.collector --identify
```

This reads PCI and I²C adapter attributes under `/sys` and opens no device. It needs no privileges. It prints:

- each ASUS-built NVIDIA card with its subsystem ID;
- that card's adapters with their names;
- whether `/dev` nodes exist for them.

Record the subsystem ID and the adapter names. Do not continue if the card is not an Astral model.

## 1. Choose one adapter

Pick a single candidate adapter by name: the one named `NVIDIA i2c adapter 1 at <PCI>`. AstralGauge selects its candidates by that name (`src/hardware.rs`, `find_i2c_bus`), and on the development machine that adapter is kernel bus `i2c-3`, where research expected the sensor. The kernel number varies between machines and boots; the name is what to match. Treat the name as a starting point, not a fact. Probing is one adapter at a time, by decision. Nothing scans.

## 2. Load the I²C device interface for this boot (host change)

Skip this step if step 0 already showed `/dev node available`.

```sh
sudo modprobe i2c-dev
ls -l /dev/i2c-*
```

This creates `/dev/i2c-*` nodes for every adapter on the machine, normally readable only by root. Undo: `sudo modprobe -r i2c-dev`, or reboot.

## 3. Give your user temporary access to that one adapter (permission change)

```sh
sudo setfacl -m u:"$USER":rw /dev/i2c-N
```

Replace `N` with the adapter number from step 1. This grants your account, and no other, access to that single node. It does not survive a reboot or an i2c-dev reload. The collector refuses to run as root, so the trial runs with exactly this access. Undo: `sudo setfacl -x u:"$USER" /dev/i2c-N`.

## 4. Read the sensor (first sensor transactions)

At idle:

```sh
PYTHONPATH=collector python3 -m astral_monitor.collector --once \
  --card 1043:XXXX --adapter-name 'EXACT ADAPTER NAME' --model 'ROG Astral …'
```

What happens on the bus:

1. The collector selects address `0x2B` on that one adapter.
2. It reads the 24 telemetry registers one at a time, about 36 small read transactions including the tear re-checks.
3. It does one 24-byte block read and compares it with the per-register reference.
4. It prints one snapshot as JSON and exits.

Nothing is written to the sensor beyond the register number each read requires. Exit code 0 means `ok`.

Expected at idle: six pins near 12 V, small currents, `status: "ok"`, and a stderr line saying which access method was chosen. If the result is `read_error` or implausible, **stop**. Do not try other adapters without a new decision.

Under normal load (a game or benchmark the card usually runs), run the collector for a minute to a scratch file and watch it in the fixture preview UI:

```sh
PYTHONPATH=collector python3 -m astral_monitor.collector \
  --card 1043:XXXX --adapter-name 'EXACT ADAPTER NAME' --model 'ROG Astral …' \
  --out "$XDG_RUNTIME_DIR/astral-trial/snapshot.json"
ASTRAL_FIXTURE_PATH="$XDG_RUNTIME_DIR/astral-trial/snapshot.json" make preview
```

The preview shows these readings without the FIXTURE badge because they come from hardware. Optional cross-check: compare the computed connector total with the board power from `nvidia-smi --query-gpu=power.draw --format=csv`, a read-only query. Expect the two to follow each other but not match. The first trial found that the sensor lags and smooths, and reads above board power at idle; see [hardware](hardware.md).

## 5. Record the result

Add a section to `docs/hardware.md` with:

- the card variant and PCI subsystem ID;
- the adapter name;
- the kernel, NVIDIA driver, and Noctalia versions;
- the access method chosen;
- idle and load ranges per pin;
- anything odd.

Never record GPU UUIDs, serial numbers, or private paths. If the trial passed, a reviewed change adds the row to `SUPPORTED_CARDS` and updates the README's compatibility section.

## 6. Undo temporary access

```sh
sudo setfacl -x u:"$USER" /dev/i2c-N
sudo modprobe -r i2c-dev   # only if step 2 loaded it and nothing else needs it
```

Installing the service is a separate decision: see [install](install.md).
