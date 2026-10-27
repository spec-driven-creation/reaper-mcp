# duplicate_tracks fixed-lane regression

Validated on 2026-10-27 with REAPER 7.83/win64 in
`Session 6 - Attack classifier.rpp`.

## Exact cause

Source guitar `GTR-8s__FM-022`, GUID
`{DB7D7DF9-A322-476F-901A-A1B72A1A47EF}`, has `FREEMODE 2` and initially
omitted the top-level `LANEREC` record. Native action 40062 creates a copy with
one additional line: `LANEREC -1 -1 -1 0`. Instrumentation immediately after
the native action proved this occurs before item exclusion, renaming, record-arm
changes or insertion. It was the only non-FX residual difference. Original
reproduction failed, rolled back successfully and preserved existing tracks.

The copy's record is an explicit serialization of an implicit native default.
The comparison now accepts only that exact absent-to-explicit transition at
TRACK depth, with `FREEMODE 2` on both sides and exactly one destination record.
It does not discard LANEREC generally, change original snapshots, rewrite chunks,
or accept different values, duplicate records, other modes or nested records.
Unknown differences still fail. Successful normalization is reported explicitly.

## Changes

- Preserve raw REC input in strict comparison; normalize only the authorized arm
  field. Monitoring and other REC tokens remain strict.
- Add bounded non-FX line diagnostics with source/destination GUIDs and names,
  structural paths, expected/observed numeric records, and truncation indication.
- Hash unknown text and nested plugin data rather than exposing payloads, paths,
  notes or chunks. Normal and input FX errors retain full-state verification and
  include track identities and bounded hash diagnostics.
- Preserve native full FX/preset copying, GUID generation, internal routing,
  external/hardware routing exclusions, hierarchy, source snapshots, rollback and
  one operation Undo block.
- Record BUG-021 under existing WR-028; capability remains testing pending user
  acceptance.

## Validation

- `uv run python -m unittest discover -s tests`: 74 tests passed.
- `uv run python -m compileall src`: passed.
- `uv run python -m py_compile reaper/mcp_bridge.py scripts/validate_duplicate_tracks_regression.py`:
  passed.
- `npx markdownlint-cli2 README.md`: passed, zero issues.
- `powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1`:
  syntax validation and deployment passed.
- `scripts/validate_duplicate_tracks_regression.lua`, executed inside REAPER:
  58 checks passed in a disposable tab. Reproduces the exact original rejection;
  checks successful full-folder copy, native volume/pan/color/input/monitoring/
  channel/hierarchy/main-send values, item exclusion, Undo/Redo, and rejection
  with verified rollback for actual volume, pan, input, monitoring, color and FX
  changes. An exception injected immediately after native creation leaves no
  partial duplicates. Live session snapshots are read independently and remain
  unchanged by this disposable-tab regression; the tab is emptied and closed.
- The regression builds its missing-LANEREC expectation from the captured guitar
  state so it remains repeatable after REAPER materializes the default. This
  fixture affects only comparison expectations, never native source snapshots.
- MCP Inspector CLI with `uv run python -m reaper_mcp.server`, method
  `tools/list`: passed; required GUID and name inputs registered correctly.
- Live connected MCP `duplicate_tracks`, using the user's exact GUID mapping and
  options: success, five tracks, `verified_full_state: true`,
  `source_unchanged: true`, `warnings: []`. The first corrected call explicitly
  reported the single LANEREC normalization. A final call also passed after the
  native source representation already contained its explicit default.
- Final cleanup deleted only the five returned temporary GUIDs. Native snapshot
  hashes matched the immediately preceding control for all five original tracks;
  final MCP project info confirmed five tracks and stopped transport.

Local bounded evidence is under `.local/duplicate-regression/`; no plugin chunks
are included in this document or returned diagnostics.

## Native Undo observation and session state

Cleaning up the first live MCP success with native Undo also materialized the
same `LANEREC -1 -1 -1 0` default on the original guitar. Its initial hash matches
exactly when that one added line is removed; the other four original hashes are
identical. No recording or other serialized musical/FX state changed. A separate
isolated test established that writing the chunk without that record does not
restore its omission: REAPER serializes the default again. The live original was
not rewritten in an attempt to remove it. Final cleanup therefore used
operation-local deletion of the exact temporary GUIDs rather than another Undo.

The working project was never saved. It remains open with its original five
tracks, no test copies and no definitive FM-023/024/025. The explicit default
introduced by the first native Undo remains an in-memory metadata difference
from the initial snapshot; byte-identical initial serialization is not claimed.
Source verification during duplication remains strict and was not relaxed for
this Undo behavior.

The deployed bridge ReaScript was restarted in REAPER, and the existing MCP
connection successfully called it afterward. No further REAPER restart or MCP
reconnection is required for this session. Future deployments still require
restarting the running bridge ReaScript to load the deployed file.
