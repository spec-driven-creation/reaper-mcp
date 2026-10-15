"""Host probe for exact text items and GUID deletion, in an isolated instance only."""
from reaper_python import *  # noqa: F403
import ast
import json
import math
from pathlib import Path
import traceback


ROOT = Path(RPR_GetExtState("reaper-mcp-note-validation", "repository"))
OUTPUT = ROOT / ".local/note-item-validation"
report = {"host": RPR_GetAppVersion(), "checks": []}


def check(label, condition, details=None):
    report["checks"].append({"check": label, "passed": bool(condition), "details": details})
    (OUTPUT / "host-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not condition:
        raise AssertionError(f"{label}: {details}")


def operation_context():
    return {
        "project": RPR_EnumProjects(-1, "", 32768)[0],
        "cursor": RPR_GetCursorPositionEx(project),
        "transport": RPR_GetPlayStateEx(project),
        "tempo": RPR_Master_GetTempo(),
        "time_signature": RPR_GetProjectTimeSignature2(project, 0, 0)[1:],
        "time_selection": RPR_GetSet_LoopTimeRange2(project, False, False, 0, 0, False)[3:5],
        "selected_tracks": [recording_track_guid(RPR_GetSelectedTrack(project, i)) for i in range(RPR_CountSelectedTracks(project))],
        "selected_items": [get_item_identity(RPR_GetSelectedMediaItem(project, i)) for i in range(RPR_CountSelectedMediaItems(project))],
    }


def item_chunks():
    result = {}
    for track_index in range(RPR_CountTracks(project)):
        track = RPR_GetTrack(project, track_index)
        for item_index in range(RPR_CountTrackMediaItems(track)):
            item = RPR_GetTrackMediaItem(track, item_index)
            chunk = RPR_GetItemStateChunk(item, "", 4 * 1024 * 1024, False)
            assert chunk[0]
            result[get_item_identity(item)] = chunk[2]
    return result


try:
    # Fail before any project mutation when launched from a normal work session.
    assert Path(RPR_GetResourcePath()).resolve() == OUTPUT.resolve(), "Use an isolated -cfgfile under .local/note-item-validation"
    project, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    assert not path and RPR_CountTracks(project) == 0, "Probe requires a new empty temporary project"
    tree = ast.parse((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[f for f in tree.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), "bridge-note-host-probe", "exec"), globals())
    RPR_Undo_BeginBlock2(project)
    RPR_InsertTrackAtIndex(0, False)
    RPR_InsertTrackAtIndex(1, False)
    notes, other = RPR_GetTrack(project, 0), RPR_GetTrack(project, 1)
    RPR_GetSetMediaTrackInfo_String(notes, "P_NAME", "Notes", True)
    RPR_GetSetMediaTrackInfo_String(other, "P_NAME", "Neighbor MIDI", True)
    RPR_SetCurrentBPM(project, 123.45, False)
    neighbor = RPR_CreateNewMIDIItemInProj(other, 10.25, 11.375, False)[0]
    RPR_MIDI_InsertNote(RPR_GetActiveTake(neighbor), False, False, 0, 240, 0, 65, 100, False)
    RPR_SetMediaItemSelected(neighbor, True)
    RPR_SetOnlyTrackSelected(other)
    RPR_SetEditCurPos2(project, 0.625, False, False)
    RPR_GetSet_LoopTimeRange2(project, True, False, 2, 7, False)
    RPR_Undo_EndBlock2(project, "Prepare isolated note-item fixture", -1)
    baseline_context, baseline_items = operation_context(), item_chunks()
    guids = []
    for start, text in zip((0, 1.5, 3, 4.5), ("C4", "C#4", "D4", "D#4")):
        before = item_chunks()
        result = handle_create_note_item({"track_index": 1, "text": text, "start_seconds": start, "duration_seconds": 1})
        check(f"create at {start} seconds", result.get("success") and result["start_seconds"] == start and result["duration_seconds"] == 1 and result["end_seconds"] == start + 1, result)
        guid = result["item_guid"]
        guids.append(guid)
        item = find_item_by_guid(notes, guid)
        check(f"text and no takes at {start}", RPR_GetSetMediaItemInfo_String(item, "P_NOTES", "", False)[3] == text and RPR_CountTakes(item) == 0)
        check(f"context and neighbors at {start}", operation_context() == baseline_context and all(item_chunks()[g] == chunk for g, chunk in before.items()))
        undo_label = RPR_Undo_CanUndo2(project)
        undo_result = RPR_Undo_DoUndo2(project)
        after_undo = item_chunks()
        check(f"creation Undo at {start}", undo_label == "Create note item" and undo_result != 0 and after_undo == before,
              {"undo_label": undo_label, "undo_result": undo_result, "before_guids": list(before), "after_guids": list(after_undo)})
        check(f"creation Redo at {start}", RPR_Undo_DoRedo2(project) != 0 and find_item_by_guid(notes, guid) is not None)
    before = item_chunks()
    legacy = handle_create_note_item({"track_index": 1, "text": "Am7", "start_measure": 8, "duration_measures": 2})
    check("legacy measures", legacy.get("success") and math.isclose(legacy["start_seconds"], get_measure_boundary(8), abs_tol=1e-9) and math.isclose(legacy["end_seconds"], get_measure_boundary(10), abs_tol=1e-9), legacy)
    check("legacy Undo", RPR_Undo_DoUndo2(project) != 0 and item_chunks() == before)
    invalid = [
        {"start_seconds": -1, "duration_seconds": 1},
        {"start_seconds": 0, "duration_seconds": 0},
        {"start_seconds": float("nan"), "duration_seconds": 1},
        {"start_seconds": 0, "duration_seconds": float("inf")},
        {"start_seconds": 0}, {"duration_seconds": 1},
        {"start_measure": 1}, {"start_seconds": 0, "duration_measures": 1},
        {"start_seconds": 0, "duration_seconds": 1, "start_measure": 1, "duration_measures": 1},
        {"start_seconds": 0.5, "duration_seconds": 1},
    ]
    for index, args in enumerate(invalid):
        before, undo_label = item_chunks(), RPR_Undo_CanUndo2(project)
        result = handle_create_note_item({"track_index": 1, "text": "invalid", **args})
        check(f"reject invalid/overlap {index}", "error" in result and item_chunks() == before and RPR_Undo_CanUndo2(project) == undo_label, result)
    before = item_chunks()
    result = handle_delete_item({"track_index": 2, "item_guid": guids[1]})
    check("wrong track rejected", result.get("error") == "item_track_mismatch" and item_chunks() == before, result)
    result = handle_delete_item({"track_index": 1, "item_guid": "{00000000-0000-0000-0000-000000000000}"})
    check("missing GUID rejected", result.get("error") == "item_guid_not_found" and item_chunks() == before, result)
    result = handle_delete_item({"track_index": 1, "item_guid": guids[1]})
    after = item_chunks()
    check("delete only requested GUID", result.get("success") and result["deleted_item_guid"] == guids[1] and guids[1] not in after and after == {g: chunk for g, chunk in before.items() if g != guids[1]}, result)
    check("deletion context preserved", operation_context() == baseline_context)
    check("deletion Undo", RPR_Undo_CanUndo2(project) == "Delete item by GUID" and RPR_Undo_DoUndo2(project) != 0 and item_chunks() == before)
    check("deletion Undo context preserved", operation_context() == baseline_context)
    check("original MIDI neighbor intact", all(item_chunks()[g] == chunk for g, chunk in baseline_items.items()))
    RPR_Main_SaveProjectEx(project, str(OUTPUT / "note-items.rpp"), 8)
    check("save disposable evidence", not RPR_IsProjectDirty(project))
    report["success"] = True
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()
finally:
    (OUTPUT / "host-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
