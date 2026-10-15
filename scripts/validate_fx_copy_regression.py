"""Reproduce exact captured plugin chains only in a guarded temporary instance."""
from reaper_python import *  # noqa: F403
import ast
import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import traceback
import uuid
import base64

ROOT = Path(RPR_GetExtState("reaper-fx-probe", "repository"))
OUTPUT = ROOT / ".local/fx-copy-validation"
report = {"host": RPR_GetAppVersion(), "chains": []}


def musical_state(track):
    effects = []
    for index in range(RPR_TrackFX_GetCount(track)):
        io = RPR_TrackFX_GetIOSize(track, index, 0, 0)
        pins = []
        for direction, count in ((0, io[3]), (1, io[4])):
            for pin in range(count):
                mapping = RPR_TrackFX_GetPinMappings(track, index, direction, pin, 0)
                pins.append((direction, pin, mapping[0] & 0xffffffff, mapping[5] & 0xffffffff))
        wet_index = RPR_TrackFX_GetParamFromIdent(track, index, ":wet")
        effects.append({"name": RPR_TrackFX_GetFXName(track, index, "", 512)[3],
                        "preset": RPR_TrackFX_GetPreset(track, index, "", 512)[3],
                        "preset_index": RPR_TrackFX_GetPresetIndex(track, index, 0)[0],
                        "enabled": bool(RPR_TrackFX_GetEnabled(track, index)),
                        "offline": bool(RPR_TrackFX_GetOffline(track, index)),
                        "parameters": [RPR_TrackFX_GetParamNormalized(track, index, p) for p in range(RPR_TrackFX_GetNumParams(track, index))],
                        "wet": RPR_TrackFX_GetParamNormalized(track, index, wet_index) if wet_index >= 0 else None,
                        "io": io[3:5], "pins": pins})
    return effects


def without_fx(chunk):
    fx = recording_fx_chunk(chunk)
    return chunk.replace(fx, "", 1) if fx else chunk


