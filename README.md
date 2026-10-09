# Noctalia Astral Monitor

A planned Noctalia plugin for monitoring individual power-pin currents on ASUS ROG Astral GPUs on Linux.

**Status: research and project setup. No runnable collector or widget yet. Hardware readings have not been validated by this project.**

## Intended first release

- A compact bar widget showing the highest measured pin current.
- A click-open panel with current and voltage for each of the six positive power feeds.
- Explicit unavailable, stale, and warning states.
- Noctalia-native styling that follows the user's theme.
- A separate read-only collector, reusable without Noctalia.

The first release will not change GPU power limits, kill processes, or expose a network service. Alerts are monitoring aids, not a guarantee against connector damage.

## Compatibility

The initial target is an ASUS ROG Astral RTX 5090 with the ITE IT8915FN sensor controller and NVIDIA I²C adapters exposed by the Linux driver. Related cards, including Astral RTX 5080 variants, need separate validation; a GPU name alone is not sufficient to establish compatibility.

The UI targets **Noctalia 5's Luau plugin API**. It is not a QML plugin for older Noctalia versions. Research used Noctalia 5.2.1. Hyprland is the initial desktop environment, but the plugin should avoid compositor-specific dependencies.

This is not a generic RTX 5090 monitoring solution. Unsupported cards must be rejected without probing unrelated devices.

## Safety limits

The sensor measures six positive power feeds, not connector temperature, contact resistance, or all ground contacts. Below-threshold readings do not establish that a connector is safe.

A missing sensor or failed read must never appear as zero current or a healthy state. Stop using equipment showing signs of physical damage; monitoring is not a substitute for inspection or manufacturer support.

Do not use broad I²C address scans to discover this sensor. Reading known telemetry registers still requires care on a shared hardware bus.

## Development

- [First increment](docs/first-increment.md): scope, boundaries, and checks.
- [Research](docs/research.md): sensor protocol, upstream implementations, and known concerns.
- [Contributing](CONTRIBUTING.md): hardware reports and contribution expectations.

There are no installation or preview commands yet. Those will accompany the first working increment, including a hardware-free fixture mode.

## Credits and license

Sensor research builds on [astral-watch](https://github.com/mbeaman/astral-watch), [AstralGauge](https://github.com/MortenSmedsrud/AstralGauge), and their cited reverse-engineering work. No upstream implementation code is included in this initial repository.

MIT licensed. Any future reuse of upstream code must retain its copyright and license notices.

Not affiliated with or endorsed by ASUS, NVIDIA, or Noctalia.
