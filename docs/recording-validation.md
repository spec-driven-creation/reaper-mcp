# Recording preparation validation — 2026-10-15

The new capability tasks RO-027 and WR-022 through WR-026 are in `testing`.
User acceptance remains pending. FiruletMap was not modified.

## Automated evidence

- `uv run python -m unittest discover -s tests`: 35 tests passed, including
  16 new contract/failure tests in `tests/test_recording_setup.py`.
- `uv run python -m compileall src`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1`:
  syntax validation and deployment passed. Source/deployed SHA256 match.
- `npx markdownlint-cli2 README.md`: passed.
- MCP Inspector CLI `tools/list`: 59 registered tools, including all eight new
  tools and their required argument schemas. Inspector `tools/call` successfully
  executed `get_track_color` against the deployed bridge.

Mock tests exercise invalid indexes/pointers/GUIDs, destination normal/input FX,
same source/destination, unavailable inputs, unsupported parameter automation,
partial native copy, state mismatch, rollback failure reporting, bounded chunk
reads, monitor modes and named/unnamed project saving. They do not prove plugin
behavior inside REAPER.

## REAPER host evidence

REAPER 7.75/x64, separate disposable configuration under
`.local/recording-validation/`, with the actual device exposing Mic 1 / Mic 2.
The finite probe in `scripts/validate_recording_setup_in_reaper.lua` loads its
Python companion, creates a separate project tab and restores the previously
active tab. The final run passed all 35 host checks:

- Source/destination folders, guitar with bx_tuner and Ampknob Trivium Rhythm,
  and MIDI track with ReaSynth and bx_tuner; factory presets selected explicitly.
- Destination MIDI note and complete serialized item retained.
- Complete serialized normal FX state, order, bypass, offline, wet/dry,
  four-channel configuration and non-default pin mapping retained.
- Source configuration retained; REAPER's FX window selection metadata excluded.
- Existing destination FX rejected, and an injected failure after the first
  native copy restored and verified the empty destination.
- Exact colors, mono, stereo and no input; source input replication; off/on/auto
  monitoring; invalid track and unavailable input rejection.
- Unnamed project rejected; named project saved with `dirty: false`.

A separate MCP SDK client then exercised the actual stdio → TCP → deployed bridge
flow. It created another destination only in the saved disposable project, called
all eight new tools, rejected copying twice, verified existing MIDI items were
unchanged and saved successfully. This is host-backed MCP evidence, distinct from
the mock tests. Local reports: `host-results.json`, `mcp-results.json`,
`inspector-tools.json` and `inspector-color.json` in the disposable directory.

An early probe closed the original REAPER process unexpectedly. No work project
was saved by the probe. Investigation found an unsafe initial chunk buffer size:
the installed Python wrapper allocates a fixed 4 MiB buffer regardless of the
size passed to the native function. The final implementation never requests more
than 4 MiB, and later validation used isolated instances. Recovery of any unsaved
state from the original REAPER session has not been verified.

## Limitations and connection diagnosis

- Source FX parameter automation/modulation and external parameter links are
  rejected, rather than copied. Input FX, multichannel audio input and
  ReaRoute/loopback assignment are outside this version.
- Complete serialized-state comparison deliberately rejects plugin state
  normalization. Newly inserted bx_tuner and ReaSynth instances can acquire a
  previously unnamed preset label on native copy. That case is rejected with
  verified destination rollback; the host acceptance chains use explicit presets.
- Track snapshots beyond the Python wrapper's 4 MiB limit are rejected.
- This does not validate audio equivalence, licenses, or every plugin format.
- Deployment does not reload an existing bridge. The final deployed bridge was
  started and validated in the disposable instance. A normal work session must
  run the deployed bridge ReaScript again.

The global Codex `[mcp_servers.reaper]` configuration pointed to the nonexistent
`C:\Code\reaper-mcp`. Only its `cwd` was corrected to
`C:\Code\spec-driven-creation\reaper-mcp`; its command, arguments and other server
settings were retained. No repository-specific MCP override was present in this
checkout. TCP availability alone does not prove the stdio server can start.
Inspector confirmed that the corrected server starts and exposes tools.
Reconnect the chat's MCP session to load the new definitions. Availability after
reconnection in the FiruletMap chat itself has not been observed.
