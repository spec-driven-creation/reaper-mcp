# REAPER MCP

## Purpose

REAPER MCP exposes the active REAPER project to MCP clients through a small,
explicit runtime chain:

```text
MCP client
-> Python MCP server
-> TCP/JSON bridge
-> REAPER ReaScript
-> REAPER API
```

The external server in `src/reaper_mcp/` defines typed MCP tools and exchanges
JSON with `127.0.0.1:8765`. It never calls REAPER APIs directly. The bridge in
`reaper/mcp_bridge.py` runs inside REAPER, owns every `RPR_*` call, validates
REAPER targets, and reads or mutates the project.

## Requirements

- Python as configured by `.python-version` and `pyproject.toml`.
- [uv](https://docs.astral.sh/uv/) for Python environments and dependencies.
- REAPER with Python/ReaScript support configured.
- Node.js and npm for the MCP Inspector launcher (`npx`).
- Codex is optional contributor tooling, not a runtime dependency.

## Setup

```powershell
git clone https://github.com/arielgrillo/reaper-mcp.git
Set-Location reaper-mcp
uv sync
powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1
```

Configure REAPER to use the Python runtime required by this repository, then
load and run the deployed `mcp_bridge.py` as a ReaScript. The bridge must remain
running while MCP tools are used.

Launch the MCP Inspector from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_mcp_inspector.ps1
```

Inspector remains responsible for starting the configured stdio MCP server.
Launch the backlog visualizer at <http://localhost:8000> with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_backlog_visualizer.ps1
```

## Architecture

### MCP server

`src/reaper_mcp/server.py`:

- exposes MCP tools and typed arguments;
- runs as an external stdio MCP process;
- sends one JSON command per TCP connection to `127.0.0.1:8765`;
- half-closes each completed request and reads the complete bridge response
  with a finite timeout;
- contains no direct `RPR_*` calls.

### REAPER bridge

`reaper/mcp_bridge.py`:

- runs inside REAPER as a deferred Python ReaScript;
- owns all direct `RPR_*` interaction;
- resolves one-based public indexes to REAPER objects;
- implements focused handlers registered in `COMMAND_HANDLERS`;
- validates requests and returns structured JSON results or errors;
- performs both read-only inspection and explicit mutations.

## Contract conventions

- Public track, item, take, FX, parameter, envelope, note, marker, and routing
  indexes are one-based unless a field explicitly says it is a raw REAPER value.
- Useful raw REAPER values remain available alongside readable values: track
  volume raw plus dB, pan raw plus percentage/direction, and FX normalized plus
  formatted values.
- Musical positions come from REAPER time-map APIs, so tempo and time-signature
  changes are respected rather than reconstructed from BPM.
- MIDI note names use the convention where pitch 60 is `C4`, 24 is `C1`, and
  26 is `D1`. A note accepts exactly one of `note_name` or numeric `pitch`.
- Item GUIDs provide stable identity for destructive item operations.
- Mutations validate explicit targets and inputs, read the applied state back,
  and reject invalid values instead of silently clamping them.
- Item creation rejects overlap with any existing item on the target track.
  Adjacent items that only touch at a boundary are allowed.
- Destructive MIDI replacement validates the complete payload before clearing
  any existing MIDI events and keeps a rollback snapshot.

## Tool reference

Requests below show the MCP argument object. Responses are summarized because
most include additional identity and raw/readable fields useful to clients.

<!-- markdownlint-disable MD013 -->

### Project and context

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `ping` | Read-only/local | none | Check that the MCP server process responds; it does not contact REAPER. | String `pong`. | `{}` |
| `get_track_count` | Read-only | none | Count normal project tracks. | Integer track count. | `{}` |
| `get_project_info` | Read-only | none | Inspect active project name, track count, tempo, and transport state. | Project identity and basic state. | `{}` |
| `get_markers_regions` | Read-only | none | Return project markers and regions in timeline order. | `events` with type, index/ID, names, seconds, and musical positions. | `{}` |
| `get_tempo_map` | Read-only | none | Return the effective initial tempo/time signature and exposed changes without inventing defaults. | Timeline-ordered `events` with BPM, signature, linear-change state, and musical position. | `{}` |
| `set_project_tempo` | Mutation | `bpm: float` | Set the effective initial tempo from 1 through 960 BPM while preserving its time signature and later events. | Requested BPM, mutation mode, and verified initial tempo/signature. | `{"bpm": 100.0}` |
| `set_project_time_signature` | Mutation | `numerator: int`, `denominator: int` | Set the effective initial meter; denominator must be a power of two from 1 through 64. When no initial marker exists, REAPER requires inserting one at time zero. | Requested meter, mutation mode, and verified initial tempo/signature. | `{"numerator": 4, "denominator": 4}` |
| `set_tempo_map_event` | Mutation | `measure: int`, `bpm?: float`, `numerator?: int`, `denominator?: int` | Create or update one non-linear tempo-map event at beat 1 of an internal measure. Provide BPM, a complete time signature, or both. The initial measure and linear ramps are rejected. | Created/updated mode plus requested values and verified event state. | `{"measure": 9, "numerator": 7, "denominator": 8}` |
| `create_region` | Mutation | `name: str`, `start_measure: int`, exclusive `end_measure: int` | Create one named region at exact positive one-based measure boundaries. | Assigned region number plus verified seconds and musical boundaries. | `{"name": "COUNTERPOINT EXPLORE", "start_measure": 1, "end_measure": 9}` |
| `rename_region` | Mutation | `region_number: int`, `new_name: str` | Rename one existing project-number-identified region without changing its boundaries, color, or unrelated timeline events. | Previous name plus verified renamed region state. | `{"region_number": 1, "new_name": "Original"}` |
| `get_project_time_selection` | Read-only | none | Inspect the project time selection. | Start, end, duration, active state, and musical positions. | `{}` |
| `get_cursor_position` | Read-only | none | Inspect the edit cursor. | Seconds and REAPER-derived musical position. | `{}` |
| `get_current_context` | Read-only | none | Combine selected tracks, cursor, and time-selection context. | `selected_tracks`, `cursor`, and `time_selection`. | `{}` |
| `get_selected_tracks` | Read-only | none | List currently selected normal tracks. | Count and selected track identities/state. | `{}` |

### Tracks and routing

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `get_tracks` | Read-only | none | Inspect all normal tracks and folder hierarchy. | `tracks` with names, mute/solo, raw+dB volume, pan, channels, and folder ancestry. | `{}` |
| `create_named_track` | Mutation | `name: str`, optional `track_index?: int` | Create exactly one normal named track; append by default or insert at a valid one-based position. | Verified track index, name, and insertion mode. | `{"name": "Bass"}` |
| `rename_track` | Mutation | `track_index: int`, `new_name: str` | Rename one existing index-identified track without changing its other state. | Track index plus previous and verified new names. | `{"track_index": 2, "new_name": "Guitar"}` |
| `create_track_folder` | Mutation | `name: str`, `children: list[str]` | Append exactly one native REAPER folder and one or more ordered, named child tracks. It creates no routing, FX, or recording configuration. | Verified folder and ordered child track states. | `{"name": "gtr_rhy", "children": ["gtr_rhy_l", "gtr_rhy_r"]}` |
| `move_track_into_folder` | Mutation | `track_index: int`, `folder_track_index: int` | Move one existing top-level normal track to the end of an existing top-level folder. Existing children are preserved; nested or folder source tracks are rejected. | Resulting indexes plus verified track and folder hierarchy. | `{"track_index": 5, "folder_track_index": 2}` |
| `get_track_routing` | Read-only | `track_index: int` | Inspect sends, receives, and hardware outputs for one valid track. | Explicit source/destination identities, raw/readable gain and pan, audio/MIDI routing, and mute state. | `{"track_index": 2}` |
| `get_track_channels` | Read-only | none | Inspect channel counts for all normal tracks. | Track identities and channel configuration. | `{}` |
| `get_master_track` | Read-only | none | Inspect master mix and channel state. | Master identity, mute/solo, raw+dB volume, pan, and channels. | `{}` |
| `get_master_fx` | Read-only | none | Inspect the master track FX chain. | Master FX identities, enabled/offline state, and preset metadata where exposed. | `{}` |

### Items and takes

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `get_track_items` | Read-only | `track_index: int` | Return only items belonging to one valid track. | `items` with one-based indexes, GUIDs, seconds, measures/beats, and state flags. | `{"track_index": 9}` |
| `get_item_info` | Read-only | `track_index: int`, `item_index: int` | Inspect one item by its current one-based index on a track. | Item identity, timing, musical boundaries, state, notes, and take details. | `{"track_index": 9, "item_index": 1}` |
| `get_item_takes` | Read-only | `track_index: int`, `item_index: int` | List takes belonging to one item. | Take count, active state, MIDI/source information, and take names. | `{"track_index": 9, "item_index": 1}` |

### MIDI

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `get_midi_summary` | Read-only | `track_index: int`, `item_index: int`, `take_index: int` | Count MIDI event classes for a validated MIDI take. | Note, control-change, and text/sysex counts. | `{"track_index": 9, "item_index": 1, "take_index": 1}` |
| `get_midi_notes` | Read-only | `track_index: int`, `item_index: int`, `take_index: int` | Read all notes from one MIDI take. | Notes with pitch/name, channel, velocity, selection/mute, PPQ, seconds, duration, and musical positions. | `{"track_index": 9, "item_index": 1, "take_index": 1}` |

### Envelopes

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `get_track_envelopes` | Read-only | `track_index: int` | List only envelopes belonging to one valid track. | Envelope identity, name, visibility/arming, point count, and raw scaling mode. | `{"track_index": 2}` |
| `get_envelope_points` | Read-only | `track_index: int`, `envelope_index: int` | Inspect points in one track envelope. | Raw time/value/shape plus musical position and REAPER-formatted value. | `{"track_index": 2, "envelope_index": 1}` |

### FX

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `get_track_fx` | Read-only | none | Inspect FX chains for all normal tracks. | Per-track FX identities, indexes, enabled/offline state, and preset metadata. | `{}` |
| `ensure_track_fx` | Mutation | `track_index: int`, `fx_name: str`, `position?: int` | Ensure an exact REAPER-recognizable VST, VST3, or VSTi name exists on a normal, child, or folder track. `position` is zero-based; omitted means preserve an existing match or append a missing FX. | Track/FX identity, one-based final FX index, zero-based position, and `preserved`, `moved`, or `inserted` action after chain read-back. | `{"track_index": 2, "fx_name": "VST: GTune (GVST)", "position": 0}` |
| `get_take_fx` | Read-only | `track_index: int`, `item_index: int`, `take_index: int` | Inspect the FX chain of one validated take. | Take identity and FX metadata. | `{"track_index": 2, "item_index": 1, "take_index": 1}` |
| `get_fx_parameters` | Read-only | `track_index: int`, `fx_index: int` | List parameters for one track FX. | Parameter indexes/names, normalized values, formatted values, and steps where exposed. | `{"track_index": 2, "fx_index": 1}` |
| `get_fx_parameter` | Read-only | `track_index: int`, `fx_index: int`, `parameter_index: int` | Read one parameter from one track FX. | Track/FX/parameter identity, normalized value, formatted value, and range metadata. | `{"track_index": 2, "fx_index": 1, "parameter_index": 3}` |
| `get_fx_presets` | Read-only | `track_index: int`, `fx_index: int` | Inspect current preset metadata without selecting a preset. | Current preset name when exposed and total preset count. | `{"track_index": 2, "fx_index": 1}` |
| `diagnose_fx_parameter_formatter` | Read-only | `track_index: int`, `fx_index: int`, `parameter_index: int` | Sample REAPER's formatter across normalized values for diagnosis. | Parameter identity and formatter samples. | `{"track_index": 2, "fx_index": 1, "parameter_index": 3}` |
| `set_fx_parameter` | Mutation | `track_index: int`, `fx_index: int`, `parameter_index: int`, exactly one of `normalized_value?: float` or `formatted_value?: str` | Set a normalized value directly or invert a supported readable value through REAPER's formatter. | Requested mode/value and read-back normalized/formatted applied value. | `{"track_index": 2, "fx_index": 1, "parameter_index": 3, "formatted_value": "-2 dB"}` |
| `set_fx_parameter_formatted` | Mutation | `track_index: int`, `fx_index: int`, `parameter_index: int`, `formatted_value: str` | Convenience typed entry point for the formatted mode above. | Same verified result as `set_fx_parameter`. | `{"track_index": 2, "fx_index": 1, "parameter_index": 3, "formatted_value": "1200 Hz"}` |
| `set_fx_enabled` | Mutation | `track_index: int`, `fx_index: int`, `enabled: bool` | Enable or bypass one valid track FX. | Requested and read-back enabled state with FX identity. | `{"track_index": 2, "fx_index": 1, "enabled": false}` |

### Track and item mutations

| Tool | Mode | Input | Purpose and constraints | Response summary | Example request |
| --- | --- | --- | --- | --- | --- |
| `set_track_volume` | Mutation | `track_index: int`, exactly one of `volume_raw?: float` or `volume_db?: float` | Set validated track gain without silently clamping. | Requested mode plus applied raw and dB values. | `{"track_index": 2, "volume_db": -6.0}` |
| `set_track_pan` | Mutation | `track_index: int`, exactly one of `pan_raw?: float` or signed `pan_percent?: float` | Set validated pan without silently clamping. | Applied raw pan, percentage, and direction. | `{"track_index": 2, "pan_percent": -25.0}` |
| `set_track_mute` | Mutation | `track_index: int`, `muted: bool` | Set mute on one validated track. | Requested and applied mute state. | `{"track_index": 2, "muted": true}` |
| `set_track_record_arm` | Mutation | `track_index: int`, `armed: bool` | Arm or disarm one validated track for recording without changing its input, monitoring, or other tracks. | Requested and applied record-arm state. | `{"track_index": 10, "armed": true}` |
| `set_track_solo` | Mutation | `track_index: int`, `solo: bool` | Set normal solo state on one validated track. | Requested and applied solo state. | `{"track_index": 2, "solo": true}` |
| `create_note_item` | Mutation | `track_index: int`, `start_measure: int`, `duration_measures: int`, `text: str` | Create an empty item with `P_NOTES`, no take/source, exact measure boundaries, and no overlap. | New item GUID/index, text, requested measures, seconds, and verified success. | `{"track_index": 9, "start_measure": 3, "duration_measures": 2, "text": "Am7"}` |
| `set_item_end_measure` | Mutation | `track_index: int`, `item_guid: str`, exclusive `end_measure: int` | Resize one item to an exact measure boundary without moving its start; reject overlap with other items. | Previous and applied item state plus verified success. | `{"track_index": 2, "item_guid": "{ITEM-GUID}", "end_measure": 47}` |
| `create_click_source_item` | Mutation | `track_index: int`, `start_measure: int`, exclusive `end_measure: int` | Create a non-overlapping native REAPER `CLICK` source item at exact measure boundaries. | Item/take identity, source type, applied boundaries, and verified success. | `{"track_index": 2, "start_measure": 41, "end_measure": 47}` |
| `create_midi_item` | Mutation | `track_index: int`, `start_measure: int`, exclusive `end_measure: int`, `notes: list[object]` | Create a non-overlapping MIDI item after validating every note through the same legacy-or-bar/beat/offset contract used by replacement. | New item/take identity, boundaries, created note read-back, and success. | `{"track_index": 9, "start_measure": 3, "end_measure": 5, "notes": [{"pitch": 60, "bar": 1, "beat": 1, "offset": 0, "duration_beats": 1, "velocity": 100}]}` |
| `replace_midi_item_content` | Mutation | `track_index: int`, `item_guid: str`, `notes: list[object]` | Bulk-replace every MIDI event using either the legacy note shape or bar/beat/offset positions; validate first and roll back after unexpected post-clear failure. Empty `notes` intentionally clears the take. | Stable item/take identity, previous counts, normalized replacement notes, boundaries, and verified success. | `{"track_index": 9, "item_guid": "{ITEM-GUID}", "notes": []}` |
| `replace_drum_item_content` | Mutation | `track_index: int`, `item_guid: str`, `mapping_id: str`, `events: list[object]` | Resolve explicitly selected Krimh drum semantics, then delegate one numeric-pitch bulk replacement to `replace_midi_item_content`. | Generic MIDI read-back plus mapping identity and semantic resolution metadata. | `{"track_index": 1, "item_guid": "{ITEM-GUID}", "mapping_id": "krimh-drums", "events": [{"bar": 1, "beat": 1, "offset": 0, "duration_beats": 0.25, "drum": "kick", "articulation": "main", "velocity": 105}]}` |

<!-- markdownlint-enable MD013 -->

## MIDI contracts

### Create a MIDI item

The item uses absolute, one-based project measures. `end_measure` is exclusive.
Every note uses a one-based measure relative to the beginning of that item.
Creation and replacement both accept the current `bar`, `beat`, `offset`, and
`duration_beats` shape documented below, or the legacy shape shown here:

```json
{
  "track_index": 9,
  "start_measure": 3,
  "end_measure": 5,
  "notes": [
    {
      "note_name": "C4",
      "start_measure": 1,
      "start_beat": 1.0,
      "duration_qn": 1.0,
      "velocity": 100
    }
  ]
}
```

Use exactly one of `note_name` or `pitch` in each note. `duration_qn` is in
quarter-note units. Notes sharing a start position form a chord; gaps and
overlaps are allowed. REAPER time-map and MIDI PPQ conversion remain internal.

### Create a text note item

`create_note_item` creates an empty MediaItem with text stored in `P_NOTES`.
It creates no audio/MIDI take and rejects blank text or an occupied time range.

### Resize and create click-source items

`set_item_end_measure` keeps the item's existing start position and changes only
its length so its end lands at the requested exclusive project measure. Both it
and `create_click_source_item` reject overlap with another item on the target
track. Click creation produces one take backed by REAPER's native `CLICK` PCM
source and verifies its source type and boundaries after creation.

### Replace MIDI content

`replace_midi_item_content` targets an existing active MIDI take by one-based
track plus exact item GUID and uses the same relative note shape. It validates
the entire payload before clearing notes, CC/pitch/program/pressure events, and
text/sysex. `notes: []` is an explicit clear operation that leaves the item in
place. The item GUID, position, length, mute, and lock state are verified after
replacement.

For bulk musical input, each note may instead use `bar`, `beat`, `offset`, and
`duration_beats`. `bar` is one-based and relative to the item; `offset` is a
non-negative fractional displacement added to the one-based `beat`.
`duration_beats` uses the effective local time-signature denominator, so one
beat is one quarter note in 4/4 and one eighth note in 6/8. Do not mix this shape
with `start_measure`, `start_beat`, or `duration_qn` in the same note. Responses
normalize positions to `start_measure`, `start_beat`, and `duration_qn`.

```json
{
  "track_index": 1,
  "item_guid": "{ITEM-GUID}",
  "notes": [
    {
      "bar": 1,
      "beat": 1,
      "offset": 0.5,
      "duration_beats": 0.25,
      "pitch": 42,
      "velocity": 90
    }
  ]
}
```

### Resolve Krimh drum semantics

`replace_drum_item_content` is the narrow drum-generation layer above the
generic MIDI bridge. It requires the explicit mapping id `krimh-drums`; Kontakt
FX and preset metadata are not treated as proof that Krimh Drums is loaded.
Each event combines `drum` and `articulation`, such as `kick` + `main` or
`crash.1` + `left-hit`, before passing only the resolved numeric pitch and
musical timing fields to `replace_midi_item_content`.

The verified declarative mapping is stored in
`src/reaper_mcp/mappings/krimh-drums.json`. Primary `note` values are Krimh
`Note 1`. Where Krimh also supplies `Note 2`, it remains available in
`alternate_notes`; the resolver uses `Note 1` by default. Unknown mappings,
unknown articulations, and invalid mapping data are explicit errors. There is
no General MIDI fallback or Kontakt-based automatic detection.

## End-to-end examples

The examples show a possible MCP client workflow; indexes and GUIDs come from
earlier responses.

1. Inspect the project with `get_project_info` using `{}`, then list tracks with
   `get_tracks` using `{}`.
2. Inspect FX with `get_track_fx`, then call `get_fx_parameter` with
   `{"track_index": 2, "fx_index": 1, "parameter_index": 3}`.
3. Apply a readable value with `set_fx_parameter_formatted` and
   `{"track_index": 2, "fx_index": 1, "parameter_index": 3,
   "formatted_value": "-2 dB"}`.
4. Create a two-measure text item with
   `{"track_index": 9, "start_measure": 3, "duration_measures": 2,
   "text": "Am7"}`.
5. Create a chord by sending C4, E4, and G4 notes with the same relative
   `start_measure` and `start_beat` to `create_midi_item`.
6. Take the returned `item_guid` and send a complete new note list to
   `replace_midi_item_content`; old MIDI events are not merged or appended.

## Safety and mutation behavior

- All mutations resolve and validate their explicit track/FX/item targets.
- `ensure_track_fx` compares exact FX display names, prevents duplicates on
  repeated calls, and uses REAPER's native chain move when an existing match is
  requested at a different position. Missing plugins fail without fallback;
  VSTi insertion does not create output tracks, routing, sends, or presets.
- Values are checked before mutation and read back before success is reported.
- Inputs outside supported ranges are errors rather than silently clamped.
- Initial tempo and meter writes preserve later tempo-map events. Setting meter
  inserts a time-zero marker only when the project has no initial marker,
  because REAPER stores an explicit time-signature change in a tempo marker.
- Internal tempo-map writes create or update only the event at the requested
  measure start and preserve omitted tempo or meter state. They do not expose
  a beat parameter or support gradual/linear tempo changes.
- Region boundaries are one-based project measures and `end_measure` is
  exclusive. Track creation appends unless a valid insertion index is supplied.
- New note and MIDI items reject overlap; boundary-touching items are valid.
- Failed MIDI-item creation cleans up a partially created item.
- MIDI replacement is explicitly destructive, validates before clearing, and
  restores a captured item chunk when an unexpected post-clear failure occurs.
- Creation and replacement are separate operations; there is no hidden
  create-or-update behavior.

## Development workflow

- Read `AGENTS.md` before contributing; it defines architecture, validation,
  deployment, Git, backlog, and README-maintenance rules.
- Deploy bridge changes with
  `powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1`.
- Launch Inspector with `scripts/start_mcp_inspector.ps1` and the backlog UI
  with `scripts/start_backlog_visualizer.ps1`.
- The repository-local capability workflow is in
  `.codex/skills/add-reaper-mcp-capability/SKILL.md`.
- Validate external code with `uv run python -m compileall src`; bridge changes
  also require deployment and runtime testing in REAPER.

## Backlog

`tasks/backlog.json` tracks planned, testing, and explicitly accepted work. The
visualizer reads it directly. The implementation remains the source of truth
for runtime behavior; the README does not duplicate the full backlog.

## Known limitations

- Formatted FX parameter writes use deterministic inversion of REAPER's
  formatter. They support continuous displays with one numeric value and unit;
  textual choices or displays containing multiple numbers may require a direct
  normalized value.
- Preset inspection exposes the current preset name and total count where
  REAPER provides them; it does not enumerate every preset name.
- The TCP bridge is local, single-request, and tied to the active REAPER project;
  the ReaScript must be running for all REAPER-backed tools.
