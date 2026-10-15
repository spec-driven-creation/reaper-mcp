# Exact note-item timing and GUID deletion validation

Validated and explicitly accepted by the user on 2026-10-15. Tasks WR-007
(extended) and WR-027 (new) are `completed`. No FiruletMap project was modified.

## Automated evidence

- `uv run python -m unittest discover -s tests`: 47 tests passed, including
  12 new note-item contract/failure tests.
- `uv run python -m compileall src`: passed.
- Bridge syntax validation and deployment through
  `powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1`:
  passed. Source and deployed bridge SHA256 hashes match.
- `npx markdownlint-cli2 README.md docs/note-item-validation.md`: passed.

Tests cover the four one-second items at 0, 1.5, 3 and 4.5 seconds; text and
take-less state; previous measure-based and positional Python calls; missing,
mixed, non-finite, negative, zero, boolean, overflowing and unrepresentable times;
invalid track/pointer; overlap and adjacency; partial creation cleanup and
failed read-back; GUID-only deletion, wrong-track/missing GUIDs and neighbors.
The mock Undo checks verify grouping; actual Undo behavior is established below.

## Host evidence

REAPER 7.75/x64 in a separate `-newinst` process with a dedicated `-cfgfile` at
`.local/note-item-validation/reaper.ini`. The temporary configuration disables
project restoration and external VST scanning; the normal configuration and
recording session remain untouched.

The guarded launcher `scripts/validate_note_items_in_reaper.lua` runs its Python
companion only in that isolated resource directory and a new empty project.
It creates a `Notes` track and a selected neighboring MIDI reference on another
track, establishes an initial Undo fixture, and sets a non-default tempo,
cursor position, track selection and time selection.

All 40 host checks passed:

- Four exact one-second items at 0, 1.5, 3 and 4.5 seconds, with C4, C#4, D4
  and D#4 text and no takes.
- Per-operation creation Undo/Redo and measure-based creation/Undo.
- Rejection of invalid/incomplete/mixed timing and occupied ranges without
  item changes or new Undo entries.
- Missing GUID and wrong-track rejection; deletion of only the requested GUID.
- Deletion Undo restores the original GUID and serialized item state.
- Cursor, transport, tempo, time signature, time selection, selected tracks,
  selected surviving items, neighboring items and reference MIDI remain intact.
- Disposable evidence project saved as `.local/note-item-validation/note-items.rpp`.

No work project was opened, edited or saved by this probe. Only processes whose
command line identifies the dedicated temporary configuration were restarted.

## MCP and deployment evidence

MCP Inspector CLI `tools/list` reports 60 tools and confirms the new seconds
fields and required `delete_item` track/GUID fields. Inspector created a text
item at 30.25 seconds for 0.125 seconds and deleted that same GUID successfully.

A fresh SDK stdio session made 24 calls through the actual MCP server and
deployed bridge in the temporary project. It validated seconds and measures,
error cases, deletion, returned project identity and unchanged existing items
and context. The deployed bridge code used port 18765 only inside the isolated
test harness; production source, deployed file and normal MCP configuration
retain port 8765. The working bridge was not stopped or reloaded.

Local reports are under `.local/note-item-validation/`: `host-results.json`,
`mcp-results.json`, `inspector-tools.json`, `inspector-create.json` and
`inspector-delete.json`. They are generated evidence, not committed work data.

Restart the deployed bridge ReaScript in the normal REAPER session to load the
new handler/signature, and reconnect MCP to refresh client tool definitions.
No dependency changes or configuration migration are required.
