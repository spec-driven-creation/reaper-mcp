import json
from importlib.resources import files


KRIMH_MAPPING_ID = "krimh-drums"
KRIMH_MAPPING_RESOURCE = "krimh-drums.json"


class DrumMappingError(ValueError):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            **self.details,
        }


def validate_drum_mapping(mapping: object) -> dict:
    if not isinstance(mapping, dict):
        raise DrumMappingError(
            "invalid_drum_mapping", "mapping data must be an object"
        )

    mapping_id = mapping.get("id")
    articulations = mapping.get("articulations")

    if mapping_id != KRIMH_MAPPING_ID or not isinstance(articulations, dict):
        raise DrumMappingError(
            "invalid_drum_mapping",
            "mapping id or articulations are invalid",
            mapping_id=mapping_id,
        )

    for articulation, assignment in articulations.items():
        if not isinstance(articulation, str) or not articulation.strip():
            raise DrumMappingError(
                "invalid_drum_mapping", "articulation names must be non-blank"
            )

        if not isinstance(assignment, dict):
            raise DrumMappingError(
                "invalid_drum_mapping",
                "articulation assignment must be an object",
                articulation=articulation,
            )

        alternate_notes = assignment.get("alternate_notes", [])

        if not isinstance(alternate_notes, list):
            raise DrumMappingError(
                "invalid_drum_mapping",
                "alternate_notes must be a list",
                articulation=articulation,
            )

        notes = [assignment.get("note"), *alternate_notes]

        if any(
            not isinstance(note, int)
            or isinstance(note, bool)
            or note < 0
            or note > 127
            for note in notes
        ):
            raise DrumMappingError(
                "invalid_drum_mapping",
                "all assigned notes must be MIDI integers from 0 through 127",
                articulation=articulation,
            )

    return mapping


def load_drum_mapping(mapping_id: str) -> dict:
    if mapping_id != KRIMH_MAPPING_ID:
        raise DrumMappingError(
            "unknown_drum_mapping",
            f"unknown drum mapping: {mapping_id}",
            mapping_id=mapping_id,
        )

    resource = files("reaper_mcp.mappings").joinpath(KRIMH_MAPPING_RESOURCE)

    try:
        mapping = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DrumMappingError(
            "invalid_drum_mapping", f"failed to load mapping data: {error}"
        ) from error

    return validate_drum_mapping(mapping)


def resolve_drum_articulation(mapping_id: str, articulation: str) -> dict:
    mapping = load_drum_mapping(mapping_id)
    assignment = mapping["articulations"].get(articulation)

    if assignment is None:
        raise DrumMappingError(
            "unknown_drum_articulation",
            f"unknown articulation for {mapping_id}: {articulation}",
            mapping_id=mapping_id,
            articulation=articulation,
        )

    return {
        "mapping_id": mapping_id,
        "articulation": articulation,
        "pitch": assignment["note"],
        "note_name": assignment.get("note_name"),
        "alternate_pitches": list(assignment.get("alternate_notes", [])),
        "alternate_note_names": list(
            assignment.get("alternate_note_names", [])
        ),
    }


def resolve_drum_events(mapping_id: str, events: list[dict]) -> tuple[list, list]:
    if not isinstance(events, list):
        raise DrumMappingError(
            "invalid_drum_event", "events must be a list"
        )

    notes = []
    resolutions = []

    for event_index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            raise DrumMappingError(
                "invalid_drum_event",
                "each event must be an object",
                event_index=event_index,
            )

        drum = event.get("drum")
        articulation = event.get("articulation")

        if (
            not isinstance(drum, str)
            or not drum.strip()
            or not isinstance(articulation, str)
            or not articulation.strip()
        ):
            raise DrumMappingError(
                "invalid_drum_event",
                "drum and articulation must be non-blank strings",
                event_index=event_index,
            )

        if "pitch" in event or "note_name" in event:
            raise DrumMappingError(
                "invalid_drum_event",
                "semantic drum events must not provide pitch or note_name",
                event_index=event_index,
            )

        articulation_id = f"{drum.strip()}.{articulation.strip()}"
        resolution = resolve_drum_articulation(mapping_id, articulation_id)
        notes.append({
            "bar": event.get("bar"),
            "beat": event.get("beat"),
            "offset": event.get("offset", 0),
            "duration_beats": event.get("duration_beats"),
            "velocity": event.get("velocity"),
            "pitch": resolution["pitch"],
        })
        resolutions.append({"event_index": event_index, **resolution})

    return notes, resolutions
