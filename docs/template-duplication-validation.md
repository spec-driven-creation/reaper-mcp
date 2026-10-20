# FX copy and template duplication — 2026-10-20

## Cause and correction

BUG-019 reproduced with the actual FM-009 guitar, FM-010 guitar and FM-010 MIDI
chains captured read-only from `session 2 - clips.rpp`. The previous comparator
rejected a removed `WNDRECT` record in each chain. Native `TrackFX_CopyToTrack`
omits this FX-chain window rectangle. No additional serialized musical-state
difference was observed after existing instance/window normalization.

`comparable_fx_chunk` now recognizes only the four-integer `WNDRECT` record at
FXCHAIN depth one. Identical text inside plugin payloads and unknown records
remain significant. Opaque state, preset records, bypass/offline, wet, pins and
order remain verified. Existing narrowly gated VST2 program-label handling stays
in place; it still requires an identical native plugin chunk and musical API
state. Automation/link exclusions remain unchanged for FX copying.

Mismatch diagnostics return normalized source/destination line locations, range
lengths and SHA256 hashes, bounded to 16 ranges. They never return changed text,
binary state or media paths. Failed copies independently verify source state
after verifying destination rollback. MCP wrappers raise `ToolError` with the
structured bridge diagnostics, producing `isError: true`.

## Duplication contract

The complete signature and policies are documented in README's
“Duplicate a track or complete folder” section. `duplicate_tracks` identifies
the source and optional insertion anchor by GUID. Descendant renames are explicit
source-GUID/name mappings. It uses native action 40062, followed by API operations
on the newly created tracks, rather than chunk replacement or FX reconstruction.

Default policies exclude items, record arm and solo. Audio files remain shared
when items are included. Internal routing must remap to the corresponding copies;
external sends/receives and hardware outputs are removed. The source main-send
setting is retained, feeding the copied folder parent or the master at top level.
Copies are inserted as a contiguous top-level block before the anchor, or appended.

New track, normal/input FX, media-item, take and take-FX GUIDs are checked against
all existing objects and against each other. Complete residual track state and
normal/input FX state are compared, with targeted identity/name/policy filtering.
Recording input warnings distinguish requested and effective raw values from
current device availability. All original track snapshots are verified, resolving
receive indices to GUIDs so insertion cannot disguise routing changes.

Native duplication of a folder-closing normal track transfers the closing flag
to its copy. The handler restores the original folder depth and makes the copy
standalone. The same targeted restoration runs during rollback. Rollback deletes
only newly created tracks, verifies original snapshots and reports deletion errors;
it does not invoke global Undo or overwrite original state chunks. Successful
operations have one native Undo block and restore the original track selection.

REAPER 7.75's Python wrapper returns routing pointers as numeric addresses, which
must be resolved against known project track pointers before calling another RPR
function. `P_DESTTRACK` and `RemoveTrackSend` with category zero include hardware
outputs before sends in the observed host. The handler accounts for that offset;
normal send counts/settings remain category-local. Host tests include an actual
internal connection and a hardware output, preventing an empty-routing false pass.

Native API references: [REAPER ReaScript API](https://www.reaper.fm/sdk/reascript/reascripthelp.html),
including `TrackFX_CopyToTrack`, `ReorderSelectedTracks`, `CreateTrackSend`,
`GetTrackSendInfo_Value`, `RemoveTrackSend` and the Undo functions.

## Validation performed

An API-only read-only capture copied the first eight source track states to the
ignored `.local/template-validation` directory. A separate REAPER 7.75 process
used its own configuration in that directory, with project restoration disabled.
Both probe scripts reject the normal work-session resource path before mutation.
No computer automation, playback, recording, original-preset writes or project
saves were performed.

The final isolated host run passed 25 checks:

- Three actual FX chains copied to empty tracks with serialized read-back.
- Each copied chain also matched the original live serialized snapshot.
- Independent preset, parameter, bypass/offline, IO and two-bank pin API checks.
- Injected partial-copy and real bypass-mismatch failures on all three chains:
  rollback and source preservation passed; mismatch diagnostics were populated.
- A folder with nested descendants, explicit renames, native input FX, colors,
  recording inputs and a real internal send; external receives/sends and hardware
  outputs were excluded, and the internal send was preserved and remapped.
- Item exclusion, unarmed/unsoloed defaults, unavailable input `999` warning with
  requested/effective values, and native input FX preservation.
- A folder-closing normal track inserted before a top-level anchor with an audio
  item referencing the same WAV file; native Undo removed exactly its copy.
- An injected rename failure removed only operation-created tracks and restored
  source state, including the original closing-folder flag.

Additional checks:

- `uv run python -m unittest discover -s tests`: 60 tests passed.
- `uv run python -m compileall src`: passed.
- Bridge deployment script: syntax validation and deployment passed. Copy errors
  now terminate the deployment script rather than reporting misleading success.
- `npx markdownlint-cli2 README.md docs/template-duplication-validation.md`: passed.
- MCP Inspector over stdio listed `duplicate_tracks` with the typed GUID contract.
  An invalid copy request returned `isError: true` with the bridge error details.
- Final read-only work-session audit: 52 tracks; the first eight track chunks
  matched their original captures; FM-011 through FM-021 guitar inputs remained
  raw `1` (Mic 2). No existing FM folders were created or removed.

Local evidence includes `diagnosis.json`, `validation.json`, `mcp-tools.json`,
`mcp-error.json`, `manifest.txt` and `work-preservation.tsv`. Opaque captured
chunks and WAV fixtures stay local and are not committed.

## Limits and activation

Snapshots are limited to the stock Python wrapper's safe 4 MiB buffer. Folder
sources must form a balanced complete subtree. Insertion is at top-level
boundaries. FX parameter automation/modulation and links remain rejected before
mutation, including template input FX. Track automation is retained by native
duplication. Unknown serialization changes fail closed with rollback; a freshly
inserted input ReaEQ was conservatively rejected, while a native JS input FX
passed full preservation checks. There was no audio audition or render.

Source/deployed bridge hashes match, and the new MCP server advertises the tool.
The already-running work-session bridge still needs a restart to load the new
handler; it returned `Unknown command: duplicate_tracks` in the activation check.
REAPER's running Python scripts use separate contexts, so a finite ReaScript
cannot replace another script's globals. The registered bridge action was invoked
through the API, but the old listener remained active. The user was asked whether
REAPER displayed its task-control termination dialog; interface automation was
not used. Reconnect the MCP client after restarting the bridge to refresh tools.

WR-023 and WR-028 remain `testing`, pending explicit user acceptance.
