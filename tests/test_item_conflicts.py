import ast
import unittest
from pathlib import Path


BRIDGE_PATH = Path(__file__).parents[1] / "reaper" / "mcp_bridge.py"


def load_get_item_conflicts(items):
    source = BRIDGE_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "get_item_conflicts"
    )

    namespace = {
        "RPR_CountTrackMediaItems": lambda _track: len(items),
        "RPR_GetTrackMediaItem": lambda _track, index: index,
        "get_item_state": lambda item, _index: items[item]
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]),
                str(BRIDGE_PATH), "exec"),
        namespace
    )
    return namespace["get_item_conflicts"]


def item_state(position_seconds, end_seconds):
    return {
        "item_index": 1,
        "guid": "{ITEM-GUID}",
        "position_seconds": position_seconds,
        "end_seconds": end_seconds,
        "start_measure": 31,
        "start_beat": 1.0,
        "end_measure": 35,
        "end_beat": 1.0
    }


class ItemConflictTests(unittest.TestCase):
    def test_sub_picosecond_boundary_drift_is_adjacent(self):
        conflicts = load_get_item_conflicts([
            item_state(42.62068965517241, 48.41379310344827)
        ])("track", 48.413793103447865, 51.310344827585794)

        self.assertEqual(conflicts, [])

    def test_exact_touching_boundary_is_adjacent(self):
        conflicts = load_get_item_conflicts([
            item_state(10.0, 20.0)
        ])("track", 20.0, 30.0)

        self.assertEqual(conflicts, [])

    def test_material_overlap_is_still_rejected(self):
        conflicts = load_get_item_conflicts([
            item_state(10.0, 20.0)
        ])("track", 19.999, 30.0)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["item_guid"], "{ITEM-GUID}")


if __name__ == "__main__":
    unittest.main()
