# REAPER MCP

## Purpose

This repository implements an MCP server for interacting with REAPER.

The project is intentionally incremental. Prefer the smallest change that enables the next useful capability.

Do not introduce additional frameworks, routing systems, abstraction layers, or architectural machinery unless the current code demonstrates a concrete need.

## Runtime Architecture

There are two separate Python runtimes.

### MCP Server

Located under:

`src/reaper_mcp/`

This code:

* runs as a normal external Python process;
* implements the MCP server;
* communicates with the REAPER bridge;
* must not call REAPER `RPR_*` APIs directly.

The MCP server currently communicates with REAPER using TCP on:

`127.0.0.1:8765`

Messages are JSON.

### REAPER Bridge

Located under:

`reaper/`

This code:

* runs inside REAPER as a Python ReaScript;
* has access to REAPER's injected `RPR_*` API;
* owns all direct interaction with REAPER;
* receives commands from the external MCP server;
* returns structured JSON responses.

Do not move REAPER-specific API calls into the external MCP server.

## Communication Boundary

The current flow is:

`MCP Client -> MCP Server -> TCP/JSON -> REAPER Bridge -> REAPER API`

Keep this boundary explicit.

The transport may evolve later, but do not replace it without a concrete reason.

## REAPER Bridge Commands

Bridge commands should be implemented as small handler functions.

Use a command-handler dispatch table instead of adding long chains of conditional statements to `process_request()`.

Preferred structure:

```python
COMMAND_HANDLERS = {
    "get_project_info": handle_get_project_info,
    "get_tracks": handle_get_tracks,
}
```

`process_request()` should remain responsible only for:

* parsing the request;
* resolving the command;
* dispatching to the handler;
* returning a clear error for unknown commands.

## Implemented Capabilities

Do not maintain a capability inventory in this file.

Use the implementation as the source of truth for available MCP tools.

Use `README.md` as the current user/developer tool reference and
`tasks/backlog.json` for capability status and planned work.

## REAPER Values

REAPER frequently exposes internal numeric representations rather than user-facing values.

Do not discard the raw value when it may be useful for future write operations.

For example:

* `D_VOL` is a linear amplitude value;
* expose a derived dB value separately;
* `D_PAN` ranges approximately from `-1.0` to `1.0`;
* expose human-readable pan percentage and direction separately.

Example:

```json
{
  "volume": 0.5576055132289662,
  "volume_db": -5.07,
  "pan": -0.696,
  "pan_percent": 69.6,
  "pan_direction": "L"
}
```

## Read Before Write

Prefer implementing and validating read-only capabilities before mutation capabilities.

Do not add write operations merely because the corresponding read operation exists.

Before introducing a REAPER mutation command, make sure:

* the target can be identified reliably;
* the requested value can be validated;
* errors can be reported clearly;
* the action has a concrete current use case.

## Python Environment

The project uses `uv`.

Run project Python through:

```text
uv run python ...
```

Add dependencies with:

```text
uv add <dependency>
```

Do not manually manage a separate `pip` requirements workflow unless the project explicitly changes away from `uv`.

## Developer Tooling

Launch MCP Inspector from the repository root with:

```text
powershell -ExecutionPolicy Bypass -File scripts/start_mcp_inspector.ps1
```

Inspector remains responsible for starting the configured stdio MCP server.

Launch the backlog visualizer from the repository root with:

```text
powershell -ExecutionPolicy Bypass -File scripts/start_backlog_visualizer.ps1
```

## REAPER ReaScript Environment

Files under `reaper/` run inside REAPER.

REAPER injects functions such as:

```text
RPR_CountTracks
RPR_GetTrack
RPR_GetTrackName
RPR_GetMediaTrackInfo_Value
```

These names do not exist in a normal Python runtime.

The bridge may therefore contain:

```python
# pyright: reportUndefinedVariable=false
```

Do not remove this merely because the `RPR_*` functions appear undefined to VS Code.

## Validation, Deployment, Commit, and Push

Changes are not considered complete until they have been validated and,
when applicable, deployed, committed, and pushed.

### REAPER Bridge Deployment

`reaper/mcp_bridge.py` is the source of truth for the REAPER bridge.

REAPER executes a deployed copy from:

`C:\Users\Usuario\AppData\Roaming\REAPER\Scripts\mcp_bridge.py`

Do not edit the deployed copy directly.

Whenever `reaper/mcp_bridge.py` is modified, run:

`powershell -ExecutionPolicy Bypass -File scripts/deploy_reaper_bridge.ps1`

The deployment script must:

1. validate `reaper/mcp_bridge.py` syntax first;
2. stop immediately if syntax validation fails;
3. deploy the bridge only when validation succeeds;
4. report whether deployment succeeded.

A bridge change must not be committed or pushed if validation or deployment fails.

### User-Controlled Reload and REAPER Testing

When changing the MCP server or REAPER bridge:

1. Complete local implementation, automated checks, and required deployment.
2. Tell the user exactly what must be reloaded or reconnected (for example,
   the deployed bridge ReaScript or the MCP server connection).
