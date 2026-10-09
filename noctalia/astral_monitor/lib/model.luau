--!nonstrict
-- Snapshot evaluation and presentation for the Astral monitor (docs/design.md).
-- Pure functions with no noctalia.* calls, written in the Lua 5.1 subset of Luau
-- so tests/plugin can run them under LuaJIT or Lua 5.x.
--
-- A view is the plain table the service publishes on noctalia.state. Missing
-- values stay nil; nothing here turns absent data into zero.

local M = {}

M.STALE_AFTER_MS = 5000
M.FUTURE_TOLERANCE_MS = 2000
M.SERVICE_SILENT_MS = 3000
M.PIN_COUNT = 6
M.SCALE_MIN_MA = 12000

local COLLECTOR_STATUSES = {
  ok = true,
  starting = true,
  unsupported = true,
  no_adapter = true,
  permission_denied = true,
  read_error = true,
}
local SOURCES = { hardware = true, fixture = true }

local function isU16(value)
  return type(value) == "number" and value == math.floor(value) and value >= 0 and value <= 65535
end

local function unavailable(state, message, nowMs, warnMa)
  return { state = state, message = message, evaluated_at_ms = nowMs, warn_ma = warnMa }
end

local function validFeeds(feeds)
  if type(feeds) ~= "table" then
    return nil, "ok snapshot without feeds"
  end
  local out = {}
  local anyNonZero = false
  for pin = 1, M.PIN_COUNT do
    local feed = feeds[pin]
    if type(feed) ~= "table" or feed.pin ~= pin or not isU16(feed.voltage_mv) or not isU16(feed.current_ma) then
      return nil, "feed for pin " .. pin .. " is missing or malformed"
    end
    if feed.voltage_mv ~= 0 or feed.current_ma ~= 0 then
      anyNonZero = true
    end
    out[pin] = { pin = pin, voltage_mv = feed.voltage_mv, current_ma = feed.current_ma }
  end
  if feeds[M.PIN_COUNT + 1] ~= nil then
    return nil, "more than six feeds"
  end
  if not anyNonZero then
    return nil, "all readings are zero"
  end
  return out
end

function M.fromReadError(err, nowMs, warnMa)
  return unavailable("no_snapshot", tostring(err or "snapshot not readable"), nowMs, warnMa)
end

-- The parser's own message is for the log; the panel says what is wrong in plain words.
function M.fromDecodeError(nowMs, warnMa)
  return unavailable("invalid", "The snapshot file is not valid JSON.", nowMs, warnMa)
end

-- Evaluate one decoded snapshot. warnMa is the warning threshold in milliamps.
function M.evaluate(snapshot, nowMs, warnMa)
  if type(snapshot) ~= "table" then
    return unavailable("invalid", "snapshot is not a JSON object", nowMs, warnMa)
  end
  if snapshot.schema_version ~= 1 then
    return unavailable("invalid", "unsupported schema_version " .. tostring(snapshot.schema_version), nowMs, warnMa)
  end
  if not SOURCES[snapshot.source] then
    return unavailable("invalid", "unknown source " .. tostring(snapshot.source), nowMs, warnMa)
  end
  if not COLLECTOR_STATUSES[snapshot.status] then
    return unavailable("invalid", "unknown status " .. tostring(snapshot.status), nowMs, warnMa)
  end
  local observed = snapshot.observed_at_ms
  if type(observed) ~= "number" then
    return unavailable("invalid", "missing observed_at_ms", nowMs, warnMa)
  end
  if observed - nowMs > M.FUTURE_TOLERANCE_MS then
    return unavailable("invalid", "sample time is in the future; check the clock", nowMs, warnMa)
  end

  local view = {
    state = snapshot.status,
    source = snapshot.source,
    message = type(snapshot.message) == "string" and snapshot.message or "",
    evaluated_at_ms = nowMs,
    observed_at_ms = observed,
    age_ms = math.max(0, nowMs - observed),
    warn_ma = warnMa,
  }
  if type(snapshot.collector) == "table" and type(snapshot.collector.started_at_ms) == "number" then
    view.started_at_ms = snapshot.collector.started_at_ms
  end
  if type(snapshot.device) == "table" and type(snapshot.device.model) == "string" then
    view.model = snapshot.device.model
  end

  if snapshot.status == "ok" then
    local feeds, reason = validFeeds(snapshot.feeds)
    if feeds == nil then
      return unavailable("invalid", reason, nowMs, warnMa)
    end
    local maxPin, maxMa, totalMa, totalMw = 1, -1, 0, 0
    for _, feed in ipairs(feeds) do
      feed.warn = feed.current_ma >= warnMa
      totalMa = totalMa + feed.current_ma
      totalMw = totalMw + feed.voltage_mv * feed.current_ma / 1000
      if feed.current_ma > maxMa then
        maxPin, maxMa = feed.pin, feed.current_ma
      end
    end
    view.state = "live"
    view.feeds = feeds
    view.max_pin = maxPin
    view.max_ma = maxMa
    view.total_ma = totalMa
    view.total_mw = totalMw
    view.level = maxMa >= warnMa and "warning" or "normal"
  end

  if view.age_ms > M.STALE_AFTER_MS then
    -- Old data says nothing about now. Readings, if any, are kept for the panel only.
    view.state = "stale"
    view.level = nil
  end
  return view
