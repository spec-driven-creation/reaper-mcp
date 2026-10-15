import ast
import re
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from reaper_mcp import server


BRIDGE = Path(__file__).parents[1] / "reaper/mcp_bridge.py"


def load_functions(namespace):
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace.update(re=re, uuid=uuid)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(BRIDGE), "exec"), namespace)
    return namespace


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.values = {1: {"I_CUSTOMCOLOR": 0x1030201, "I_RECINPUT": 0, "I_RECMON": 2},
                       2: {"I_CUSTOMCOLOR": 0, "I_RECINPUT": -1, "I_RECMON": 0}}
        self.writes = []
        self.chunks = {
            1: '<TRACK\nNCHAN 4\n<FXCHAIN\nSHOW 0\nBYPASS 1 1 0\n<VST "test"\nopaque_state\n>\nFXID {SRC}\nWAK 0 0\n>\n>\n',
            2: '<TRACK\nNCHAN 2\n<ITEM\n<SOURCE MIDI\nE 0 90 3c 7f\n>\n>\n>\n'}
        self.counts = {1: 1, 2: 0}
        self.n = load_functions({
            "RPR_CountTracks": lambda _: 2,
            "RPR_GetTrack": lambda _, i: i + 1,
            "RPR_ValidatePtr2": lambda *_: True,
            "RPR_GetTrackGUID": lambda t: str(t),
            "RPR_GetSetMediaTrackInfo_String": lambda t, *_: (True, t, "GUID", str(t), False),
            "RPR_GetTrackName": lambda t, *_: (True, t, f"Track {t}", 512),
            "RPR_GetMediaTrackInfo_Value": self.get_value,
            "RPR_SetMediaTrackInfo_Value": self.set_value,
            "RPR_ColorFromNative": lambda v, *_: (v, v & 255, (v >> 8) & 255, (v >> 16) & 255),
            "RPR_GetNumAudioInputs": lambda: 2,
            "RPR_GetInputChannelName": lambda i: f"Input {i + 1}",
            "RPR_GetMIDIInputName": lambda *_: (False, 0, "", 512),
            "RPR_Undo_BeginBlock2": lambda *_: None,
            "RPR_Undo_EndBlock2": lambda *_: None,
            "RPR_TrackList_AdjustWindows": lambda *_: None,
            "RPR_TrackFX_GetCount": lambda t: self.counts[t],
            "RPR_TrackFX_GetRecCount": lambda t: 0,
            "RPR_GetTrackStateChunk": lambda t, _, size, undo: (True, t, self.chunks[t], size, undo),
            "RPR_SetTrackStateChunk": self.set_chunk,
            "RPR_TrackFX_CopyToTrack": self.copy_fx,
            "RPR_TrackFX_Delete": self.delete_fx,
        })

    def get_value(self, track, key):
        if key == "IP_TRACKNUMBER":
            return track
        if key == "I_NCHAN":
            return int(re.search(r"NCHAN (\d+)", self.chunks[track])[1])
        return self.values[track][key]

    def set_value(self, track, key, value):
        self.writes.append((track, key, value))
        if key == "I_NCHAN":
            self.chunks[track] = re.sub(r"NCHAN \d+", f"NCHAN {int(value)}", self.chunks[track])
        else:
            self.values[track][key] = value
        return True

    def copy_fx(self, source, index, destination, position, move):
        self.assertFalse(move)
        fx = self.n["portable_fx_chunk"](self.n["recording_fx_chunk"](self.chunks[source]))
        self.set_chunk(destination, self.chunks[destination][:-2] + fx + ">\n", False)

    def delete_fx(self, track, index):
        fx = self.n["recording_fx_chunk"](self.chunks[track])
        self.chunks[track] = self.chunks[track].replace(fx, "")
        self.counts[track] = 0
        return True

    def set_chunk(self, track, chunk, undo):
        self.writes.append((track, "chunk"))
        self.chunks[track] = chunk
        self.counts[track] = int("<FXCHAIN" in chunk)
        return True

    def call(self, command, **request):
        return self.n["handle_" + command](request)

    def test_color_exact_copy_default_and_rgb(self):
        result = self.call("set_track_color", track_index=2, source_track_index=1)
        self.assertTrue(result["success"])
        self.assertEqual(result["rgb"], [1, 2, 3])
        self.assertTrue(result["custom"])
        result = self.call("set_track_color", track_index=2, color_raw=0)
        self.assertFalse(result["custom"])
        self.assertIsNone(result["rgb"])

    def test_invalid_targets_and_stale_guid_do_not_write(self):
        for index in (0, 3, True, "1"):
            self.assertIn("error", self.call("set_track_color", track_index=index, color_raw=0))
        self.assertIn("error", self.call("set_track_color", track_index=2, track_guid="old", color_raw=0))
        self.n["RPR_ValidatePtr2"] = lambda *_: False
        self.assertIn("error", self.call("get_track_color", track_index=1))
        self.assertEqual(self.writes, [])

    def test_fx_complete_state_preserves_items_and_source(self):
        source, destination = self.chunks[1], self.chunks[2]
        result = self.call("copy_track_fx_chain", source_track_index=1, track_index=2)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.chunks[1], source)
        self.assertIn("opaque_state", self.chunks[2])
        self.assertIn("BYPASS 1 1 0", self.chunks[2])
        self.assertIn(destination[destination.index("<ITEM"):destination.rfind(">")], self.chunks[2])
        self.assertNotIn("FXID {SRC}", self.chunks[2])

    def test_existing_destination_fx_rejected_before_write(self):
        self.counts[2] = 1
        self.assertIn("error", self.call("copy_track_fx_chain", source_track_index=1, track_index=2))
        self.assertEqual(self.writes, [])

    def test_same_track_and_input_fx_destination_rejected(self):
        self.assertIn("error", self.call("copy_track_fx_chain", source_track_index=1, track_index=1))
        self.n["RPR_TrackFX_GetRecCount"] = lambda _: 1
        self.assertIn("error", self.call("copy_track_fx_chain", source_track_index=1, track_index=2))
        self.assertEqual(self.writes, [])

    def test_chunk_buffer_bound_and_unavailable_snapshot(self):
        def unavailable(track, text, size, undo):
            self.assertEqual(size, 4 * 1024 * 1024)
            return False, track, "", size, undo
        self.n["RPR_GetTrackStateChunk"] = unavailable
        self.assertIn("error", self.call("copy_track_fx_chain", source_track_index=1, track_index=2))
        self.assertEqual(self.writes, [])

    def test_source_parameter_automation_rejected_before_write(self):
        self.chunks[1] = self.chunks[1].replace("FXID {SRC}", "<PARMENV 0\nPT 0 1\n>\nFXID {SRC}")
        self.assertIn("error", self.call("copy_track_fx_chain", source_track_index=1, track_index=2))
        self.assertEqual(self.writes, [])

    def test_native_copy_exception_and_rollback_failure_reported(self):
        def fail_copy(*args):
            self.copy_fx(*args)
            raise RuntimeError("native copy failed after insert")
        self.n["RPR_TrackFX_CopyToTrack"] = fail_copy
        self.n["RPR_TrackFX_Delete"] = lambda *_: False
        result = self.call("copy_track_fx_chain", source_track_index=1, track_index=2)
        self.assertIn("error", result)
        self.assertFalse(result["rollback_succeeded"])

    def test_partial_fx_failure_restores_destination(self):
        original = self.chunks[2]
        def corrupt(*args):
            self.copy_fx(*args)
            self.chunks[2] = self.chunks[2].replace("opaque_state", "corrupted")
        self.n["RPR_TrackFX_CopyToTrack"] = corrupt
        self.n["RPR_SetTrackStateChunk"] = lambda *_: False
        result = self.call("copy_track_fx_chain", source_track_index=1, track_index=2)
        self.assertIn("error", result)
        self.assertTrue(result["rollback_succeeded"])
        self.assertEqual(self.chunks[2], original)

    def test_automation_excluded_links_rejected(self):
        fx = '<FXCHAIN\n<PARMENV 0\nPT 0 1\n>\n<VST test\nopaque\n>\n>\n'
        self.assertNotIn("PARMENV", self.n["portable_fx_chunk"](fx))
        self.assertIn("opaque", self.n["portable_fx_chunk"](fx))
        with self.assertRaises(RuntimeError):
            self.n["portable_fx_chunk"]('<FXCHAIN\nPLINK 1 1 0\n>\n')

    def test_audio_input_availability_and_replication(self):
        for raw in (-1, 0, 1, 1024):
            self.assertTrue(self.call("set_track_record_input", track_index=2, record_input_raw=raw)["success"])
        result = self.call("set_track_record_input", track_index=2, source_track_index=1)
        self.assertEqual(result["name"], "Input 1")
        self.writes.clear()
        for raw in (2, 1025, 2048, 4096, True, -2):
            self.assertIn("error", self.call("set_track_record_input", track_index=2, record_input_raw=raw))
        self.assertEqual(self.writes, [])

    def test_monitoring_modes_do_not_arm(self):
        for mode, raw in (("off", 0), ("on", 1), ("auto", 2)):
            result = self.call("set_track_record_monitoring", track_index=2, mode=mode)
            self.assertTrue(result["success"])
            self.assertEqual(result["record_monitoring_raw"], raw)
        self.assertTrue(all(key == "I_RECMON" for _, key, _ in self.writes))
        self.assertIn("error", self.call("set_track_record_monitoring", track_index=2, mode="invalid"))

    def test_failed_write_readback_rolls_back(self):
        self.n["RPR_SetMediaTrackInfo_Value"] = lambda *_: True
        result = self.call("set_track_record_monitoring", track_index=2, mode="on")
        self.assertIn("error", result)
        self.assertTrue(result["rollback_succeeded"])

    def test_project_without_path_never_calls_save(self):
        self.n["RPR_EnumProjects"] = lambda *_: ("project", -1, "", 32768)
        self.n["RPR_Main_SaveProject"] = lambda *_: self.fail("Must not open save dialog")
        self.assertIn("error", self.call("save_project"))

    def test_save_checks_dirty_and_identity(self):
        self.n["RPR_EnumProjects"] = lambda *_: ("project", -1, "test.rpp", 32768)
        self.n["RPR_Main_SaveProject"] = lambda *_: None
        self.n["RPR_IsProjectDirty"] = lambda _: 0
        self.assertTrue(self.call("save_project")["success"])
        self.n["RPR_IsProjectDirty"] = lambda _: 1
        self.assertIn("error", self.call("save_project"))

    def test_mcp_wrappers_forward_contract(self):
        names = ("get_track_color", "set_track_color", "copy_track_fx_chain",
                 "get_track_record_input", "set_track_record_input",
                 "get_track_record_monitoring", "set_track_record_monitoring", "save_project")
        for name in names:
            with self.subTest(name=name), patch.object(server, "send_reaper_command", return_value={"ok": True}) as send:
                args = {"track_index": 2} if name != "save_project" else {}
                if name == "copy_track_fx_chain":
                    args["source_track_index"] = 1
                if name == "set_track_record_monitoring":
                    args["mode"] = "off"
                self.assertEqual(getattr(server, name)(**args), {"ok": True})
                self.assertEqual(send.call_args.args, (name,))
                for key, value in args.items():
                    self.assertEqual(send.call_args.kwargs[key], value)
