--!nonstrict
-- Bar widget: highest current across the six feeds, or the reason there is none.
-- Renders the service's view; never reads the snapshot itself.

local model = require("./lib/model.luau")

local view = noctalia.state.get("astral.view")

local function fixtureBadge()
  return ui.row({ fill = "secondary/0.22", radius = 5, paddingH = 5, align = "center" }, {
    ui.label({ text = "FIXTURE", fontSize = 9, fontWeight = "bold", color = "secondary" }),
  })
end

local function render()
  local p = model.barPresentation(model.effective(view, noctalia.nowMs()))
  local vertical = barWidget.isVertical()
  local text = vertical and p.short or p.text
  local children = { ui.glyph({ name = p.glyph, color = p.color }) }
  if text ~= "" then
    table.insert(children, ui.label({ text = text, color = p.color, fontWeight = "semibold" }))
  end
  if p.fixture then
    table.insert(children, fixtureBadge())
  end
  local container = vertical and ui.column or ui.row
  barWidget.render(container({ gap = 5, align = "center" }, children))
  barWidget.setTooltip(p.tooltip)
end

noctalia.state.watch("astral.view", function(value)
  view = value
  render()
end)

-- Re-check once a second so a silent service turns into "stale" here too.
function update()
  noctalia.setUpdateInterval(1000)
  render()
end

function onClick()
  noctalia.togglePanel("mtrenker/astral_monitor:panel")
end

render()
