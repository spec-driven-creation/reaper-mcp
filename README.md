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

## Audio item edge editing

`set_item_edges(item_guid, start_seconds, end_seconds, track_guid=None,
track_index=None, fade_in_seconds=None, fade_out_seconds=None)` changes absolute
project boundaries of one GUID-identified audio item. Supply a track GUID or a
one-based track index; supplying both also checks that they identify the same
track. The item GUID must be unique across the active project and belong to that
track. The active project must be stopped. This tool uses REAPER APIs only.

```json
{
  "item_guid": "{ITEM-GUID}",
  "track_guid": "{TRACK-GUID}",
  "start_seconds": 12.5,
  "end_seconds": 18.25
}
```

For constant take rate `r`, the bridge writes `D_POSITION = start_seconds`,
`D_LENGTH = end_seconds - start_seconds`, and
`D_STARTOFFS = old_offset + (start_seconds - old_position) * r`. It preserves
the project time of existing source samples, rather than moving/slipping,
quantizing, stretching or changing their pitch or rate. Independent native audio
accessor comparisons validated this mapping at take rates 1 and 1.5.

The first version supports a single take with a plain file-backed WAV source.
It rejects MIDI, multiple/absent takes, parent/section/reversed sources, stretch
markers, take envelopes (including rate-related automation), take FX, automatic
stretching, project playrate automation and unrecognized master envelopes.
Missing/unavailable sources, locked items, invalid/nonfinite numbers, negative
starts or offsets, nonpositive lengths and source overruns fail before mutation.
Both the old and requested read intervals must fit entirely within the source.
The existing `B_LOOPSRC` flag is preserved, with a warning when enabled; an
extension never wraps/repeats audio. Values are never clamped to source bounds.

Source diagnostics distinguish the disk file from REAPER's in-memory source.
`before`/`after` include `source_pointer_valid`, `source_length_is_qn`,
`source_sample_rate`, `source_channels`, `source_has_parent`, `source_online`,
`source_file_exists` and `source_file_readable`. Length is read from REAPER in
seconds; the Python binding returns `(length, source, lengthIsQNOut)`. No WAV
header duration is substituted when REAPER returns zero or unavailable metadata.

When installed, SWS's read-only `CF_GetMediaSourceOnline` supplies the native
`source_online` boolean. SWS is optional: without it the value is `null`, and
unusable native metadata is reported as `source_offline_or_unavailable` rather
than guessing offline state. Other preflight `error_code` values include
`invalid_source_pointer`, `source_file_unavailable`, `source_offline`,
`source_metadata_unavailable` (online but unusable metadata), and
`source_length_not_seconds`. These failures occur before Undo or item writes.
The bridge never brings sources online, changes availability preferences or
replaces source objects to make an edit succeed. If the file is readable but
REAPER reports it offline, bring it online in REAPER before retrying. Check
Preferences > Media > Set media items offline when application is not active;
this preference can prevent background MCP edits. It is not changed by the tool.

Omitted manual fades and existing automatic fades are preserved exactly. New
manual fades must be finite, nonnegative and no longer than the new item. An
explicit fade is rejected if that edge has a positive automatic fade. Resizing
also rejects a range too short to preserve existing fade lengths. Fade shape,
curvature and automatic lengths are verified; durations alone do not establish
whether a fade affects an attack. No audio attack detection is performed.

One call creates one Undo step named `Set audio item edges preserving sample
timing`. The bridge captures the complete item chunk before writing and verifies
identity, source, boundaries, offset, preserved properties and the serialized
remainder. It checks the source/time mapping at three points of the retained
interval and its linear intercept (also when the old/new ranges do not overlap).
Numeric read-back tolerance is 1 nanosecond, with no requested-value adjustment.
Other items/tracks, FX, recording inputs, MIDI and tempo are never written.

The response includes `before`, `after` (raw REAPER attribute names plus source
and take identity), `start_delta_seconds`, `end_delta_seconds`,
`source_offset_delta_seconds`, `verification`, `warnings` and `rollback`.
On write/verification failure the synchronous handler restores its written
fields; if necessary it restores only the target item snapshot, verifies complete
restoration and reports `rollback.attempted`/`rollback.verified`. It refuses to
restore over a changed target identity. An unrecoverable native restoration
failure is reported explicitly, never described as successful rollback.
Failures propagate through MCP with `isError: true`, including rollback details.

See [isolated host and protocol validation](docs/item-edges-validation.md).

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

### Preparing recording tracks

