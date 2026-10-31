"""Read-only live Notes Harmony probe; run as a Python ReaScript in REAPER."""
from reaper_python import *  # noqa: F403
import ast
import hashlib
import json
import math
from pathlib import Path
import traceback

ROOT = Path(RPR_GetExtState("reaper-mcp-item-notes-validation", "repository"))
OUT = ROOT / ".local/item-notes-validation"
OUT.mkdir(parents=True, exist_ok=True)
report = {}
try:
    tree = ast.parse((ROOT / "reaper/mcp_bridge.py").read_text(encoding="utf-8"))
    namespace = dict(globals())
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
                            type_ignores=[]), "bridge-probe", "exec"), namespace)
    project = RPR_EnumProjects(-1, "", 32768)[0]

    def context():
        return {
            "project": RPR_EnumProjects(-1, "", 32768),
            "changes": RPR_GetProjectStateChangeCount(project),
            "dirty": RPR_IsProjectDirty(project),
            "play_state": RPR_GetPlayState(),
            "cursor": RPR_GetCursorPosition(),
            "selected_tracks": [str(RPR_GetSelectedTrack(0, i)) for i in range(RPR_CountSelectedTracks(0))],
            "selected_items": [namespace["get_item_identity"](RPR_GetSelectedMediaItem(0, i)) for i in range(RPR_CountSelectedMediaItems(0))],
        }

    before = context()
    assert before["project"][2].lower().endswith("turbulence.rpp")
    matches = [t for t in namespace["handle_get_tracks"]({})["tracks"] if t["name"] == "Notes Harmony"]
    assert len(matches) == 1
    index = matches[0]["index"]
    plain = namespace["handle_get_track_items"]({"track_index": index})
    result = namespace["handle_get_track_items"]({"track_index": index, "include_notes": True})
    assert result["item_count"] == 83
    for old, item in zip(plain["items"], result["items"]):
        info = namespace["handle_get_item_info"]({"track_index": index, "item_index": item["item_index"]})
        assert info["notes"] == item["notes"] and info["take_count"] == 0
        assert {k: v for k, v in item.items() if k != "notes"} == old
    assert context() == before
    (OUT / "items.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"success": True, "host": RPR_GetAppVersion(), "track_index": index,
              "track_name": result["track_name"], "item_count": result["item_count"],
              "nonempty_notes": sum(bool(i["notes"]) for i in result["items"]),
              "notes_sha256": hashlib.sha256(json.dumps([i["notes"] for i in result["items"]], ensure_ascii=False).encode()).hexdigest(),
              "context_preserved": True, "play_state": before["play_state"]}
except Exception:
    report = {"success": False, "traceback": traceback.format_exc()}
(OUT / "host-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
