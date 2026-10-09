# First increment

## Outcome

A Noctalia user can see the highest measured power-pin current in the bar and inspect all six feeds in a popup. Missing or outdated data is visibly unavailable, never reassuring.

This is the proposed implementation direction, not a completed feature or a frozen public API. Review a running UI slice before building out history or notification behavior.

## Boundaries

Keep the hardware collector separate from the Noctalia plugin. One collector should serve every widget instance without multiplying sensor reads.

The collector should:

- Identify the supported GPU and resolve its adapter from PCI identity at startup, not hardcode a bus number.
- Address only the verified telemetry device and registers. Never fall back to motherboard bus 0 or scan arbitrary I²C addresses.
- Read at roughly one-second intervals, with bounded retries and validation.
- Publish a small local JSON snapshot atomically, with a schema version, GPU identity, sample timestamp, explicit status, and per-feed readings with named units.
- Distinguish no device, unsupported hardware, permission failure, read failure, and invalid data.
- Run under a dedicated account with access scoped to the required adapter, not give the desktop shell raw bus access.

Choose and document the exact schema, file ownership, runtime path, and restart behavior before implementation. The snapshot must not be writable by untrusted users. Device access permits more than reads; read-only behavior must also be enforced by the collector's code.

The plugin should:

- Use Noctalia 5's Luau APIs, native controls, and palette roles.
- Show the highest measured current in a compact bar item.
- Open a panel with six comparable current bars and exact voltage/current values.
- Label computed connector watts separately from total GPU board power.
- Mark stale readings even if the collector dies without writing an error.
- Use text or icons as well as color for warnings.
- Avoid claims such as "connector safe".
- Keep missing-data states visible rather than hiding the widget.

Never draw a physical connector orientation until the pin mapping and viewing direction have been validated. A numbered list is sufficient for the first slice.

## Reuse and testing

Keep transport, decoding, and UI separate without building a general sensor framework. Prefer reusing reviewed astral-watch logic with its license notices over duplicating low-level access.

Provide timestamped fixtures so contributors can run and review the UI without a supported GPU or elevated privileges. Fixture mode must be visibly labeled and must never open I²C devices.

Required checks:

- Known bytes decode to the expected units and pin ordering.
- Short, invalid, and failed reads cannot become valid zero readings.
- Collector loss, restart, and stale snapshots are visible in the UI.
- Multiple widget instances do not create multiple hardware pollers.
- Unsupported hardware causes no sensor access.
- Monitoring issues no power-limit, clock, fan, or process-control commands.
- Noctalia's plugin lint passes for the declared API level.
- A real GPU trial records the card variant, driver, kernel, and observed limitations before claiming support.

Document build, test, fixture preview, install, and uninstall commands when they exist. Check hardware paths separately from fixture tests.

## Not in this increment

Automatic throttling, process termination, remote servers, historical dashboards, support for unrelated GPUs, or claims of melt prevention. Notification policy follows after live readings and failure states are validated.
