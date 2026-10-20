# Audio item edges validation

WR-029 implements `set_item_edges` through the existing TCP/JSON boundary.
The public contract and conservative limitations are in the README.

## Isolated native tests

`scripts/validate_item_edges.lua` loads the Python probe via REAPER's ReaScript
API. It refuses to operate unless the resource directory is exactly this
repository's `.local/edges-validation` and the project is empty and stopped.
It generates a 20-second, mono, 48 kHz WAV with two sine components. No recorded
media, user project or computer automation is used.

Initialize an independent REAPER resource directory there, with Python enabled
and the usual resources/preferences copied from an initialized installation.
Use `loadlastproj=0`, an empty `lastproject`, and `projecttabs=0` in its reaper.ini.
Then launch a separate REAPER process with these arguments:

```text
-newinst -nosplash -ignoreerrors
-cfgfile C:/Code/spec-driven-creation/reaper-mcp/.local/edges-validation/reaper.ini
-new C:/Code/spec-driven-creation/reaper-mcp/scripts/validate_item_edges.lua
```

The script records `.local/edges-validation/validation.json`, the initial item
chunk, last successful edge response, injected-write rollback result and a
GUID-targeted request for protocol tests. A failed assertion stops validation
and records a traceback. A successful probe serves only the disposable project
on port 8766 for subsequent MCP tests. It does not replace the live port 8765.

Checks cover left/right extension and trimming, simultaneous edges, constant
take rates 1 and 1.5, omitted/explicit fades, automatic fades, both loop flag
states, source bounds, negative offsets, locks, wrong/missing/duplicate GUIDs,
wrong tracks, nonfinite/invalid inputs, MIDI, multiple takes, stretch markers,
automatic stretching, section/reversed sources and missing files.

The native take accessor uses time relative to the item. At project times
5.25, 6.125 and 7.25 seconds, 64 samples are extracted before and after every
edge operation. Each comparison requires non-silent data and maximum absolute
sample difference below 1e-7. This independently validates the compensation
formula, including non-unit rate; it does not merely compare the formula with
itself. Normal calls subsequently verify the same proven linear mapping from
native read-back values at three retained-interval points and its intercept.

Undo and Redo compare complete item chunks. A simulated offset write failure
after position/length changes must restore the exact original item. A separate
injection alters pitch during the offset write: verification must reject it
and restore the complete target snapshot. Neighboring item and other-track
chunks must remain identical. The test hook exists only in the probe namespace;
there is no public failure injection or arbitrary-code MCP tool.

## MCP protocol tests

With the successful isolated probe still running, create the local server entry:

```python
from reaper_mcp import server
server.PORT = 8766
server.mcp.run(transport="stdio")
```

Save it as `.local/edges-validation/mcp_server.py`, then run:

```text
uv run python scripts/validate_item_edges_mcp.py
```

The client initializes MCP over stdio, enumerates the new tool, edits the
synthetic item, requires `isError: true` for a negative-offset request and
restores the test boundaries. Evidence is written to `mcp-validation.json`.
The same entry can be started by MCP Inspector CLI with `--method tools/list`
or `--method tools/call --tool-name set_item_edges` and explicit test arguments.

## Scope of evidence

Host: REAPER 7.75, Windows, Python 3.14. Native sample comparisons validate timing
for the supported fixture and rates, rather than subjective audible quality.
They do not prove attack safety, or support for stretch/section/looped mappings.
All other take envelopes and take FX are conservatively rejected. Source audio
is read, never rewritten. FM-009 through FM-021 have not been edited.

Validation on 2026-10-20 passed the repository's 64 unit tests, source compilation,
README lint, 53 native host checks, stdio MCP edits/errors and Inspector tool
enumeration/error propagation. Deployment syntax validation and copying to
`C:/Users/Usuario/AppData/Roaming/REAPER/Scripts/mcp_bridge.py` succeeded.
The previously running production bridge still reports `Unknown command` for
this tool: guarded hot reload could not locate its runtime namespace.
Restart that bridge ReaScript and reconnect the MCP client to activate the new
tool in the existing session. Isolated MCP/REAPER activation was verified;
production-session activation is still pending. No production item was edited.

The capability remains `testing` until explicit user acceptance. A native API or
process failure that prevents restoration is reported with failed rollback; no
software tool can guarantee recovery after REAPER termination or memory loss.
