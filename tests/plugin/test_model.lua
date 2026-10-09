-- Unit tests for noctalia/astral_monitor/lib/model.luau.
-- Run: luajit tests/plugin/test_model.lua <repo-root>   (Lua 5.1-5.4 also work)

local root = arg[1] or "."
local model = dofile(root .. "/noctalia/astral_monitor/lib/model.luau")

local failures, count = 0, 0
local function test(name, fn)
  count = count + 1
  local ok, err = pcall(fn)
  if not ok then
    failures = failures + 1
    print("FAIL " .. name .. ": " .. tostring(err))
  end
end
local function eq(actual, expected, what)
  if actual ~= expected then
    error((what or "value") .. ": expected " .. tostring(expected) .. ", got " .. tostring(actual), 2)
  end
end

local NOW = 1760000000000
local WARN = 9200

local function feeds(currents)
  local out = {}
  for pin = 1, 6 do
    out[pin] = { pin = pin, voltage_mv = 12050, current_ma = currents[pin] }
  end
  return out
end

local function snapshot(overrides)
  local s = {
    schema_version = 1,
    source = "hardware",
    status = "ok",
    message = "",
    observed_at_ms = NOW - 400,
    interval_ms = 1000,
    collector = { instance = "abcd1234", started_at_ms = NOW - 60000, sequence = 60 },
    device = { model = "Test card" },
    feeds = feeds({ 8100, 8300, 8550, 8200, 8400, 8050 }),
  }
  for k, v in pairs(overrides or {}) do
    s[k] = v
  end
  return s
end

local function noFeeds(status, message)
  local s = snapshot({ status = status, message = message or "detail" })
  s.feeds = nil
  return s
end

-- Evaluation -------------------------------------------------------------

