import ast
import math
import unittest
from pathlib import Path


BRIDGE_PATH = Path(__file__).parents[1] / "reaper" / "mcp_bridge.py"


def load_handler(namespace):
    source = BRIDGE_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    handler = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "handle_rename_region"
    )
    extracted = ast.Module(body=[handler], type_ignores=[])
    exec(compile(extracted, str(BRIDGE_PATH), "exec"), namespace)
    return namespace["handle_rename_region"]


class RenameRegionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.regions = [{
            "region_number": 1,
            "name": "",
            "start_seconds": 2.0,
            "end_seconds": 10.0,
            "color": 7
        }]

        def get_regions(_request):
            return {"regions": [dict(region) for region in self.regions]}

        def set_region(_project, number, is_region, start, end, name, color):
            self.calls.append((number, is_region, start, end, name, color))
            self.regions[0]["name"] = name
            return True

        self.handler = load_handler({
            "math": math,
            "handle_get_markers_regions": get_regions,
            "RPR_SetProjectMarker3": set_region,
            "RPR_UpdateTimeline": lambda: None
        })

    def test_renames_region_and_preserves_region_state(self):
        result = self.handler({"region_number": 1, "new_name": " Original "})

        self.assertTrue(result["success"])
        self.assertEqual(result["previous_name"], "")
        self.assertEqual(result["region"]["name"], "Original")
        self.assertEqual(self.calls, [(1, True, 2.0, 10.0, "Original", 7)])

    def test_rejects_invalid_input_before_mutation(self):
        invalid_requests = [
            {"region_number": True, "new_name": "Original"},
            {"region_number": 0, "new_name": "Original"},
            {"region_number": 1, "new_name": "   "},
            {"region_number": 1, "new_name": "x" * 256}
        ]

        for request in invalid_requests:
            with self.subTest(request=request):
                self.assertIn("error", self.handler(request))
        self.assertEqual(self.calls, [])

    def test_rejects_missing_region_before_mutation(self):
        result = self.handler({"region_number": 2, "new_name": "Original"})

        self.assertEqual(
            result["error"],
            "region_number does not identify an existing region"
        )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