The tools below operate on normal tracks in the active project. Track indexes
are one-based. An optional `track_guid` guards against a stale destination index;
copy operations also accept `source_track_guid`. Read tools return the current
GUID. Mutations validate pointers and identities, create an undo step, and verify
the applied state. They do not arm recording.

<!-- markdownlint-disable MD013 -->

| Tool | Arguments | Result |
| --- | --- | --- |
| `get_track_color` | `track_index`, optional `track_guid` | `color_raw`, `custom`, `rgb` |
| `set_track_color` | `track_index`, exactly one of `color_raw` or `source_track_index`, optional GUIDs | Requested/applied raw value and readable color |
| `copy_track_fx_chain` | `source_track_index`, destination `track_index`, optional GUIDs | Verified count, channel count and identities |
| `get_track_record_input` | `track_index`, optional `track_guid` | `record_input_raw`, `kind`, `name`, `available` |
| `set_track_record_input` | `track_index`, exactly one of `record_input_raw` or `source_track_index`, optional GUIDs | Requested/applied value and current device name |
| `get_track_record_monitoring` | `track_index`, optional `track_guid` | `record_monitoring_raw`, `mode` |
| `set_track_record_monitoring` | `track_index`, `mode`, optional `track_guid` | Verified raw and readable mode |
| `save_project` | none | `project_id`, `project_path`, `dirty`, `success` |

<!-- markdownlint-enable MD013 -->

Native colors without REAPER's `0x1000000` flag use the theme default
(`custom: false`, `rgb: null`), including raw `0` and stored RGB values such as
`16576`. The setter preserves the raw integer and custom flag exactly; it never
adds the flag. Valid raw colors range from `0` to `0x1ffffff`. Copy from a source
to preserve default behavior, custom black, or an exact custom native color.

FX copying uses `TrackFX_CopyToTrack` with full serialized state verification,
including opaque
plugin state, presets, order, bypass, offline, wet/dry and pin mappings. It also
copies `I_NCHAN` so those mappings retain their channel context. Input FX are not
copied. The destination must have neither normal nor input FX. New FX instance
GUIDs are generated. Source FX parameter automation/modulation and external
parameter links are rejected before mutation. Items, MIDI, automation, sends and
other destination properties are preserved. Full FX state and non-FX destination
state are compared after writing; a failed write or mismatch restores and checks
the original destination snapshot (`rollback_succeeded` in errors). The source
is never written. Only chain-level FX instance GUIDs and recognized window or
selection records (`FLOAT`, `FLOATPOS`, `WNDRECT`, `SHOW`, `LASTSEL`) are
excluded from
comparisons. Matching text inside opaque plugin state remains byte-exact;
unknown records and plugin-state whitespace remain significant. REAPER can
update the source FX window selection.

One observed VST2 wrapper normalization is allowed: an empty six-byte program
label trailer becoming a populated UTF-8 label, with its remaining flag bytes
unchanged. This is accepted only when every other serialized field matches and
REAPER's native `vst_chunk`, preset API state, normalized parameters, bypass,
offline, wet value, I/O sizes and pin mappings (both 64-channel banks) match
exactly. Named labels changing, VST3 trailers, unavailable native chunks or any
other difference still fail and trigger rollback. Successful responses include
one-based `normalized_vst_program_labels` indices (usually an empty array).

A conservative mismatch can reject plugins that reserialize their state
differently, including newly inserted bx_tuner/ReaSynth instances whose unnamed
initial preset gains a name on copy. The host probe uses explicit factory
presets. A mismatch leaves the source unchanged and rolls back the destination;
it does not silently normalize the source. Track snapshots are limited to 4 MiB;
larger or unavailable chunks are rejected before writing. This is not an
audio-equivalence or plugin-license check.

