# Contributing

This project currently contains a Noctalia plugin that runs against a hardware-free fixture source, plus research and design notes. There is no hardware collector yet. Run `make check` before proposing a change; the [README](README.md#commands) lists the preview commands.

Keep contributions focused on the [first increment](docs/first-increment.md). Discuss hardware access, privilege changes, and public data-format changes before implementing them. UI work should include a hardware-free preview and explicit unavailable/stale states.

## Hardware reports

Include:

- Exact card model and PCI subsystem IDs.
- Linux distribution, kernel, NVIDIA driver, and Noctalia versions.
- Whether the expected NVIDIA I²C adapter is exposed.
- Whether observations came from fixtures or live hardware.
- Read errors and limitations, not just successful samples.

Do not publish GPU UUIDs, serial numbers, private paths, unrelated logs, or credentials. Never run broad I²C scans to gather a report.

## Code reuse

Retain upstream copyright and license notices for copied or adapted code. Link the source and commit. MIT licensing permits reuse; it does not remove attribution obligations.

Contributions must not silently enable power changes, terminate workloads, install system services, or alter device permissions. Installation and removal must be explicit and documented.

Do not claim hardware support or successful tests that have not been demonstrated.
