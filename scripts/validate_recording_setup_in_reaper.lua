-- Finite host probe: never modifies existing project tabs.
local _, filename = reaper.get_action_context()
local root = filename:match("^(.*)[/\\]scripts[/\\][^/\\]+$")
assert(root, "Validation launcher must remain in repository scripts/")
reaper.SetExtState("reaper-mcp-validation", "repository", root, false)
local path = root .. "/scripts/validate_recording_setup_in_reaper.py"
local id = reaper.AddRemoveReaScript(true, 0, path, false)
assert(id ~= 0, "Python ReaScript support is required")
reaper.Main_OnCommand(id, 0)
local started = reaper.time_precise()
local function finish()
  if reaper.time_precise() - started < 2 then reaper.defer(finish); return end
  reaper.AddRemoveReaScript(false, 0, path, false)
  reaper.DeleteExtState("reaper-mcp-validation", "repository", false)
end
reaper.defer(finish)