3. Wait for the user's explicit confirmation that the required updates are ready
   before running any tests against REAPER, including read-only MCP queries,
   MCP Inspector calls that reach REAPER, and integration scripts.

Do not open or launch REAPER instances, or start, stop, restart, or reload the
bridge on your own. The user performs these actions. Deployment copies the
validated file; it does not authorize restarting the running bridge.

Local checks and tool discovery that do not contact REAPER may proceed without
this confirmation. If confirmation is pending, report runtime validation as
pending and keep implemented backlog work in `testing` after successful local
validation and required deployment. Do not claim REAPER integration passed.

### Git Commit and Push

After all requested changes have been successfully validated and any required
REAPER bridge deployment has succeeded:

1. inspect `git status`;
2. identify only the files belonging to the current task;
3. do not stage unrelated user changes;
4. stage the files modified for the current task;
5. create a concise commit message derived from the task summary;
6. push the commit to the current branch's configured remote.

Do not use `git add -A` or otherwise include unrelated working-tree changes.

Before pushing, verify that a remote and upstream branch are configured.

If no remote or upstream exists, report this clearly and do not invent one.

If commit or push fails, report the failure and do not claim the task is complete.

### Completion Report

At the end of every coding task, report:

* files changed;
* summary of the implementation;
* validation commands and results;
* REAPER bridge deployment result, when applicable;
* commit hash and commit message;
* remote and branch pushed;
* whether the push succeeded.

## Code Style

Prefer:

* small focused functions;
* explicit names;
* simple data structures;
* dispatch tables where command routing is required;
* localized changes;
* clear structured JSON responses.

Avoid:

* premature classes;
* generic command frameworks;
* unnecessary inheritance;
* large refactors unrelated to the requested change;
* duplicating REAPER semantics in the MCP layer.

## Error Handling

Return useful errors across the bridge boundary.

Unknown commands should return a structured error rather than silently failing.

External MCP code should handle failures such as:

* REAPER not running;
* bridge not running;
* TCP connection failure;
* malformed bridge response;
* unsupported command.

Do not hide errors that are useful for diagnosing the integration.

## Validation

After modifying external MCP code, run at minimum:

```text
uv run python -m compileall src
```

For code under `reaper/`, validate Python syntax without assuming `RPR_*` functions are available outside REAPER.

When a change affects actual REAPER behavior, the final validation must be performed against a running REAPER instance.

For MCP-facing changes, validate through the MCP Inspector when practical.

## Development Workflow

### Backlog Intake

`tasks/backlog.json` is the source of truth for repository task tracking.

Before implementing a requested change:

1. inspect the backlog for an existing task that represents the work;
2. use the existing task when one matches;
3. otherwise create a task with the next stable ID for an existing category before implementation begins.

When creating a task:

* infer the category only when the request makes it clear, and tell the user which existing category was selected;
* if the category is ambiguous, ask the user to choose from the categories already present in the backlog;
* do not invent a new category silently; when no category fits, ask whether one should be created;
* set the initial status to `pending`;
* include an ID, category, title, priority, description, dependencies, and observable acceptance criteria;
* include a capability name when applicable and a bugs array when consistent with the current backlog schema;
* do not duplicate an existing task.

Use these task status semantics:

* `pending`: implementation is not complete;
* `testing`: implementation and automated validation are complete and required deployment succeeded, but user/runtime acceptance is pending;
* `completed`: the user explicitly accepted the behavior.

Never move newly implemented work directly from `pending` to `completed`.

When implementing a new capability:

1. inspect the existing code first;
2. make the smallest necessary change;
3. implement or extend the REAPER bridge if REAPER API access is required;
4. verify the bridge independently when practical;
5. expose the capability through the MCP server;
6. validate through MCP Inspector;
7. preserve existing behavior.

Do not rewrite working sections merely to make them stylistically different.

### README Maintenance

`README.md` is the primary user/developer reference for the current implemented
MCP surface.

Treat the implementation as the source of truth.

Whenever a task adds, removes, renames, or materially changes any of the
following:

* an MCP tool;
* a public input or output contract;
* setup or runtime requirements;
* developer startup/deployment scripts;
* externally visible architecture;
* safety or mutation semantics;
* a meaningful current limitation;

update `README.md` as part of the same task.

Do not update `README.md` for internal refactors that do not change documented behavior.

When updating the README:

* inspect the current implementation before documenting behavior;
* document only capabilities that actually exist;
* do not present pending backlog tasks as implemented features;
* keep tool names, signatures, indexing conventions, and examples synchronized
  with code;
* preserve the distinction between raw REAPER values and human-readable derived
  values where relevant;
* keep examples aligned with the current public contracts;
* remove or update known limitations when they are resolved.

After substantive README changes, run:

`npx markdownlint-cli2 README.md`

Fix lint issues introduced by the change before considering the task complete.

README maintenance belongs in the same commit as the public behavior change
that required it whenever practical.

## Repository Responsibility

Treat this repository as the source of truth for the current implementation.

Before proposing structural changes, inspect the existing files and follow the architecture already present unless concrete evidence justifies changing it.
