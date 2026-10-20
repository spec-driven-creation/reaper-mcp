-- Launch only in a disposable REAPER instance configured with .local/edges-validation/reaper.ini.
local _, filename = reaper.get_action_context()
local root = assert(filename:match('^(.*)[/\\]scripts[/\\][^/\\]+$'))
reaper.SetExtState('reaper-edges-validation', 'repository', root, false)
local path = root .. '/scripts/validate_item_edges.py'
local id = reaper.AddRemoveReaScript(true, 0, path, false)
reaper.Main_OnCommand(id, 0)
reaper.AddRemoveReaScript(false, 0, path, false)
reaper.DeleteExtState('reaper-edges-validation', 'repository', false)
