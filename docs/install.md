# Install and uninstall

**Only for a card listed in the supported-card table.** It lists only ROG Astral RTX 5090 subsystem `1043:89e3`; other cards need a [controlled live trial](live-trial.md) first. On any other machine the collector reports `unsupported` and never touches I²C.

Nothing happens automatically: the plugin does not install the collector, change device permissions, or start services. Run these from a checkout of the repository.

## Install

```sh
sudo make install                                # collector, account, device access, i2c-dev
sudo systemctl enable --now astral-monitor       # start the collector, now and at boot
make plugin-install                              # as your user: add the plugin to Noctalia
```

Enabling the plugin does not place its widget. Open Noctalia **Settings → Bar**, add a widget to a section, and pick **Astral Monitor**. Clicking it opens the panel.

`sudo make install` ends by listing the device nodes it granted. Exactly one `/dev/i2c-*` node should show group `astral-monitor`. If it warns that none was granted, run `sudo make uninstall`.

Check the collector:

```sh
systemctl status astral-monitor
cat /run/astral-monitor/snapshot.json            # "status": "ok"
```

## Uninstall

```sh
make plugin-uninstall
sudo make uninstall
```

`sudo make uninstall` stops and disables the service, removes every installed file, reloads udev and systemd, and deletes the `astral-monitor` account. It leaves i2c-dev loaded until reboot in case something else uses it (`sudo modprobe -r i2c-dev` unloads it now).

## What `sudo make install` does

Files go under `$(PREFIX)/lib`, `/usr/local/lib` by default, which systemd, udev, sysusers, and modules-load all search. Nothing is written to `/etc`.

| Item | Path |
| --- | --- |
| Collector code and upstream license notice | `/usr/local/lib/astral-monitor/` |
| Service | `/usr/local/lib/systemd/system/astral-monitor.service` |
| Access to the one sensor adapter | `/usr/local/lib/udev/rules.d/70-astral-monitor.rules` |
| System account `astral-monitor` | `/usr/local/lib/sysusers.d/astral-monitor.conf` |
| Load i2c-dev at boot | `/usr/local/lib/modules-load.d/astral-monitor-i2c-dev.conf` |
| Snapshot, created by the running service | `/run/astral-monitor/snapshot.json` |

After copying the files, it activates them:

- creates the account with `systemd-sysusers`;
- loads `i2c-dev`;
- reloads and re-triggers udev so the rule applies;
- runs `systemctl daemon-reload`.

It does not enable or start the service.

The udev rule is generated from the supported-card table at install time (`python3 -m astral_monitor.collector --udev-rule` prints it). It grants the `astral-monitor` group read-write access to the adapter named `NVIDIA i2c adapter 1 at …` on a listed card, and to nothing else.

The service runs as `astral-monitor` with no network, no capabilities, and a read-only view of the system apart from its runtime directory. `systemd-analyze security astral-monitor` summarises the sandbox.

`make plugin-install` copies the plugin into `~/.local/share/noctalia/plugins/astral_monitor` and enables it with `noctalia msg plugins enable`, which records the choice in Noctalia's own settings. The copy does not depend on this checkout staying in place. After pulling an update, run it again.

## Staging and packaging

`make install DESTDIR=/some/root PREFIX=/usr` installs only the files into a staging root. It skips the account, module, udev, and systemd activation, as a package build expects.
