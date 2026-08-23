import unittest

from reaper_mcp.drum_mapping import (
    DrumMappingError,
    resolve_drum_articulation,
    resolve_drum_events,
    validate_drum_mapping,
)


class DrumMappingTests(unittest.TestCase):
    def test_required_krimh_articulations(self):
        expected = {
            "kick.main": 24,
            "snare.hit": 26,
            "hihat.closed": 42,
            "ride.bell": 61,
            "crash.1.left-hit": 52,
            "china.right-hit": 67,
        }

        for articulation, pitch in expected.items():
            with self.subTest(articulation=articulation):
                resolved = resolve_drum_articulation(
                    "krimh-drums", articulation
                )
                self.assertEqual(resolved["pitch"], pitch)

    def test_xhihat_note_one_is_default_and_note_two_is_preserved(self):
        closed = resolve_drum_articulation("krimh-drums", "xhihat.closed")
        open_five = resolve_drum_articulation(
            "krimh-drums", "xhihat.open-5"
        )
        self.assertEqual(closed["pitch"], 82)
        self.assertEqual(closed["alternate_pitches"], [70])
        self.assertEqual(open_five["pitch"], 87)
        self.assertEqual(open_five["alternate_pitches"], [71])

    def test_unknown_mapping_has_no_general_midi_fallback(self):
        with self.assertRaises(DrumMappingError) as context:
            resolve_drum_articulation("general-midi", "kick.main")

        self.assertEqual(context.exception.code, "unknown_drum_mapping")

    def test_unknown_articulation_fails(self):
        with self.assertRaises(DrumMappingError) as context:
            resolve_drum_articulation("krimh-drums", "kick.gm")

        self.assertEqual(context.exception.code, "unknown_drum_articulation")

    def test_invalid_mapping_data_fails(self):
        with self.assertRaises(DrumMappingError) as context:
            validate_drum_mapping({
                "id": "krimh-drums",
                "articulations": {"kick.main": {"note": 200}},
            })

        self.assertEqual(context.exception.code, "invalid_drum_mapping")

    def test_semantic_events_resolve_before_generic_midi(self):
        notes, resolutions = resolve_drum_events("krimh-drums", [{
            "bar": 1,
            "beat": 1,
            "offset": 0,
            "duration_beats": 0.25,
            "drum": "kick",
            "articulation": "main",
            "velocity": 105,
        }])
        self.assertEqual(notes, [{
            "bar": 1,
            "beat": 1,
            "offset": 0,
            "duration_beats": 0.25,
            "velocity": 105,
            "pitch": 24,
        }])
        self.assertEqual(resolutions[0]["articulation"], "kick.main")


if __name__ == "__main__":
    unittest.main()
