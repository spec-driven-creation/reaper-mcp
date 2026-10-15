-- Executes only the explicit FM-003 -> FM-004 authorization guarded in the Python probe.
local _, filename = reaper.get_action_context()
local root = filename:match("^(.*)[/\\]scripts[/\\][^/\\]+$")
assert(root)
reaper.SetExtState("reaper-fx-probe", "repository", root, false)
local path = root .. "/scripts/complete_fm004_fx.py"
local id = reaper.AddRemoveReaScript(true, 0, path, false)
reaper.Main_OnCommand(id, 0)
local started = reaper.time_precise()
local function finish()
  if reaper.time_precise() - started < 2 then reaper.defer(finish); return end
  reaper.AddRemoveReaScript(false, 0, path, false)
  reaper.DeleteExtState("reaper-fx-probe", "repository", false)
end
reaper.defer(finish)