try:
    assert Path(RPR_GetResourcePath()).resolve() == OUTPUT.resolve(), "Temporary -cfgfile required"
    project = RPR_EnumProjects(-1, "", 32768)[0]
    assert RPR_CountTracks(project) == 0, "New empty temporary project required"
    tree = ast.parse((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[f for f in tree.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), "fx-regression", "exec"), globals())
    for label, source_index, destination_index in (("guitar", 9, 13), ("midi", 10, 14)):
        source_chunk = (OUTPUT / f"work-track-{source_index}.txt").read_text(encoding="utf-8")
        destination_chunk = (OUTPUT / f"work-track-{destination_index}.txt").read_text(encoding="utf-8")
        insert = RPR_CountTracks(project)
        RPR_InsertTrackAtIndex(insert, False)
        RPR_InsertTrackAtIndex(insert + 1, False)
        src, dst = RPR_GetTrack(project, insert), RPR_GetTrack(project, insert + 1)
        channels = re.search(r"(?m)^NCHAN \d+", source_chunk)[0]
        minimal = '<TRACK\nNAME "Source ' + label + '"\n' + channels + '\n' + recording_fx_chunk(source_chunk) + '>\n'
        assert RPR_SetTrackStateChunk(src, minimal, False)
        assert RPR_SetTrackStateChunk(dst, destination_chunk, False)
        # Add destination-only routing/automation to the fixture; never to work tracks.
        RPR_CreateTrackSend(src, dst)
        configured = read_recording_chunk(dst)
        envelope = '<VOLENV2\nACT 1 -1\nVIS 0 1 1\nARM 0\nDEFSHAPE 0 -1 -1\nPT 0 1 0\n>\n'
        assert RPR_SetTrackStateChunk(dst, configured[:configured.rfind('>')] + envelope + '>\n', False)
        before = read_recording_chunk(dst)
        source_before = read_recording_chunk(src)
        api_before = musical_state(src)
        (OUTPUT / f"{label}-source-before.txt").write_text(source_before, encoding="utf-8")
        native_copy = RPR_TrackFX_CopyToTrack
        def capture(src_track, fx_index, dst_track, dst_index, move):
            native_copy(src_track, fx_index, dst_track, dst_index, move)
            if RPR_TrackFX_GetCount(dst_track) == RPR_TrackFX_GetCount(src_track):
                (OUTPUT / f"{label}-before-rollback.txt").write_text(read_recording_chunk(dst_track), encoding="utf-8")
        RPR_TrackFX_CopyToTrack = capture
        result = handle_copy_track_fx_chain({"source_track_index": insert + 1, "track_index": insert + 2})
        RPR_TrackFX_CopyToTrack = native_copy
        applied = (OUTPUT / f"{label}-before-rollback.txt").read_text(encoding="utf-8")
        a = comparable_fx_chunk(recording_fx_chunk(source_before)).splitlines()
        b = comparable_fx_chunk(recording_fx_chunk(applied)).splitlines()
        changes = []
        for line in difflib.unified_diff(a, b, n=0):
            if line.startswith(("---", "+++", "@@")):
                changes.append(line)
            elif len(line) > 160 or re.fullmatch(r"[+-][A-Za-z0-9+/=]{16,}", line):
                changes.append(f"{line[0]} payload line: {len(line)-1} chars, sha256={hashlib.sha256(line[1:].encode()).hexdigest()}")
            else:
                changes.append(line)
        chain_report = {"chain": label, "result": result, "diff": changes,
                                 "rollback_exact": read_recording_chunk(dst).replace(recording_fx_chunk(read_recording_chunk(dst)), "", 1) == before.replace(recording_fx_chunk(before), "", 1) if not result.get("success") else None,
                                 "plugins": get_track_fx_entries(src)}
        report["chains"].append(chain_report)
        assert result.get('success'), result
        original_match, original_labels = verify_copied_fx_state(src, dst, recording_fx_chunk(source_chunk), recording_fx_chunk(applied))
        assert original_match, 'Original live serialized state did not match copied state'
        chain_report['original_live_snapshot_match'] = original_match
        chain_report['original_live_normalized_labels'] = original_labels
        chain_report['musical_api_exact'] = musical_state(dst) == api_before
        assert chain_report['musical_api_exact']
        chain_report['source_preserved'] = comparable_recording_source(read_recording_chunk(src)) == comparable_recording_source(source_before)
        assert chain_report['source_preserved']
        chain_report['destination_non_fx_preserved'] = re.sub(r'(?m)^NCHAN \d+', 'NCHAN', without_fx(read_recording_chunk(dst))) == re.sub(r'(?m)^NCHAN \d+', 'NCHAN', without_fx(before))
        assert chain_report['destination_non_fx_preserved']
        occupied = read_recording_chunk(dst)
        rejected = handle_copy_track_fx_chain({"source_track_index": insert + 1, "track_index": insert + 2})
        assert 'error' in rejected and read_recording_chunk(dst) == occupied
        chain_report['occupied_destination_rejected'] = True
        for index in reversed(range(RPR_TrackFX_GetCount(dst))):
            assert RPR_TrackFX_Delete(dst, index)
        original_channels = int(re.search(r'(?m)^NCHAN (\d+)', before)[1])
        RPR_SetMediaTrackInfo_Value(dst, 'I_NCHAN', original_channels)
        for failure in ('partial', 'sonic'):
            def fail_copy(s, i, d, j, move):
                native_copy(s, i, d, j, move)
                if failure == 'partial':
                    raise RuntimeError('Injected failure after first FX')
                if i == RPR_TrackFX_GetCount(s) - 1:
                    RPR_TrackFX_SetEnabled(d, 0, not RPR_TrackFX_GetEnabled(s, 0))
            RPR_TrackFX_CopyToTrack = fail_copy
            failed = handle_copy_track_fx_chain({"source_track_index": insert + 1, "track_index": insert + 2})
            RPR_TrackFX_CopyToTrack = native_copy
            assert 'error' in failed and failed.get('rollback_succeeded'), failed
            assert without_fx(read_recording_chunk(dst)) == without_fx(before)
            chain_report[f'{failure}_failure_rollback'] = failed
        assert RPR_SetMediaTrackInfo_Value(src, 'I_CUSTOMCOLOR', 16576)
        color = handle_set_track_color({'track_index': insert + 2, 'source_track_index': insert + 1})
        assert color.get('success') and color['color_raw'] == 16576 and not color['custom'], color
        chain_report['default_color'] = color
    report["success"] = True
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()
(OUTPUT / "host-regression.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
