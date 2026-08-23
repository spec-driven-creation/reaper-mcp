import ast
import math
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = REPOSITORY_ROOT / "reaper" / "mcp_bridge.py"
MEASURE_QN = 3.5


def get_musical_position(position):
    measure = math.floor(max(position, 0) / MEASURE_QN) + 1
    return {
        "musical_position": {
            "measure": measure,
            "time_signature": {"numerator": 7, "denominator": 8},
        }
    }


def get_measure_boundary(measure):
    return (measure - 1) * MEASURE_QN


def beats_to_time(_project, beat_offset, measure_index):
    return (measure_index * MEASURE_QN + beat_offset * 0.5,)


def load_bridge_functions(*names):
    bridge_tree = ast.parse(BRIDGE_PATH.read_text(encoding="utf-8"))
    functions = [
        node
        for node in bridge_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {
        "math": math,
        "get_midi_pitch": lambda _name: None,
        "get_musical_position": get_musical_position,
        "get_measure_boundary": get_measure_boundary,
        "RPR_TimeMap2_beatsToTime": beats_to_time,
        "RPR_TimeMap2_timeToQN": lambda _project, position: position,
        "RPR_TimeMap2_QNToTime": lambda _project, position: position,
    }
    exec(compile(module, str(BRIDGE_PATH), "exec"), namespace)
    return namespace


class MidiNoteContractTests(unittest.TestCase):
    def setUp(self):
        namespace = load_bridge_functions("validate_midi_note_payload")
        self.validate = namespace["validate_midi_note_payload"]

    @staticmethod
    def note(**changes):
        note = {
            "bar": 1,
            "beat": 1,
            "offset": 0,
            "duration_beats": 0.5,
            "pitch": 24,
            "velocity": 110,
        }
        note.update(changes)
        return note

    def validate_notes(self, notes):
        return self.validate(notes, 0.0, 8 * MEASURE_QN, 1)

    def test_one_current_musical_note_in_seven_eight(self):
        validated, error = self.validate_notes([self.note()])
        self.assertIsNone(error)
        self.assertEqual(validated[0]["start_measure"], 1)
        self.assertEqual(validated[0]["duration_qn"], 0.25)

    def test_several_notes_and_fractional_offsets(self):
        notes = [
            self.note(bar=2, beat=4, offset=0.5),
            self.note(bar=1, beat=1, offset=0),
            self.note(bar=1, beat=3, offset=0.25),
        ]
        validated, error = self.validate_notes(notes)
        self.assertIsNone(error)
        self.assertEqual(
            [note["start_beat"] for note in validated], [1.0, 3.25, 4.5]
        )

    def test_bulk_payload_of_97_notes(self):
        notes = []

        for index in range(97):
            notes.append(self.note(
                bar=(index % 8) + 1,
                beat=(index % 7) + 1,
                offset=0.5 if index % 3 == 0 else 0,
                pitch=24 + (index % 40),
                velocity=50 + (index % 70),
                duration_beats=0.25,
            ))

        validated, error = self.validate_notes(notes)
        self.assertIsNone(error)
        self.assertEqual(len(validated), 97)

    def test_invalid_current_note_values(self):
        cases = {
            "missing_duration": {
                key: value
                for key, value in self.note().items()
                if key != "duration_beats"
            },
            "zero_duration": self.note(duration_beats=0),
            "negative_duration": self.note(duration_beats=-1),
            "invalid_pitch": self.note(pitch=128),
            "invalid_velocity": self.note(velocity=0),
            "invalid_bar": self.note(bar=0),
            "invalid_beat": self.note(beat=8),
            "non_finite_offset": self.note(offset=float("nan")),
        }

        for name, note in cases.items():
            with self.subTest(name=name):
                validated, error = self.validate_notes([note])
                self.assertIsNone(validated)
                self.assertIsNotNone(error)

    def test_invalid_create_payload_returns_before_item_creation(self):
        namespace = load_bridge_functions(
            "validate_midi_note_payload", "handle_create_midi_item"
        )
        add_calls = []
        namespace.update({
            "resolve_track": lambda _request: ({"track": object()}, None),
            "RPR_AddMediaItemToTrack": lambda track: add_calls.append(track),
        })
        response = namespace["handle_create_midi_item"]({
            "track_index": 1,
            "start_measure": 1,
            "end_measure": 9,
            "notes": [self.note(duration_beats=0)],
        })
        self.assertEqual(response["error"], "invalid_midi_note")
        self.assertEqual(add_calls, [])


if __name__ == "__main__":
    unittest.main()
