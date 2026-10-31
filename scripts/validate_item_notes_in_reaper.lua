-- Read-only probe of the active Turbulence project. Never creates fixture items.
local _, filename = reaper.get_action_context()
local root = assert(filename:match("^(.*)[/\\]scripts[/\\][^/\\]+$"))
local path = root .. "/scripts/validate_item_notes_in_reaper.py"
reaper.SetExtState("reaper-mcp-item-notes-validation", "repository", root, false)
local id = reaper.AddRemoveReaScript(true, 0, path, false)
assert(id ~= 0, "Python ReaScript support required")
reaper.Main_OnCommand(id, 0)
reaper.AddRemoveReaScript(false, 0, path, false)
reaper.DeleteExtState("reaper-mcp-item-notes-validation", "repository", false)