Recording input values preserve REAPER's raw encoding: `-1` is no input; mono
inputs start at `0`; stereo pairs start at `1024` (first pair). Audio channels
must exist on the current device. Read or copy a source input to avoid guessing.
MIDI inputs are also supported when available; virtual keyboard and all-input
selectors retain their raw encoding. Multichannel and ReaRoute/loopback inputs
are not supported by this setter. Monitoring modes are `off` (0), `on` (1), and
`auto` (2, REAPER's tape-style monitoring, disabled during playback).

`save_project` saves only an active project with an existing filename.
An unnamed project returns an error without opening Save As. Success requires
the same project/path and no pending modifications after saving;
saving has no undo step.

Example sequence: source guitar 2, source MIDI 3, destination guitar 5 and
MIDI 6.

```text
get_track_color(track_index=2)
set_track_color(track_index=5, source_track_index=2)
copy_track_fx_chain(source_track_index=2, track_index=5)
get_track_record_input(track_index=2)
set_track_record_input(track_index=5, source_track_index=2)
get_track_record_monitoring(track_index=2)
set_track_record_monitoring(track_index=5, mode="auto")
set_track_color(track_index=6, source_track_index=3)
copy_track_fx_chain(source_track_index=3, track_index=6)
set_track_record_input(track_index=6, source_track_index=3)
set_track_record_monitoring(track_index=6, mode="off")
save_project()
```

Use the mode actually read from the source. A bypassed amplifier stays bypassed;
enabling it requires the separate explicit tool
`set_fx_enabled(track_index=5, fx_index=2, enabled=true)`.

For a finite host acceptance probe, run
`scripts/validate_recording_setup_in_reaper.lua` as a ReaScript. It loads the
Python probe, creates a disposable project tab with bx_tuner, Ampknob Trivium
Rhythm, ReaSynth and existing MIDI, and restores the original active tab. Results
and the disposable saved project go under `.local/recording-validation/`.
Automated mock tests are separate: `uv run python -m unittest discover -s tests`.

### MCP connection diagnosis

A TCP response on port 8765 proves only that the bridge is running. The MCP client
must also start the external stdio server successfully. For Codex, the configured
server's `cwd` must point to this checkout and its command must launch
`uv run python -m reaper_mcp.server`. A stale checkout path can prevent all tools
from appearing even while TCP works. Reconnect the MCP client after correcting
its server configuration or after changing tool definitions. Restart the bridge
ReaScript after deploying bridge changes; deployment does not reload running code.

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
| `create_note_item` | Mutation | `track_index: int`, non-blank `text: str`, exactly one complete pair: `start_measure: int` + `duration_measures: int` OR `start_seconds: float` + `duration_seconds: float` | Create an empty item with `P_NOTES`, no take/source, verified exact timing and no overlap; one Undo step. | Project/track identity, item GUID/index, text, applied start/duration/end seconds, timing mode, requested measures and success. | `{"track_index": 9, "start_seconds": 1.5, "duration_seconds": 1.0, "text": "C4"}` |
| `delete_item` | Mutation | `track_index: int`, `item_guid: str` | Delete only the GUID-identified item belonging to the explicit track; one Undo step. Reject missing or wrong-track GUIDs before mutation. | Project/track identity, `item_guid`, `deleted_item_guid`, verified success. | `{"track_index": 9, "item_guid": "{ITEM-GUID}"}` |
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

### Create and delete text note items

`create_note_item` creates an empty MediaItem with text stored in `P_NOTES`.
It creates no audio/MIDI take and rejects blank text or an occupied time range.
Text is preserved exactly, including whitespace around non-blank content; NUL
characters are rejected. Provide exactly one complete timing pair:

- `start_measure` (one-based positive integer) and `duration_measures` (positive
  integer). Both boundaries come from the project's actual tempo map. Existing
  named calls and Python positional calls `(track_index, start_measure,
  duration_measures, text)` remain compatible.
  The exclusive end measure must fit REAPER's integer range (<= 2147483647).
- `start_seconds` (finite number >= 0) and `duration_seconds` (finite number > 0).
  These are absolute project seconds, without beat/measure quantization. Their
  sum must be finite and represent an end strictly after the start.

Null timing fields are treated as absent. Incomplete pairs, mixed modes,
booleans, invalid numbers and overlap are rejected before creating an item.
Adjacent ranges that only touch are allowed. If creation or read-back fails,
the bridge removes the partially created item and reports `rollback_succeeded`.

For example, these calls create four one-second text items, including attacks
between beats:

```text
create_note_item(track_index=9, text="C4", start_seconds=0, duration_seconds=1)
create_note_item(track_index=9, text="C#4", start_seconds=1.5, duration_seconds=1)
create_note_item(track_index=9, text="D4", start_seconds=3, duration_seconds=1)
create_note_item(track_index=9, text="D#4", start_seconds=4.5, duration_seconds=1)
```

To label a MIDI note on an existing `Notes` track, use that note's
`position_seconds`, `duration_seconds` and `note_name` from `get_midi_notes`.
Read and explicitly identify the destination track first. The creation tool
does not create tracks or derive note timing itself. Simultaneous or overlapping
MIDI notes require separate destination tracks or a combined label, because
text-item overlap is intentionally rejected.

`create_note_item` returns applied `start_seconds` (also available as the
backward-compatible `position_seconds`), `duration_seconds`, `end_seconds`,
`text`, `take_count: 0`, `item_guid`, and a diagnostic `item_index`. It also
returns `timing_mode` plus the requested measure fields (null for seconds mode).
Timing read-back uses an absolute tolerance of 1e-9 seconds, without rounding
the applied values returned to the caller.

`delete_item(track_index=9, item_guid="{GUID-FROM-CREATION}")` resolves the item
only by GUID within the active project. It accepts any media-item type, including
empty, MIDI and audio items. It never uses selection or an item index. Missing
GUIDs return `item_guid_not_found`; a GUID on another track returns
`item_track_mismatch` with the actual track index. Success requires both native
deletion and verification that the GUID disappeared and the track count dropped
by exactly one. A failed deletion/read-back returns an error, not success.

Both tools return `project_id` (session-local REAPER project handle),
`project_path` (empty for an unnamed project), `project_name`, `track_index`,
`track_name` and the stable `track_guid`. Deletion also returns
`deleted_item_guid`. Both operate on the active project, update the arrangement
and create an individual item-only Undo step. They do not change cursor,
transport, tempo, track selection, neighboring items or their selection.
Deleting a selected target necessarily removes that item from the selection.

Run `scripts/validate_note_items_in_reaper.lua` only in a new isolated REAPER
instance whose `-cfgfile` is `.local/note-item-validation/reaper.ini`. Its guarded
Python probe refuses a work session, checks real Undo/Redo and context/item
preservation, and writes its report and temporary project in that directory.
After deployment, restart the bridge ReaScript to load its new handlers and
reconnect the MCP client to refresh the changed/new tool definitions.

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

### Duplicate a track or complete folder

`duplicate_tracks(source_track_guid, new_name, include_descendants=False,
include_items=False, descendant_names=None, insert_before_track_guid=None,
preserve_record_arm=False, preserve_solo=False)` uses REAPER's native
**Track: Duplicate tracks** action, preserving opaque plugin state rather than
rebuilding tracks or replacing GUID text in chunks. Sources use GUIDs, never
mutable indices. Folder sources require `include_descendants=True` and a balanced
complete subtree. Nested descendants retain their order and hierarchy.

`descendant_names` maps source descendant GUIDs to explicit new names; omitted
names stay unchanged. Insert before an existing top-level track GUID, or append
when the insertion GUID is omitted. The copies form a contiguous top-level block.
Normal tracks copied out of a folder become standalone tracks.

Normal and input FX, colors, volume, pan, mute, channels, recording configuration,
input and monitoring are preserved and read back. Copies are unarmed and without
solo unless the corresponding `preserve_*` option is explicitly true. Missing
recording inputs produce warnings containing both `requested_record_input_raw`
and `effective_record_input_raw`; a stored raw number does not imply that the
current device offers that input.

Internal sends/receives must be remapped by native duplication to the corresponding
copies, retaining send settings. External sends, external receives and hardware
outputs are removed from the copies; no option silently preserves those links.
The main/parent send remains enabled when enabled in the source: it feeds the
copied parent inside the subtree, or the master for a top-level copy. Stop
playback/recording before this operation. REAPER may create temporary external
connections during its synchronous native action; these are removed and verified
before returning.

Items are excluded by default. With `include_items=True`, native duplication
preserves items and takes with new object GUIDs. Audio references the same source
files; no physical media files are copied, written or deleted. Native MIDI pooling
and other shared media semantics remain in effect.

The result includes `created_tracks` in source order, each with
`source_track_guid`, new `track_guid`, final one-based `track_index` and `name`,
plus warnings and verification flags. Track, FX, item and take GUIDs must be new
and unique. Source and all pre-existing track snapshots are compared after the
operation. Selection is restored. One Undo step covers the operation; failure
removes only newly created tracks and reports `rollback_succeeded` and
`source_unchanged`, without applying a global Undo or overwriting originals.

Both `copy_track_fx_chain` and `duplicate_tracks` expose bridge failures as MCP
`isError: true`, retaining JSON diagnostics in the error text. FX mismatch
diagnostics contain normalized source/destination line locations, lengths and
SHA256 digests, capped at 16 changed ranges, never payload text or media paths.
Copy failures independently check source preservation after rollback.

Limitations: the Python track snapshot limit is 4 MiB. FX parameter automation,
modulation and parameter links remain rejected before mutation, including on
template input FX; track automation is retained by native duplication. Unknown
serialization differences remain errors with rollback. A plugin whose native
copy changes its preset API state (including some freshly inserted VST defaults)
can still be conservatively rejected. There is no blanket binary-state exception.
External routing with associated automation may also be conservatively rejected
when removal changes otherwise verified state. Audio equivalence is not auditioned.
Restart the deployed bridge and reconnect the MCP server after adding a tool.
