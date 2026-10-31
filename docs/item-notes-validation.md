# Item notes validation

## Automated checks (2026-10-31)

`uv run python -m unittest discover -s tests`: 79 tests passed, including five
new item-note tests. They cover empty, multiline, Unicode and long text with
and without takes, 83-item batches, default omission without reading P_NOTES,
invalid track/item indexes, invalid include_notes values, API read failures,
unchanged item state and MCP argument forwarding. The transport regression
now reads a large multiline Unicode response over multiple TCP chunks.

`uv run python -m compileall src`, Python syntax validation of the host probe,
backlog JSON parsing, and `git diff --check` passed.
`npx markdownlint-cli2 README.md` passed with zero issues.

MCP Inspector CLI `tools/list`, using `uv run python -m reaper_mcp.server`,
confirmed `get_track_items.include_notes` is boolean, optional and defaults to
false. Required track/item indexes are unchanged. The project's `reaper-mcp`
console entry point prints a greeting; use the server module for Inspector.
Local discovery evidence: `.local/item-notes-validation/mcp-tools.json`.

Restricted-environment checks initially failed on temporary-file access and
socket permissions; the complete suite passed outside that environment. These
initial failures are not REAPER integration results.

## Deployment and live integration

`scripts/deploy_reaper_bridge.ps1` validated syntax and successfully copied the
source bridge to REAPER's Scripts directory. Deployment alone does not reload
the running script.

Connected MCP reads confirmed active `turbulence.rpp`, 14 tracks and the unique
track named `Notes Harmony` at one-based index 9. The active old bridge returned
item 1 with zero takes but without `notes`, so this is identification evidence,
not successful validation of the new notes reader. UI reload attempts failed
with window geometry/monitor errors. A command-line probe produced no evidence
file. Do not infer integration success from either attempt.

Pending: restart the deployed bridge ReaScript, reconnect MCP for the updated
schema, and call `get_track_items` with `{"track_index":9,"include_notes":true}`.
Confirm 83 results with notes, compare individual `get_item_info` responses,
and verify project/selection/playback state is preserved.

For a reproducible independent host check, run
`scripts/validate_item_notes_in_reaper.lua` from REAPER's action list with
Turbulence active. It loads only bridge functions (no socket listener), resolves
the track name before using its index, reads all 83 items, compares every batch
note with the individual query, and checks project identity, change count,
dirty status, cursor, selections and playback state before/after. It never
creates or edits items. It writes full texts only to the ignored local
`items.json` and summary evidence to `host-results.json` under
`.local/item-notes-validation/`. This host probe is provided but has not yet
passed in this session. It is distinct from automated mocked tests and does
not replace end-to-end MCP verification of the reloaded bridge.

RO-028 remains `testing`, pending runtime verification and explicit acceptance.

## Deferred execution error follow-up

The user reported that restarting displays only `Deferred script execution
error`, without a traceback. BUG-022 is recorded under FN-003 and remains open:
the root cause has not been established. Source and deployed files matched by
SHA256. Connected MCP continued returning the old item-info contract.

The deferred callback now catches otherwise unreported exceptions and prints
the complete Python traceback to the REAPER console. It stops on failure and
does not retry or modify project state. The test exercises both successful
rescheduling and a missing callback name, verifying full traceback output and
no retry. All 80 automated tests, compilation, backlog JSON, README lint and
diff checks passed; syntax validation and deployment succeeded. Host validation
of this diagnostic is pending a new script start; it is not a root-cause fix.
