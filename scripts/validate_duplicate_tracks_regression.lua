-- Guarded regression: read the requested live session, mutate only a disposable tab.
local _, filename = reaper.get_action_context()
local root = assert(filename:match('^(.*)[/\\]scripts[/\\][^/\\]+$'))
reaper.SetExtState('reaper-duplicate-regression', 'repository', root, false)
local path = root .. '/scripts/validate_duplicate_tracks_regression.py'
local id = reaper.AddRemoveReaScript(true, 0, path, false)
assert(id ~= 0, 'Python ReaScript support required')
reaper.Main_OnCommand(id, 0)
reaper.AddRemoveReaScript(false, 0, path, false)
reaper.DeleteExtState('reaper-duplicate-regression', 'repository', false)
