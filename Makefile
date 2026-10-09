PYTHON ?= python3
SCENARIO ?= cycle
PLUGIN := noctalia/astral_monitor

.PHONY: check test lint fixture preview preview-panel preview-clean

check: test lint

test:
	PYTHONPATH=collector $(PYTHON) -m unittest discover -s tests -v

lint:
	noctalia plugins lint $(PLUGIN)

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
