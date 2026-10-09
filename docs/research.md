# Sensor and integration research

This is a source review, not a hardware validation report.

## Sources reviewed

- [astral-watch, dce7eee](https://github.com/mbeaman/astral-watch/tree/dce7eee77676268c66b3624c7a2870ed9d84eb9c)
- [AstralGauge, 2c330af](https://github.com/MortenSmedsrud/AstralGauge/tree/2c330affa3473a193e8c71a1894465c19c3fc7b2)
- [Noctalia 5.2.1](https://github.com/noctalia-dev/noctalia/tree/6ef43e2bf2f3d5b4205ec72a72e34a2ab76ce3b4)
- [ASUS Power Detector+ guide](https://rog.asus.com/us/articles/guides/how-gpu-tweaks-power-detector-alerts-you-to-abnormal-current-on-your-rog-astral-graphics-card/)

## Sensor protocol

Both monitoring projects access an ITE IT8915FN controller through NVIDIA's Linux I²C adapter rather than NVML's total-board power interface.

| Property | Value reported by upstream |
| --- | --- |
| Seven-bit device address | `0x2B` |
| Telemetry range | `0x80–0x97` |
| Payload | 24 bytes: six groups of four |
| Each group | Big-endian u16 millivolts, then u16 milliamps |
| Ordering | First group is pin 6; last group is pin 1 |

The preferred transfer is `I2C_SMBUS_I2C_BLOCK_DATA`, with a host-specified length and no device-supplied length prefix. This is not interchangeable with ordinary SMBus block reads or arbitrary raw combined transfers.

The fallback reads individual registers. Since a 16-bit value spans two reads, the sensor can update between them. astral-watch rereads the high byte to reduce inconsistent pairs. Its block path first compares the decoded voltages against a bytewise reference. Neither approach proves that the controller freezes the complete telemetry window during a transfer.

Sensor reads select a register pointer but do not send register configuration data. That does not make arbitrary bus access safe or establish an OS-enforced read-only permission boundary.

## Implementation comparison

### astral-watch

Relevant files: `src/i2c.rs`, `src/decode.rs`, `src/main.rs`, `src/alert.rs`, and `src/safety.rs`.

Strengths for reuse:

- Validates the block-read strategy against a bytewise reference per bus/address.
- Reports telemetry failures instead of presenting zeros.
- Supports rediscovery tied to GPU PCI identity.
- Keeps power-changing behavior behind an optional build feature and separate command.
- Has tests for decoding, transfer strategies, alert lifecycle, and power-cap behavior.

Limitations:

- Normal sample plausibility only checks whether the maximum pin voltage is within 5–20 V.
- Automatic discovery tries the known address on NVIDIA-named adapters; a smaller supported-card scope is preferable for this project.
- Bus permissions allow writes even when this program only reads.
- Its alert heuristics and safety claims are not evidence that a connector is safe.

The optional safety mode lowers a power limit via NVML and leaves it reduced until manual restoration or reboot. It is outside this project's first increment.

### AstralGauge

Relevant files: `src/hardware.rs`, `src/main.rs`, `src/alerts.rs`, and `src/web.rs`.

- Uses the same register map and block-read protocol.
- Accepts a successful 24-byte block without astral-watch's reference comparison.
- Falls back to 24 individual byte reads without high-byte rechecking.
- Defaults to bus 0 when autodetection fails.
- Publishes zero pin readings when the device cannot be opened; later read failures skip publication, leaving old values displayed.
- Uses NVML device index 0 rather than correlating it with the selected sensor bus.
- Optional automatic limiting restores the old limit after 30 seconds below the threshold.
- Optional protection can SIGKILL GPU processes.
- Optional web UI binds to all IPv4 interfaces without authentication, including alert acknowledgment.

These behaviors are reasons to reuse the sensor knowledge rather than embed the application.

## Thresholds are not safety certification

ASUS's guide identifies 9.2 A per pin as its cable-spec threshold. astral-watch uses an overload threshold of 9.2 A plus its own imbalance/disconnection heuristics. AstralGauge defaults to yellow at 9.2 A and red at 10 A.

The sensor does not measure connector temperature or contact resistance. A low reading on one feed can reflect poor contact while other feeds carry more load. No current threshold guarantees protection against damage.

## Noctalia integration

Noctalia 5 supports `plugin.toml` manifests with Luau widget, panel, and service entries. It provides native declarative UI, theme roles, shared plugin state, JSON decoding, and file reads. The asynchronous file-read API requires plugin API 23; other used capabilities must be checked against the declared minimum.

References in the Noctalia source:

- `docs/user/plugins/development/manifest.mdx`
- `docs/user/plugins/development/entries.mdx`
- `docs/user/plugins/development/declarative-ui.mdx`
- `docs/user/plugins/development/runtime-api.mdx`
- `docs/user/plugins/development/workflow.mdx`

A separate collector can publish a local snapshot for a plugin service to distribute to bar and panel entries. This avoids root privileges in the shell, per-widget hardware polling, and unnecessary network listeners.

## Validation status

No collector from either upstream was built or executed during this review, and no sensor transaction was performed. The available development machine exposed the expected NVIDIA adapter in sysfs but did not have the i2c-dev userspace interface loaded.

Adapter availability is not proof that the sensor answers correctly. Report live support only after a controlled trial.