end

-- The view to render now: guards against a service that stopped publishing.
function M.effective(view, nowMs)
  if type(view) ~= "table" or type(view.evaluated_at_ms) ~= "number" then
    return unavailable("starting", "Waiting for the monitor service.", nowMs)
  end
  if nowMs - view.evaluated_at_ms <= M.SERVICE_SILENT_MS then
    return view
  end
  local copy = {}
  for key, value in pairs(view) do
    copy[key] = value
  end
  copy.state = "stale"
  copy.level = nil
  copy.message = "Monitor service not updating."
  copy.service_silent = true
  if type(view.observed_at_ms) == "number" then
    copy.age_ms = math.max(0, nowMs - view.observed_at_ms)
  end
  return copy
end

-- Formatting --------------------------------------------------------------

function M.amps(ma, decimals)
  if ma == nil then
    return "—"
  end
  return string.format("%." .. (decimals or 2) .. "f A", ma / 1000)
end

function M.volts(mv)
  if mv == nil then
    return "—"
  end
  return string.format("%.2f V", mv / 1000)
end

function M.watts(mw, decimals)
  if mw == nil then
    return "—"
  end
  return string.format("%." .. (decimals or 1) .. "f W", mw / 1000)
end

function M.age(ms)
  if ms == nil then
    return "unknown time"
  end
  if ms < 1000 then
    return "<1 s"
  end
  if ms < 120000 then
    return string.format("%d s", math.floor(ms / 1000))
  end
  return string.format("%d min", math.floor(ms / 60000))
end

-- Presentation ------------------------------------------------------------

local MUTED = "on_surface_variant"

local TITLES = {
  stale = "Stale",
  starting = "Collector starting",
  unsupported = "No supported card",
  no_adapter = "Sensor adapter missing",
  permission_denied = "No access to the sensor adapter",
  read_error = "Sensor read failed",
  no_snapshot = "No snapshot",
  invalid = "Snapshot invalid",
}

local HINTS = {
  no_snapshot = "Is the collector running?",
}

local function withHint(state, message)
  local hint = HINTS[state]
  if message == nil or message == "" then
    return hint or ""
  end
  if hint == nil then
    return message
  end
  return hint .. " (" .. message .. ")"
end

function M.statusLine(view)
  local state = view.state
  if state == "live" then
    local updated = "updated " .. M.age(view.age_ms) .. " ago"
    if view.level == "warning" then
      return {
        glyph = "alert-triangle",
        color = "error",
        title = "Pin " .. view.max_pin .. " at " .. M.amps(view.max_ma) .. ", at or above " .. M.amps(view.warn_ma, 1),
        detail = "Live, " .. updated,
      }
    end
    return { glyph = "bolt", color = "primary", title = "Live", detail = "Highest feed pin " .. view.max_pin .. ", " .. updated }
  end
  if state == "stale" then
    local detail = "Last sample " .. M.age(view.age_ms) .. " ago. Values below are not current."
    if view.feeds == nil then
      detail = "Last sample " .. M.age(view.age_ms) .. " ago. No readings."
    end
    if view.service_silent then
      detail = view.message .. " " .. detail
    end
    return { glyph = "clock-exclamation", color = MUTED, title = TITLES.stale, detail = detail }
  end
  local detail = withHint(state, view.message)
  local glyph = "bolt-off"
  if state == "starting" then
    glyph = "loader"
  elseif state == "permission_denied" then
    glyph = "lock"
  end
  return { glyph = glyph, color = MUTED, title = TITLES[state] or state, detail = detail }
end

function M.barPresentation(view)
  local p = { fixture = view.source == "fixture" }
  local state = view.state
  if state == "live" then
    p.text = M.amps(view.max_ma, 1)
    p.short = string.format("%.1f", view.max_ma / 1000)
    if view.level == "warning" then
      p.glyph, p.color = "alert-triangle", "error"
    else
      p.glyph = "bolt"
    end
  elseif state == "stale" then
    p.glyph, p.color, p.text = "clock-exclamation", MUTED, "stale"
  elseif state == "starting" then
    p.glyph, p.color, p.text = "loader", MUTED, "starting"
  elseif state == "permission_denied" then
    p.glyph, p.color, p.text = "lock", MUTED, "no access"
  else
    p.glyph, p.color, p.text = "bolt-off", MUTED, "no data"
  end
  p.short = p.short or ""

  local line = M.statusLine(view)
  local rows = { { "Astral feeds", line.title } }
  if state == "live" then
    table.insert(rows, { "Highest", "Pin " .. view.max_pin .. ", " .. M.amps(view.max_ma) })
  end
  if view.age_ms ~= nil then
    table.insert(rows, { "Sample age", M.age(view.age_ms) })
  elseif line.detail ~= "" then
    table.insert(rows, { "Detail", line.detail })
  end
  if p.fixture then
    table.insert(rows, { "Source", "Fixture data, not hardware" })
  end
  p.tooltip = rows
  return p
end

-- Shared bar scale so feeds compare at a glance: 12 A, or the highest reading above it.
function M.scaleMa(view)
  local scale = M.SCALE_MIN_MA
  if view.max_ma ~= nil and view.max_ma > scale then
    scale = view.max_ma
  end
  return scale
end

return M
