-- Guarded temporary-instance regression probe; never runs in a work session.
local _, filename = reaper.get_action_context()
local root = filename:match("^(.*)[/\\]scripts[/\\][^/\\]+$")
assert(root)
reaper.SetExtState("reaper-fx-probe", "repository", root, false)
local path = root .. "/scripts/validate_fx_copy_regression.py"
local id = reaper.AddRemoveReaScript(true, 0, path, false)
reaper.Main_OnCommand(id, 0)
local started = reaper.time_precise()
local function finish()
  if reaper.time_precise() - started < 2 then reaper.defer(finish); return end
  reaper.AddRemoveReaScript(false, 0, path, false)
  reaper.DeleteExtState("reaper-fx-probe", "repository", false)
end
reaper.defer(finish)
