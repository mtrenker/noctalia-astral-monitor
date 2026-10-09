# Hardware observations

Results of [controlled live trials](live-trial.md). An observation here is evidence, not a support claim; the supported-card table in `collector/astral_monitor/identify.py` is the claim.

## ROG Astral RTX 5090, subsystem 1043:89e3 (2026-10-09)

| Item | Value |
| --- | --- |
| Card | NVIDIA GeForce RTX 5090, ASUS subsystem `1043:89e3` (listed as ROG Astral RTX 5090 by astral-watch) |
| Kernel | 7.2.8-arch1-2 (Arch Linux) |
| NVIDIA driver | 615.71.09 |
| Noctalia | 5.2.1 |
| Adapter | `NVIDIA i2c adapter 1 at <PCI>`, the first of seven NVIDIA adapters on the card; kernel bus `i2c-3` on this boot |
| Access | Address `0x2B`. The block read matched the per-register reference on the first sample, so the collector used one transaction per sample |
| Privileges | Unprivileged user with a temporary ACL on that one device node; no root, no udev rule, no service |

Only this one adapter was opened. No other adapter or address was tried.

### Idle

A single `--once` read with the desktop idle: six pins at 12.16–12.17 V and 0.42–0.46 A, 33 W computed through the connector. `nvidia-smi` reported 24 W board power and 1 % utilisation at the same time.

### Normal workload (ComfyUI)

The operator ran ComfyUI image generation. 60 samples were taken at 1 Hz from the collector's snapshot, together with `nvidia-smi --query-gpu=power.draw,utilization.gpu`, a read-only query.

| Measure | Result |
| --- | --- |
| Samples | 60 of 60 `ok`; no read errors; snapshot age at most 1.0 s |
| Voltage | 12.04–12.17 V on every pin |
| Current per pin | 0.68–6.56 A; highest pin 6 at 6.56 A, below the 9.2 A warning |
| Mean current per pin | 2.55 (pin 1) to 2.80 A (pin 6) |
| Connector, computed | 53–457 W |
| Board power, `nvidia-smi` | 33–534 W |
| Balance above 300 W | Pins within 18 % of their mean; pin 1 lowest and pin 6 highest throughout |

The workload was bursty: generation steps of roughly 2–3 s at 500–535 W board power alternated with near-idle gaps.

### Findings and limitations

- **The sensor's readings lag and smooth.** The computed connector power peaked about 1–2 s after `nvidia-smi`'s board power and decayed over several seconds afterwards, so short bursts never reached their full value. The highest connector reading, 457 W, came while board power was already falling. A short current spike may therefore not appear at its full size, or at all. This makes the 9.2 A warning a trend indicator, not a fast trip.
- **The connector total is not a lower bound on board power.** At idle the computed connector power, 33–75 W, exceeded `nvidia-smi`'s 24–64 W. The two measure different things at different rates. The trial plan's "close to, and not above" check was wrong and has been corrected.
- **Sustained load was not tested.** No steady multi-minute load was run, so steady-state accuracy and readings near 9 A per pin remain unverified.
- **One sample may straddle an update.** One sample at 15:31:38 showed pins 4–6 about 10 % above pins 1–3 while current was rising. That fits values refreshing between register groups, but this trial cannot tell.
- **Pin order is register order.** "Pin 1" to "Pin 6" follow the sensor's register order, reversed as upstream does. No physical connector position was checked.
- **Coverage.** This covers one card, one boot, and one workload. Other 1043 subsystems, including other Astral 5090 and 5080 SKUs, remain untested.
