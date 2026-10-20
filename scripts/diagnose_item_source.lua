-- Read-only native/binding comparison for the reported FM-009 item.
local _, filename = reaper.get_action_context()
local root = assert(filename:match('^(.*)[/\\]scripts[/\\][^/\\]+$'))
local item_guid = '{B19B1EFB-5752-48D4-91EE-A512981D7751}'
local track_guid = '{DB7D7DF9-A322-476F-901A-A1B72A1A47EF}'
local project, project_path = reaper.EnumProjects(-1, '')
local track, item
for t = 0, reaper.CountTracks(project) - 1 do
  local candidate = reaper.GetTrack(project, t)
  if reaper.GetTrackGUID(candidate) == track_guid then
    assert(not track, 'Duplicate track GUID')
    track = candidate
    for i = 0, reaper.CountTrackMediaItems(track) - 1 do
      local candidate_item = reaper.GetTrackMediaItem(track, i)
      local _, guid = reaper.GetSetMediaItemInfo_String(candidate_item, 'GUID', '', false)
      if guid == item_guid then assert(not item, 'Duplicate item GUID'); item = candidate_item end
    end
  end
end
assert(track and item, 'Expected real item/track not found; nothing changed')
local ok, before = reaper.GetItemStateChunk(item, '', false)
assert(ok)
local take = reaper.GetTake(item, 0)
local source = reaper.GetMediaItemTake_Source(take)
local length, is_qn = reaper.GetMediaSourceLength(source)
local file = assert(io.open(root .. '/.local/source-length/native.txt', 'w'))
file:write('project=' .. project_path .. '\nsource_pointer=' .. tostring(source) ..
  '\nsource_valid=' .. tostring(reaper.ValidatePtr(source, 'PCM_source*')) ..
  '\nsource_type=' .. reaper.GetMediaSourceType(source, '') ..
  '\nsource_parent=' .. tostring(reaper.GetMediaSourceParent(source)) ..
  '\nsource_file=' .. reaper.GetMediaSourceFileName(source, '') ..
  '\nsource_length=' .. tostring(length) .. '\nlength_is_qn=' .. tostring(is_qn) ..
  '\nsample_rate=' .. tostring(reaper.GetMediaSourceSampleRate(source)) ..
  '\nchannels=' .. tostring(reaper.GetMediaSourceNumChannels(source)) .. '\n')
if reaper.APIExists('CF_GetMediaSourceOnline') then
  file:write('source_online=' .. tostring(reaper.CF_GetMediaSourceOnline(source)) .. '\n')
end
file:close()
reaper.SetExtState('reaper-source-diagnostic', 'repository', root, false)
local path = root .. '/scripts/diagnose_item_source.py'
local id = reaper.AddRemoveReaScript(true, 0, path, false)
reaper.Main_OnCommand(id, 0)
reaper.AddRemoveReaScript(false, 0, path, false)
reaper.DeleteExtState('reaper-source-diagnostic', 'repository', false)
local after_ok, after = reaper.GetItemStateChunk(item, '', false)
assert(after_ok and before == after, 'Read-only diagnostic detected changed item state')
