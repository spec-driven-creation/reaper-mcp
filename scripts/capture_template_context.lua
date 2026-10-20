-- Read-only capture of the explicitly requested session for isolated validation.
local _, path = reaper.get_action_context()
local root = path:match('^(.*)[/\\]scripts[/\\][^/\\]+$')
local project, name = reaper.EnumProjects(-1, '')
assert(name:match('session 2 %- clips.rpp$'), 'Wrong project')
assert(reaper.GetPlayStateEx(project) == 0, 'Project must be stopped')
local dir = root .. '/.local/template-validation/'
reaper.RecursiveCreateDirectory(dir, 0)
local manifest = assert(io.open(dir .. 'manifest.txt', 'w'))
for i = 0, reaper.CountTracks(project)-1 do
  local track = reaper.GetTrack(project, i)
  local _, label = reaper.GetTrackName(track)
  manifest:write((i+1) .. '\t' .. reaper.GetTrackGUID(track) .. '\t' .. label .. '\n')
  if i < 8 then
    local ok, chunk = reaper.GetTrackStateChunk(track, '', false)
    assert(ok)
    local file = assert(io.open(dir .. 'track-' .. (i+1) .. '.txt', 'w'))
    file:write(chunk); file:close()
  end
end
manifest:close()
