--!nonstrict
-- Panel: the six positive feeds on one shared scale, with exact readings,
-- computed watts, and freshness. Pins are a numbered list; no physical
-- connector layout is implied. Renders the service's view only.

local model = require("./lib/model.luau")

local MUTED = "on_surface_variant"

local view = noctalia.state.get("astral.view")
local open = false

local function fixtureBadge()
  return ui.row({ fill = "secondary/0.22", radius = 6, paddingH = 8, paddingV = 2, align = "center", gap = 4 }, {
    ui.glyph({ name = "flask", size = 12, color = "secondary" }),
    ui.label({ text = "FIXTURE DATA", fontSize = 10, fontWeight = "bold", color = "secondary" }),
  })
end

-- Fixed-width, end-aligned cell so every row's bar gets the same length.
local function cell(width, child)
  return ui.row({ width = width, justify = "end", align = "center" }, { child })
end

local function feedRow(v, pin, scaleMa, current)
  local feed = v.feeds and v.feeds[pin] or nil
  local warn = current and feed ~= nil and feed.warn
  local meter
  if feed ~= nil then
    meter = ui.progress({
      progress = math.min(1, feed.current_ma / scaleMa),
      fill = warn and "error" or (current and "primary" or MUTED .. "/0.5"),
      track = "outline/0.35",
      radius = 3,
      height = 8,
      flexGrow = 1,
    })
  else
    meter = ui.label({ text = "no reading", fontSize = 12, color = MUTED, flexGrow = 1 })
  end
  local ampsColor = warn and "error" or (current and "on_surface" or MUTED)
  return ui.row({ key = "pin-" .. pin, gap = 8, align = "center", minHeight = 24 }, {
    ui.row({ width = 40 }, { ui.label({ text = "Pin " .. pin, color = MUTED }) }),
    meter,
    cell(64, ui.label({
      text = model.amps(feed and feed.current_ma),
      fontWeight = current and "bold" or "normal",
      color = ampsColor,
    })),
    cell(62, ui.label({ text = model.volts(feed and feed.voltage_mv), color = MUTED })),
    cell(64, ui.label({ text = model.watts(feed and (feed.voltage_mv * feed.current_ma / 1000)), color = MUTED })),
    -- The slot is always present so rows stay aligned; the glyph only shows on a warning.
    ui.glyph({ name = "alert-triangle", size = 16, color = "error", opacity = warn and 1 or 0 }),
  })
end

local function render()
  if not open then
    return
  end
  local v = model.effective(view, noctalia.nowMs())
  local line = model.statusLine(v)
  local current = v.state == "live"
  local scaleMa = model.scaleMa(v)

  local header = { ui.glyph({ name = "bolt", size = 18, color = "primary" }),
    ui.label({ text = "Astral power feeds", fontSize = 15, fontWeight = "bold", flexGrow = 1 }) }
  if v.source == "fixture" then
    table.insert(header, fixtureBadge())
  end
  table.insert(header, ui.button({ glyph = "close", variant = "ghost", controlSize = "sm", onClick = "onCloseClicked" }))

  local rows = {}
  for pin = 1, model.PIN_COUNT do
    table.insert(rows, feedRow(v, pin, scaleMa, current))
  end

  local totalsColor = current and "on_surface" or MUTED
  local totals = ui.column({ gap = 4 }, {
    ui.row({ gap = 8, align = "center" }, {
      ui.label({ text = "Connector total", flexGrow = 1 }),
      cell(64, ui.label({ text = model.amps(v.total_ma, 1), color = totalsColor })),
      cell(70, ui.label({
        text = model.watts(v.total_mw, 0),
        fontWeight = current and "bold" or "normal",
        color = totalsColor,
      })),
    }),
    ui.label({
      text = "Computed from the six feeds, not total board power."
        .. (v.warn_ma and (" Warning at " .. model.amps(v.warn_ma, 1) .. " per feed.") or ""),
      fontSize = 12,
      color = MUTED,
      maxLines = 2,
    }),
  })

  local sourceText = v.source == "fixture" and "Fixture source" or (v.source == "hardware" and "Collector" or "No source")
  if v.model ~= nil then
    sourceText = sourceText .. " · " .. v.model
  end
  if v.started_at_ms ~= nil then
    sourceText = sourceText .. " · started " .. model.age(noctalia.nowMs() - v.started_at_ms) .. " ago"
  end

  panel.render(ui.column({ gap = 12, padding = 16 }, {
    ui.row({ gap = 8, align = "center" }, header),
    ui.row({ gap = 10, align = "center" }, {
      ui.glyph({ name = line.glyph, size = 20, color = line.color }),
      ui.column({ gap = 2, flexGrow = 1 }, {
        ui.label({ text = line.title, fontWeight = "bold", color = line.color == MUTED and "on_surface" or line.color }),
        ui.label({ text = line.detail, fontSize = 12, color = MUTED, maxLines = 2 }),
      }),
    }),
    ui.separator({}),
    ui.column({ gap = 6 }, rows),
    ui.separator({}),
    totals,
    ui.column({ gap = 2 }, {
      ui.label({ text = sourceText, fontSize = 11, color = MUTED, maxLines = 1 }),
      ui.label({
        text = "Monitoring aid only. Does not measure connector temperature or contact quality.",
        fontSize = 11,
        color = MUTED,
        maxLines = 2,
      }),
    }),
  }))
end

noctalia.state.watch("astral.view", function(value)
  view = value
  render()
end)

function onOpen()
  open = true
  panel.setWantsSecondTicks(true)
  render()
end

function onClose()
  open = false
end

-- Second ticks keep ages moving and catch a silent service while open.
function update()
  render()
end

function onCloseClicked()
  panel.close()
end
