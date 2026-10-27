"""Guarded FM-022 reproduction in a disposable tab; never save or edit the live session.

Run validate_duplicate_tracks_regression.lua in the running REAPER instance.
Reports only bounded diagnostics and checks under .local/duplicate-regression/.
"""
from reaper_python import *
import ast
import base64
import difflib
import hashlib
import json
import math
import re
import traceback
import uuid
from pathlib import Path

ROOT = Path(RPR_GetExtState('reaper-duplicate-regression', 'repository'))
OUT = ROOT / '.local/duplicate-regression'
OUT.mkdir(parents=True, exist_ok=True)
report = {'host': RPR_GetAppVersion(), 'checks': []}
original_project = RPR_EnumProjects(-1, '', 32768)[0]
test_project = None


def check(label, condition, details=None):
    report['checks'].append({'check': label, 'passed': bool(condition), 'details': details})
    (OUT / 'host-results.json').write_text(json.dumps(report, indent=2))
    assert condition, label


try:
    assert RPR_EnumProjects(-1, '', 32768)[2].endswith('Session 6 - Attack classifier.rpp')
    assert RPR_CountTracks(0) == 5 and RPR_GetPlayState() == 0
    tree = ast.parse((ROOT / 'reaper/mcp_bridge.py').read_text())
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
                            type_ignores=[]), 'bridge-regression', 'exec'), globals())
    original_tracks = template_tracks()
    original_snapshots = {recording_track_guid(t): template_source_snapshot(t) for t in original_tracks}
    chunks = [read_recording_chunk(t) for t in original_tracks]
    RPR_Main_OnCommand(40859, 0)  # New project tab, no changes to the work session.
    test_project = RPR_EnumProjects(-1, '', 32768)[0]
    assert test_project != original_project and RPR_CountTracks(0) == 0
    for index, chunk in enumerate(chunks):
        RPR_InsertTrackAtIndex(index, False)
        assert RPR_SetTrackStateChunk(RPR_GetTrack(0, index), chunk, False)
    source_guid = '{2E018A42-422A-4D74-919D-1FC0D6410F03}'
    guitar_guid = '{DB7D7DF9-A322-476F-901A-A1B72A1A47EF}'
    request = {'source_track_guid': source_guid, 'new_name': 'FM-023',
               'include_descendants': True, 'include_items': False,
               'preserve_record_arm': False, 'preserve_solo': False,
               'descendant_names': {guitar_guid: 'GTR-8s__FM-023',
                    '{95C979DB-6E93-40ED-8F03-26D13BBE43F0}': 'MIDI_FM-023'}}
    # Loading a state chunk can materialize LANEREC too. Use the captured live
    # guitar representation only as the comparison expectation; all source and
    # rollback snapshots continue reading actual native tracks, never fixtures.
    lines, depth, captured_lines = chunks[3].splitlines(keepends=True), 0, []
    for line in lines:
        text = line.strip()
        if not (depth == 1 and text == 'LANEREC -1 -1 -1 0'):
            captured_lines.append(line)
        depth += int(text.startswith('<')) - int(text == '>')
    captured_guitar = ''.join(captured_lines)
    def captured_expectation(chunk):
        return captured_guitar if 'TRACKID ' + guitar_guid in chunk else chunk
    before = template_tracks()
    baseline = {recording_track_guid(t): template_source_snapshot(t) for t in before}
    def restored():
        return (template_tracks() == before and all(
            template_source_snapshot(t) == baseline[recording_track_guid(t)] for t in before))
    strict = template_non_fx_comparison
    def old_comparison(a, b, items):
        return template_residual(captured_expectation(a), items), template_residual(b, items), []
    template_non_fx_comparison = old_comparison
    result = handle_duplicate_tracks(request)
    def captured_comparison(a, b, items):
        return strict(captured_expectation(a), b, items)
    template_non_fx_comparison = captured_comparison
    check('original-failure-and-rollback', result.get('rollback_succeeded') and
          result.get('source_unchanged') and restored(), result)
    differences = result['diagnostics']['non_fx']['differences']
    check('exact-cause', len(differences) == 1 and differences[0]['expected'] is None and
          differences[0]['observed'].get('value') == 'LANEREC -1 -1 -1 0')
    result = handle_duplicate_tracks(request)
    check('full-folder-success', result.get('success') and result.get('verified_full_state'), result)
    for entry in result['created_tracks']:
        src = template_track_by_guid(entry['source_track_guid'])
        dst = template_track_by_guid(entry['track_guid'])
        for key in ('D_VOL', 'D_PAN', 'I_CUSTOMCOLOR', 'I_RECMON', 'I_RECINPUT', 'I_NCHAN', 'I_FOLDERDEPTH', 'B_MAINSEND'):
            check('native-' + entry['name'] + '-' + key,
                  RPR_GetMediaTrackInfo_Value(src, key) == RPR_GetMediaTrackInfo_Value(dst, key))
        check('excluded-items-' + entry['name'], RPR_CountTrackMediaItems(dst) == 0)
    RPR_Undo_DoUndo2(0)
    check('undo-removes-whole-copy', restored())
    RPR_Undo_DoRedo2(0)
    check('redo-restores-whole-copy', RPR_CountTracks(0) == 10 and all(
        template_track_by_guid(entry['track_guid']) for entry in result['created_tracks']))
    RPR_Undo_DoUndo2(0)
    check('undo-cleanup', restored())
    native_reorder = RPR_ReorderSelectedTracks
    for attribute, value in (('D_VOL', 0.123), ('D_PAN', 0.234), ('I_RECMON', 2),
                             ('I_RECINPUT', -1), ('I_CUSTOMCOLOR', 0x1010203)):
        def corrupt(position, flags):
            ok = native_reorder(position, flags)
            copies = [t for t in template_tracks() if recording_track_guid(t) not in baseline]
            RPR_SetMediaTrackInfo_Value(copies[3], attribute, value)
            return ok
        RPR_ReorderSelectedTracks = corrupt
        result = handle_duplicate_tracks(request)
        RPR_ReorderSelectedTracks = native_reorder
        check('reject-' + attribute, 'error' in result and result.get('rollback_succeeded') and
              result.get('source_unchanged') and restored(), result)
    def corrupt_fx(position, flags):
        ok = native_reorder(position, flags)
        copies = [t for t in template_tracks() if recording_track_guid(t) not in baseline]
        RPR_TrackFX_SetEnabled(copies[3], 0, not RPR_TrackFX_GetEnabled(copies[3], 0))
        return ok
    RPR_ReorderSelectedTracks = corrupt_fx
    result = handle_duplicate_tracks(request)
    RPR_ReorderSelectedTracks = native_reorder
    check('reject-fx-and-rollback', 'FX state' in result.get('error', '') and
          result.get('rollback_succeeded') and result.get('source_unchanged') and restored(), result)
    native_action = RPR_Main_OnCommand
    def partial_failure(command, flag):
        native_action(command, flag)
        if command == 40062:
            raise RuntimeError('Injected failure after native tracks were created')
    RPR_Main_OnCommand = partial_failure
    result = handle_duplicate_tracks(request)
    RPR_Main_OnCommand = native_action
    check('partial-native-failure-no-orphans', result.get('rollback_succeeded') and
          result.get('source_unchanged') and restored(), result)
    report['success'] = True
except Exception:
    report['exception'] = traceback.format_exc()
finally:
    if test_project is not None:
        RPR_SelectProjectInstance(test_project)
        for track in reversed(template_tracks()):
            RPR_DeleteTrack(track)
        # No media or source state remains; clear DIRTY only on this disposable tab.
        RPR_GetSetProjectInfo(test_project, 'DIRTY', 0, True)
        RPR_Main_OnCommand(40860, 0)
    RPR_SelectProjectInstance(original_project)
    if 'original_snapshots' in globals():
        report['original_session_unchanged'] = (template_tracks() == original_tracks and all(
            template_source_snapshot(t) == original_snapshots[recording_track_guid(t)] for t in original_tracks))
    (OUT / 'host-results.json').write_text(json.dumps(report, indent=2))
