-- Execute the guarded Python probe through REAPER's ReaScript API.
local _, filename = reaper.get_action_context()
local root = assert(filename:match('^(.*)[/\\]scripts[/\\][^/\\]+$'))
reaper.SetExtState('reaper-template-validation', 'repository', root, false)
local path = root .. '/scripts/diagnose_template_copy.py'
local id = reaper.AddRemoveReaScript(true, 0, path, false)
reaper.Main_OnCommand(id, 0)
reaper.AddRemoveReaScript(false, 0, path, false)
reaper.DeleteExtState('reaper-template-validation', 'repository', false)
