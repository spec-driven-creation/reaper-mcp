import copy
import json
import unittest
from unittest.mock import patch

from reaper_mcp import server
import test_note_items


class ItemNotesTests(unittest.TestCase):
    def setUp(self):
        fixture = test_note_items.NoteItemTests()
        fixture.setUp()
        self.fixture = fixture
        self.n = fixture.n
        self.n.update({
            "RPR_GetActiveTake": lambda item: "take" if item["takes"] else None,
            "RPR_GetTakeName": lambda _: "Take name",
            "get_take_source_type": lambda _: "MIDI",
        })

    def test_complete_text_with_and_without_takes_and_unchanged_state(self):
        texts = ["", "line one\nline two\r\n", "  armonía ♯ 日本語 🎵  ", "á\n" * 40000]
        for takes in (0, 1):
            for text in texts:
                with self.subTest(takes=takes, length=len(text)):
                    self.fixture.tracks[1].clear()
                    item = self.fixture.add_item(1)
                    item.update(P_NOTES=text, takes=takes, B_UISEL=1)
                    before = copy.deepcopy(self.fixture.tracks)
                    with patch.dict(self.n, RPR_GetSetMediaItemInfo_String=self.read_only_string):
                        plain = self.n["handle_get_track_items"]({"track_index": 1})
                        detailed = self.n["handle_get_track_items"]({"track_index": 1, "include_notes": True})
                        info = self.n["handle_get_item_info"]({"track_index": 1, "item_index": 1})
                    self.assertNotIn("notes", plain["items"][0])
                    self.assertEqual(detailed["items"][0], {**plain["items"][0], "notes": text})
                    self.assertEqual(info["notes"], text)
                    self.assertEqual(json.loads(json.dumps(info))["notes"], text)
                    self.assertEqual(info["take_count"], takes)
                    self.assertEqual(self.fixture.tracks, before)
                    self.assertEqual(self.fixture.events, [])

    def read_only_string(self, item, key, value, write):
        self.assertIs(write, False)
        self.assertEqual(value, "")
        return self.fixture.item_string(item, key, value, write)

    def test_all_track_items_and_default_does_not_read_notes(self):
        for index in range(83):
            self.fixture.add_item(1)["P_NOTES"] = f"nota {index}\n♯"
        result = self.n["handle_get_track_items"]({"track_index": 1, "include_notes": True})
        self.assertEqual(result["item_count"], 83)
        self.assertEqual([i["item_index"] for i in result["items"]], list(range(1, 84)))
        self.assertEqual([i["notes"] for i in result["items"]], [i["P_NOTES"] for i in self.fixture.tracks[1]])
        self.n["get_item_notes"] = lambda _: self.fail("Notes read without opt-in")
        self.n["handle_get_track_items"]({"track_index": 1})
        self.assertEqual(self.n["handle_get_track_items"]({"track_index": 2, "include_notes": True})["items"], [])

    def test_invalid_indexes_and_option(self):
        self.fixture.add_item(1)
        for value in (None, True, "1", 0, -1, 3):
            self.assertIn("error", self.n["handle_get_track_items"]({"track_index": value, "include_notes": True}))
        for value in (None, True, "1", 0, -1, 2):
            self.assertIn("error", self.n["handle_get_item_info"]({"track_index": 1, "item_index": value}))
        for value in (None, 0, 1, "true"):
            self.assertIn("error", self.n["handle_get_track_items"]({"track_index": 1, "include_notes": value}))

    def test_api_failure_is_not_empty_notes(self):
        self.fixture.add_item(1)
        original = self.fixture.item_string
        self.n["RPR_GetSetMediaItemInfo_String"] = lambda item, key, value, write: (False, item, key, "", write) if key == "P_NOTES" else original(item, key, value, write)
        for handler, request in (("handle_get_item_info", {"track_index": 1, "item_index": 1}),
                                 ("handle_get_track_items", {"track_index": 1, "include_notes": True})):
            result = self.n[handler](request)
            self.assertIn("P_NOTES", result["error"])
            self.assertEqual(result["item_index"], 1)

    def test_mcp_forwards_option_and_defaults(self):
        with patch.object(server, "send_reaper_command", return_value={}) as send:
            server.get_track_items(9)
            send.assert_called_with("get_track_items", track_index=9, include_notes=False)
            server.get_track_items(9, include_notes=True)
            send.assert_called_with("get_track_items", track_index=9, include_notes=True)
            server.get_item_info(9, 1)
            send.assert_called_with("get_item_info", track_index=9, item_index=1)
