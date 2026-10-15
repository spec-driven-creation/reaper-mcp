# FX copy and default-color regressions — 2026-10-15

BUG-017 and BUG-018 were registered before changing the implementation. Their
corrections have automated and host evidence below and were explicitly accepted
by the user on 2026-10-15. Both bugs are closed as fixed in commit
`d985c3ec9c06ef9694a1fa096cb60e9a93221adb`; WR-022 and WR-023 are completed.
The earlier BUG-016 closure is preserved.

## Reproduction and precise differences

A guarded read-only capture verified the active project path, unique names,
GUIDs and folder membership of FM-003 and FM-004. Both destinations were empty.
Actual GTune, Ampknob Trivium Rhythm and Sketch Piano plugins were available.
Captured state was reproduced in a separate REAPER 7.75/x64 process using
`.local/fx-copy-validation/reaper.ini`, with project restoration disabled.
The native copy was instrumented to capture destination state before rollback.
No opaque payloads are included in this report or committed fixtures.

Both initial failures reproduced, with successful rollback. After the previous
identity/UI exclusions, each diff contained one removed record:

- Guitar GTune: `FLOAT 5919 1047 322 360`.
- MIDI GTune: `FLOAT 5564 1048 322 360`.

REAPER replaced these open floating-editor rectangles with `FLOATPOS 0 0 0 0`.
FX instance GUIDs also changed, as expected; Sketch Piano's stored editor
rectangle was reset. All remaining serialized plugin state matched in that
initial isolated reproduction, and independent musical API snapshots matched.

The guarded live completion then exposed a second MIDI difference. Both
destinations were restored and the project was not saved on the failed attempts.
Sketch Piano's final VST2 wrapper trailer changed from six zero bytes to
`zero + "Sketch Piano" + five zeros` (18 bytes). Loading the captured source
into the isolated process had already populated this label, so a second test
explicitly compared the original live serialized snapshot with the copied state.

Evidence separating this label from musical state:

- Native `vst_chunk` was available on both live instances: 1596 base64 characters,
  identical SHA256 `d6ca77897b271afaa8830a24efcad2c59beb0f2ac2d9eec88923574d4aec2f0c`.
- Preset API state/index, three normalized parameters, enabled/offline flags,
  wet value, I/O sizes and all 32 queried output pin mappings were identical.
- Every other serialized field, including VST wrapper header, plugin payload,
  preset records and channel/pin configuration, matched exactly.

The color failure was also reproduced: raw `16576` without `0x1000000` remains
a default color. REAPER can retain RGB bits without enabling a custom color.
The previous setter incorrectly rejected this valid raw value.

## Correction boundaries

Recognized FXCHAIN-level `FLOAT`, `FLOATPOS`, `SHOW`, `LASTSEL` and destination
FX instance IDs are non-musical identity/UI metadata. Identical-looking text
inside plugin payloads is never ignored; unknown fields and whitespace remain
significant. Source instance IDs are always preserved by source verification.

The VST2 exception is limited to the observed empty-to-populated label trailer.
It requires an unchanged remainder of the serialized chain AND exact native
`vst_chunk`, preset API state, parameters, bypass, offline, wet, I/O and pin maps
across both 64-channel banks. Unavailable/truncated native state, named labels
changing, VST3 trailers, altered flags or any other payload changes are rejected.
The implementation neither changes source presets nor writes source state.

Colors now accept native integers from 0 to `0x1ffffff`, preserving the custom
flag and raw value exactly. Copying `16576` returns `custom: false`, `rgb: null`.
This was tested in the temporary project; work-project colors were left alone.

## Validation actually performed

- `uv run python -m unittest discover -s tests`: 54 tests passed, including
  regressions for window metadata, opaque payload/whitespace/preset/bypass/wet/
  pin differences, VST2 gate failures, default colors and rollback.
- `uv run python -m compileall src`: passed.
- Bridge syntax validation/deployment through the repository script: passed;
  source and deployed SHA256 hashes match. `uv sync --locked` passed.
- `npx markdownlint-cli2 README.md docs/fx-copy-regression.md`: passed.
- The isolated host probe passed for both actual plugin chains, including the
  original live snapshot. It independently checked musical API state, source
  preservation and destination MIDI/items/routing/automation. It rejected an
  occupied destination, injected failure after one FX, and injected a real
  bypass change; both failure scenarios restored the complete empty destination.
- MCP Inspector read the actual default color `16576` successfully. The live
  MCP connection read back both source and completed destination chains.

Local evidence: `host-regression-before.json`, `host-regression.json`,
`work-context.json`, bounded API/hash reports and `work-completion.json` under
`.local/fx-copy-validation/`. Full diagnostic snapshots remain local and ignored.

## Authorized FiruletMap completion

After deployment and bridge reload, the finite completion script rechecked the
active path, unique names, folder GUIDs, track GUIDs and empty destinations.
It backed up the on-disk project and current in-memory track snapshots locally.
Both native copies succeeded with full-state and independent musical checks:

- GTR-8s__FM-003 → GTR-8s__FM-004: GTune / Ampknob, two FX, two channels.
- MIDI_FM-003 → MIDI_FM-004: Sketch Piano / GTune, two FX, two channels;
  `normalized_vst_program_labels: [1]`.

All project tracks were compared immediately around the operations. Only the
two destination FX chains changed. Source state, MIDI, Notes empty items,
colors, inputs, mute, arm, routing, automation and other track properties were
preserved. Cursor, selection, tempo and stopped transport were unchanged during
the guarded execution. The authorized project was saved with `dirty: false`.
No playback or recording command was issued. A later read-only MCP query showed
playback active after completion; no transport action was taken in response.

The normal bridge was reloaded; tool signatures are unchanged, so reconnecting
MCP is not required for this fix. No arbitrary-code MCP tool was introduced.
Validation proves state preservation, not audible equivalence: no audio audition,
render or recording was performed. Other plugin serialization differences remain
conservative failures with rollback, rather than blanket binary exclusions.