test("fresh ok snapshot is live and normal", function()
  local v = model.evaluate(snapshot(), NOW, WARN)
  eq(v.state, "live")
  eq(v.level, "normal")
  eq(v.max_pin, 3)
  eq(v.max_ma, 8550)
  eq(v.total_ma, 49600)
  eq(#v.feeds, 6)
  eq(v.feeds[1].pin, 1)
  eq(v.feeds[6].current_ma, 8050)
end)

test("current at the threshold is a warning on that feed", function()
  local v = model.evaluate(snapshot({ feeds = feeds({ 8100, 8300, 9200, 8200, 8400, 8050 }) }), NOW, WARN)
  eq(v.level, "warning")
  eq(v.feeds[3].warn, true)
  eq(v.feeds[2].warn, false)
end)

test("a real zero on one feed stays a reading", function()
  local v = model.evaluate(snapshot({ feeds = feeds({ 0, 8300, 8550, 8200, 8400, 8050 }) }), NOW, WARN)
  eq(v.state, "live")
  eq(v.feeds[1].current_ma, 0)
end)

test("ok snapshot older than 5 s is stale and keeps readings for the panel only", function()
  local v = model.evaluate(snapshot({ observed_at_ms = NOW - 5001 }), NOW, WARN)
  eq(v.state, "stale")
  eq(v.level, nil)
  eq(#v.feeds, 6)
end)

test("5 s exactly is still live", function()
  eq(model.evaluate(snapshot({ observed_at_ms = NOW - 5000 }), NOW, WARN).state, "live")
end)

test("an old error status is stale, not the error", function()
  local s = noFeeds("permission_denied")
  s.observed_at_ms = NOW - 30000
  local v = model.evaluate(s, NOW, WARN)
  eq(v.state, "stale")
  eq(v.feeds, nil)
end)

test("collector statuses pass through without readings", function()
  for _, status in ipairs({ "starting", "unsupported", "no_adapter", "permission_denied", "read_error" }) do
    local v = model.evaluate(noFeeds(status, "why"), NOW, WARN)
    eq(v.state, status, status)
    eq(v.feeds, nil, status .. " feeds")
    eq(v.max_ma, nil, status .. " max")
    eq(v.message, "why", status .. " message")
  end
end)

test("timestamps more than 2 s in the future are invalid", function()
  eq(model.evaluate(snapshot({ observed_at_ms = NOW + 2001 }), NOW, WARN).state, "invalid")
  eq(model.evaluate(snapshot({ observed_at_ms = NOW + 1500 }), NOW, WARN).state, "live")
end)

test("structural problems are invalid", function()
  local cases = {
    { "schema", snapshot({ schema_version = 2 }) },
    { "source", snapshot({ source = "demo" }) },
    { "status", snapshot({ status = "fine" }) },
    { "time", snapshot({ observed_at_ms = "soon" }) },
    { "no feeds", noFeeds("ok") },
    { "all zero", snapshot({ feeds = feeds({ 0, 0, 0, 0, 0, 0 }) }) },
  }
  local zero = snapshot()
  for pin = 1, 6 do
    zero.feeds[pin].voltage_mv = 0
    zero.feeds[pin].current_ma = 0
  end
  table.insert(cases, { "all twelve values zero", zero })
  for _, case in ipairs(cases) do
    local v = model.evaluate(case[2], NOW, WARN)
    if case[1] == "all zero" then
      -- Voltages are non-zero here, so this is a valid idle sample.
      eq(v.state, "live", case[1])
    else
      eq(v.state, "invalid", case[1])
      eq(v.feeds, nil, case[1] .. " feeds")
    end
  end
  eq(model.evaluate("text", NOW, WARN).state, "invalid", "non-table")
end)

test("short, null, out-of-range, and misordered feeds are invalid", function()
  local short = snapshot()
  short.feeds[6] = nil -- five feeds; also what a JSON null decodes to
  local hole = snapshot()
  hole.feeds[2] = nil
  local fraction = snapshot()
  fraction.feeds[4].current_ma = 8200.5
  local negative = snapshot()
  negative.feeds[1].voltage_mv = -1
  local huge = snapshot()
  huge.feeds[1].current_ma = 70000
  local order = snapshot()
  order.feeds[1].pin, order.feeds[2].pin = 2, 1
  local seven = snapshot()
  seven.feeds[7] = { pin = 7, voltage_mv = 12000, current_ma = 1 }
  local missing = snapshot()
  missing.feeds[5].current_ma = nil
  for name, s in pairs({ short = short, hole = hole, fraction = fraction, negative = negative,
                         huge = huge, order = order, seven = seven, missing = missing }) do
    local v = model.evaluate(s, NOW, WARN)
    eq(v.state, "invalid", name)
    eq(v.max_ma, nil, name .. " max")
  end
end)

test("read and decode errors are unavailable states", function()
  local a = model.fromReadError("No such file or directory", NOW)
  eq(a.state, "no_snapshot")
  eq(a.feeds, nil)
  local d = model.fromDecodeError(NOW, WARN)
  eq(d.state, "invalid")
  eq(d.warn_ma, WARN, "threshold still shown when data is missing")
  eq(model.statusLine(a).detail, "Is the collector running? (No such file or directory)")
end)

-- Service liveness --------------------------------------------------------

test("no view yet renders as starting", function()
  eq(model.effective(nil, NOW).state, "starting")
end)

test("a view the service stopped refreshing turns stale", function()
  local v = model.evaluate(snapshot(), NOW, WARN)
  eq(model.effective(v, NOW + 3000).state, "live")
  local silent = model.effective(v, NOW + 3001)
  eq(silent.state, "stale")
  eq(silent.level, nil)
  eq(silent.service_silent, true)
  eq(v.state, "live", "original view untouched")
end)

-- Presentation ------------------------------------------------------------

test("bar shows the highest current with one decimal", function()
  local p = model.barPresentation(model.evaluate(snapshot(), NOW, WARN))
  eq(p.text, "8.6 A")
  eq(p.glyph, "bolt")
  eq(p.color, nil)
  eq(p.fixture, false)
end)

test("bar warning changes glyph and colour", function()
  local v = model.evaluate(snapshot({ feeds = feeds({ 8100, 9650, 8550, 8200, 8400, 8050 }) }), NOW, WARN)
  local p = model.barPresentation(v)
  eq(p.glyph, "alert-triangle")
  eq(p.color, "error")
  eq(p.text, "9.7 A")
end)

test("no unavailable state shows a number in the bar", function()
  local views = {
    model.evaluate(snapshot({ observed_at_ms = NOW - 9000 }), NOW, WARN),
    model.fromReadError("missing", NOW),
    model.fromDecodeError(NOW, WARN),
    model.effective(nil, NOW),
  }
  for _, status in ipairs({ "starting", "unsupported", "no_adapter", "permission_denied", "read_error" }) do
    table.insert(views, model.evaluate(noFeeds(status), NOW, WARN))
  end
  for _, v in ipairs(views) do
    local p = model.barPresentation(v)
    eq(p.text:find("%d"), nil, v.state .. " text " .. p.text)
    eq(p.short, "", v.state .. " short")
    eq(p.glyph ~= "bolt", true, v.state .. " glyph")
  end
end)

test("permission denied has its own wording", function()
  local p = model.barPresentation(model.evaluate(noFeeds("permission_denied"), NOW, WARN))
  eq(p.text, "no access")
  eq(p.glyph, "lock")
  eq(model.statusLine(model.evaluate(noFeeds("permission_denied"), NOW, WARN)).title,
    "No access to the sensor adapter")
end)

test("fixture source is flagged everywhere", function()
  local v = model.evaluate(snapshot({ source = "fixture" }), NOW, WARN)
  local p = model.barPresentation(v)
  eq(p.fixture, true)
  eq(p.tooltip[#p.tooltip][2], "Fixture data, not hardware")
end)

test("missing values format as a dash, never zero", function()
  eq(model.amps(nil), "—")
  eq(model.volts(nil), "—")
  eq(model.watts(nil), "—")
  eq(model.amps(0), "0.00 A")
  eq(model.volts(12080), "12.08 V")
  eq(model.watts(101716), "101.7 W")
end)

test("no wording claims safety", function()
  local all = {}
  local v = model.evaluate(snapshot(), NOW, WARN)
  for _, view in ipairs({ v, model.evaluate(snapshot({ feeds = feeds({ 9300, 1, 1, 1, 1, 1 }) }), NOW, WARN) }) do
    local line = model.statusLine(view)
    table.insert(all, line.title .. " " .. line.detail)
    for _, row in ipairs(model.barPresentation(view).tooltip) do
      table.insert(all, row[1] .. " " .. row[2])
    end
  end
  for _, text in ipairs(all) do
    local lower = text:lower()
    eq(lower:find("safe"), nil, text)
    eq(lower:find("healthy"), nil, text)
    eq(lower:find("%f[%a]ok%f[%A]"), nil, text)
  end
end)

test("shared scale is 12 A or the highest reading", function()
  eq(model.scaleMa(model.evaluate(snapshot(), NOW, WARN)), 12000)
  eq(model.scaleMa(model.evaluate(snapshot({ feeds = feeds({ 13000, 1, 1, 1, 1, 1 }) }), NOW, WARN)), 13000)
  eq(model.scaleMa(model.fromReadError("x", NOW)), 12000)
end)

print(string.format("%d tests, %d failed", count, failures))
os.exit(failures == 0 and 0 or 1)
