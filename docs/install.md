# Install and uninstall

**Only for a card listed in the supported-card table.** It lists only ROG Astral RTX 5090 subsystem `1043:89e3`; other cards need a [controlled live trial](live-trial.md) first. On any other machine the collector reports `unsupported` and never touches I²C.

Nothing here runs automatically: the plugin does not install the collector, change device permissions, or enable services. Every step is a command you run and can reverse. Run from the root of a checkout you will keep, not a temporary worktree.

## What gets installed

| Item | Path |
| --- | --- |
| Collector code and upstream license notice | `/usr/local/lib/astral-monitor/` |
| System account `astral-monitor` | `/etc/sysusers.d/astral-monitor.conf` |
| Access to the one sensor adapter | `/etc/udev/rules.d/70-astral-monitor.rules` |
| Load i2c-dev at boot (optional) | `/etc/modules-load.d/astral-monitor-i2c-dev.conf` |
| Service | `/etc/systemd/system/astral-monitor.service` |
| Snapshot (created by the service) | `/run/astral-monitor/snapshot.json` |

## Install

1. Copy the collector:

   ```sh
   sudo install -d -m 0755 /usr/local/lib/astral-monitor/astral_monitor /usr/local/lib/astral-monitor/LICENSES
   sudo install -m 0644 collector/astral_monitor/*.py /usr/local/lib/astral-monitor/astral_monitor/
   sudo install -m 0644 LICENSES/* /usr/local/lib/astral-monitor/LICENSES/
   ```

2. Create the account:

   ```sh
   sudo install -m 0644 packaging/astral-monitor.sysusers /etc/sysusers.d/astral-monitor.conf
   sudo systemd-sysusers /etc/sysusers.d/astral-monitor.conf
   ```

3. Load i2c-dev now, and optionally at every boot:

   ```sh
   sudo modprobe i2c-dev
   sudo install -m 0644 packaging/i2c-dev.conf /etc/modules-load.d/astral-monitor-i2c-dev.conf
   ```

4. Grant the account access to the sensor adapter only. Generate the rule from the supported-card table, read it, then install it:

   ```sh
   PYTHONPATH=collector python3 -m astral_monitor.collector --udev-rule > /tmp/70-astral-monitor.rules
   cat /tmp/70-astral-monitor.rules
   sudo install -m 0644 /tmp/70-astral-monitor.rules /etc/udev/rules.d/70-astral-monitor.rules
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=i2c-dev --action=change
   ls -l /dev/i2c-*
   ```

   Exactly one node should show group `astral-monitor`. If none or several do, stop and uninstall.

5. Start the service:

   ```sh
   sudo install -m 0644 packaging/astral-monitor.service /etc/systemd/system/astral-monitor.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now astral-monitor.service
   systemctl status astral-monitor.service
   cat /run/astral-monitor/snapshot.json
   ```

   The service has no network access, no capabilities, and a read-only view of the system apart from its runtime directory. `systemd-analyze security astral-monitor.service` summarises the sandbox.

6. Add the plugin to Noctalia. This changes your Noctalia settings:

   ```sh
   noctalia msg plugins source add astral-monitor path "$PWD/noctalia"
   noctalia msg plugins enable mtrenker/astral_monitor
   ```

   Then add the "Astral Monitor" widget to a bar in Settings. Its default snapshot path is `/run/astral-monitor/snapshot.json`.

## Uninstall

Reverse order; each step stands alone, so a partial install can be removed the same way.

```sh
noctalia msg plugins disable mtrenker/astral_monitor
noctalia msg plugins source remove astral-monitor

sudo systemctl disable --now astral-monitor.service
sudo rm /etc/systemd/system/astral-monitor.service
sudo systemctl daemon-reload

sudo rm /etc/udev/rules.d/70-astral-monitor.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=i2c-dev --action=change

sudo rm -f /etc/modules-load.d/astral-monitor-i2c-dev.conf
sudo modprobe -r i2c-dev   # optional; only if nothing else uses it

sudo rm /etc/sysusers.d/astral-monitor.conf
sudo userdel astral-monitor
sudo groupdel astral-monitor 2>/dev/null || true

sudo rm -r /usr/local/lib/astral-monitor
```

Stopping the service removes `/run/astral-monitor`. The plugin then shows "No snapshot".
