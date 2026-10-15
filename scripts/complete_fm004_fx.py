"""Finite, identity-guarded execution of the two explicitly authorized FM-004 copies."""
from reaper_python import *  # noqa: F403
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import traceback
import uuid
import base64

ROOT = Path(RPR_GetExtState("reaper-fx-probe", "repository"))
OUTPUT = ROOT / ".local/fx-copy-validation"
EXPECTED = Path(r"C:\Code\spec-driven-creation\firulet-map\clips-source\clips-source.rpp")
report, copied = {"copies": []}, []


def project_context():
    return {"cursor": RPR_GetCursorPositionEx(project), "transport": RPR_GetPlayStateEx(project),
            "tempo": RPR_Master_GetTempo(), "signature": RPR_GetProjectTimeSignature2(project, 0, 0)[1:],
            "time_selection": RPR_GetSet_LoopTimeRange2(project, False, False, 0, 0, False)[3:5],
            "tracks_selected": [recording_track_guid(RPR_GetSelectedTrack(project, i)) for i in range(RPR_CountSelectedTracks(project))],
            "items_selected": [get_item_identity(RPR_GetSelectedMediaItem(project, i)) for i in range(RPR_CountSelectedMediaItems(project))]}


def snapshot():
    return {recording_track_guid(RPR_GetTrack(project, i)): read_recording_chunk(RPR_GetTrack(project, i))
            for i in range(RPR_CountTracks(project))}


def resolve_authorized(name, folder):
    current, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    assert current == project and Path(path).resolve() == EXPECTED.resolve(), "Active project changed"
    original = [t for t in captured["tracks"] if t["name"] == name and t["parent_name"] == folder]
    assert len(original) == 1
    matches = []
    for i in range(RPR_CountTracks(project)):
        track = RPR_GetTrack(project, i)
        if RPR_GetTrackName(track, "", 512)[2] == name:
            parent = RPR_GetParentTrack(track)
            assert RPR_ValidatePtr2(project, parent, "MediaTrack*")
            assert RPR_GetTrackName(parent, "", 512)[2] == folder
            assert recording_track_guid(parent) == original[0]["parent_guid"]
            assert recording_track_guid(track) == original[0]["guid"], "Track GUID changed"
            matches.append((i + 1, track))
    assert len(matches) == 1, "Track identity ambiguous or missing"
    return matches[0]


try:
    project, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    assert Path(path).resolve() == EXPECTED.resolve(), "Authorized project must already be active"
    assert RPR_GetPlayStateEx(project) == 0, "Transport must be stopped"
    deployed = Path(RPR_GetResourcePath()) / "Scripts/mcp_bridge.py"
    source = deployed.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).digest() == hashlib.sha256((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8").encode()).digest()
    tree = ast.parse(source)
    exec(compile(ast.Module(body=[f for f in tree.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), "deployed-fm004-handlers", "exec"), globals())
    probe = ast.parse((ROOT / "scripts/validate_fx_copy_regression.py").read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[f for f in probe.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), "musical-state-verifier", "exec"), globals())
    captured = json.loads((OUTPUT / "work-context.json").read_text(encoding="utf-8"))
    pairs = [("GTR-8s__FM-003", "GTR-8s__FM-004"), ("MIDI_FM-003", "MIDI_FM-004")]
    for src_name, dst_name in pairs:
        resolve_authorized(src_name, "FM-003")
        _, dst = resolve_authorized(dst_name, "FM-004")
        assert RPR_TrackFX_GetCount(dst) == 0 and RPR_TrackFX_GetRecCount(dst) == 0, "Destination occupied"
    before, context_before = snapshot(), project_context()
    for guid, chunk in before.items():
        (OUTPUT / f"before-completion-{guid.strip('{}')}.txt").write_text(chunk, encoding="utf-8")
    shutil.copy2(EXPECTED, OUTPUT / "clips-source-before-completion.rpp")
    for src_name, dst_name in pairs:
        src_index, src = resolve_authorized(src_name, "FM-003")
        dst_index, dst = resolve_authorized(dst_name, "FM-004")
        assert RPR_TrackFX_GetCount(dst) == 0 and RPR_TrackFX_GetRecCount(dst) == 0
        assert RPR_GetPlayStateEx(project) == 0
        api_before = musical_state(src)
        (OUTPUT / f"live-{dst_name}-source-before.txt").write_text(read_recording_chunk(src), encoding="utf-8")
        native_copy = RPR_TrackFX_CopyToTrack
        def capture_copy(s, i, d, j, move):
            native_copy(s, i, d, j, move)
            if RPR_TrackFX_GetCount(d) == RPR_TrackFX_GetCount(s):
                (OUTPUT / f"live-{dst_name}-before-rollback.txt").write_text(read_recording_chunk(d), encoding="utf-8")
                detail = {"source": musical_state(s), "destination": musical_state(d), "vst_chunks": []}
                for effect in range(RPR_TrackFX_GetCount(s)):
                    blobs = []
                    for target in (s, d):
                        info = RPR_TrackFX_GetNamedConfigParm(target, effect, "vst_chunk", "", 4 * 1024 * 1024)
                        blobs.append({"available": bool(info[0]), "length": len(info[4]), "sha256": hashlib.sha256(info[4].encode()).hexdigest()})
                    detail["vst_chunks"].append(blobs)
                (OUTPUT / f"live-{dst_name}-api.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        RPR_TrackFX_CopyToTrack = capture_copy
        result = handle_copy_track_fx_chain({"source_track_index": src_index, "track_index": dst_index,
                                              "source_track_guid": recording_track_guid(src), "track_guid": recording_track_guid(dst)})
        RPR_TrackFX_CopyToTrack = native_copy
        report["copies"].append(result)
        assert result.get("success"), result
        copied.append((dst, int(re.search(r'(?m)^NCHAN (\d+)', before[recording_track_guid(dst)])[1])))
        assert musical_state(dst) == api_before, "Independent musical API verification failed"
    destination_guids = {recording_track_guid(track) for track, _ in copied}
    after = snapshot()
    assert after.keys() == before.keys(), "Project track identities changed"
    for guid, chunk in before.items():
        if guid in destination_guids:
            assert without_fx(after[guid]) == without_fx(chunk), "Destination non-FX state changed"
        else:
            assert comparable_recording_source(after[guid]) == comparable_recording_source(chunk), "Non-target/source configuration changed"
    assert project_context() == context_before, "Project context changed"
    report["all_track_state_preserved_except_destination_fx"] = True
    report["context_preserved"] = True
    report["save"] = handle_save_project({})
    assert report["save"].get("success") and not report["save"]["dirty"]
    assert Path(report["save"]["project_path"]).resolve() == EXPECTED.resolve()
    report["success"] = True
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()
    if copied:
        for track, channels in reversed(copied):
            for index in reversed(range(RPR_TrackFX_GetCount(track))):
                RPR_TrackFX_Delete(track, index)
            RPR_SetMediaTrackInfo_Value(track, "I_NCHAN", channels)
        RPR_UpdateArrange()
        report["completion_rolled_back"] = True
(OUTPUT / "work-completion.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
