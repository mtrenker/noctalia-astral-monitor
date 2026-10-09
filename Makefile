PYTHON ?= python3
SCENARIO ?= cycle
PLUGIN := noctalia/astral_monitor
PLUGIN_ID := mtrenker/astral_monitor

# System install (sudo make install). Everything lives under $(PREFIX)/lib, which systemd,
# udev, sysusers and modules-load all search, so nothing is written to /etc.
PREFIX ?= /usr/local
DESTDIR ?=
LIBDIR := $(DESTDIR)$(PREFIX)/lib
APPDIR := $(LIBDIR)/astral-monitor
UNITDIR := $(LIBDIR)/systemd/system
UDEVDIR := $(LIBDIR)/udev/rules.d
SYSUSERSDIR := $(LIBDIR)/sysusers.d
MODULESDIR := $(LIBDIR)/modules-load.d

# Per-user plugin install (make plugin-install, no sudo): Noctalia's local plugin directory.
NOCTALIA ?= noctalia
NOCTALIA_DATA := $(or $(NOCTALIA_DATA_HOME),$(XDG_DATA_HOME),$(HOME)/.local/share)
PLUGINDIR := $(NOCTALIA_DATA)/noctalia/plugins/astral_monitor

.PHONY: check test lint fixture preview preview-panel preview-clean \
	install uninstall plugin-install plugin-uninstall

check: test lint

test:
	PYTHONPATH=collector:tests $(PYTHON) -m unittest discover -s tests -v

lint:
	$(NOCTALIA) plugins lint $(PLUGIN)

# Hardware-free fixture source, foreground; Ctrl-C stops it (the snapshot then goes stale).
fixture:
	PYTHONPATH=collector $(PYTHON) -m astral_monitor.fixture --scenario $(SCENARIO)

# Isolated nested-Hyprland Noctalia preview, foreground; Ctrl-C stops it.
preview:
	scripts/preview.sh run

preview-panel:
	scripts/preview.sh panel

preview-clean:
	scripts/preview.sh clean

# Installs files and activates the account, device rule and i2c-dev. Does not start the
# service: run `sudo systemctl enable --now astral-monitor` yourself. With DESTDIR set
# (staging or packaging) only files are installed.
install:
	install -d -m 0755 $(APPDIR)/astral_monitor $(APPDIR)/LICENSES $(UNITDIR) $(UDEVDIR) \
		$(SYSUSERSDIR) $(MODULESDIR)
	install -m 0644 collector/astral_monitor/*.py $(APPDIR)/astral_monitor/
	install -m 0644 LICENSES/* $(APPDIR)/LICENSES/
	sed 's|/usr/local/lib/astral-monitor|$(PREFIX)/lib/astral-monitor|' \
		packaging/astral-monitor.service > $(UNITDIR)/astral-monitor.service
	chmod 0644 $(UNITDIR)/astral-monitor.service
	PYTHONPATH=collector $(PYTHON) -m astral_monitor.collector --udev-rule \
		> $(UDEVDIR)/70-astral-monitor.rules
	chmod 0644 $(UDEVDIR)/70-astral-monitor.rules
	install -m 0644 packaging/astral-monitor.sysusers $(SYSUSERSDIR)/astral-monitor.conf
	install -m 0644 packaging/i2c-dev.conf $(MODULESDIR)/astral-monitor-i2c-dev.conf
ifeq ($(DESTDIR),)
	systemd-sysusers $(SYSUSERSDIR)/astral-monitor.conf
	modprobe i2c-dev
	udevadm control --reload
	udevadm trigger --subsystem-match=i2c-dev --action=change
	udevadm settle
	systemctl daemon-reload
	@echo
	@echo "Installed. Sensor adapter access:"
	@ls -l /dev/i2c-* | grep astral-monitor || echo "  WARNING: no adapter granted; run 'sudo make uninstall'"
	@echo "Start the collector:  sudo systemctl enable --now astral-monitor"
	@echo "Add the plugin:       make plugin-install   (as your user, without sudo)"
endif

# Stops the service and removes everything install created. Leaves i2c-dev loaded until
# reboot, in case something else uses it.
uninstall:
ifeq ($(DESTDIR),)
	-systemctl disable --now astral-monitor.service
endif
	rm -f $(UNITDIR)/astral-monitor.service $(UDEVDIR)/70-astral-monitor.rules \
		$(SYSUSERSDIR)/astral-monitor.conf $(MODULESDIR)/astral-monitor-i2c-dev.conf
	rm -f $(APPDIR)/astral_monitor/*.py $(APPDIR)/LICENSES/*
	rm -rf $(APPDIR)/astral_monitor/__pycache__
	-rmdir $(APPDIR)/astral_monitor $(APPDIR)/LICENSES $(APPDIR)
ifeq ($(DESTDIR),)
	systemctl daemon-reload
	udevadm control --reload
	udevadm trigger --subsystem-match=i2c-dev --action=change
	-userdel astral-monitor
	-groupdel astral-monitor
	@echo "Uninstalled. i2c-dev stays loaded until reboot (or: sudo modprobe -r i2c-dev)."
endif

plugin-install:
	@test "$$(id -u)" != 0 || { echo "Run plugin-install as your user, not with sudo."; exit 1; }
	install -d -m 0755 $(PLUGINDIR)/lib $(PLUGINDIR)/translations
	install -m 0644 $(PLUGIN)/plugin.toml $(PLUGIN)/*.luau $(PLUGINDIR)/
	install -m 0644 $(PLUGIN)/lib/*.luau $(PLUGINDIR)/lib/
	install -m 0644 $(PLUGIN)/translations/*.json $(PLUGINDIR)/translations/
	$(NOCTALIA) msg plugins enable $(PLUGIN_ID)
	@echo "Enabled. Add the \"Astral Monitor\" widget to a bar in Noctalia Settings."

plugin-uninstall:
	-$(NOCTALIA) msg plugins disable $(PLUGIN_ID)
	rm -f $(PLUGINDIR)/plugin.toml $(PLUGINDIR)/*.luau $(PLUGINDIR)/lib/*.luau \
		$(PLUGINDIR)/translations/*.json
	-rmdir $(PLUGINDIR)/lib $(PLUGINDIR)/translations $(PLUGINDIR)
