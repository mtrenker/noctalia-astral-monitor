"""Plugin checks that need no running shell: Lua unit tests, the fixture-to-plugin
contract, and structural rules (one reader, no hardware or control access)."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import unittest

from astral_monitor import fixture

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "noctalia" / "astral_monitor"


def lua_interpreter():
    for name in (os.environ.get("LUA"), "luajit", "lua5.4", "lua5.1", "lua"):
        if name and shutil.which(name):
            return name
    return None


LUA = lua_interpreter()


def to_lua(value):
    """JSON value -> Lua literal, matching how Noctalia's json.decode maps it (null -> nil)."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "{" + ", ".join(f"[{i}] = {to_lua(v)}" for i, v in enumerate(value, start=1)) + "}"
    return "{" + ", ".join(f"[{json.dumps(k)}] = {to_lua(v)}" for k, v in value.items()) + "}"


@unittest.skipIf(LUA is None, "no Lua interpreter (luajit, lua5.4, lua5.1, lua) on PATH")
class LuaTest(unittest.TestCase):
    def test_model_unit_tests(self):
        result = subprocess.run([LUA, "tests/plugin/test_model.lua", "."], cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def evaluate(self, value, now_ms):
        script = (
            f"local m = dofile({json.dumps(str(PLUGIN / 'lib' / 'model.luau'))})\n"
            f"local v = m.evaluate({to_lua(value)}, {now_ms}, 9200)\n"
            "print(v.state .. '|' .. tostring(v.level) .. '|' .. tostring(v.source))\n"
        )
        result = subprocess.run([LUA, "-"], input=script, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def test_fixture_snapshots_evaluate_to_the_intended_states(self):
        now = 1_760_000_000_000
        expected = {
            "normal": "live|normal|fixture",
            "warning": "live|warning|fixture",
            "starting": "starting|nil|fixture",
            "unsupported": "unsupported|nil|fixture",
            "no_adapter": "no_adapter|nil|fixture",
            "permission_denied": "permission_denied|nil|fixture",
            "read_error": "read_error|nil|fixture",
        }
        for scenario, want in expected.items():
            value = fixture.snapshot_for(scenario, fixture.Collector(now - 5000), now - 300, t=1.0)
            self.assertEqual(self.evaluate(value, now), want, scenario)
        aged = fixture.snapshot_for("normal", fixture.Collector(now - 60000), now - 6000)
        self.assertEqual(self.evaluate(aged, now), "stale|nil|fixture")


class StructureTest(unittest.TestCase):
    def sources(self):
        return {p.relative_to(PLUGIN).as_posix(): p.read_text(encoding="utf-8")
                for p in PLUGIN.rglob("*.luau")}

    def test_only_the_service_reads_files_or_publishes_state(self):
        for name, source in self.sources().items():
            reads = re.search(r"noctalia\.(readFile|readFileAsync|fileInfo|listDir)\b", source)
            publishes = "noctalia.state.set" in source
            if name == "service.luau":
                self.assertTrue(reads and publishes, name)
            else:
                self.assertIsNone(reads, name)
                self.assertFalse(publishes, name)

    def test_plugin_has_no_hardware_process_or_network_access(self):
        forbidden = re.compile(r"/dev/|i2c|nvidia-smi|runAsync|runStream|runInTerminal|"
                               r"noctalia\.(http|httpStream|download|writeFile|removeFile|renameFile)\b")
        for name, source in self.sources().items():
            code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("--"))
            self.assertIsNone(forbidden.search(code), name)


if __name__ == "__main__":
    unittest.main()
