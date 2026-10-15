import ast
import copy
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from reaper_mcp import server


BRIDGE = Path(__file__).parents[1] / "reaper/mcp_bridge.py"


class NoteItemTests(unittest.TestCase):
    def setUp(self):
        self.tracks = {1: [], 2: []}
        self.undo = []
        self.events = []
        self.sequence = 0
        tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        self.n = {"math": math}
        exec(compile(ast.Module(body=[f for f in tree.body if isinstance(f, ast.FunctionDef)], type_ignores=[]), str(BRIDGE), "exec"), self.n)
        self.n.update({
            "RPR_EnumProjects": lambda *_: ("project", -1, "temporary.rpp", 32768),
            "RPR_GetSetProjectInfo_String": lambda *_: (True, "project", "PROJECT_NAME", "temporary.rpp", False),
            "RPR_CountTracks": lambda _: len(self.tracks),
            "RPR_GetTrack": lambda _, index: index + 1,
            "RPR_GetMediaTrackInfo_Value": lambda track, _: track,
            "RPR_GetTrackName": lambda track, *_: (True, track, f"Track {track}", 512),
            "RPR_GetSetMediaTrackInfo_String": lambda track, *_: (True, track, "GUID", f"{{TRACK-{track}}}", False),
            "RPR_ValidatePtr2": lambda _, pointer, kind: pointer is not None,
            "RPR_CountTrackMediaItems": lambda track: len(self.tracks[track]),
            "RPR_GetTrackMediaItem": lambda track, index: self.tracks[track][index],
            "RPR_AddMediaItemToTrack": self.add_item,
            "RPR_GetSetMediaItemInfo_String": self.item_string,
            "RPR_GetMediaItemInfo_Value": lambda item, key: item.get(key, 0),
            "RPR_SetMediaItemInfo_Value": self.set_value,
            "RPR_CountTakes": lambda item: item["takes"],
            "RPR_GetMediaItem_Track": lambda item: item["track"],
            "RPR_DeleteTrackMediaItem": self.delete_item,
            "RPR_Undo_BeginBlock2": self.begin_undo,
            "RPR_Undo_EndBlock2": lambda project, name, flags: self.events.append(("end", project, name, flags)),
            "RPR_UpdateArrange": lambda: self.events.append(("arrange",)),
            "get_measure_boundary": lambda measure: (measure - 1) * 2.0,
            "get_musical_position": lambda seconds: {"musical_position": {"measure": int(seconds // 2) + 1, "beat_within_measure": (seconds % 2) * 2 + 1}},
        })

    def add_item(self, track):
        self.sequence += 1
        item = {"track": track, "GUID": f"{{ITEM-{self.sequence}}}", "P_NOTES": "", "takes": 0,
                "D_POSITION": 0.0, "D_LENGTH": 0.0, "B_UISEL": 0}
        self.tracks[track].append(item)
        return item

    def set_value(self, item, key, value):
        item[key] = value
        return True

    def item_string(self, item, key, value, write):
        if write:
            item[key] = value
        return True, item, key, item[key], write

    def delete_item(self, track, item):
        self.tracks[track].remove(item)
        return True

    def begin_undo(self, project):
        self.assertEqual(project, "project")
        self.undo.append(copy.deepcopy(self.tracks))
        self.events.append(("begin", project))

    def create(self, **args):
        return self.n["handle_create_note_item"]({"track_index": 1, "text": "C4", **args})

    def delete(self, guid, track=1):
        return self.n["handle_delete_item"]({"track_index": track, "item_guid": guid})

    def test_four_exact_seconds_items_text_and_identity(self):
        for i, start in enumerate((0, 1.5, 3, 4.5)):
            text = ("C4", "C#4", "D4", "D#4")[i]
            result = self.create(start_seconds=start, duration_seconds=1, text=text)
            self.assertTrue(result["success"], result)
            self.assertEqual(result["start_seconds"], start)
            self.assertEqual(result["position_seconds"], start)
            self.assertEqual(result["duration_seconds"], 1)
            self.assertEqual(result["end_seconds"], start + 1)
            self.assertEqual(result["text"], text)
            self.assertEqual(result["take_count"], 0)
            self.assertEqual(result["project_path"], "temporary.rpp")
            self.assertEqual(result["project_id"], "project")
            self.assertEqual(result["track_guid"], "{TRACK-1}")
            self.assertEqual(result["item_guid"], self.tracks[1][-1]["GUID"])
        self.assertEqual(len(self.undo), 4)
        self.assertEqual(len([e for e in self.events if e[0] == "end"]), 4)
        self.assertTrue(all(e[-1] == 4 for e in self.events if e[0] == "end"))

    def test_measures_still_use_project_boundaries(self):
        result = self.create(start_measure=3, duration_measures=2)
        self.assertTrue(result["success"])
        self.assertEqual(result["position_seconds"], 4)
        self.assertEqual(result["duration_seconds"], 4)
        self.assertEqual(result["end_seconds"], 8)
        self.assertEqual(result["start_measure"], 3)
        self.assertEqual(result["duration_measures"], 2)

    def test_missing_and_mixed_timing_rejected_without_mutation(self):
        cases = ({}, {"start_seconds": 0}, {"duration_seconds": 1},
                 {"start_measure": 1}, {"duration_measures": 1},
                 {"start_seconds": 0, "duration_measures": 1},
                 {"start_measure": 1, "duration_measures": 1, "start_seconds": 0},
                 {"start_measure": 1, "duration_measures": 1, "start_seconds": 0, "duration_seconds": 1})
        for args in cases:
            with self.subTest(args=args):
                self.assertIn("error", self.create(**args))
        self.assertEqual(self.tracks[1], [])
        self.assertEqual(self.events, [])

    def test_invalid_times_and_text_rejected_without_mutation(self):
        for field in ("start_seconds", "duration_seconds"):
            for value in (None, True, "1", float("inf"), float("-inf"), float("nan"), 10 ** 400, -1):
                args = {"start_seconds": 0, "duration_seconds": 1, field: value}
                with self.subTest(args=args):
                    self.assertIn("error", self.create(**args))
        for args in ({"start_seconds": 0, "duration_seconds": 0},
                     {"start_seconds": 1e308, "duration_seconds": 1e308},
                     {"start_seconds": 1e308, "duration_seconds": 1e-20},
                     {"start_measure": True, "duration_measures": 1},
                     {"start_measure": 10 ** 400, "duration_measures": 1},
                     {"start_measure": 1, "duration_measures": 0}):
            self.assertIn("error", self.create(**args))
        for text in (None, "", "  ", "C4\x00D4"):
            self.assertIn("error", self.create(start_seconds=0, duration_seconds=1, text=text))
        self.assertEqual(self.tracks[1], [])
        self.assertEqual(self.events, [])

    def test_overlap_rejected_and_adjacency_allowed(self):
        self.assertTrue(self.create(start_seconds=0, duration_seconds=1)["success"])
        before = copy.deepcopy(self.tracks)
        count = len(self.undo)
        result = self.create(start_seconds=0.5, duration_seconds=1)
        self.assertEqual(result["error"], "item_overlap")
        self.assertEqual(self.tracks, before)
        self.assertEqual(len(self.undo), count)
        self.assertTrue(self.create(start_seconds=1, duration_seconds=1)["success"])

    def test_invalid_track_or_pointer_rejected(self):
        self.assertIn("error", self.create(track_index=0, start_seconds=0, duration_seconds=1))
        self.n["RPR_ValidatePtr2"] = lambda *_: False
        self.assertIn("error", self.create(start_seconds=0, duration_seconds=1))
        self.assertEqual(self.events, [])

    def test_partial_creation_and_readback_failure_remove_new_item(self):
        for failure in ("write", "text", "takes", "position"):
            with self.subTest(failure=failure):
                self.setUp()
                if failure == "write":
                    self.n["RPR_SetMediaItemInfo_Value"] = lambda *_: False
                elif failure == "text":
                    self.n["RPR_GetSetMediaItemInfo_String"] = lambda item, key, value, write: (True, item, key, "wrong" if key == "P_NOTES" else item[key], write)
                elif failure == "takes":
                    self.n["RPR_CountTakes"] = lambda _: 1
                else:
                    self.n["RPR_GetMediaItemInfo_Value"] = lambda item, key: 99 if key == "D_POSITION" else item.get(key, 0)
                result = self.create(start_seconds=0, duration_seconds=1)
                self.assertIn("error", result)
                self.assertTrue(result["rollback_succeeded"])
                self.assertEqual(self.tracks[1], [])
                self.assertEqual(self.events[-1], ("arrange",))

    def test_readback_zero_duration_is_not_accepted_as_numeric_tolerance(self):
        self.n["RPR_GetMediaItemInfo_Value"] = lambda item, key: 0 if key == "D_LENGTH" else item.get(key, 0)
        result = self.create(start_seconds=0, duration_seconds=1e-10)
        self.assertIn("error", result)
        self.assertTrue(result["rollback_succeeded"])

    def test_delete_guid_only_preserves_neighbors_and_supports_undo(self):
        results = [self.create(start_seconds=start, duration_seconds=1) for start in (0, 1.5, 3, 4.5)]
        self.tracks[1][0]["B_UISEL"] = 1
        before = copy.deepcopy(self.tracks)
        guid = results[1]["item_guid"]
        result = self.delete(guid)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["deleted_item_guid"], guid)
        self.assertEqual(result["project_id"], "project")
        self.assertEqual(self.tracks[1], [item for item in before[1] if item["GUID"] != guid])
        self.tracks = self.undo.pop()
        self.assertEqual(self.tracks, before)
        self.tracks = self.undo.pop()
        self.assertEqual(len(self.tracks[1]), 3)

    def test_wrong_track_and_missing_guid_do_not_start_undo(self):
        result = self.create(start_seconds=0, duration_seconds=1)
        before = copy.deepcopy(self.tracks)
        events = list(self.events)
        self.assertEqual(self.delete(result["item_guid"], 2)["error"], "item_track_mismatch")
        self.assertEqual(self.delete("{MISSING}")["error"], "item_guid_not_found")
        for guid in (None, "", " ", 123):
            self.assertIn("error", self.delete(guid))
        self.assertEqual(self.events, events)
        self.assertEqual(self.tracks, before)

    def test_deletion_requires_native_success_and_actual_absence(self):
        result = self.create(start_seconds=0, duration_seconds=1)
        self.n["RPR_DeleteTrackMediaItem"] = lambda *_: True
        error = self.delete(result["item_guid"])
        self.assertIn("error", error)
        self.assertFalse(error["item_absent"])
        self.assertEqual(len(self.tracks[1]), 1)

    def test_mcp_contract_preserves_positional_and_named_measures_and_seconds(self):
        with patch.object(server, "send_reaper_command", return_value={"success": True}) as send:
            server.create_note_item(1, 3, 2, "Am7")
            self.assertEqual(send.call_args.kwargs["start_measure"], 3)
            self.assertEqual(send.call_args.kwargs["text"], "Am7")
            server.create_note_item(track_index=1, text="C4", start_seconds=1.5, duration_seconds=1)
            self.assertEqual(send.call_args.kwargs["start_seconds"], 1.5)
            self.assertIsNone(send.call_args.kwargs["start_measure"])
            server.delete_item(track_index=1, item_guid="{GUID}")
            send.assert_called_with("delete_item", track_index=1, item_guid="{GUID}")
