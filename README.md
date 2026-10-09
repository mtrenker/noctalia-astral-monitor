# Noctalia Astral Monitor

A planned Noctalia plugin for monitoring individual power-pin currents on ASUS ROG Astral GPUs on Linux.

**Status: fixture preview. The Noctalia plugin runs against a hardware-free fixture source. There is no hardware collector yet, and no hardware readings have been validated by this project.**

## Intended first release

- A compact bar widget showing the highest measured pin current.
- A click-open panel with current and voltage for each of the six positive power feeds.
- Explicit unavailable, stale, and warning states.
- Noctalia-native styling that follows the user's theme.
- A separate read-only collector, reusable without Noctalia.

The first release will not change GPU power limits, kill processes, or expose a network service. Alerts are monitoring aids, not a guarantee against connector damage.

## Compatibility

The initial target is an ASUS ROG Astral RTX 5090 with the ITE IT8915FN sensor controller and NVIDIA I²C adapters exposed by the Linux driver. Related cards, including Astral RTX 5080 variants, need separate validation; a GPU name alone is not sufficient to establish compatibility.

The UI targets **Noctalia 5's Luau plugin API**. It is not a QML plugin for older Noctalia versions. The plugin declares plugin API 23, so it needs Noctalia 5.0.0-beta.8 or later; it is developed and previewed on 5.2.1. Hyprland is the initial desktop environment, but the plugin should avoid compositor-specific dependencies.

This is not a generic RTX 5090 monitoring solution. Unsupported cards must be rejected without probing unrelated devices.

## Safety limits

The sensor measures six positive power feeds, not connector temperature, contact resistance, or all ground contacts. Below-threshold readings do not establish that a connector is safe.

A missing sensor or failed read must never appear as zero current or a healthy state. Stop using equipment showing signs of physical damage; monitoring is not a substitute for inspection or manufacturer support.

Do not use broad I²C address scans to discover this sensor. Reading known telemetry registers still requires care on a shared hardware bus.

## Development

- [Design](docs/design.md): components, snapshot schema, freshness and display states, privileges, and UI composition.
- [First increment](docs/first-increment.md): scope, boundaries, and checks.
- [Research](docs/research.md): sensor protocol, upstream implementations, and known concerns.
- [Contributing](CONTRIBUTING.md): hardware reports and contribution expectations.

Layout: `noctalia/astral_monitor/` is the plugin, `collector/astral_monitor/` holds the snapshot schema, decoder, and fixture source, and `tests/` holds the checks.

### Requirements

- Python 3.9 or later, standard library only.
- LuaJIT or Lua 5.1 to 5.4 for the plugin's unit tests. Without one, those tests are skipped and say so.
- Noctalia for `noctalia plugins lint` and the preview.
- For the preview only: Hyprland with Lua configuration (tested with 0.56), `dbus-run-session`, and optionally `grim` for screenshots.

No supported GPU, elevated privileges, or I²C access is needed for any of this.

### Commands

| Task | Command |
| --- | --- |
| Tests and plugin lint | `make check` |
| Fixture source, rotating through states | `make fixture` |
| Fixture source, one state | `make fixture SCENARIO=permission_denied` |
| Native preview | `make preview` |
| Toggle the panel in the preview | `make preview-panel` |
| Screenshot of the preview | `scripts/preview.sh shot /tmp/astral-preview.png` |
| Teardown | Ctrl-C the preview and the fixture source, then `make preview-clean` |

Run the fixture source and the preview in two terminals; both stay in the foreground.

Scenarios: `cycle` (normal, warning, permission denied, read error, stale, collector restart), `normal`, `warning`, `starting`, `unsupported`, `no_adapter`, `permission_denied`, `read_error`, `invalid` (a truncated file), and `stale` (writes briefly, then stops). Stopping the fixture source with Ctrl-C also leaves a stale snapshot behind, which is how a crashed collector looks.

The fixture source writes `$XDG_RUNTIME_DIR/astral-monitor-fixture/snapshot.json`. Every snapshot it writes is labelled `"source": "fixture"`, and the bar and panel show a FIXTURE badge for it.

### How the preview is isolated

`make preview` opens a nested Hyprland window with its own Wayland display and a private D-Bus session, then starts a second Noctalia inside it with config, state, and data directories under `$XDG_RUNTIME_DIR/astral-monitor-preview`. It uses the Tokyo-Night theme, offline mode, and two instances of the bar widget to show that they share one reader. Your running shell, its settings, and its plugins are not touched, and nothing is installed. `make preview-panel` refuses to run unless the preview's own display is live, so it cannot reach your shell. The plugin's log is `$XDG_RUNTIME_DIR/astral-monitor-preview/noctalia.log`.

Installation into your own Noctalia, and the hardware collector with its install and uninstall steps, arrive with the live increment.

## Credits and license

Sensor research builds on [astral-watch](https://github.com/mbeaman/astral-watch), [AstralGauge](https://github.com/MortenSmedsrud/AstralGauge), and their cited reverse-engineering work. No upstream implementation code is included yet. The decoder test uses a published telemetry capture from astral-watch's tests, credited in `tests/test_snapshot.py`.

MIT licensed. Any future reuse of upstream code must retain its copyright and license notices.

Not affiliated with or endorsed by ASUS, NVIDIA, or Noctalia.
