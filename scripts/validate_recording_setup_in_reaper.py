"""Finite host acceptance probe. Run as a Python ReaScript, never as MCP code.

Creates its own project tab, writes only under .local/recording-validation,
leaves the disposable tab for inspection, and restores the original active tab.
"""
from reaper_python import *  # noqa: F403
import ast
import json
import math
import re
import traceback
import uuid
from pathlib import Path


ROOT = Path(RPR_GetExtState("reaper-mcp-validation", "repository"))
OUTPUT = ROOT / ".local" / "recording-validation"
OUTPUT.mkdir(parents=True, exist_ok=True)
original_project = RPR_EnumProjects(-1, "", 32768)[0]
report = {"host": RPR_GetAppVersion(), "checks": []}


def check(label, condition, details=None):
    report["checks"].append({"check": label, "passed": bool(condition), "details": details})
    (OUTPUT / "host-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not condition:
        raise AssertionError(f"{label}: {details}")


try:
    tree = ast.parse((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), "bridge-host-probe", "exec"), globals())
    RPR_Main_OnCommand(40859, 0)  # New project tab; existing projects stay untouched.
    test_project = RPR_EnumProjects(-1, "", 32768)[0]
    check("isolated tab", test_project != original_project)
    check("unsaved project rejected", "error" in handle_save_project({}))
    handle_create_track_folder({"name": "Source", "children": ["Guitar source", "MIDI source"]})
    handle_create_track_folder({"name": "Destination", "children": ["Guitar destination", "MIDI destination"]})
    tracks = {i: RPR_GetTrack(0, i - 1) for i in (2, 3, 5, 6)}
    for index, names in ((2, ["bx_tuner", "Ampknob - Trivium Rhythm"]),
                         (3, ["ReaSynth", "bx_tuner"])):
        for name in names:
            fx_index = RPR_TrackFX_AddByName(tracks[index], name, False, -1)
            check("plugin loaded " + name, fx_index >= 0)
            if name == "bx_tuner":
                check("explicit tuner preset", RPR_TrackFX_SetPreset(tracks[index], fx_index, "Default"))
            if name == "ReaSynth":
                check("explicit instrument program", RPR_TrackFX_SetPresetByIndex(tracks[index], fx_index, 0))
    RPR_TrackFX_SetEnabled(tracks[2], 1, False)
    RPR_TrackFX_SetOffline(tracks[3], 1, True)
    RPR_SetMediaTrackInfo_Value(tracks[2], "I_NCHAN", 4)
    RPR_TrackFX_SetPinMappings(tracks[2], 1, 0, 0, 4, 0)
    RPR_TrackFX_SetParamNormalized(tracks[2], 1, RPR_TrackFX_GetParamFromIdent(tracks[2], 1, ":wet"), 0.37)
    for index in (2, 3):
        RPR_SetMediaTrackInfo_Value(tracks[index], "I_CUSTOMCOLOR", RPR_ColorToNative(40 * index, 80, 160) | 0x1000000)
    # MIDI already exists at destination before any replication.
    item = RPR_CreateNewMIDIItemInProj(tracks[6], 0, 4, False)[0]
    take = RPR_GetActiveTake(item)
    RPR_MIDI_InsertNote(take, False, False, 0, 960, 0, 60, 100, False)
    destination_before = read_recording_chunk(tracks[6])
    source_before = {i: read_recording_chunk(tracks[i]) for i in (2, 3)}
    for i in (2, 3):
        (OUTPUT / f"source-before-{i}.txt").write_text(source_before[i], encoding="utf-8")
    native_copy = RPR_TrackFX_CopyToTrack
    def capture_copy(src, index, dst, position, move):
        native_copy(src, index, dst, position, move)
        (OUTPUT / "applied-fx.txt").write_text(read_recording_chunk(dst), encoding="utf-8")
    RPR_TrackFX_CopyToTrack = capture_copy
    def fail_second_copy(src, index, dst, position, move):
        if index == 1:
            raise RuntimeError("Injected host partial-copy failure")
        native_copy(src, index, dst, position, move)
    RPR_TrackFX_CopyToTrack = fail_second_copy
    failed = handle_copy_track_fx_chain({"track_index": 5, "source_track_index": 2})
    check("host partial-copy rollback", "error" in failed and failed.get("rollback_succeeded"), failed)
    RPR_TrackFX_CopyToTrack = capture_copy
    for src, dst in ((2, 5), (3, 6)):
        color = handle_set_track_color({"track_index": dst, "source_track_index": src})
        check("copy color " + str(dst), color.get("success"), color)
        copied = handle_copy_track_fx_chain({"track_index": dst, "source_track_index": src})
        if not copied.get("success"):
            for i in (src, dst):
                (OUTPUT / f"track-{i}.txt").write_text(read_recording_chunk(tracks[i]), encoding="utf-8")
        check("copy full FX " + str(dst), copied.get("success"), copied)
        check("source unchanged " + str(src), comparable_recording_source(read_recording_chunk(tracks[src])) == comparable_recording_source(source_before[src]))
        check("existing FX rejected " + str(dst), "error" in handle_copy_track_fx_chain({"track_index": dst, "source_track_index": src}))
        monitoring = handle_set_track_record_monitoring({"track_index": dst, "mode": "auto"})
        check("monitoring auto " + str(dst), monitoring.get("success"), monitoring)
    check("bypass retained", not RPR_TrackFX_GetEnabled(tracks[5], 1))
    check("offline retained", bool(RPR_TrackFX_GetOffline(tracks[6], 1)))
    check("MIDI item retained", RPR_CountTrackMediaItems(tracks[6]) == 1)
    check("MIDI note retained", RPR_MIDI_CountEvts(RPR_GetActiveTake(RPR_GetTrackMediaItem(tracks[6], 0)), 0, 0, 0)[2] == 1)
    check("MIDI full item state retained", destination_before[destination_before.index("<ITEM"):destination_before.rfind(">")]
          in read_recording_chunk(tracks[6]))
    for mode in ("off", "on", "auto"):
        result = handle_set_track_record_monitoring({"track_index": 5, "mode": mode})
        check("monitor " + mode, result.get("success"), result)
    for raw in (-1, 0, 1024):
        result = handle_set_track_record_input({"track_index": 5, "record_input_raw": raw})
        available = describe_record_input(raw)["available"]
        check("input " + str(raw), result.get("success", False) == available, result)
    result = handle_set_track_record_input({"track_index": 6, "source_track_index": 5})
    check("input replication", result.get("success"), result)
    check("unavailable input rejected", "error" in handle_set_track_record_input({"track_index": 5, "record_input_raw": 1023}))
    check("invalid track rejected", "error" in handle_set_track_color({"track_index": 999, "color_raw": 0}))
    path = str(OUTPUT / "recording-setup.rpp")
    RPR_Main_SaveProjectEx(test_project, path, 8)
    RPR_MarkProjectDirty(test_project)
    saved = handle_save_project({})
    check("save named project", saved.get("success") and not saved["dirty"], saved)
    report["success"] = True
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()
finally:
    RPR_SelectProjectInstance(original_project)
    (OUTPUT / "host-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
