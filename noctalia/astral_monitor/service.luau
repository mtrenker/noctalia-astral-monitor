--!nonstrict
-- The plugin's only snapshot reader. Polls the collector's JSON file once per
-- second, evaluates it, and publishes the view on noctalia.state for every bar
-- widget instance and the panel.

local model = require("./lib/model.luau")

local VIEW_KEY = "astral.view"
local PENDING_LIMIT_MS = 5000

local path = noctalia.getConfig("snapshot_path")
local warnMa = math.floor(noctalia.getConfig("warn_current_a") * 1000 + 0.5)
local pendingSince = nil
local lastDecodeErr = nil

local function publish(view)
  noctalia.state.set(VIEW_KEY, view)
end

local function onRead(contents, err)
  pendingSince = nil
  local now = noctalia.nowMs()
  if contents == nil then
    publish(model.fromReadError(err, now, warnMa))
    return
  end
  local decoded, decodeErr = noctalia.json.decode(contents)
  if decoded == nil then
    if decodeErr ~= lastDecodeErr then
      noctalia.log("snapshot is not valid JSON: " .. tostring(decodeErr))
      lastDecodeErr = decodeErr
    end
    publish(model.fromDecodeError(now, warnMa))
    return
  end
  lastDecodeErr = nil
  publish(model.evaluate(decoded, now, warnMa))
end

local function poll()
  local now = noctalia.nowMs()
  if pendingSince ~= nil and now - pendingSince < PENDING_LIMIT_MS then
    return
  end
  if noctalia.readFileAsync(path, onRead) then
    pendingSince = now
  else
    publish(model.fromReadError("snapshot read could not be queued", now, warnMa))
  end
end

noctalia.setUpdateInterval(1000)

function update()
  poll()
end

poll()
