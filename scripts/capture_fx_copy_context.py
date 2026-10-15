"""Read-only snapshot of the explicitly authorized FiruletMap project for diagnosis."""
from reaper_python import *  # noqa: F403
import ast
import json
from pathlib import Path
import traceback

ROOT = Path(RPR_GetExtState("reaper-fx-probe", "repository"))
OUTPUT = ROOT / ".local/fx-copy-validation"
EXPECTED = Path(r"C:\Code\spec-driven-creation\firulet-map\clips-source\clips-source.rpp")
report = {}
try:
    project, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    assert Path(path).resolve() == EXPECTED.resolve(), "Authorized project must already be active"
    assert RPR_GetPlayStateEx(project) == 0, "Project must be stopped"
    tree = ast.parse((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[f for f in tree.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), "read-only-fx-context", "exec"), globals())
    report = {"project_path": path, "project_id": str(project), "tracks": [], "host": RPR_GetAppVersion()}
    for i in range(RPR_CountTracks(project)):
        track = RPR_GetTrack(project, i)
        _, name = get_track_identity(track)
        guid = recording_track_guid(track)
        parent = RPR_GetParentTrack(track)
        parent_name = RPR_GetTrackName(parent, "", 512)[2] if RPR_ValidatePtr2(project, parent, "MediaTrack*") else None
        chunk = read_recording_chunk(track)
        (OUTPUT / f"work-track-{i + 1}.txt").write_text(chunk, encoding="utf-8")
        report["tracks"].append({"index": i + 1, "name": name, "guid": guid,
                                 "parent_name": parent_name, "parent_guid": recording_track_guid(parent) if parent_name else None,
                                 "fx": get_track_fx_entries(track), "color": read_track_color(track)})
    for name, parent in (("GTR-8s__FM-003", "FM-003"), ("MIDI_FM-003", "FM-003"),
                         ("GTR-8s__FM-004", "FM-004"), ("MIDI_FM-004", "FM-004")):
        matches = [t for t in report["tracks"] if t["name"] == name and t["parent_name"] == parent]
        assert len(matches) == 1, f"Track/folder identity is ambiguous: {name}"
        if parent == "FM-004":
            assert not matches[0]["fx"], f"Destination is occupied: {name}"
    report["success"] = True
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()
(OUTPUT / "work-context.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
