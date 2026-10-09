# Design

This records the direction for the MVP in [issue #1](https://github.com/mtrenker/noctalia-astral-monitor/issues/1). The snapshot contract, the Noctalia plugin, the fixture source, and the collector are implemented. The collector has passed one [controlled live trial](live-trial.md), recorded in [hardware](hardware.md). The UI was accepted at the fixture checkpoint, including the stale-reading behaviour below.

Background: [first increment](first-increment.md), [sensor research](research.md).

## Components and boundary

```text
collector (root-free system service, one per machine)    fixture source (developer tool)
  reads one I²C adapter, decodes, validates                 builds the same snapshots from canned bytes
            \                                               /
             snapshot.json  (atomic JSON file, schema v1, world-readable)
                              |
                Noctalia plugin service (one per shell)  -- reads the file once per second
                              |  noctalia.state "astral.view"
             bar widget instances (any number)   panel
```

- Only the collector touches hardware. It is a separate process that runs without Noctalia.
- Only the plugin **service** reads the snapshot file. Widgets and the panel render the view the service publishes. Adding widgets on more bars or outputs therefore adds no file reads and no sensor transactions.
- The fixture source writes the same schema to a different path and labels every snapshot `"source": "fixture"`. It never opens a device node.
- Shared Python code (`collector/astral_monitor/snapshot.py`) owns the schema, the telemetry decoder, and the atomic writer. The fixture source and the collector both use it. `identify.py` reads sysfs only; `i2c.py` is the only module that opens a device; `collector.py` is the poll loop and CLI.

## Collector language

**Chosen:** Python 3 standard library (`fcntl.ioctl` with `I2C_SMBUS`), no third-party packages.

- No new toolchain: Python is already needed for the fixture source and tests. A Rust build of astral-watch's reader would add rustup/cargo to every contributor's and installer's machine.
- The decoder and writer that the collector needs are already tested through the fixture path.
- The parts worth porting from astral-watch are small: the `I2C_SMBUS_I2C_BLOCK_DATA` read, the bytewise reference comparison, and the high-byte recheck. Port them with astral-watch's MIT copyright notice and source commit in the file header.
- Cost: an interpreter runs as a long-lived service. At one sample per second the CPU cost is negligible; the service is small enough to audit in one sitting.

Revisit only if the live trial shows that Python cannot issue the required transfer.

## Supported-card identification and adapter selection (collector)

The collector decides support from PCI identity before any I²C transaction.

1. Scan `/sys/bus/pci/devices/*` for display-class functions with vendor `0x10de` (NVIDIA), subsystem vendor `0x1043` (ASUS), and a subsystem device listed in the **supported-card table**.
2. If no listed card is present, publish `unsupported` and stop probing. Retry identification every 30 s, still without I²C access.
3. Each table row names the card, its subsystem device ID, and an **adapter selector**: the adapter's sysfs `name` attribute pattern under that PCI function (for example `NVIDIA i2c adapter N at …`). Candidate adapters are only the `i2c-*` children of the matched PCI function, so other cards and motherboard buses are never candidates.
4. Exactly one adapter must match the selector. None → `no_adapter`. More than one → `no_adapter` with a message; do not guess.
5. Open only `/dev/i2c-<n>` for that adapter, address only `0x2B`, and issue only the reads listed in [research](research.md#sensor-protocol). The adapter number is looked up on every (re)identification and never configured or cached across boots. `i2c-3` on the development machine is an observation, not a contract.
6. Rediscover after read failures by repeating steps 1–4, so a GPU reset that renumbers adapters is handled.

The table started empty and now lists only `1043:89e3` (see [hardware](hardware.md)). A row is added only after a controlled live trial records the subsystem ID, adapter name, kernel, and driver version, and a validation read matches the bytewise reference. The astral-watch card list is a source of candidates, not of support. A local, explicit `--card SUBSYS --adapter-name NAME` override may exist for that trial; it still requires the PCI match.

No broad scans, no fallback to bus 0, no NVML device-index guessing, no power, clock, fan, or process commands.

## Snapshot schema v1

One JSON object, UTF-8, at most 4 KiB.

```json
{
  "schema_version": 1,
  "source": "hardware",
  "status": "ok",
  "message": "",
  "observed_at_ms": 1760000000123,
  "interval_ms": 1000,
  "collector": { "instance": "5f2c9e1a", "started_at_ms": 1759999990000, "sequence": 42 },
  "device": { "model": "ROG Astral RTX 5090", "pci_subsystem": "1043:89ed" },
  "feeds": [
    { "pin": 1, "voltage_mv": 12080, "current_ma": 8420 }
  ]
}
```

| Field | Rule |
| --- | --- |
| `schema_version` | Integer `1`. Readers reject any other value. Additive optional fields do not bump it; renames or meaning changes do. |
| `source` | `"hardware"` or `"fixture"`. |
| `status` | One of the collector statuses below. |
| `message` | Short human-readable detail; empty for `ok`. Never contains paths under a home directory, serials, or UUIDs. |
| `observed_at_ms` | Unix wall-clock milliseconds when this status was determined. Refreshed on **every** poll, including failures, so a live collector never goes stale. |
| `interval_ms` | The collector's poll interval. Informational. |
| `collector` | `instance` is random per process start; `started_at_ms` is the process start; `sequence` counts writes from 1 and resets on restart. |
| `device` | Present once a supported card is identified. `pci_subsystem` is `vvvv:dddd`. No GPU UUID, serial, or board ID. |
| `feeds` | Present only when `status` is `"ok"`: exactly six objects ordered pin 1 to 6, integer `voltage_mv` and `current_ma` in 0–65535 as measured. The sensor's register order (pin 6 first) is undone by the decoder. |

Values are the sensor's own millivolts and milliamps, so the file never rounds. Watts are always derived by readers and labelled as computed.

### Collector statuses

| Status | Meaning |
| --- | --- |
| `ok` | A sample passed validation; `feeds` holds it. |
| `starting` | The process is up but has no validated sample yet. Written first after every start. |
| `unsupported` | No card from the supported-card table is present. No I²C transaction was made. |
| `no_adapter` | A supported card is present but its adapter or `/dev/i2c-*` node is missing (for example `i2c-dev` not loaded). |
| `permission_denied` | Opening the adapter failed with `EACCES`/`EPERM`. |
| `read_error` | The transfer failed, was short, did not match the bytewise reference, or decoded to implausible values (all-zero, max voltage outside 5–20 V). |

A failed read never publishes zeros or the previous sample. It publishes `read_error` without `feeds`.

### Writing

Write to a temporary file in the same directory, `fsync`, then `rename` over `snapshot.json` (mode `0644`). Readers therefore see the old or the new snapshot, never a partial one.

## Freshness and display states (plugin)

The service evaluates every read into a **view** with one `state`:

| `state` | When | Readings shown |
| --- | --- | --- |
| `live` | `ok`, valid feeds, age ≤ 5 s | Current |
| `stale` | Any status whose `observed_at_ms` is more than 5 s old | If that snapshot was `ok`, the panel shows its readings muted and labelled with their age; the bar shows none |
| `starting`, `unsupported`, `no_adapter`, `permission_denied`, `read_error` | Collector status, age ≤ 5 s | None |
| `no_snapshot` | File missing or unreadable | None |
| `invalid` | Not JSON, wrong `schema_version`, unknown `source`/`status`, `ok` without six valid feeds, all twelve values zero, or `observed_at_ms` more than 2 s in the future | None |

- The 5 s stale limit is fixed: five missed one-second polls. It is not a setting.
- Stale wins over every collector status, because an old `permission_denied` says nothing about now.
- A `live` view has `level = "warning"` when any feed's current is at or above the warning threshold (plugin setting `warn_current_a`, default 9.2 A, the ASUS cable-spec figure). Otherwise `level = "normal"`. There is no "safe" level.
- Missing values stay `nil` in the view and render as `—`, never as `0`. A real 0 mA reading from a valid `ok` sample is shown as `0.00 A`.
- The widget and panel also check the view's own `evaluated_at_ms`. If the service has not published for 3 s, they show `stale` with "Monitor service not updating", so a stuck or crashed service cannot freeze a healthy-looking number.
- Collector restart needs no extra state: it appears as `stale` while the process is down, `starting` after it comes back, then `live`. The panel shows how long ago the collector started.

## Privilege and ownership (collector)

| Item | Decision |
| --- | --- |
| Account | Dedicated system user and group `astral-monitor`, no login shell, no home. |
| Device access | A udev rule matching the supported card's PCI subsystem and the adapter `name` sets `GROUP="astral-monitor", MODE="0660"` on that one `/dev/i2c-*` node. Other adapters keep their defaults. `--udev-rule` generates it from the supported-card table. |
| Read-only | Device access permits writes, so the collector's code enforces read-only use: only `I2C_SLAVE` (never the force variant) for address `0x2B`, and `I2C_SMBUS` read transfers of registers `0x80`–`0x97`. Tests assert no other ioctl request is issued. |
| Service | `packaging/astral-monitor.service`: `User=astral-monitor`, `RuntimeDirectory=astral-monitor` (mode `0755`), `DevicePolicy=closed` with `DeviceAllow=char-i2c rw` (the adapter number is not stable, so the udev rule's file permissions narrow access to one node), no capabilities, `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`, `ProtectSystem=strict`, `ProtectHome=yes`, `NoNewPrivileges=yes`, and a system-call filter. |
| Root | The collector refuses to run as root, so a trial cannot bypass the boundary. The trial grants one user a temporary ACL on one node instead. |
| Snapshot | `/run/astral-monitor/snapshot.json`, owned by `astral-monitor`, mode `0644`. Only the collector can write it; desktop users read it. |
| Shell | Noctalia runs unprivileged and only reads the snapshot. It never gets `/dev/i2c-*` access. |
| Install | Explicit steps in [install](install.md) that the operator runs with `sudo`. Nothing is installed or enabled by the plugin. Uninstall reverses each step. |
| `i2c-dev` | Loading it is an operator step, documented with its persistence option. The collector reports `no_adapter` until it is loaded. |

The fixture source writes to `$XDG_RUNTIME_DIR/astral-monitor-fixture/snapshot.json` as the developer.

## UI composition

Thesis: the monitor should feel **sober, exact, and candid** because it is glanced at while a high-power card is under load and a reassuring wrong answer is worse than none. Numbers come first, one shared scale makes feeds comparable, every state changes both its glyph and its words, and freshness is always written out.

Prohibitions: no "safe", "OK", "healthy", or green check; no zero-length bar or `0` for missing data; no connector drawing or physical pin layout until orientation is validated; no colour-only meaning; never present fixture data without a fixture label.

### Bar widget

One compact row, native label and glyph styling, default widget colour when normal.

| State | Glyph | Text | Colour |
| --- | --- | --- | --- |
| `live`, normal | `bolt` | Highest current, `8.4 A` | Widget default |
| `live`, warning | `alert-triangle` | `9.6 A` | `error` |
| `stale` | `clock-exclamation` | `stale` | `on_surface_variant` |
| `starting` | `loader` | `starting` | `on_surface_variant` |
| `permission_denied` | `lock` | `no access` | `on_surface_variant` |
| other unavailable | `bolt-off` | `no data` | `on_surface_variant` |

- Fixture snapshots add a small `FIXTURE` badge after the text, in `secondary`: an accent that is never used for a status, unlike `tertiary`, which is green in some palettes.
- The tooltip names the state, the highest pin, and the sample age.
- Click toggles the panel.
- On a vertical bar the text is shortened to the number.

### Panel

Attached to the bar, opening near the widget, 460 px wide.

1. Header: title "Astral power feeds", the `FIXTURE` badge when applicable.
2. Status line: glyph, a title such as "Live", "Stale", or "No access to the sensor adapter", and a detail line such as "Highest feed pin 3, updated 1 s ago" or "Last sample 14 s ago. Values below are not current."
3. Six rows, pin 1 to 6, labelled "Pin 1" to "Pin 6" as numbered list items with no implied physical position. Each row has a progress bar on a shared scale (12 A, or the highest reading if above), current `8.42 A`, voltage `12.08 V`, and computed `101.7 W`. A row at or above the threshold shows `alert-triangle` and uses `error`. Without readings, rows show `—` and no bar.
4. Totals: "Connector total" with amps and watts, then "Computed from the six feeds, not total board power. Warning at 9.2 A per feed."
5. Footer: source and device model, collector start age, and the standing note "Monitoring aid only. Does not measure connector temperature or contact quality."

### Copy

Plain sentences, no exclamation marks. Errors say what is missing and, where it helps, what to do ("Start the collector", "Load i2c-dev"). Detailed installation help lives in the README, not the panel.

## Not decided here

- Notification policy, history, and imbalance heuristics: after live readings are validated.
- Physical connector orientation: after the pin mapping and viewing direction are validated on hardware.
- Translations beyond English.
