from reaper_python import *
import ast
import json
import math
import re
import struct
import traceback
import wave
from pathlib import Path

ROOT = Path(RPR_GetExtState('reaper-edges-validation', 'repository'))
OUT = ROOT / '.local/edges-validation'
report = {'checks': []}


def check(label, value):
    report['checks'].append({'check': label, 'passed': bool(value)})
    assert value, label


def audio_samples(take):
    accessor = RPR_CreateTakeAudioAccessor(take)
    try:
        samples = []
        for t in (5.25, 6.125, 7.25):
            buffer = [0.0] * 64
            position = RPR_GetMediaItemInfo_Value(RPR_GetMediaItemTake_Item(take), 'D_POSITION')
            result, buffer = RPR_GetAudioAccessorSamples(accessor, 48000, 1, t - position, 64, buffer)
            assert result == 1, (result, t, RPR_GetAudioAccessorStartTime(accessor), RPR_GetAudioAccessorEndTime(accessor), item_edges_state(RPR_GetMediaItemTake_Item(take)))
            samples.extend(buffer)
        return samples
    finally:
        RPR_DestroyAudioAccessor(accessor)


try:
    assert Path(RPR_GetResourcePath()).resolve() == OUT.resolve(), 'Wrong resource directory'
    assert RPR_CountTracks(0) == 0 and RPR_GetPlayState() == 0, 'Disposable empty stopped project required'
    tree = ast.parse((ROOT / 'reaper/mcp_bridge.py').read_text())
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), 'bridge', 'exec'), globals())
    with wave.open(str(OUT / 'fixture.wav'), 'wb') as output:
        output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', round(18000 * math.sin(i * .071) + 4000 * math.sin(i * .013))) for i in range(48000 * 20)))
    RPR_InsertTrackAtIndex(0, False)
    RPR_InsertTrackAtIndex(1, False)
    track = RPR_GetTrack(0, 0)
    other = RPR_GetTrack(0, 1)
    item = RPR_AddMediaItemToTrack(track)
    fixture = (OUT / 'fixture.wav').as_posix()
    assert RPR_SetItemStateChunk(item, '<ITEM\nPOSITION 5\nLENGTH 3\n<SOURCE WAVE\nFILE "' + fixture + '"\n>\n>\n', False)
    take = RPR_GetTake(item, 0)
    RPR_SetMediaItemInfo_Value(item, 'D_POSITION', 5)
    RPR_SetMediaItemInfo_Value(item, 'D_LENGTH', 3)
    RPR_SetMediaItemTakeInfo_Value(take, 'D_STARTOFFS', 4)
    RPR_SetMediaItemInfo_Value(item, 'D_FADEINLEN', .01)
    RPR_SetMediaItemInfo_Value(item, 'D_FADEOUTLEN', .02)
    RPR_SetMediaItemInfo_Value(item, 'I_CUSTOMCOLOR', 0x1009988)
    neighbor = RPR_AddMediaItemToTrack(track)
    RPR_SetMediaItemInfo_Value(neighbor, 'D_POSITION', 12)
    RPR_SetMediaItemInfo_Value(neighbor, 'D_LENGTH', 1)
    neighbor_chunk = item_edges_chunk(neighbor)
    other_chunk = read_recording_chunk(other)
    request = {'item_guid': get_item_identity(item), 'track_guid': recording_track_guid(track), 'start_seconds': 5, 'end_seconds': 8}
    original = item_edges_chunk(item)
    (OUT / 'initial-item.txt').write_text(original)
    for rate in (1, 1.5):
        assert RPR_SetMediaItemTakeInfo_Value(take, 'D_PLAYRATE', rate)
        RPR_UpdateItemInProject(item)
        baseline = audio_samples(take)
        for label, start, end in (('extend-left', 4.5, 8), ('trim-left', 5, 8), ('extend-right', 5, 9), ('trim-right', 5, 8), ('both', 4.75, 8.5)):
            result = handle_set_item_edges({**request, 'start_seconds': start, 'end_seconds': end})
            (OUT / 'last-result.json').write_text(json.dumps(result, indent=2))
            check(label + '-rate-' + str(rate), result.get('success'))
            actual = audio_samples(take)
            check('native-audio-invariance-' + label + '-' + str(rate), max(abs(a-b) for a, b in zip(actual, baseline)) < 1e-7 and max(map(abs, actual)) > .01)
        check('restore-edges', handle_set_item_edges(request).get('success'))
    before = item_edges_chunk(item)
    result = handle_set_item_edges({**request, 'start_seconds': 4.5, 'end_seconds': 9, 'fade_in_seconds': .03, 'fade_out_seconds': .04})
    check('explicit-fades', result.get('success') and result['after']['D_FADEINLEN'] == .03 and result['after']['D_FADEOUTLEN'] == .04)
    after = item_edges_chunk(item)
    RPR_Undo_DoUndo2(0)
    item = find_item_by_guid(track, request['item_guid'])
    check('one-step-undo', item_edges_chunk(item) == before)
    RPR_Undo_DoRedo2(0)
    item = find_item_by_guid(track, request['item_guid'])
    take = RPR_GetTake(item, 0)
    check('redo', item_edges_chunk(item) == after)
    for label, args in (
        ('negative-offset', {'start_seconds': 0}), ('insufficient-source', {'end_seconds': 40}),
        ('missing-guid', {'item_guid': '{BAD}'}), ('wrong-track', {'track_index': 2}),
        ('invalid-number', {'start_seconds': float('nan')}), ('negative-start', {'start_seconds': -1}),
        ('end-before-start', {'end_seconds': 1}), ('invalid-fade', {'fade_in_seconds': -1}),
        ('excessive-fade', {'fade_out_seconds': 20}),
    ):
        before_failure = item_edges_chunk(item)
        failure = handle_set_item_edges({**request, **args})
        check(label, 'error' in failure and not failure['rollback']['attempted'] and item_edges_chunk(item) == before_failure)
    for label, attr, value in (('locked', 'C_LOCK', 1), ('auto-stretch', 'C_AUTOSTRETCH', 1)):
        RPR_SetMediaItemInfo_Value(item, attr, value)
        check(label, 'error' in handle_set_item_edges(request))
        RPR_SetMediaItemInfo_Value(item, attr, 0)
    RPR_SetTakeStretchMarker(take, -1, 1, 1)
    check('stretch-markers', 'error' in handle_set_item_edges(request))
    RPR_DeleteTakeStretchMarkers(take, 0, 1)
    extra = RPR_AddTakeToMediaItem(item)
    check('multiple-takes', 'error' in handle_set_item_edges(request))
    RPR_SetItemStateChunk(item, after, False)
    take = RPR_GetTake(item, 0)
    midi = RPR_CreateNewMIDIItemInProj(track, 20, 21, False)
    check('midi', 'error' in handle_set_item_edges({**request, 'item_guid': get_item_identity(midi)}))
    RPR_DeleteTrackMediaItem(track, midi)
    for automatic in (0, .025):
        RPR_SetMediaItemInfo_Value(item, 'D_FADEINLEN_AUTO', automatic)
        outcome = handle_set_item_edges({**request, 'fade_in_seconds': .03})
        check('automatic-fade-' + str(automatic), bool(outcome.get('success')) if automatic == 0 else 'error' in outcome)
    RPR_SetMediaItemInfo_Value(item, 'D_FADEINLEN_AUTO', 0)
    for looping in (0, 1):
        RPR_SetMediaItemInfo_Value(item, 'B_LOOPSRC', looping)
        outcome = handle_set_item_edges(request)
        check('loop-flag-' + str(looping), outcome.get('success') and outcome['after']['B_LOOPSRC'] == looping and outcome['verification']['no_source_repeat'])
    duplicate = RPR_AddMediaItemToTrack(other)
    RPR_GetSetMediaItemInfo_String(duplicate, 'GUID', request['item_guid'], True)
    check('duplicate-guid', 'error' in handle_set_item_edges(request))
    RPR_DeleteTrackMediaItem(other, duplicate)
    source_chunk = item_edges_chunk(item)
    envelope_chunk = source_chunk.replace('<SOURCE WAVE', '<VOLENV\nACT 1 -1\nVIS 1 1 1\nARM 1\nDEFSHAPE 0 -1 -1\nPT 0 1 0\n>\n<SOURCE WAVE')
    assert RPR_SetItemStateChunk(item, envelope_chunk, False)
    check('take-envelope', RPR_CountTakeEnvelopes(RPR_GetTake(item, 0)) == 1 and 'error' in handle_set_item_edges(request))
    assert RPR_SetItemStateChunk(item, source_chunk, False)
    fx_take = RPR_GetTake(item, 0)
    assert RPR_TakeFX_AddByName(fx_take, 'ReaEQ (Cockos)', 1) >= 0
    check('take-fx', 'error' in handle_set_item_edges(request))
    assert RPR_SetItemStateChunk(item, source_chunk, False)
    section = source_chunk.replace('<SOURCE WAVE\n', '<SOURCE SECTION\nLENGTH 20\nSTARTPOS 0\nOVERLAP 0\n<SOURCE WAVE\n').replace('\n>\n>\n', '\n>\n>\n>\n')
    assert RPR_SetItemStateChunk(item, section, False)
    check('section-source', 'error' in handle_set_item_edges(request))
    reverse = section.replace('OVERLAP 0', 'OVERLAP 0\nMODE 3')
    assert RPR_SetItemStateChunk(item, reverse, False)
    check('reverse-source', 'error' in handle_set_item_edges(request))
    assert RPR_SetItemStateChunk(item, source_chunk, False)
    missing = source_chunk.replace('fixture.wav', 'absent-fixture.wav')
    assert RPR_SetItemStateChunk(item, missing, False)
    check('missing-source', 'error' in handle_set_item_edges(request))
    assert RPR_SetItemStateChunk(item, source_chunk, False)
    take = RPR_GetTake(item, 0)
    native = RPR_SetMediaItemTakeInfo_Value
    fired = [False]
    def fail_once(t, attr, value):
        if attr == 'D_STARTOFFS' and not fired[0]:
            fired[0] = True
            return False
        return native(t, attr, value)
    RPR_SetMediaItemTakeInfo_Value = fail_once
    failed = handle_set_item_edges({**request, 'start_seconds': 4.25, 'end_seconds': 9})
    RPR_SetMediaItemTakeInfo_Value = native
    (OUT / 'rollback.json').write_text(json.dumps(failed, indent=2))
    check('injected-partial-write-rollback', fired[0] and 'error' in failed and failed['rollback']['verified'])
    def corrupt_once(t, attr, value):
        result = native(t, attr, value)
        if attr == 'D_STARTOFFS' and not fired[0]:
            fired[0] = True
            native(t, 'D_PITCH', .5)
        return result
    fired[0] = False
    RPR_SetMediaItemTakeInfo_Value = corrupt_once
    failed = handle_set_item_edges({**request, 'start_seconds': 4.25, 'end_seconds': 9})
    RPR_SetMediaItemTakeInfo_Value = native
    check('verification-failure-snapshot-rollback', fired[0] and 'error' in failed and failed['rollback']['verified'] and failed['rollback'].get('snapshot_restored'))
    check('neighbor-preserved', item_edges_chunk(neighbor) == neighbor_chunk)
    check('other-track-preserved', read_recording_chunk(other) == other_chunk)
    (OUT / 'request.json').write_text(json.dumps(request))
    report['success'] = True
except Exception:
    report['exception'] = traceback.format_exc()
(OUT / 'validation.json').write_text(json.dumps(report, indent=2))
if report.get('success'):
    # Serve this disposable project on a separate local port for protocol testing.
    exec(compile((ROOT / 'reaper/mcp_bridge.py').read_text().replace('PORT = 8765', 'PORT = 8766'), 'isolated-bridge', 'exec'), globals())
