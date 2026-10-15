# pyright: reportUndefinedVariable=false

import socket
import json
import math
import re
import uuid

HOST = "127.0.0.1"
PORT = 8765
REQUEST_CHUNK_SIZE = 4096
MAX_REQUEST_BYTES = 4 * 1024 * 1024

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)
server.setblocking(False)

RPR_ShowConsoleMsg("REAPER MCP bridge listening on 127.0.0.1:8765\n")


def process_request(data):
    request = json.loads(data)

    command = request.get("command")

    handler = COMMAND_HANDLERS.get(command)

    if handler is None:
        return {
            "error": f"Unknown command: {command}"
        }

    return handler(request)

def linear_to_db(value: float) -> float | None:
    if value <= 0:
        return None

    return 20 * math.log10(value)

def get_pan_info(value: float) -> dict:
    if value < 0:
        direction = "L"
    elif value > 0:
        direction = "R"
    else:
        direction = "C"

    return {
        "pan": value,
        "pan_percent": round(abs(value) * 100, 1),
        "pan_direction": direction
    }

def handle_get_track_count(request):
    return {
        "track_count": RPR_CountTracks(0)
    }

def handle_get_project_info(request):
    project_info = RPR_GetSetProjectInfo_String(
        0,
        "PROJECT_NAME",
        "",
        False
    )

    project_name = project_info[3]

    time_signature = RPR_GetProjectTimeSignature2(
        0,
        0,
        0
    )

    bpm = time_signature[1]

    play_state_value = RPR_GetPlayState()

    if play_state_value & 4:
        play_state = "recording"
    elif play_state_value & 1:
        play_state = "playing"
    elif play_state_value & 2:
        play_state = "paused"
    else:
        play_state = "stopped"

    return {
        "project_name": project_name,
        "track_count": RPR_CountTracks(0),
        "tempo": bpm,
        "play_state": play_state
    }

def get_musical_position(position_seconds):
    beat_info = RPR_TimeMap2_timeToBeats(
        0,
        position_seconds,
        0,
        0,
        0.0,
        0
    )

    beat_within_measure = beat_info[0]
    measure = beat_info[3]
    measure_length = beat_info[4]
    full_beats = beat_info[5]
    denominator = beat_info[6]

    return {
        "position_beats": full_beats,
        "musical_position": {
            "measure": measure + 1,
            "beat": round(full_beats, 10),
            "beat_within_measure": round(beat_within_measure + 1, 10),
            "time_signature": {
                "numerator": measure_length,
                "denominator": denominator
            }
        }
    }

def get_midi_note_name(pitch):
    note_names = (
        "C", "C#", "D", "D#", "E", "F",
        "F#", "G", "G#", "A", "A#", "B"
    )
    octave = (pitch // 12) - 1
    return f"{note_names[pitch % 12]}{octave}"

def get_midi_pitch(note_name):
    if not isinstance(note_name, str):
        return None

    match = re.fullmatch(
        r"([A-Ga-g])([#b]?)(-1|[0-9])",
        note_name.strip()
    )

    if match is None:
        return None

    semitones = {
        "C": 0, "D": 2, "E": 4, "F": 5,
        "G": 7, "A": 9, "B": 11
    }
    accidental = {"": 0, "#": 1, "b": -1}[match.group(2)]
    octave = int(match.group(3))
    pitch = ((octave + 1) * 12) + semitones[match.group(1).upper()]
    pitch += accidental

    return pitch if 0 <= pitch <= 127 else None

def handle_get_tempo_map(request):
    events = []
    marker_count = RPR_CountTempoTimeSigMarkers(0)
    has_initial_marker = False

    if marker_count > 0:
        first_marker = RPR_GetTempoTimeSigMarker(
            0, 0, 0.0, 0, 0.0, 0.0, 0, 0, False
        )
        has_initial_marker = first_marker[0] and math.isclose(
            first_marker[3], 0.0, rel_tol=0.0, abs_tol=1e-9
        )

    if not has_initial_marker:
        project_time_signature = RPR_GetProjectTimeSignature2(
            0,
            0,
            0
        )
        effective_time_signature = RPR_TimeMap_GetTimeSigAtTime(
            0,
            0.0,
            0,
            0,
            0.0
        )
        musical = get_musical_position(0.0)

        events.append({
            "index": 1,
            "position_seconds": 0.0,
            "bpm": project_time_signature[1],
            "numerator": effective_time_signature[2],
            "denominator": effective_time_signature[3],
            "marker_numerator": None,
            "marker_denominator": None,
            "linear_tempo_change": None,
            "position_beats": musical["position_beats"],
            "musical_position": musical["musical_position"]
        })

    for reaper_index in range(marker_count):
        marker_info = RPR_GetTempoTimeSigMarker(
            0,
            reaper_index,
            0.0,
            0,
            0.0,
            0.0,
            0,
            0,
            False
        )

        if not marker_info[0]:
            continue

        position_seconds = marker_info[3]
        effective_time_signature = RPR_TimeMap_GetTimeSigAtTime(
            0,
            position_seconds,
            0,
            0,
            0.0
        )
        musical = get_musical_position(position_seconds)

        events.append({
            "index": len(events) + 1,
            "position_seconds": position_seconds,
            "bpm": marker_info[6],
            "numerator": effective_time_signature[2],
            "denominator": effective_time_signature[3],
            "marker_numerator": marker_info[7],
            "marker_denominator": marker_info[8],
            "linear_tempo_change": bool(marker_info[9]),
            "position_beats": musical["position_beats"],
            "musical_position": musical["musical_position"]
        })

    return {
        "events": events
    }

def get_initial_tempo_state():
    initial_event = handle_get_tempo_map({})["events"][0]
    return {
        "bpm": initial_event["bpm"],
        "numerator": initial_event["numerator"],
        "denominator": initial_event["denominator"]
    }

def find_initial_tempo_marker():
    for reaper_index in range(RPR_CountTempoTimeSigMarkers(0)):
        marker = RPR_GetTempoTimeSigMarker(
            0, reaper_index, 0.0, 0, 0.0, 0.0, 0, 0, False
        )
        if marker[0] and math.isclose(
            marker[3], 0.0, rel_tol=0.0, abs_tol=1e-9
        ):
            return reaper_index, marker
    return None, None

def resolve_tempo_map_position(measure):
    if (
        not isinstance(measure, int) or isinstance(measure, bool)
        or measure < 1
    ):
        return None, {"error": "measure must be a 1-based positive integer"}
    if measure == 1:
        return None, {
            "error": (
                "The initial project position must be changed with "
                "set_project_tempo or set_project_time_signature"
            )
        }

    position_seconds = get_measure_boundary(measure)
    if not math.isfinite(position_seconds):
        return None, {"error": "REAPER returned an invalid measure boundary"}

    return {
        "measure": measure,
        "position_seconds": position_seconds
    }, None

def find_tempo_marker_at_position(position_seconds):
    matches = []
    for reaper_index in range(RPR_CountTempoTimeSigMarkers(0)):
        marker = RPR_GetTempoTimeSigMarker(
            0, reaper_index, 0.0, 0, 0.0, 0.0, 0, 0, False
        )
        if marker[0] and math.isclose(
            marker[3], position_seconds, rel_tol=1e-9, abs_tol=1e-7
        ):
            matches.append((reaper_index, marker))

    if len(matches) > 1:
        return None, None, {
            "error": "Multiple tempo-map events resolve to the requested position"
        }
    if not matches:
        return None, None, None
    return matches[0][0], matches[0][1], None

def get_effective_bpm_at_position(position_seconds):
    effective_bpm = RPR_GetProjectTimeSignature2(0, 0, 0)[1]
    for reaper_index in range(RPR_CountTempoTimeSigMarkers(0)):
        marker = RPR_GetTempoTimeSigMarker(
            0, reaper_index, 0.0, 0, 0.0, 0.0, 0, 0, False
        )
        if not marker[0] or marker[3] > position_seconds + 1e-7:
            break
        effective_bpm = marker[6]
    return effective_bpm

def handle_set_tempo_map_event(request):
    measure = request.get("measure")
    bpm = request.get("bpm")
    numerator = request.get("numerator")
    denominator = request.get("denominator")

    if "beat" in request:
        return {
            "error": (
                "beat is not supported; tempo-map events are placed at "
                "beat 1 of the requested measure"
            )
        }

    position, error = resolve_tempo_map_position(measure)
    if error is not None:
        return error

    if bpm is not None and (
        not isinstance(bpm, (int, float)) or isinstance(bpm, bool)
        or not math.isfinite(bpm) or bpm < 1.0 or bpm > 960.0
    ):
        return {"error": "bpm must be a finite number from 1 to 960"}
    if (numerator is None) != (denominator is None):
        return {
            "error": "numerator and denominator must be provided together"
        }
    if numerator is not None and (
        not isinstance(numerator, int) or isinstance(numerator, bool)
        or numerator < 1 or numerator > 255
    ):
        return {"error": "numerator must be an integer from 1 to 255"}
    if denominator is not None and (
        not isinstance(denominator, int) or isinstance(denominator, bool)
        or denominator < 1 or denominator > 64
        or denominator & (denominator - 1)
    ):
        return {
            "error": "denominator must be a power-of-two integer from 1 to 64"
        }
    if bpm is None and numerator is None:
        return {"error": "Provide bpm, a time signature, or both"}
    marker_index, marker, error = find_tempo_marker_at_position(
        position["position_seconds"]
    )
    if error is not None:
        return error
    if marker is not None and bool(marker[9]):
        return {
            "error": (
                "Linear tempo-change markers are outside this capability"
            )
        }

    effective_signature = RPR_TimeMap_GetTimeSigAtTime(
        0, position["position_seconds"], 0, 0, 0.0
    )
    effective_bpm = get_effective_bpm_at_position(
        position["position_seconds"]
    )
    applied_bpm = float(bpm) if bpm is not None else (
        marker[6] if marker is not None else effective_bpm
    )
    applied_numerator = numerator if numerator is not None else (
        marker[7] if marker is not None and marker[7] > 0
        else effective_signature[2]
    )
    applied_denominator = denominator if denominator is not None else (
        marker[8] if marker is not None and marker[8] > 0
        else effective_signature[3]
    )
    reaper_marker_index = marker_index if marker is not None else -1
    updated = RPR_SetTempoTimeSigMarker(
        0, reaper_marker_index, -1.0, measure - 1, 0.0,
        applied_bpm, applied_numerator, applied_denominator, False
    )
    if not updated:
        return {"error": "REAPER failed to set the tempo-map event"}

    read_index, read_marker, read_error = find_tempo_marker_at_position(
        position["position_seconds"]
    )
    public_event = next((
        event for event in handle_get_tempo_map({})["events"]
        if math.isclose(
            event["position_seconds"], position["position_seconds"],
            rel_tol=1e-9, abs_tol=1e-7
        )
    ), None)
    verified = (
        read_error is None and read_marker is not None
        and math.isclose(
            read_marker[6], applied_bpm, rel_tol=1e-9, abs_tol=1e-9
        )
        and read_marker[7] == applied_numerator
        and read_marker[8] == applied_denominator
        and not bool(read_marker[9])
        and public_event is not None
        and math.isclose(
            public_event["bpm"], applied_bpm,
            rel_tol=1e-9, abs_tol=1e-9
        )
        and public_event["numerator"] == applied_numerator
        and public_event["denominator"] == applied_denominator
    )
    if not verified:
        if marker is None and read_index is not None:
            rollback_succeeded = bool(
                RPR_DeleteTempoTimeSigMarker(0, read_index)
            )
        elif marker is not None:
            rollback_succeeded = bool(RPR_SetTempoTimeSigMarker(
                0, marker_index, marker[3], -1, -1.0, marker[6],
                marker[7], marker[8], marker[9]
            ))
        else:
            rollback_succeeded = False
        return {
            "error": "Tempo-map event read-back verification failed",
            "rollback_succeeded": rollback_succeeded
        }

    RPR_UpdateTimeline()
    return {
        "operation": "updated" if marker is not None else "created",
        "requested": {
            "measure": measure,
            "bpm": bpm,
            "numerator": numerator,
            "denominator": denominator
        },
        "tempo_map_event": public_event,
        "success": True
    }

def handle_set_project_tempo(request):
    bpm = request.get("bpm")
    if (
        not isinstance(bpm, (int, float)) or isinstance(bpm, bool)
        or not math.isfinite(bpm) or bpm < 1.0 or bpm > 960.0
    ):
        return {"error": "bpm must be a finite number from 1 to 960"}

    bpm = float(bpm)
    marker_index, marker = find_initial_tempo_marker()
    if marker is None:
        RPR_SetCurrentBPM(0, bpm, True)
        mutation = "project_default"
    else:
        updated = RPR_SetTempoTimeSigMarker(
            0, marker_index, marker[3], -1, -1.0, bpm,
            marker[7], marker[8], marker[9]
        )
        if not updated:
            return {"error": "REAPER failed to update the initial tempo"}
        mutation = "initial_marker"

    applied = get_initial_tempo_state()
    if not math.isclose(
        applied["bpm"], bpm, rel_tol=1e-9, abs_tol=1e-9
    ):
        return {
            "error": "Initial tempo read-back verification failed",
            "requested_bpm": bpm, "applied": applied
        }
    RPR_UpdateTimeline()
    return {
        "requested_bpm": bpm, "mutation": mutation,
        "applied": applied, "success": True
    }

def handle_set_project_time_signature(request):
    numerator = request.get("numerator")
    denominator = request.get("denominator")
    if (
        not isinstance(numerator, int) or isinstance(numerator, bool)
        or numerator < 1 or numerator > 255
    ):
        return {"error": "numerator must be an integer from 1 to 255"}
    if (
        not isinstance(denominator, int) or isinstance(denominator, bool)
        or denominator < 1 or denominator > 64
        or denominator & (denominator - 1)
    ):
        return {
            "error": "denominator must be a power-of-two integer from 1 to 64"
        }

    initial = get_initial_tempo_state()
    marker_index, marker = find_initial_tempo_marker()
    if marker is None:
        marker_index = -1
        time_position, measure_position, beat_position = 0.0, -1, -1.0
        marker_bpm, linear = initial["bpm"], False
        mutation = "inserted_initial_marker"
    else:
        time_position, measure_position, beat_position = marker[3], -1, -1.0
        marker_bpm, linear = marker[6], marker[9]
        mutation = "initial_marker"

    updated = RPR_SetTempoTimeSigMarker(
        0, marker_index, time_position, measure_position, beat_position,
        marker_bpm, numerator, denominator, linear
    )
    if not updated:
        return {"error": "REAPER failed to update the initial time signature"}

    applied = get_initial_tempo_state()
    if (
        applied["numerator"] != numerator
        or applied["denominator"] != denominator
    ):
        return {
            "error": "Initial time-signature read-back verification failed",
            "requested": {"numerator": numerator, "denominator": denominator},
            "applied": applied
        }
    RPR_UpdateTimeline()
    return {
        "requested": {"numerator": numerator, "denominator": denominator},
        "mutation": mutation, "applied": applied, "success": True
    }

def handle_get_markers_regions(request):
    markers = []
    regions = []
    marker_region_count = RPR_CountProjectMarkers(0, 0, 0)[0]

    for enumeration_index in range(marker_region_count):
        marker_info = RPR_EnumProjectMarkers3(
            0,
            enumeration_index,
            False,
            0.0,
            0.0,
            "",
            0,
            0
        )

        if not marker_info[0]:
            continue

        is_region = bool(marker_info[3])
        position_seconds = marker_info[4]
        end_seconds = marker_info[5]
        project_number = marker_info[7]
        color = marker_info[8]
        marker_object = RPR_GetRegionOrMarker(
            0, enumeration_index, ""
        )
        name_info = RPR_GetSetRegionOrMarkerInfo_String(
            0, marker_object, "P_NAME", "", False
        )
        name = name_info[4] if name_info[0] else marker_info[6]

        if is_region:
            start_musical = get_musical_position(position_seconds)
            end_musical = get_musical_position(end_seconds)

            regions.append({
                "index": enumeration_index + 1,
                "enumeration_index": enumeration_index,
                "region_number": project_number,
                "name": name,
                "start_seconds": position_seconds,
                "end_seconds": end_seconds,
                "duration_seconds": end_seconds - position_seconds,
                "start_beats": start_musical["position_beats"],
                "end_beats": end_musical["position_beats"],
                "start_musical_position": (
                    start_musical["musical_position"]
                ),
                "end_musical_position": end_musical["musical_position"],
                "color": color,
                "is_region": True
            })
        else:
            musical = get_musical_position(position_seconds)

            markers.append({
                "index": enumeration_index + 1,
                "enumeration_index": enumeration_index,
                "marker_number": project_number,
                "name": name,
                "position_seconds": position_seconds,
                "position_beats": musical["position_beats"],
                "musical_position": musical["musical_position"],
                "color": color,
                "is_region": False
            })

    return {
        "markers": markers,
        "regions": regions
    }

def handle_create_region(request):
    name = request.get("name")
    start_measure = request.get("start_measure")
    end_measure = request.get("end_measure")
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-blank string"}
    name = name.strip()
    if len(name) > 255:
        return {"error": "name must not exceed 255 characters"}
    if (
        not isinstance(start_measure, int) or isinstance(start_measure, bool)
        or start_measure < 1
    ):
        return {"error": "start_measure must be a positive integer"}
    if (
        not isinstance(end_measure, int) or isinstance(end_measure, bool)
        or end_measure < 1
    ):
        return {"error": "end_measure must be a positive integer"}
    if end_measure <= start_measure:
        return {"error": "end_measure must be greater than start_measure"}

    start_seconds = get_measure_boundary(start_measure)
    end_seconds = get_measure_boundary(end_measure)
    if end_seconds <= start_seconds:
        return {"error": "REAPER resolved an invalid region time range"}
    region_number = RPR_AddProjectMarker2(
        0, True, start_seconds, end_seconds, name, -1, 0
    )
    if region_number < 0:
        return {"error": "REAPER failed to create the region"}

    regions = handle_get_markers_regions({})["regions"]

    def region_matches(candidate):
        return (
            candidate["name"] == name
            and math.isclose(
                candidate["start_seconds"], start_seconds,
                rel_tol=1e-9, abs_tol=1e-7
            )
            and math.isclose(
                candidate["end_seconds"], end_seconds,
                rel_tol=1e-9, abs_tol=1e-7
            )
        )

    created = next((
        region for region in regions
        if region["region_number"] == region_number
        and region_matches(region)
    ), None)

    if created is None:
        matching_regions = [
            region for region in regions if region_matches(region)
        ]
        if len(matching_regions) == 1:
            created = matching_regions[0]

    if created is None:
        rollback_succeeded = bool(
            RPR_DeleteProjectMarker(0, region_number, True)
        )
        return {
            "error": "Region read-back verification failed",
            "region_number": region_number,
            "expected": {
                "name": name,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds
            },
            "regions_read_back": regions,
            "rollback_succeeded": rollback_succeeded
        }
    RPR_UpdateTimeline()
    return {
        "requested": {"name": name, "start_measure": start_measure,
                      "end_measure": end_measure},
        "region": created, "success": True
    }

def handle_rename_region(request):
    region_number = request.get("region_number")
    new_name = request.get("new_name")

    if (
        not isinstance(region_number, int)
        or isinstance(region_number, bool)
        or region_number < 1
    ):
        return {"error": "region_number must be a positive integer"}
    if not isinstance(new_name, str) or not new_name.strip():
        return {"error": "new_name must be a non-blank string"}

    new_name = new_name.strip()
    if len(new_name) > 255:
        return {"error": "new_name must not exceed 255 characters"}

    regions = handle_get_markers_regions({})["regions"]
    target = next((
        region for region in regions
        if region["region_number"] == region_number
    ), None)
    if target is None:
        return {"error": "region_number does not identify an existing region"}

    previous_name = target["name"]
    write_succeeded = bool(RPR_SetProjectMarker3(
        0,
        region_number,
        True,
        target["start_seconds"],
        target["end_seconds"],
        new_name,
        target["color"]
    ))
    if not write_succeeded:
        return {"error": "REAPER failed to rename the region"}

    renamed_regions = handle_get_markers_regions({})["regions"]
    renamed = next((
        region for region in renamed_regions
        if region["region_number"] == region_number
    ), None)
    if (
        renamed is None
        or renamed["name"] != new_name
        or not math.isclose(
            renamed["start_seconds"], target["start_seconds"],
            rel_tol=1e-9, abs_tol=1e-7
        )
        or not math.isclose(
            renamed["end_seconds"], target["end_seconds"],
            rel_tol=1e-9, abs_tol=1e-7
        )
        or renamed["color"] != target["color"]
    ):
        rollback_succeeded = bool(RPR_SetProjectMarker3(
            0,
            region_number,
            True,
            target["start_seconds"],
            target["end_seconds"],
            previous_name,
            target["color"]
        ))
        return {
            "error": "Region rename read-back verification failed",
            "region_number": region_number,
            "rollback_succeeded": rollback_succeeded
        }

    RPR_UpdateTimeline()
    return {
        "requested": {
            "region_number": region_number,
            "new_name": new_name
        },
        "previous_name": previous_name,
        "region": renamed,
        "success": True
    }

def handle_get_tracks(request):
    tracks = []
    folder_stack = []

    track_count = RPR_CountTracks(0)

    for index in range(track_count):
        track = RPR_GetTrack(0, index)

        track_name_info = RPR_GetTrackName(track, "", 512)
        track_name = track_name_info[2]

        muted = bool(
            RPR_GetMediaTrackInfo_Value(track, "B_MUTE")
        )

        solo_value = RPR_GetMediaTrackInfo_Value(track, "I_SOLO")
        solo = solo_value > 0

        volume = RPR_GetMediaTrackInfo_Value(track, "D_VOL")
        volume_db = linear_to_db(volume)

        pan = RPR_GetMediaTrackInfo_Value(track, "D_PAN")
        pan_info = get_pan_info(pan)

        folder_depth = int(
            RPR_GetMediaTrackInfo_Value(track, "I_FOLDERDEPTH")
        )

        parent_index = None
        parent_name = None

        if folder_stack:
            parent_index = folder_stack[-1]["index"]
            parent_name = folder_stack[-1]["name"]

        tracks.append({
            "index": index + 1,
            "name": track_name,
            "muted": muted,
            "solo": solo,
            "volume": volume,
            "volume_db": (
                round(volume_db, 2)
                if volume_db is not None
                else None
            ),
            **pan_info,
            "folder_depth": folder_depth,
            "is_folder": folder_depth > 0,
            "is_nested": parent_index is not None,
            "parent_index": parent_index,
            "parent_name": parent_name,
            "record_armed": bool(RPR_GetMediaTrackInfo_Value(
                track, "I_RECARM"
            )),
            "record_input_raw": int(RPR_GetMediaTrackInfo_Value(
                track, "I_RECINPUT"
            )),
            "record_monitoring_raw": int(RPR_GetMediaTrackInfo_Value(
                track, "I_RECMON"
            ))
        })

        if folder_depth > 0:
            folder_stack.append({
                "index": index + 1,
                "name": track_name
            })

        elif folder_depth < 0:
            for _ in range(abs(folder_depth)):
                if folder_stack:
                    folder_stack.pop()

    return {
        "tracks": tracks
    }

def validate_track_name(request, field_name="name"):
    name = request.get(field_name)
    if not isinstance(name, str) or not name.strip():
        return None, {"error": f"{field_name} must be a non-blank string"}
    name = name.strip()
    if len(name) > 255:
        return None, {"error": f"{field_name} must not exceed 255 characters"}
    return name, None

def handle_create_named_track(request):
    name, error = validate_track_name(request)
    if error is not None:
        return error
    track_count = RPR_CountTracks(0)
    track_index = request.get("track_index")
    if track_index is None:
        track_index = track_count + 1
    elif (
        not isinstance(track_index, int) or isinstance(track_index, bool)
        or track_index < 1 or track_index > track_count + 1
    ):
        return {
            "error": (
                "track_index must be a 1-based insertion position from 1 "
                f"to {track_count + 1}"
            )
        }

    RPR_InsertTrackAtIndex(track_index - 1, True)
    if RPR_CountTracks(0) != track_count + 1:
        return {"error": "REAPER failed to create exactly one track"}
    track = RPR_GetTrack(0, track_index - 1)
    named = RPR_GetSetMediaTrackInfo_String(track, "P_NAME", name, True)
    applied_index, applied_name = get_track_identity(track)
    if not named[0] or applied_index != track_index or applied_name != name:
        RPR_DeleteTrack(track)
        return {
            "error": "Track name read-back verification failed",
            "rollback_succeeded": RPR_CountTracks(0) == track_count
        }
    RPR_TrackList_AdjustWindows(False)
    return {
        "track_index": applied_index, "track_name": applied_name,
        "insertion": "append" if track_index == track_count + 1 else "explicit",
        "success": True
    }

def handle_rename_track(request):
    context, error = resolve_track(request)
    if error is not None:
        return error
    new_name, error = validate_track_name(request, "new_name")
    if error is not None:
        return error
    previous_name = context["track_name"]
    renamed = RPR_GetSetMediaTrackInfo_String(
        context["track"], "P_NAME", new_name, True
    )
    applied_index, applied_name = get_track_identity(context["track"])
    if (
        not renamed[0] or applied_index != context["track_index"]
        or applied_name != new_name
    ):
        restored = RPR_GetSetMediaTrackInfo_String(
            context["track"], "P_NAME", previous_name, True
        )
        return {
            "error": "Track rename read-back verification failed",
            "rollback_succeeded": bool(restored[0])
        }
    RPR_TrackList_AdjustWindows(False)
    return {
        "track_index": applied_index, "previous_name": previous_name,
        "track_name": applied_name, "success": True
    }

def delete_tracks(tracks):
    for track in reversed(tracks):
        if track:
            RPR_DeleteTrack(track)

def handle_create_track_folder(request):
    name, error = validate_track_name(request)
    if error is not None:
        return error
    children = request.get("children")
    if not isinstance(children, list) or not children:
        return {"error": "children must be a non-empty list of track names"}

    child_names = []
    for child in children:
        child_name, error = validate_track_name({"name": child})
        if error is not None:
            return {"error": f"Invalid child track name: {error['error']}"}
        child_names.append(child_name)

    original_count = RPR_CountTracks(0)
    created_tracks = []
    requested_names = [name, *child_names]
    for offset, track_name in enumerate(requested_names):
        RPR_InsertTrackAtIndex(original_count + offset, True)
        track = RPR_GetTrack(0, original_count + offset)
        if not track:
            delete_tracks(created_tracks)
            return {
                "error": "REAPER failed to create the requested tracks",
                "rollback_succeeded": RPR_CountTracks(0) == original_count
            }
        created_tracks.append(track)
        named = RPR_GetSetMediaTrackInfo_String(
            track, "P_NAME", track_name, True
        )
        if not named[0]:
            delete_tracks(created_tracks)
            return {
                "error": "REAPER failed to name a created track",
                "rollback_succeeded": RPR_CountTracks(0) == original_count
            }

    folder_set = bool(RPR_SetMediaTrackInfo_Value(
        created_tracks[0], "I_FOLDERDEPTH", 1
    ))
    child_end_set = bool(RPR_SetMediaTrackInfo_Value(
        created_tracks[-1], "I_FOLDERDEPTH", -1
    ))
    tracks_after = handle_get_tracks({})["tracks"]
    folder_after = tracks_after[original_count]
    children_after = tracks_after[original_count + 1:]
    verified = (
        folder_set and child_end_set
        and RPR_CountTracks(0) == original_count + len(requested_names)
        and folder_after["name"] == name
        and folder_after["is_folder"]
        and [child["name"] for child in children_after] == child_names
        and all(
            child["parent_index"] == folder_after["index"]
            for child in children_after
        )
        and children_after[-1]["folder_depth"] == -1
    )
    if not verified:
        delete_tracks(created_tracks)
        return {
            "error": "Track folder read-back verification failed",
            "rollback_succeeded": RPR_CountTracks(0) == original_count,
            "tracks_read_back": tracks_after
        }

    RPR_TrackList_AdjustWindows(False)
    return {
        "folder": folder_after,
        "children": children_after,
        "success": True
    }

def get_track_guid(track):
    return RPR_GetTrackGUID(track) if track else None

def find_track_index_by_guid(track_guid):
    for index in range(RPR_CountTracks(0)):
        if get_track_guid(RPR_GetTrack(0, index)) == track_guid:
            return index + 1
    return None

def get_folder_last_descendant_index(tracks, folder_track_index):
    depth = 0
    for track in tracks[folder_track_index - 1:]:
        depth += track["folder_depth"]
        if track["index"] > folder_track_index and depth <= 0:
            return track["index"]
    return None

def restore_track_selection(selected_guids):
    for index in range(RPR_CountTracks(0)):
        track = RPR_GetTrack(0, index)
        RPR_SetTrackSelected(track, get_track_guid(track) in selected_guids)

def handle_move_track_into_folder(request):
    track_context, error = resolve_track(request)
    if error is not None:
        return error
    folder_context, error = resolve_track({
        "track_index": request.get("folder_track_index")
    })
    if error is not None:
        return {"error": f"Invalid folder_track_index: {error['error']}"}
    if track_context["track"] == folder_context["track"]:
        return {"error": "A track cannot be moved into itself"}

    tracks_before = handle_get_tracks({})["tracks"]
    track_before = tracks_before[track_context["track_index"] - 1]
    folder_before = tracks_before[folder_context["track_index"] - 1]
    if track_before["is_folder"] or track_before["is_nested"]:
        return {"error": "The track to move must be a top-level normal track"}
    if not folder_before["is_folder"] or folder_before["is_nested"]:
        return {"error": "The destination must be a top-level folder track"}

    folder_end_index = get_folder_last_descendant_index(
        tracks_before, folder_context["track_index"]
    )
    if folder_end_index is None:
        return {"error": "The destination folder has invalid native depth"}

    track_guid = get_track_guid(track_context["track"])
    folder_guid = get_track_guid(folder_context["track"])
    order_before = [
        get_track_guid(RPR_GetTrack(0, index))
        for index in range(RPR_CountTracks(0))
    ]
    selected_guids = {
        guid for index, guid in enumerate(order_before)
        if bool(RPR_GetMediaTrackInfo_Value(
            RPR_GetTrack(0, index), "I_SELECTED"
        ))
    }
    for index in range(RPR_CountTracks(0)):
        RPR_SetTrackSelected(RPR_GetTrack(0, index), False)
    RPR_SetTrackSelected(track_context["track"], True)
    reordered = bool(RPR_ReorderSelectedTracks(folder_end_index, 2))
    restore_track_selection(selected_guids)

    resulting_track_index = find_track_index_by_guid(track_guid)
    resulting_folder_index = find_track_index_by_guid(folder_guid)
    tracks_after = handle_get_tracks({})["tracks"]
    track_after = (
        tracks_after[resulting_track_index - 1]
        if resulting_track_index is not None else None
    )
    folder_after = (
        tracks_after[resulting_folder_index - 1]
        if resulting_folder_index is not None else None
    )
    order_after_without_moved = [
        get_track_guid(RPR_GetTrack(0, index))
        for index in range(RPR_CountTracks(0))
        if get_track_guid(RPR_GetTrack(0, index)) != track_guid
    ]
    verified = (
        reordered and track_after is not None and folder_after is not None
        and folder_after["is_folder"]
        and track_after["parent_index"] == resulting_folder_index
        and order_after_without_moved == [
            guid for guid in order_before if guid != track_guid
        ]
    )
    if not verified:
        return {
            "error": "Track move read-back verification failed",
            "track": track_after,
            "folder": folder_after,
            "tracks_read_back": tracks_after
        }

    RPR_TrackList_AdjustWindows(False)
    return {
        "track_index": resulting_track_index,
        "folder_track_index": resulting_folder_index,
        "track": track_after,
        "folder": folder_after,
        "success": True
    }

def get_track_identity(track):
    if not track:
        return None, None

    track_index = int(
        RPR_GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER")
    )
    track_name_info = RPR_GetTrackName(track, "", 512)

    return track_index, track_name_info[2]

def resolve_track(request):
    track_index = request.get("track_index")

    if not isinstance(track_index, int) or isinstance(track_index, bool):
        return None, {"error": "track_index must be a 1-based integer"}

    track_count = RPR_CountTracks(0)

    if track_index < 1 or track_index > track_count:
        return None, {
            "error": (
                f"Track index {track_index} is out of range; "
                f"project has {track_count} tracks"
            )
        }

    track = RPR_GetTrack(0, track_index - 1)
    _, track_name = get_track_identity(track)

    return {
        "track": track,
        "track_index": track_index,
        "track_name": track_name
    }, None

def resolve_item(request):
    context, error = resolve_track(request)

    if error is not None:
        return None, error

    item_index = request.get("item_index")

    if not isinstance(item_index, int) or isinstance(item_index, bool):
        return None, {"error": "item_index must be a 1-based integer"}

    item_count = RPR_CountTrackMediaItems(context["track"])

    if item_index < 1 or item_index > item_count:
        return None, {
            "error": (
                f"Item index {item_index} is out of range; track "
                f"{context['track_index']} has {item_count} items"
            )
        }

    context["item_index"] = item_index
    context["item"] = RPR_GetTrackMediaItem(
        context["track"], item_index - 1
    )
    return context, None

def resolve_take(request):
    context, error = resolve_item(request)

    if error is not None:
        return None, error

    take_index = request.get("take_index")

    if not isinstance(take_index, int) or isinstance(take_index, bool):
        return None, {"error": "take_index must be a 1-based integer"}

    take_count = RPR_CountTakes(context["item"])

    if take_index < 1 or take_index > take_count:
        return None, {
            "error": (
                f"Take index {take_index} is out of range; item "
                f"{context['item_index']} has {take_count} takes"
            )
        }

    context["take_index"] = take_index
    context["take"] = RPR_GetTake(context["item"], take_index - 1)
    context["take_name"] = RPR_GetTakeName(context["take"])
    return context, None

def get_item_identity(item):
    guid_info = RPR_GetSetMediaItemInfo_String(
        item, "GUID", "", False
    )
    return guid_info[3]

def get_item_state(item, item_index):
    position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
    duration = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
    end_position = position + duration
    start_musical = get_musical_position(position)["musical_position"]
    end_musical = get_musical_position(end_position)["musical_position"]

    return {
        "item_index": item_index,
        "guid": get_item_identity(item),
        "position_seconds": position,
        "end_seconds": end_position,
        "duration_seconds": duration,
        "start_measure": start_musical["measure"],
        "start_beat": start_musical["beat_within_measure"],
        "end_measure": end_musical["measure"],
        "end_beat": end_musical["beat_within_measure"],
        "muted": bool(RPR_GetMediaItemInfo_Value(item, "B_MUTE")),
        "locked": bool(RPR_GetMediaItemInfo_Value(item, "C_LOCK")),
        "selected": bool(RPR_GetMediaItemInfo_Value(item, "B_UISEL"))
    }

def get_measure_boundary(measure):
    return RPR_TimeMap_GetMeasureInfo(
        0, measure - 1, 0.0, 0.0, 0, 0, 0.0
    )[0]

def get_item_conflicts(
    track, position_seconds, end_seconds, excluded_item_guid=None
):
    conflicts = []
    boundary_tolerance_seconds = 1e-9

    for reaper_item_index in range(RPR_CountTrackMediaItems(track)):
        existing_item = RPR_GetTrackMediaItem(track, reaper_item_index)
        existing = get_item_state(existing_item, reaper_item_index + 1)

        if existing["guid"] == excluded_item_guid:
            continue

        if (
            position_seconds
            < existing["end_seconds"] - boundary_tolerance_seconds
            and end_seconds
            > existing["position_seconds"] + boundary_tolerance_seconds
        ):
            conflicts.append({
                "item_index": existing["item_index"],
                "item_guid": existing["guid"],
                "position_seconds": existing["position_seconds"],
                "end_seconds": existing["end_seconds"],
                "start_measure": existing["start_measure"],
                "start_beat": existing["start_beat"],
                "end_measure": existing["end_measure"],
                "end_beat": existing["end_beat"]
            })

    return conflicts

def find_item_index(track, item_guid):
    for reaper_item_index in range(RPR_CountTrackMediaItems(track)):
        candidate = RPR_GetTrackMediaItem(track, reaper_item_index)

        if get_item_identity(candidate) == item_guid:
            return reaper_item_index + 1

    return None

def find_item_by_guid(track, item_guid):
    for reaper_item_index in range(RPR_CountTrackMediaItems(track)):
        candidate = RPR_GetTrackMediaItem(track, reaper_item_index)

        if get_item_identity(candidate) == item_guid:
            return candidate

    return None

def delete_created_item(track, item, item_guid):
    deleted = RPR_DeleteTrackMediaItem(track, item)
    RPR_UpdateArrange()

    return bool(deleted) and find_item_index(track, item_guid) is None

def resolve_item_by_guid(request):
    context, error = resolve_track(request)

    if error is not None:
        return None, error

    item_guid = request.get("item_guid")

    if not isinstance(item_guid, str) or not item_guid.strip():
        return None, {"error": "item_guid must be a non-blank string"}

    item_guid = item_guid.strip()
    item = find_item_by_guid(context["track"], item_guid)

    if not item:
        for reaper_track_index in range(RPR_CountTracks(0)):
            candidate_track = RPR_GetTrack(0, reaper_track_index)

            if find_item_by_guid(candidate_track, item_guid):
                return None, {
                    "error": "item_track_mismatch",
                    "item_guid": item_guid,
                    "requested_track_index": context["track_index"],
                    "actual_track_index": reaper_track_index + 1
                }

        return None, {
            "error": "item_guid_not_found",
            "item_guid": item_guid
        }

    context["item"] = item
    context["item_guid"] = item_guid
    context["item_index"] = find_item_index(context["track"], item_guid)
    return context, None

def get_take_source_type(take):
    source = RPR_GetMediaItemTake_Source(take)
    return RPR_GetMediaSourceType(source, "", 128)[1]

def find_track_index_by_name(track_name):
    matching_indexes = []

    for reaper_track_index in range(RPR_CountTracks(0)):
        candidate_track = RPR_GetTrack(0, reaper_track_index)
        _, candidate_name = get_track_identity(candidate_track)

        if candidate_name == track_name:
            matching_indexes.append(reaper_track_index + 1)

    return matching_indexes[0] if len(matching_indexes) == 1 else None

def decode_audio_channels(source_channels_raw, destination_channels_raw):
    if source_channels_raw < 0:
        return [], []

    source_offset = source_channels_raw & 1023
    source_mode = source_channels_raw >> 10

    if source_mode == 0:
        source_channel_count = 2
    elif source_mode == 1:
        source_channel_count = 1
    else:
        source_channel_count = source_mode * 2

    source_channels = list(range(
        source_offset + 1,
        source_offset + source_channel_count + 1
    ))
    destination_offset = destination_channels_raw & 1023
    destination_channel_count = (
        1
        if destination_channels_raw & 1024
        else source_channel_count
    )
    destination_channels = list(range(
        destination_offset + 1,
        destination_offset + destination_channel_count + 1
    ))

    return source_channels, destination_channels

def decode_midi_routing(midi_flags_raw):
    source_channel = midi_flags_raw & 31
    destination_channel = (midi_flags_raw >> 5) & 31

    if source_channel == 0:
        midi_source = "all"
    elif source_channel == 31:
        midi_source = "disabled"
    else:
        midi_source = source_channel

    midi_destination = (
        "original"
        if destination_channel == 0
        else destination_channel
    )

    return midi_source, midi_destination

def get_routing_entry(track, category, routing_index):
    volume = RPR_GetTrackSendInfo_Value(
        track,
        category,
        routing_index,
        "D_VOL"
    )
    volume_db = linear_to_db(volume)
    pan = RPR_GetTrackSendInfo_Value(
        track,
        category,
        routing_index,
        "D_PAN"
    )
    pan_info = get_pan_info(pan)
    source_channels_raw = int(RPR_GetTrackSendInfo_Value(
        track,
        category,
        routing_index,
        "I_SRCCHAN"
    ))
    destination_channels_raw = int(RPR_GetTrackSendInfo_Value(
        track,
        category,
        routing_index,
        "I_DSTCHAN"
    ))
    midi_flags_raw = int(RPR_GetTrackSendInfo_Value(
        track,
        category,
        routing_index,
        "I_MIDIFLAGS"
    ))

    source_channels, destination_channels = decode_audio_channels(
        source_channels_raw,
        destination_channels_raw
    )
    midi_source, midi_destination = decode_midi_routing(midi_flags_raw)

    track_index, track_name = get_track_identity(track)
    hardware_output_name = None

    if category < 0:
        receive_name = RPR_GetTrackReceiveName(
            track,
            routing_index,
            "",
            512
        )[3]
        source_track_index = find_track_index_by_name(receive_name)
        source_track_name = receive_name
        destination_track_index = track_index
        destination_track_name = track_name
    elif category == 0:
        hardware_output_count = RPR_GetTrackNumSends(track, 1)
        send_name = RPR_GetTrackSendName(
            track,
            hardware_output_count + routing_index,
            "",
            512
        )[3]
        source_track_index = track_index
        source_track_name = track_name
        destination_track_index = find_track_index_by_name(send_name)
        destination_track_name = send_name
    else:
        hardware_output_name = RPR_GetTrackSendName(
            track,
            routing_index,
            "",
            512
        )[3]
        source_track_index = track_index
        source_track_name = track_name
        destination_track_index = None
        destination_track_name = None

    return {
        "index": routing_index + 1,
        "source_track_index": source_track_index,
        "source_track_name": source_track_name,
        "destination_track_index": destination_track_index,
        "destination_track_name": destination_track_name,
        "hardware_output_name": hardware_output_name,
        "volume_raw": volume,
        "volume_db": round(volume_db, 2) if volume_db is not None else None,
        "pan_raw": pan_info["pan"],
        "pan_percent": pan_info["pan_percent"],
        "pan_direction": pan_info["pan_direction"],
        "muted": bool(RPR_GetTrackSendInfo_Value(
            track,
            category,
            routing_index,
            "B_MUTE"
        )),
        "audio_source_channels_raw": source_channels_raw,
        "audio_source_channels": source_channels,
        "audio_destination_channels_raw": destination_channels_raw,
        "audio_destination_channels": destination_channels,
        "midi_flags_raw": midi_flags_raw,
        "midi_source": midi_source,
        "midi_destination": midi_destination
    }

def handle_get_track_routing(request):
    track_index = request.get("track_index")

    if not isinstance(track_index, int) or isinstance(track_index, bool):
        return {
            "error": "track_index must be a 1-based integer"
        }

    track_count = RPR_CountTracks(0)

    if track_index < 1 or track_index > track_count:
        return {
            "error": (
                f"Track index {track_index} is out of range; "
                f"project has {track_count} tracks"
            )
        }

    track = RPR_GetTrack(0, track_index - 1)
    _, track_name = get_track_identity(track)

    categories = {
        "sends": 0,
        "receives": -1,
        "hardware_outputs": 1
    }
    routing = {}

    for collection_name, category in categories.items():
        routing_count = RPR_GetTrackNumSends(track, category)
        routing[collection_name] = [
            get_routing_entry(track, category, routing_index)
            for routing_index in range(routing_count)
        ]

    return {
        "track_index": track_index,
        "track_name": track_name,
        **routing
    }

def handle_get_track_items(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    item_count = RPR_CountTrackMediaItems(context["track"])
    items = [
        get_item_state(
            RPR_GetTrackMediaItem(context["track"], item_index),
            item_index + 1
        )
        for item_index in range(item_count)
    ]

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_count": item_count,
        "items": items
    }

def handle_get_selected_tracks(request):
    selected_tracks = []

    for selected_index in range(RPR_CountSelectedTracks(0)):
        track = RPR_GetSelectedTrack(0, selected_index)
        track_index, track_name = get_track_identity(track)
        selected_tracks.append({
            "track_index": track_index,
            "track_name": track_name
        })

    selected_tracks.sort(key=lambda track: track["track_index"])
    return {"tracks": selected_tracks}

def handle_get_item_info(request):
    context, error = resolve_item(request)

    if error is not None:
        return error

    item = context["item"]
    item_state = get_item_state(item, context["item_index"])
    take_count = RPR_CountTakes(item)
    active_take = RPR_GetActiveTake(item)

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        **item_state,
        "take_count": take_count,
        "active_take_name": (
            RPR_GetTakeName(active_take) if take_count > 0 else None
        ),
        "active_source_type": (
            get_take_source_type(active_take) if take_count > 0 else None
        )
    }

def handle_get_item_takes(request):
    context, error = resolve_item(request)

    if error is not None:
        return error

    active_take = RPR_GetActiveTake(context["item"])
    take_count = RPR_CountTakes(context["item"])
    takes = []

    for reaper_take_index in range(take_count):
        take = RPR_GetTake(context["item"], reaper_take_index)
        takes.append({
            "take_index": reaper_take_index + 1,
            "name": RPR_GetTakeName(take),
            "active": take == active_take,
            "source_type": get_take_source_type(take)
        })

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_index": context["item_index"],
        "item_guid": get_item_identity(context["item"]),
        "take_count": take_count,
        "takes": takes
    }

def require_midi_take(request):
    context, error = resolve_take(request)

    if error is not None:
        return None, error

    if not RPR_TakeIsMIDI(context["take"]):
        return None, {
            "error": (
                f"Take {context['take_index']} on item "
                f"{context['item_index']} is not MIDI"
            )
        }

    return context, None

def handle_get_midi_summary(request):
    context, error = require_midi_take(request)

    if error is not None:
        return error

    counts = RPR_MIDI_CountEvts(context["take"], 0, 0, 0)
    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_index": context["item_index"],
        "take_index": context["take_index"],
        "take_name": context["take_name"],
        "note_count": counts[2],
        "control_change_count": counts[3],
        "text_sysex_count": counts[4]
    }

def handle_get_midi_notes(request):
    context, error = require_midi_take(request)

    if error is not None:
        return error

    counts = RPR_MIDI_CountEvts(context["take"], 0, 0, 0)
    notes = []

    for reaper_note_index in range(counts[2]):
        note = RPR_MIDI_GetNote(
            context["take"], reaper_note_index,
            False, False, 0.0, 0.0, 0, 0, 0
        )

        if not note[0]:
            continue

        start_seconds = RPR_MIDI_GetProjTimeFromPPQPos(
            context["take"], note[5]
        )
        end_seconds = RPR_MIDI_GetProjTimeFromPPQPos(
            context["take"], note[6]
        )
        start_musical = get_musical_position(start_seconds)
        end_musical = get_musical_position(end_seconds)
        notes.append({
            "note_index": reaper_note_index + 1,
            "selected": bool(note[3]),
            "muted": bool(note[4]),
            "start_ppq": note[5],
            "end_ppq": note[6],
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "duration_seconds": end_seconds - start_seconds,
            "channel": note[7] + 1,
            "pitch": note[8],
            "note_name": get_midi_note_name(note[8]),
            "velocity": note[9],
            "start_musical_position": start_musical["musical_position"],
            "end_musical_position": end_musical["musical_position"]
        })

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_index": context["item_index"],
        "take_index": context["take_index"],
        "take_name": context["take_name"],
        "note_count": len(notes),
        "notes": notes
    }

def get_envelope_metadata(envelope, envelope_index):
    return {
        "envelope_index": envelope_index,
        "name": RPR_GetEnvelopeName(envelope, "", 512)[2],
        "visible": bool(RPR_GetEnvelopeInfo_Value(
            envelope, "B_VISIBLE"
        )),
        "armed": bool(RPR_GetEnvelopeInfo_Value(envelope, "B_ARM")),
        "active": bool(RPR_GetEnvelopeInfo_Value(
            envelope, "B_ACTIVE"
        )),
        "scaling_mode_raw": RPR_GetEnvelopeScalingMode(envelope),
        "point_count": RPR_CountEnvelopePoints(envelope)
    }

def handle_get_track_envelopes(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    envelope_count = RPR_CountTrackEnvelopes(context["track"])
    envelopes = [
        get_envelope_metadata(
            RPR_GetTrackEnvelope(context["track"], envelope_index),
            envelope_index + 1
        )
        for envelope_index in range(envelope_count)
    ]

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "envelope_count": envelope_count,
        "envelopes": envelopes
    }

def resolve_track_envelope(request):
    context, error = resolve_track(request)

    if error is not None:
        return None, error

    envelope_index = request.get("envelope_index")

    if (
        not isinstance(envelope_index, int)
        or isinstance(envelope_index, bool)
    ):
        return None, {
            "error": "envelope_index must be a 1-based integer"
        }

    envelope_count = RPR_CountTrackEnvelopes(context["track"])

    if envelope_index < 1 or envelope_index > envelope_count:
        return None, {
            "error": (
                f"Envelope index {envelope_index} is out of range; "
                f"track {context['track_index']} has "
                f"{envelope_count} envelopes"
            )
        }

    context["envelope_index"] = envelope_index
    context["envelope"] = RPR_GetTrackEnvelope(
        context["track"], envelope_index - 1
    )
    return context, None

def handle_get_envelope_points(request):
    context, error = resolve_track_envelope(request)

    if error is not None:
        return error

    envelope = context["envelope"]
    point_count = RPR_CountEnvelopePoints(envelope)
    points = []

    for reaper_point_index in range(point_count):
        point = RPR_GetEnvelopePoint(
            envelope, reaper_point_index,
            0.0, 0.0, 0, 0.0, False
        )

        if point[0]:
            evaluated = RPR_Envelope_Evaluate(
                envelope, point[3], 0.0, 0,
                0.0, 0.0, 0.0, 0.0
            )
            formatted_value = RPR_Envelope_FormatValue(
                envelope, evaluated[5], "", 512
            )[2]
            points.append({
                "point_index": reaper_point_index + 1,
                "time_seconds": point[3],
                "value_raw": point[4],
                "formatted_value": formatted_value,
                "shape_raw": point[5],
                "tension": point[6],
                "selected": bool(point[7]),
                "musical_position": get_musical_position(
                    point[3]
                )["musical_position"]
            })

    metadata = get_envelope_metadata(
        envelope, context["envelope_index"]
    )
    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        **metadata,
        "points": points
    }

def handle_get_track_channels(request):
    tracks = []

    for reaper_track_index in range(RPR_CountTracks(0)):
        track = RPR_GetTrack(0, reaper_track_index)
        track_index, track_name = get_track_identity(track)
        tracks.append({
            "track_index": track_index,
            "track_name": track_name,
            "channel_count": int(RPR_GetMediaTrackInfo_Value(
                track, "I_NCHAN"
            )),
            "midi_hardware_output_raw": int(
                RPR_GetMediaTrackInfo_Value(track, "I_MIDIHWOUT")
            )
        })

    return {"tracks": tracks}

def handle_get_master_track(request):
    track = RPR_GetMasterTrack(0)
    reaper_track_number, track_name = get_track_identity(track)
    volume = RPR_GetMediaTrackInfo_Value(track, "D_VOL")
    volume_db = linear_to_db(volume)
    pan_info = get_pan_info(RPR_GetMediaTrackInfo_Value(track, "D_PAN"))

    return {
        "track_index": 0,
        "reaper_track_number": reaper_track_number,
        "track_name": track_name,
        "muted": bool(RPR_GetMediaTrackInfo_Value(track, "B_MUTE")),
        "solo": RPR_GetMediaTrackInfo_Value(track, "I_SOLO") > 0,
        "volume": volume,
        "volume_db": round(volume_db, 2) if volume_db is not None else None,
        **pan_info,
        "channel_count": int(RPR_GetMediaTrackInfo_Value(
            track, "I_NCHAN"
        ))
    }

def handle_get_master_fx(request):
    track = RPR_GetMasterTrack(0)
    reaper_track_number, track_name = get_track_identity(track)
    fx_count = RPR_TrackFX_GetCount(track)
    fx = []

    for reaper_fx_index in range(fx_count):
        fx.append({
            "index": reaper_fx_index + 1,
            "name": RPR_TrackFX_GetFXName(
                track, reaper_fx_index, "", 512
            )[3],
            "enabled": bool(RPR_TrackFX_GetEnabled(
                track, reaper_fx_index
            )),
            "offline": bool(RPR_TrackFX_GetOffline(
                track, reaper_fx_index
            ))
        })

    return {
        "track_index": 0,
        "reaper_track_number": reaper_track_number,
        "track_name": track_name,
        "fx_count": fx_count,
        "fx": fx
    }

def handle_get_project_time_selection(request):
    selection = RPR_GetSet_LoopTimeRange2(
        0, False, False, 0.0, 0.0, False
    )
    start_seconds = selection[3]
    end_seconds = selection[4]
    has_selection = end_seconds > start_seconds

    return {
        "has_time_selection": has_selection,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "duration_seconds": end_seconds - start_seconds,
        "start_musical_position": (
            get_musical_position(start_seconds)["musical_position"]
            if has_selection else None
        ),
        "end_musical_position": (
            get_musical_position(end_seconds)["musical_position"]
            if has_selection else None
        )
    }

def handle_get_cursor_position(request):
    position_seconds = RPR_GetCursorPositionEx(0)
    musical = get_musical_position(position_seconds)
    return {
        "position_seconds": position_seconds,
        "position_beats": musical["position_beats"],
        "musical_position": musical["musical_position"]
    }

def handle_get_current_context(request):
    return {
        "selected_tracks": handle_get_selected_tracks(request)["tracks"],
        "cursor": handle_get_cursor_position(request),
        "time_selection": handle_get_project_time_selection(request)
    }

def handle_get_take_fx(request):
    context, error = resolve_take(request)

    if error is not None:
        return error

    fx_count = RPR_TakeFX_GetCount(context["take"])
    fx = []

    for reaper_fx_index in range(fx_count):
        fx.append({
            "index": reaper_fx_index + 1,
            "name": RPR_TakeFX_GetFXName(
                context["take"], reaper_fx_index, "", 512
            )[3],
            "enabled": bool(RPR_TakeFX_GetEnabled(
                context["take"], reaper_fx_index
            )),
            "offline": bool(RPR_TakeFX_GetOffline(
                context["take"], reaper_fx_index
            ))
        })

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_index": context["item_index"],
        "take_index": context["take_index"],
        "take_name": context["take_name"],
        "fx_count": fx_count,
        "fx": fx
    }

def handle_get_track_fx(request):
    tracks = []

    track_count = RPR_CountTracks(0)

    for track_index in range(track_count):
        track = RPR_GetTrack(0, track_index)

        track_name_info = RPR_GetTrackName(track, "", 512)
        track_name = track_name_info[2]

        fx = get_track_fx_entries(track)

        tracks.append({
            "track_index": track_index + 1,
            "track_name": track_name,
            "fx_count": len(fx),
            "fx": fx
        })

    return {
        "tracks": tracks
    }

def get_track_fx_entries(track):
    entries = []
    for reaper_fx_index in range(RPR_TrackFX_GetCount(track)):
        fx_name_info = RPR_TrackFX_GetFXName(
            track, reaper_fx_index, "", 512
        )
        entries.append({
            "index": reaper_fx_index + 1,
            "name": fx_name_info[3],
            "enabled": bool(RPR_TrackFX_GetEnabled(
                track, reaper_fx_index
            )),
            "offline": bool(RPR_TrackFX_GetOffline(
                track, reaper_fx_index
            ))
        })
    return entries

def get_track_fx_move_destination(current_index, target_index):
    if current_index < target_index:
        return target_index + 1
    return target_index

def handle_ensure_track_fx(request):
    track_context, error = resolve_track(request)
    if error is not None:
        return error
    fx_name = request.get("fx_name")
    if not isinstance(fx_name, str) or not fx_name.strip():
        return {"error": "fx_name must be a non-blank string"}
    fx_name = fx_name.strip()
    position = request.get("position")
    if position is not None and (
        not isinstance(position, int) or isinstance(position, bool)
        or position < 0
    ):
        return {"error": "position must be a zero-based non-negative integer"}

    track = track_context["track"]
    before = get_track_fx_entries(track)
    matching_indexes = [
        entry["index"] - 1 for entry in before
        if entry["name"] == fx_name
    ]
    if matching_indexes:
        current_index = matching_indexes[0]
        if position is not None and position >= len(before):
            return {"error": (
                f"position {position} is out of range for an existing FX; "
                f"track has {len(before)} FX"
            )}
        action = "preserved"
        if position is not None and current_index != position:
            RPR_TrackFX_CopyToTrack(
                track,
                current_index,
                track,
                get_track_fx_move_destination(current_index, position),
                True
            )
            action = "moved"
    else:
        if position is not None and position > len(before):
            return {"error": (
                f"position {position} is out of range for insertion; "
                f"track has {len(before)} FX"
            )}
        instantiate = 1 if position is None else -1000 - position
        added_index = RPR_TrackFX_AddByName(
            track, fx_name, False, instantiate
        )
        if added_index < 0:
            return {
                "error": f"REAPER could not locate FX plugin: {fx_name}",
                "track_index": track_context["track_index"],
                "track_name": track_context["track_name"]
            }
        action = "inserted"
        position = added_index

    after = get_track_fx_entries(track)
    expected_index = position if position is not None else (
        matching_indexes[0] if matching_indexes else len(after) - 1
    )
    verified = (
        0 <= expected_index < len(after)
        and after[expected_index]["name"] == fx_name
    )
    if not verified:
        rollback_succeeded = None
        if action == "inserted" and 0 <= expected_index < len(after):
            RPR_TrackFX_Delete(track, expected_index)
            rollback_succeeded = get_track_fx_entries(track) == before
        elif action == "moved":
            matching_after = [
                entry["index"] - 1 for entry in after
                if entry["name"] == fx_name
            ]
            if matching_after:
                rollback_source = matching_after[0]
                RPR_TrackFX_CopyToTrack(
                    track,
                    rollback_source,
                    track,
                    get_track_fx_move_destination(
                        rollback_source, current_index
                    ),
                    True
                )
                rollback_succeeded = get_track_fx_entries(track) == before
        return {
            "error": "FX chain read-back verification failed",
            "requested_fx_name": fx_name,
            "expected_position": expected_index,
            "fx_read_back": after,
            "rollback_succeeded": rollback_succeeded
        }
    return {
        "success": True,
        "track_index": track_context["track_index"],
        "track_name": track_context["track_name"],
        "fx_name": fx_name,
        "fx_index": expected_index + 1,
        "position": expected_index,
        "action": action,
        "fx": after[expected_index],
        "fx_count": len(after)
    }

def resolve_track_fx(request):
    track_index = request.get("track_index")
    fx_index = request.get("fx_index")

    if not isinstance(track_index, int) or isinstance(track_index, bool):
        return None, {
            "error": "track_index must be a 1-based integer"
        }

    track_count = RPR_CountTracks(0)

    if track_index < 1 or track_index > track_count:
        return None, {
            "error": (
                f"Track index {track_index} is out of range; "
                f"project has {track_count} tracks"
            )
        }

    track = RPR_GetTrack(0, track_index - 1)

    if not isinstance(fx_index, int) or isinstance(fx_index, bool):
        return None, {
            "error": "fx_index must be a 1-based integer"
        }

    fx_count = RPR_TrackFX_GetCount(track)

    if fx_index < 1 or fx_index > fx_count:
        return None, {
            "error": (
                f"FX index {fx_index} is out of range; "
                f"track {track_index} has {fx_count} FX"
            )
        }

    reaper_fx_index = fx_index - 1

    track_name_info = RPR_GetTrackName(track, "", 512)
    track_name = track_name_info[2]

    fx_name_info = RPR_TrackFX_GetFXName(
        track,
        reaper_fx_index,
        "",
        512
    )
    fx_name = fx_name_info[3]

    return {
        "track_index": track_index,
        "track": track,
        "track_name": track_name,
        "fx_index": fx_index,
        "reaper_fx_index": reaper_fx_index,
        "fx_name": fx_name
    }, None

def get_fx_parameter_info(track, reaper_fx_index, parameter_index):
    parameter_name_info = RPR_TrackFX_GetParamName(
        track,
        reaper_fx_index,
        parameter_index,
        "",
        512
    )
    parameter_value_info = RPR_TrackFX_GetParamEx(
        track,
        reaper_fx_index,
        parameter_index,
        0.0,
        0.0,
        0.0
    )
    formatted_value_info = RPR_TrackFX_GetFormattedParamValue(
        track,
        reaper_fx_index,
        parameter_index,
        "",
        512
    )

    return {
        "index": parameter_index + 1,
        "name": parameter_name_info[4],
        "value": parameter_value_info[0],
        "formatted_value": formatted_value_info[4],
        "min_value": parameter_value_info[4],
        "max_value": parameter_value_info[5],
        "mid_value": parameter_value_info[6]
    }

def normalize_formatted_value(value):
    return " ".join(value.split()).casefold()

def parse_formatted_number(value):
    normalized_value = normalize_formatted_value(value)
    matches = list(re.finditer(
        r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[-+]?\d+)?",
        normalized_value
    ))

    if len(matches) != 1:
        return None

    match = matches[0]
    number_text = match.group(0).replace(",", ".")

    if "e" in number_text:
        mantissa, exponent_text = number_text.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa = number_text
        exponent = 0

    decimal_places = (
        len(mantissa.split(".", 1)[1])
        if "." in mantissa
        else 0
    )

    try:
        number = float(number_text)
    except ValueError:
        return None

    if not math.isfinite(number):
        return None

    tolerance = 0.5 * (10 ** (exponent - decimal_places))

    return number, tolerance

def formatted_numbers_match(target_number, formatted_number_info):
    formatted_number, formatted_tolerance = formatted_number_info

    return (
        abs(formatted_number - target_number)
        <= formatted_tolerance + 1e-12
    )

def format_fx_parameter_normalized(
    track,
    reaper_fx_index,
    reaper_parameter_index,
    normalized_value
):
    formatted_value_info = RPR_TrackFX_FormatParamValueNormalized(
        track,
        reaper_fx_index,
        reaper_parameter_index,
        normalized_value,
        "",
        512
    )

    if not formatted_value_info[0]:
        return None

    return formatted_value_info[5]

def resolve_formatted_fx_parameter(
    track,
    reaper_fx_index,
    reaper_parameter_index,
    requested_formatted_value
):
    parsed_target = parse_formatted_number(requested_formatted_value)

    if parsed_target is None:
        return None

    target_number, _ = parsed_target
    sample_count = 64
    samples = []

    for sample_index in range(sample_count + 1):
        normalized_value = sample_index / sample_count
        formatted_value = format_fx_parameter_normalized(
            track,
            reaper_fx_index,
            reaper_parameter_index,
            normalized_value
        )

        if formatted_value is None:
            return None

        parsed_formatted_value = parse_formatted_number(formatted_value)

        if parsed_formatted_value is None:
            return None

        if formatted_numbers_match(target_number, parsed_formatted_value):
            return normalized_value

        samples.append((
            normalized_value,
            parsed_formatted_value
        ))

    for sample_index in range(sample_count):
        low_normalized, low_parsed = samples[sample_index]
        high_normalized, high_parsed = samples[sample_index + 1]

        if low_parsed is None or high_parsed is None:
            continue

        low_number, _ = low_parsed
        high_number, _ = high_parsed

        if (
            low_number == high_number
            or target_number < min(low_number, high_number)
            or target_number > max(low_number, high_number)
        ):
            continue

        is_increasing = high_number > low_number

        for _ in range(40):
            middle_normalized = (
                low_normalized + high_normalized
            ) / 2
            middle_formatted = format_fx_parameter_normalized(
                track,
                reaper_fx_index,
                reaper_parameter_index,
                middle_normalized
            )

            if middle_formatted is None:
                return None

            middle_parsed = parse_formatted_number(middle_formatted)

            if middle_parsed is None:
                break

            if formatted_numbers_match(target_number, middle_parsed):
                return middle_normalized

            middle_number, _ = middle_parsed

            if (middle_number < target_number) == is_increasing:
                low_normalized = middle_normalized
            else:
                high_normalized = middle_normalized

    return None

def handle_get_fx_parameters(request):
    fx_context, error = resolve_track_fx(request)

    if error is not None:
        return error

    track = fx_context["track"]
    reaper_fx_index = fx_context["reaper_fx_index"]

    parameter_count = RPR_TrackFX_GetNumParams(
        track,
        reaper_fx_index
    )
    parameters = []

    for parameter_index in range(parameter_count):
        parameters.append(get_fx_parameter_info(
            track,
            reaper_fx_index,
            parameter_index
        ))

    return {
        "track_index": fx_context["track_index"],
        "track_name": fx_context["track_name"],
        "fx_index": fx_context["fx_index"],
        "fx_name": fx_context["fx_name"],
        "parameter_count": parameter_count,
        "parameters": parameters
    }

def resolve_fx_parameter(request):
    fx_context, error = resolve_track_fx(request)

    if error is not None:
        return None, error

    parameter_index = request.get("parameter_index")

    if (
        not isinstance(parameter_index, int)
        or isinstance(parameter_index, bool)
    ):
        return None, {
            "error": "parameter_index must be a 1-based integer"
        }

    parameter_count = RPR_TrackFX_GetNumParams(
        fx_context["track"],
        fx_context["reaper_fx_index"]
    )

    if parameter_index < 1 or parameter_index > parameter_count:
        return None, {
            "error": (
                f"Parameter index {parameter_index} is out of range; "
                f"FX {fx_context['fx_index']} has "
                f"{parameter_count} parameters"
            )
        }

    fx_context["parameter_index"] = parameter_index
    fx_context["reaper_parameter_index"] = parameter_index - 1

    return fx_context, None

def handle_get_fx_parameter(request):
    parameter_context, error = resolve_fx_parameter(request)

    if error is not None:
        return error

    parameter = get_fx_parameter_info(
        parameter_context["track"],
        parameter_context["reaper_fx_index"],
        parameter_context["reaper_parameter_index"]
    )

    return {
        "track_index": parameter_context["track_index"],
        "track_name": parameter_context["track_name"],
        "fx_index": parameter_context["fx_index"],
        "fx_name": parameter_context["fx_name"],
        "parameter_index": parameter["index"],
        "parameter_name": parameter["name"],
        "value": parameter["value"],
        "formatted_value": parameter["formatted_value"],
        "min_value": parameter["min_value"],
        "max_value": parameter["max_value"],
        "mid_value": parameter["mid_value"]
    }

def handle_diagnose_fx_parameter_formatter(request):
    parameter_context, error = resolve_fx_parameter(request)

    if error is not None:
        return error

    parameter = get_fx_parameter_info(
        parameter_context["track"],
        parameter_context["reaper_fx_index"],
        parameter_context["reaper_parameter_index"]
    )
    samples = []

    for sample_index in range(11):
        normalized_value = sample_index / 10
        formatted_value_info = RPR_TrackFX_FormatParamValueNormalized(
            parameter_context["track"],
            parameter_context["reaper_fx_index"],
            parameter_context["reaper_parameter_index"],
            normalized_value,
            "",
            512
        )

        samples.append({
            "normalized_value": normalized_value,
            "formatter_success": bool(formatted_value_info[0]),
            "formatted_value": formatted_value_info[5]
        })

    return {
        "track_index": parameter_context["track_index"],
        "track_name": parameter_context["track_name"],
        "fx_index": parameter_context["fx_index"],
        "fx_name": parameter_context["fx_name"],
        "parameter_index": parameter["index"],
        "parameter_name": parameter["name"],
        "samples": samples
    }

def handle_set_fx_parameter(request):
    parameter_context, error = resolve_fx_parameter(request)

    if error is not None:
        return error

    normalized_value = request.get("normalized_value")
    formatted_value = request.get("formatted_value")
    has_normalized_value = normalized_value is not None
    has_formatted_value = formatted_value is not None

    if has_normalized_value == has_formatted_value:
        return {
            "error": (
                "Exactly one of normalized_value or formatted_value "
                "must be provided"
            )
        }

    if has_normalized_value:
        if (
            not isinstance(normalized_value, (int, float))
            or isinstance(normalized_value, bool)
            or not math.isfinite(normalized_value)
        ):
            return {
                "error": (
                    "normalized_value must be a finite number "
                    "from 0.0 to 1.0"
                )
            }

        if normalized_value < 0.0 or normalized_value > 1.0:
            return {
                "error": (
                    f"Normalized value {normalized_value} is out "
                    "of range; expected 0.0 to 1.0"
                )
            }

        input_mode = "normalized"
        resolved_normalized_value = float(normalized_value)

    else:
        if (
            not isinstance(formatted_value, str)
            or not formatted_value.strip()
        ):
            return {
                "error": "formatted_value must be a non-empty string"
            }

        input_mode = "formatted"
        resolved_normalized_value = resolve_formatted_fx_parameter(
            parameter_context["track"],
            parameter_context["reaper_fx_index"],
            parameter_context["reaper_parameter_index"],
            formatted_value
        )

        if resolved_normalized_value is None:
            return {
                "error": (
                    "formatted_value could not be resolved reliably; "
                    "only continuous parameters with a single numeric "
                    "formatted value are supported"
                )
            }

    write_succeeded = RPR_TrackFX_SetParamNormalized(
        parameter_context["track"],
        parameter_context["reaper_fx_index"],
        parameter_context["reaper_parameter_index"],
        resolved_normalized_value
    )

    if not write_succeeded:
        return {
            "error": "REAPER failed to set the FX parameter"
        }

    try:
        applied_value = RPR_TrackFX_GetParamNormalized(
            parameter_context["track"],
            parameter_context["reaper_fx_index"],
            parameter_context["reaper_parameter_index"]
        )
        parameter = get_fx_parameter_info(
            parameter_context["track"],
            parameter_context["reaper_fx_index"],
            parameter_context["reaper_parameter_index"]
        )
    except Exception as read_back_error:
        return {
            "error": (
                "Failed to read back the FX parameter: "
                f"{read_back_error}"
            )
        }

    if (
        not isinstance(applied_value, (int, float))
        or isinstance(applied_value, bool)
        or not math.isfinite(applied_value)
        or applied_value < 0.0
        or applied_value > 1.0
    ):
        return {
            "error": "REAPER returned an invalid parameter read-back value"
        }

    canonical_formatted_value = None

    if input_mode == "formatted":
        requested_formatted_number = parse_formatted_number(
            formatted_value
        )
        read_back_formatted_number = parse_formatted_number(
            parameter["formatted_value"]
        )
        canonical_formatted_value = format_fx_parameter_normalized(
            parameter_context["track"],
            parameter_context["reaper_fx_index"],
            parameter_context["reaper_parameter_index"],
            applied_value
        )
        canonical_formatted_number = (
            parse_formatted_number(canonical_formatted_value)
            if canonical_formatted_value is not None
            else None
        )

        if (
            requested_formatted_number is None
            or read_back_formatted_number is None
            or canonical_formatted_number is None
        ):
            return {
                "error": (
                    "REAPER returned an unparseable formatted "
                    "read-back value"
                )
            }

        requested_number, _ = requested_formatted_number

        if (
            not formatted_numbers_match(
                requested_number,
                read_back_formatted_number
            )
            or not formatted_numbers_match(
                requested_number,
                canonical_formatted_number
            )
        ):
            return {
                "error": (
                    "REAPER formatted read-back did not match the "
                    "requested numeric value"
                )
            }

    response = {
        "track_index": parameter_context["track_index"],
        "track_name": parameter_context["track_name"],
        "fx_index": parameter_context["fx_index"],
        "fx_name": parameter_context["fx_name"],
        "parameter_index": parameter["index"],
        "parameter_name": parameter["name"],
        "input_mode": input_mode,
        "resolved_normalized_value": resolved_normalized_value,
        "applied_value": applied_value,
        "formatted_value": parameter["formatted_value"],
        "success": True
    }

    if input_mode == "normalized":
        response["requested_normalized_value"] = float(normalized_value)
    else:
        response["requested_formatted_value"] = formatted_value
        response["canonical_formatted_value"] = (
            canonical_formatted_value
        )

    return response

def handle_set_fx_enabled(request):
    context, error = resolve_track_fx(request)

    if error is not None:
        return error

    enabled = request.get("enabled")

    if not isinstance(enabled, bool):
        return {"error": "enabled must be a boolean"}

    RPR_TrackFX_SetEnabled(
        context["track"], context["reaper_fx_index"], enabled
    )
    applied_enabled = bool(RPR_TrackFX_GetEnabled(
        context["track"], context["reaper_fx_index"]
    ))

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "fx_index": context["fx_index"],
        "fx_name": context["fx_name"],
        "requested_enabled": enabled,
        "applied_enabled": applied_enabled,
        "success": applied_enabled == enabled
    }

def handle_set_track_volume(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    volume_raw = request.get("volume_raw")
    volume_db = request.get("volume_db")
    has_raw = volume_raw is not None
    has_db = volume_db is not None

    if has_raw == has_db:
        return {
            "error": "Exactly one of volume_raw or volume_db must be provided"
        }

    requested_value = volume_raw if has_raw else volume_db

    if (
        not isinstance(requested_value, (int, float))
        or isinstance(requested_value, bool)
        or not math.isfinite(requested_value)
    ):
        return {"error": "Volume input must be a finite number"}

    if has_raw:
        if volume_raw < 0.0:
            return {"error": "volume_raw must be greater than or equal to 0"}

        input_mode = "raw"
        resolved_volume_raw = float(volume_raw)
        requested_volume_raw = resolved_volume_raw
        requested_volume_db = linear_to_db(resolved_volume_raw)
    else:
        input_mode = "db"
        try:
            resolved_volume_raw = math.pow(
                10.0, float(volume_db) / 20.0
            )
        except OverflowError:
            return {
                "error": "volume_db is outside the representable volume range"
            }

        if not math.isfinite(resolved_volume_raw):
            return {
                "error": "volume_db is outside the representable volume range"
            }

        requested_volume_raw = resolved_volume_raw
        requested_volume_db = float(volume_db)

    write_succeeded = RPR_SetMediaTrackInfo_Value(
        context["track"], "D_VOL", resolved_volume_raw
    )

    if not write_succeeded:
        return {"error": "REAPER failed to set track volume"}

    applied_volume_raw = RPR_GetMediaTrackInfo_Value(
        context["track"], "D_VOL"
    )
    applied_volume_db = linear_to_db(applied_volume_raw)

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "input_mode": input_mode,
        "requested_volume_raw": requested_volume_raw,
        "requested_volume_db": requested_volume_db,
        "applied_volume_raw": applied_volume_raw,
        "applied_volume_db": (
            round(applied_volume_db, 2)
            if applied_volume_db is not None
            else None
        ),
        "success": math.isclose(
            applied_volume_raw, resolved_volume_raw,
            rel_tol=1e-9, abs_tol=1e-12
        )
    }

def handle_set_track_pan(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    pan_raw = request.get("pan_raw")
    pan_percent = request.get("pan_percent")
    has_raw = pan_raw is not None
    has_percent = pan_percent is not None

    if has_raw == has_percent:
        return {
            "error": "Exactly one of pan_raw or pan_percent must be provided"
        }

    requested_value = pan_raw if has_raw else pan_percent

    if (
        not isinstance(requested_value, (int, float))
        or isinstance(requested_value, bool)
        or not math.isfinite(requested_value)
    ):
        return {"error": "Pan input must be a finite number"}

    if has_raw:
        if pan_raw < -1.0 or pan_raw > 1.0:
            return {"error": "pan_raw must be from -1.0 to 1.0"}

        input_mode = "raw"
        resolved_pan_raw = float(pan_raw)
    else:
        if pan_percent < -100.0 or pan_percent > 100.0:
            return {"error": "pan_percent must be from -100.0 to 100.0"}

        input_mode = "percent"
        resolved_pan_raw = float(pan_percent) / 100.0

    write_succeeded = RPR_SetMediaTrackInfo_Value(
        context["track"], "D_PAN", resolved_pan_raw
    )

    if not write_succeeded:
        return {"error": "REAPER failed to set track pan"}

    applied_pan_raw = RPR_GetMediaTrackInfo_Value(
        context["track"], "D_PAN"
    )
    requested_pan = get_pan_info(resolved_pan_raw)
    applied_pan = get_pan_info(applied_pan_raw)

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "input_mode": input_mode,
        "requested_pan_raw": requested_pan["pan"],
        "requested_pan_percent": requested_pan["pan_percent"],
        "requested_pan_direction": requested_pan["pan_direction"],
        "applied_pan_raw": applied_pan["pan"],
        "applied_pan_percent": applied_pan["pan_percent"],
        "applied_pan_direction": applied_pan["pan_direction"],
        "success": math.isclose(
            applied_pan_raw, resolved_pan_raw,
            rel_tol=1e-9, abs_tol=1e-12
        )
    }

def handle_set_track_mute(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    muted = request.get("muted")

    if not isinstance(muted, bool):
        return {"error": "muted must be a boolean"}

    write_succeeded = RPR_SetMediaTrackInfo_Value(
        context["track"], "B_MUTE", 1.0 if muted else 0.0
    )

    if not write_succeeded:
        return {"error": "REAPER failed to set track mute state"}

    applied_muted = bool(RPR_GetMediaTrackInfo_Value(
        context["track"], "B_MUTE"
    ))

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "requested_muted": muted,
        "applied_muted": applied_muted,
        "success": applied_muted == muted
    }

def handle_set_track_record_arm(request):
    context, error = resolve_track(request)
    if error is not None:
        return error
    armed = request.get("armed")
    if not isinstance(armed, bool):
        return {"error": "armed must be a boolean"}
    write_succeeded = RPR_SetMediaTrackInfo_Value(
        context["track"], "I_RECARM", 1.0 if armed else 0.0
    )
    if not write_succeeded:
        return {"error": "REAPER failed to set track record-arm state"}
    applied_armed = bool(RPR_GetMediaTrackInfo_Value(
        context["track"], "I_RECARM"
    ))
    RPR_TrackList_AdjustWindows(False)
    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "requested_armed": armed,
        "applied_armed": applied_armed,
        "success": applied_armed == armed
    }

def handle_set_track_solo(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    solo = request.get("solo")

    if not isinstance(solo, bool):
        return {"error": "solo must be a boolean"}

    setter_result = RPR_SetTrackUISolo(
        context["track"], 1 if solo else 0, 1
    )

    if setter_result < 0:
        return {"error": "REAPER failed to set track solo state"}

    applied_solo_raw = int(RPR_GetMediaTrackInfo_Value(
        context["track"], "I_SOLO"
    ))
    applied_solo = applied_solo_raw > 0

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "requested_solo": solo,
        "applied_solo": applied_solo,
        "applied_solo_raw": applied_solo_raw,
        "success": applied_solo == solo
    }

def get_active_project_identity():
    project, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    name = RPR_GetSetProjectInfo_String(project, "PROJECT_NAME", "", False)[3]
    return project, {"project_id": str(project), "project_path": path,
                     "project_name": name}


def resolve_note_item_range(request):
    start_measure = request.get("start_measure")
    duration_measures = request.get("duration_measures")
    start_seconds = request.get("start_seconds")
    duration_seconds = request.get("duration_seconds")
    measures = start_measure is not None or duration_measures is not None
    seconds = start_seconds is not None or duration_seconds is not None
    if measures == seconds:
        return None, {"error": "Specify exactly one complete timing pair: start_measure/duration_measures or start_seconds/duration_seconds; do not mix modes"}
    if measures:
        if type(start_measure) is not int or start_measure < 1:
            return None, {"error": "start_measure must be a 1-based positive integer"}
        if type(duration_measures) is not int or duration_measures < 1:
            return None, {"error": "duration_measures must be a positive integer"}
        if start_measure + duration_measures > 2147483647:
            return None, {"error": "Measure end exceeds REAPER's supported integer range"}
        start_seconds = get_measure_boundary(start_measure)
        end_seconds = get_measure_boundary(start_measure + duration_measures)
        duration_seconds = end_seconds - start_seconds
    else:
        for name, value in (("start_seconds", start_seconds),
                            ("duration_seconds", duration_seconds)):
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            if not valid:
                return None, {"error": f"{name} must be a finite number; both seconds fields are required"}
        start_seconds, duration_seconds = float(start_seconds), float(duration_seconds)
        end_seconds = start_seconds + duration_seconds
    if (not math.isfinite(start_seconds) or not math.isfinite(duration_seconds)
            or not math.isfinite(end_seconds) or start_seconds < 0
            or duration_seconds <= 0 or end_seconds <= start_seconds):
        return None, {"error": "Timing must have finite start >= 0, duration > 0 and a representable end after start"}
    return {"timing_mode": "measures" if measures else "seconds",
            "start_measure": start_measure, "duration_measures": duration_measures,
            "end_measure": start_measure + duration_measures if measures else None,
            "position_seconds": start_seconds, "start_seconds": start_seconds,
            "duration_seconds": duration_seconds, "end_seconds": end_seconds}, None


def handle_create_note_item(request):
    project, project_identity = get_active_project_identity()
    context, error = resolve_recording_track(request)
    if error is not None:
        return {**project_identity, **error}
    identity = {**project_identity, **recording_identity(context)}
    requested, error = resolve_note_item_range(request)
    if error is not None:
        return {**identity, **error}
    text = request.get("text")
    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        return {**identity, "error": "text must be a non-empty string without NUL characters"}
    conflicts = get_item_conflicts(
        context["track"], requested["position_seconds"], requested["end_seconds"]
    )
    if conflicts:
        return {**identity, "error": "item_overlap", "requested_range": requested,
                "conflicts": conflicts}
    item, item_guid = None, None
    RPR_Undo_BeginBlock2(project)
    try:
        item = RPR_AddMediaItemToTrack(context["track"])
        if not RPR_ValidatePtr2(project, item, "MediaItem*"):
            item = None
            raise RuntimeError("REAPER failed to create the media item")
        item_guid = get_item_identity(item)
        position_written = RPR_SetMediaItemInfo_Value(item, "D_POSITION", requested["position_seconds"])
        length_written = RPR_SetMediaItemInfo_Value(item, "D_LENGTH", requested["duration_seconds"])
        notes_written = RPR_GetSetMediaItemInfo_String(item, "P_NOTES", text, True)[0]
        if not position_written or not length_written or not notes_written:
            raise RuntimeError("REAPER failed to initialize the note item")
        item_index = find_item_index(context["track"], item_guid)
        applied_position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        applied_duration = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
        notes_info = RPR_GetSetMediaItemInfo_String(item, "P_NOTES", "", False)
        take_count = RPR_CountTakes(item)
        if (item_index is None or not item_guid or not notes_info[0]
                or notes_info[3] != text or take_count != 0
                or not math.isfinite(applied_position) or applied_position < 0
                or not math.isfinite(applied_duration) or applied_duration <= 0
                or not math.isfinite(applied_position + applied_duration)
                or applied_position + applied_duration <= applied_position
                or not math.isclose(applied_position, requested["position_seconds"], rel_tol=0, abs_tol=1e-9)
                or not math.isclose(applied_duration, requested["duration_seconds"], rel_tol=0, abs_tol=1e-9)):
            raise RuntimeError("Note item read-back verification failed")
        return {**identity, **requested, "item_index": item_index, "item_guid": item_guid,
                "text": notes_info[3], "position_seconds": applied_position,
                "start_seconds": applied_position, "duration_seconds": applied_duration,
                "end_seconds": applied_position + applied_duration,
                "take_count": take_count, "success": True}
    except Exception as error:
        rollback_succeeded = None
        if item is not None:
            try:
                rollback_succeeded = delete_created_item(context["track"], item, item_guid)
            except Exception:
                rollback_succeeded = False
        return {**identity, "error": str(error), "rollback_succeeded": rollback_succeeded}
    finally:
        RPR_Undo_EndBlock2(project, "Create note item", 4)
        RPR_UpdateArrange()


def handle_delete_item(request):
    project, project_identity = get_active_project_identity()
    context, error = resolve_item_by_guid(request)
    if error is not None:
        return {**project_identity, **error}
    track, item = context["track"], context["item"]
    if (not RPR_ValidatePtr2(project, track, "MediaTrack*")
            or not RPR_ValidatePtr2(project, item, "MediaItem*")
            or RPR_GetMediaItem_Track(item) != track):
        return {**project_identity, "error": "Item or track is invalid or item does not belong to the requested track"}
    identity = {**project_identity, "track_index": context["track_index"],
                "track_name": context["track_name"], "track_guid": recording_track_guid(track)}
    before_count = RPR_CountTrackMediaItems(track)
    RPR_Undo_BeginBlock2(project)
    try:
        deleted = RPR_DeleteTrackMediaItem(track, item)
        absent = find_item_by_guid(track, context["item_guid"]) is None
        if not deleted or not absent or RPR_CountTrackMediaItems(track) != before_count - 1:
            return {**identity, "error": "Item deletion read-back verification failed",
                    "item_guid": context["item_guid"], "item_absent": absent}
        return {**identity, "success": True, "item_guid": context["item_guid"],
                "deleted_item_guid": context["item_guid"]}
    except Exception as error:
        return {**identity, "error": str(error), "item_guid": context["item_guid"]}
    finally:
        RPR_Undo_EndBlock2(project, "Delete item by GUID", 4)
        RPR_UpdateArrange()

def handle_set_item_end_measure(request):
    context, error = resolve_item_by_guid(request)

    if error is not None:
        return error

    end_measure = request.get("end_measure")

    if (
        not isinstance(end_measure, int)
        or isinstance(end_measure, bool)
        or end_measure < 1
    ):
        return {"error": "end_measure must be a 1-based positive integer"}

    previous = get_item_state(context["item"], context["item_index"])
    end_seconds = get_measure_boundary(end_measure)
    duration_seconds = end_seconds - previous["position_seconds"]

    if (
        not math.isfinite(end_seconds)
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0.0
    ):
        return {
            "error": "end_measure must be after the item's start position"
        }

    conflicts = get_item_conflicts(
        context["track"],
        previous["position_seconds"],
        end_seconds,
        excluded_item_guid=context["item_guid"]
    )

    if conflicts:
        return {
            "error": "item_overlap",
            "item_guid": context["item_guid"],
            "requested_end_measure": end_measure,
            "conflicts": conflicts
        }

    length_written = RPR_SetMediaItemInfo_Value(
        context["item"], "D_LENGTH", duration_seconds
    )
    RPR_UpdateArrange()

    if not length_written:
        return {"error": "REAPER failed to set the item length"}

    applied = get_item_state(context["item"], context["item_index"])
    success = (
        applied["guid"] == context["item_guid"]
        and math.isclose(
            applied["end_seconds"], end_seconds,
            rel_tol=1e-9, abs_tol=1e-9
        )
        and applied["end_measure"] == end_measure
        and math.isclose(applied["end_beat"], 1.0, abs_tol=1e-7)
    )

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_guid": context["item_guid"],
        "requested_end_measure": end_measure,
        "previous": previous,
        "applied": applied,
        "success": success
    }

def handle_create_click_source_item(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    start_measure = request.get("start_measure")
    end_measure = request.get("end_measure")

    if (
        not isinstance(start_measure, int)
        or isinstance(start_measure, bool)
        or start_measure < 1
    ):
        return {"error": "start_measure must be a 1-based positive integer"}

    if (
        not isinstance(end_measure, int)
        or isinstance(end_measure, bool)
        or end_measure <= start_measure
    ):
        return {
            "error": "end_measure must be an integer greater than start_measure"
        }

    position_seconds = get_measure_boundary(start_measure)
    end_seconds = get_measure_boundary(end_measure)
    duration_seconds = end_seconds - position_seconds

    if (
        not math.isfinite(position_seconds)
        or not math.isfinite(end_seconds)
        or duration_seconds <= 0.0
    ):
        return {"error": "REAPER returned invalid measure boundary positions"}

    conflicts = get_item_conflicts(
        context["track"], position_seconds, end_seconds
    )

    if conflicts:
        return {
            "error": "item_overlap",
            "requested_range": {
                "start_measure": start_measure,
                "end_measure": end_measure,
                "position_seconds": position_seconds,
                "end_seconds": end_seconds
            },
            "conflicts": conflicts
        }

    item = RPR_AddMediaItemToTrack(context["track"])

    if not item:
        return {"error": "REAPER failed to create the media item"}

    item_guid = get_item_identity(item)
    position_written = RPR_SetMediaItemInfo_Value(
        item, "D_POSITION", position_seconds
    )
    length_written = RPR_SetMediaItemInfo_Value(
        item, "D_LENGTH", duration_seconds
    )
    take = RPR_AddTakeToMediaItem(item)
    source = RPR_PCM_Source_CreateFromType("CLICK")

    if not position_written or not length_written or not take or not source:
        delete_created_item(context["track"], item, item_guid)
        return {"error": "REAPER failed to initialize the click-source item"}

    RPR_SetMediaItemTake_Source(take, source)
    RPR_UpdateArrange()

    item_index = find_item_index(context["track"], item_guid)
    applied = get_item_state(item, item_index)
    take_count = RPR_CountTakes(item)
    active_take = RPR_GetActiveTake(item)
    source_type = get_take_source_type(active_take) if active_take else ""
    take_name = RPR_GetTakeName(active_take) if active_take else ""
    success = (
        item_index is not None
        and take_count == 1
        and source_type == "CLICK"
        and math.isclose(
            applied["position_seconds"], position_seconds,
            rel_tol=1e-9, abs_tol=1e-9
        )
        and math.isclose(
            applied["end_seconds"], end_seconds,
            rel_tol=1e-9, abs_tol=1e-9
        )
    )

    if not success:
        delete_created_item(context["track"], item, item_guid)
        return {"error": "click-source item failed read-back verification"}

    return {
        "track_index": context["track_index"],
        "track_name": context["track_name"],
        "item_index": item_index,
        "item_guid": item_guid,
        "start_measure": start_measure,
        "end_measure": end_measure,
        "take_count": take_count,
        "take_name": take_name,
        "source_type": source_type,
        "applied": applied,
        "success": True
    }

def validate_midi_note_payload(
    requested_notes, position_seconds, end_seconds, start_measure
):
    if not isinstance(requested_notes, list):
        return None, {"error": "notes must be a list"}

    end_musical = get_musical_position(
        max(position_seconds, end_seconds - 1e-9)
    )["musical_position"]
    item_measure_count = end_musical["measure"] - start_measure + 1
    validated_notes = []

    for note_index, note in enumerate(requested_notes, start=1):
        if not isinstance(note, dict):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "message": "each note must be an object"
            }

        has_pitch = "pitch" in note
        has_note_name = "note_name" in note

        if has_pitch == has_note_name:
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "pitch/note_name",
                "message": "provide exactly one of pitch or note_name"
            }

        pitch = (
            note.get("pitch")
            if has_pitch
            else get_midi_pitch(note.get("note_name"))
        )
        velocity = note.get("velocity")
        legacy_fields = {"start_measure", "start_beat", "duration_qn"}
        musical_fields = {"bar", "beat", "offset", "duration_beats"}
        has_legacy_shape = bool(legacy_fields.intersection(note))
        has_musical_shape = bool(musical_fields.intersection(note))

        if has_legacy_shape == has_musical_shape:
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "musical_position",
                "message": (
                    "provide exactly one complete position shape: "
                    "start_measure/start_beat/duration_qn or "
                    "bar/beat/offset/duration_beats"
                )
            }

        if has_musical_shape:
            missing_fields = musical_fields.difference(note)

            if missing_fields:
                return None, {
                    "error": "invalid_midi_note",
                    "note_index": note_index,
                    "field": "musical_position",
                    "message": "missing fields: " + ", ".join(
                        sorted(missing_fields)
                    )
                }

            note_start_measure = note.get("bar")
            beat = note.get("beat")
            offset = note.get("offset")
            duration_beats = note.get("duration_beats")

            for field, value in (
                ("beat", beat),
                ("offset", offset),
                ("duration_beats", duration_beats)
            ):
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                ):
                    return None, {
                        "error": "invalid_midi_note",
                        "note_index": note_index,
                        "field": field,
                        "message": f"{field} must be a finite number"
                    }

            if beat < 1.0 or offset < 0.0 or duration_beats <= 0.0:
                return None, {
                    "error": "invalid_midi_note",
                    "note_index": note_index,
                    "field": "musical_position",
                    "message": (
                        "beat must be at least 1, offset must be non-negative, "
                        "and duration_beats must be positive"
                    )
                }

            note_start_beat = float(beat) + float(offset)
            duration_qn = None
        else:
            missing_fields = legacy_fields.difference(note)

            if missing_fields:
                return None, {
                    "error": "invalid_midi_note",
                    "note_index": note_index,
                    "field": "musical_position",
                    "message": "missing fields: " + ", ".join(
                        sorted(missing_fields)
                    )
                }

            note_start_measure = note.get("start_measure")
            note_start_beat = note.get("start_beat")
            duration_qn = note.get("duration_qn")

        if has_pitch and (
            not isinstance(pitch, int)
            or isinstance(pitch, bool)
            or pitch < 0
            or pitch > 127
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "pitch",
                "message": "pitch must be an integer from 0 through 127"
            }

        if has_note_name and pitch is None:
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "note_name",
                "message": "note_name must be a valid MIDI note with octave"
            }

        if (
            not isinstance(velocity, int)
            or isinstance(velocity, bool)
            or velocity < 1
            or velocity > 127
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "velocity",
                "message": "velocity must be an integer from 1 through 127"
            }

        if not has_musical_shape and (
            not isinstance(duration_qn, (int, float))
            or isinstance(duration_qn, bool)
            or not math.isfinite(duration_qn)
            or duration_qn <= 0
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "duration_qn",
                "message": "duration_qn must be a finite positive number"
            }

        if (
            not isinstance(note_start_measure, int)
            or isinstance(note_start_measure, bool)
            or note_start_measure < 1
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "start_measure",
                "message": "start_measure must be a 1-based relative measure"
            }

        if note_start_measure > item_measure_count:
            return None, {
                "error": "midi_note_outside_item",
                "note_index": note_index,
                "field": "start_measure",
                "message": "note start_measure is outside the MIDI item"
            }

        if (
            not isinstance(note_start_beat, (int, float))
            or isinstance(note_start_beat, bool)
            or not math.isfinite(note_start_beat)
            or note_start_beat < 1.0
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "start_beat",
                "message": "start_beat must be a finite number of at least 1"
            }

        absolute_measure = start_measure + note_start_measure - 1

        try:
            measure_start = get_measure_boundary(absolute_measure)
            measure_end = get_measure_boundary(absolute_measure + 1)
            note_start_seconds = RPR_TimeMap2_beatsToTime(
                0, float(note_start_beat) - 1.0, absolute_measure - 1
            )[0]
            note_start_qn = RPR_TimeMap2_timeToQN(0, note_start_seconds)
            if has_musical_shape:
                time_signature = get_musical_position(
                    note_start_seconds
                )["musical_position"]["time_signature"]
                duration_qn = (
                    float(duration_beats)
                    * 4.0
                    / time_signature["denominator"]
                )
            note_end_qn = note_start_qn + float(duration_qn)
            note_end_seconds = RPR_TimeMap2_QNToTime(0, note_end_qn)
        except Exception as position_error:
            return None, {
                "error": "midi_note_position_resolution_failed",
                "note_index": note_index,
                "message": str(position_error)
            }

        if (
            not math.isfinite(note_start_seconds)
            or note_start_seconds < measure_start - 1e-9
            or note_start_seconds >= measure_end - 1e-9
        ):
            return None, {
                "error": "invalid_midi_note",
                "note_index": note_index,
                "field": "start_beat",
                "message": "start_beat is outside the local time signature"
            }

        if (
            note_start_seconds < position_seconds - 1e-9
            or note_start_seconds >= end_seconds - 1e-9
            or not math.isfinite(note_end_seconds)
            or note_end_seconds > end_seconds + 1e-9
        ):
            return None, {
                "error": "midi_note_outside_item",
                "note_index": note_index,
                "message": "note start or end is outside the MIDI item"
            }

        validated_notes.append({
            "pitch": pitch,
            "velocity": velocity,
            "duration_qn": float(duration_qn),
            "start_measure": note_start_measure,
            "start_beat": round(float(note_start_beat), 10),
            "start_qn": note_start_qn,
            "end_qn": note_end_qn
        })

    validated_notes.sort(key=lambda note: (
        note["start_qn"], note["pitch"], note["end_qn"]
    ))
    return validated_notes, None

def handle_create_midi_item(request):
    context, error = resolve_track(request)

    if error is not None:
        return error

    start_measure = request.get("start_measure")
    end_measure = request.get("end_measure")
    requested_notes = request.get("notes")

    if (
        not isinstance(start_measure, int)
        or isinstance(start_measure, bool)
        or start_measure < 1
    ):
        return {"error": "start_measure must be a 1-based positive integer"}

    if (
        not isinstance(end_measure, int)
        or isinstance(end_measure, bool)
        or end_measure <= start_measure
    ):
        return {
            "error": "end_measure must be an integer greater than start_measure"
        }

    if not isinstance(requested_notes, list) or not requested_notes:
        return {"error": "notes must be a non-empty list"}

    position_seconds = get_measure_boundary(start_measure)
    end_seconds = get_measure_boundary(end_measure)
    duration_seconds = end_seconds - position_seconds

    if (
        not math.isfinite(position_seconds)
        or not math.isfinite(end_seconds)
        or duration_seconds <= 0.0
    ):
        return {
            "error": "REAPER returned invalid measure boundary positions"
        }

    start_qn = RPR_TimeMap2_timeToQN(0, position_seconds)
    end_qn = RPR_TimeMap2_timeToQN(0, end_seconds)
    available_duration_qn = end_qn - start_qn

    if (
        not math.isfinite(start_qn)
        or not math.isfinite(end_qn)
        or available_duration_qn <= 0.0
    ):
        return {"error": "REAPER returned an invalid musical item duration"}

    validated_notes, validation_error = validate_midi_note_payload(
        requested_notes, position_seconds, end_seconds, start_measure
    )

    if validation_error is not None:
        return validation_error

    conflicts = get_item_conflicts(
        context["track"], position_seconds, end_seconds
    )

    if conflicts:
        return {
            "error": "item_overlap",
            "requested_range": {
                "start_measure": start_measure,
                "end_measure": end_measure,
                "position_seconds": position_seconds,
                "end_seconds": end_seconds,
                "duration_seconds": duration_seconds
            },
            "conflicts": conflicts
        }

    item = None

    try:
        item = RPR_AddMediaItemToTrack(context["track"])

        if not item:
            return {"error": "REAPER failed to create the MIDI item"}

        item_guid = get_item_identity(item)
        take_guid = "{" + str(uuid.uuid4()).upper() + "}"
        source_guid = "{" + str(uuid.uuid4()).upper() + "}"
        source_end_ppq = int(round(available_duration_qn * 960))
        # Initialize only the in-project MIDI container here. Note timing is
        # converted and inserted below through REAPER's QN/PPQ APIs.
        item_chunk = "\n".join([
            "<ITEM",
            f"POSITION {position_seconds:.17g}",
            "SNAPOFFS 0",
            f"LENGTH {duration_seconds:.17g}",
            "LOOP 0",
            "ALLTAKES 0",
            "FADEIN 1 0 0 1 0 0 0",
            "FADEOUT 1 0 0 1 0 0 0",
            "MUTE 0 0",
            "SEL 0",
            f"IGUID {item_guid}",
            "IID -1",
            'NAME ""',
            "VOLPAN 1 0 1 -1",
            "SOFFS 0 0",
            "PLAYRATE 1 1 0 -1 0 0.0025",
            "CHANMODE 0",
            f"GUID {take_guid}",
            "<SOURCE MIDI",
            "HASDATA 1 960 QN",
            "CCINTERP 32",
            f"E {source_end_ppq} b0 7b 00",
            f"GUID {source_guid}",
            ">",
            ">"
        ])

        if not RPR_SetItemStateChunk(item, item_chunk, False):
            raise RuntimeError("REAPER failed to initialize MIDI item state")

        take = RPR_GetTake(item, 0)

        if not take or not RPR_TakeIsMIDI(take):
            raise RuntimeError("REAPER failed to initialize the MIDI take")

        for note in validated_notes:
            if not RPR_MIDI_InsertNote(
                take,
                False,
                False,
                RPR_MIDI_GetPPQPosFromProjQN(take, note["start_qn"]),
                RPR_MIDI_GetPPQPosFromProjQN(take, note["end_qn"]),
                0,
                note["pitch"],
                note["velocity"],
                True
            ):
                raise RuntimeError("REAPER failed to insert a MIDI note")

        RPR_MIDI_Sort(take)
        RPR_UpdateArrange()
        return finalize_create_midi_item({
            "item_guid": item_guid,
            "start_measure": start_measure,
            "end_measure": end_measure,
            "position_seconds": position_seconds,
            "end_seconds": end_seconds,
            "available_duration_qn": available_duration_qn,
            "validated_notes": validated_notes
        }, context)
    except Exception as creation_error:
        cleanup_succeeded = True

        if item:
            cleanup_succeeded = delete_created_item(
                context["track"], item, get_item_identity(item)
            )

        return {
            "error": "midi_item_creation_failed",
            "message": str(creation_error),
            "cleanup_succeeded": cleanup_succeeded
        }

def finalize_create_midi_item(operation, context):
    item = find_item_by_guid(context["track"], operation["item_guid"])
    take = RPR_GetTake(item, 0) if item else None

    try:
        if not item or not take:
            raise RuntimeError("REAPER did not materialize the MIDI item")

        item_index = find_item_index(context["track"], operation["item_guid"])
        applied_position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        applied_duration = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
        applied_end = applied_position + applied_duration
        counts = RPR_MIDI_CountEvts(take, 0, 0, 0)
        created_notes = []
        notes_match = counts[2] == len(operation["validated_notes"])

        for reaper_note_index in range(counts[2]):
            note_info = RPR_MIDI_GetNote(
                take, reaper_note_index,
                False, False, 0.0, 0.0, 0, 0, 0
            )

            if not note_info[0]:
                notes_match = False
                continue

            note_start_qn = RPR_MIDI_GetProjQNFromPPQPos(
                take, note_info[5]
            )
            note_end_qn = RPR_MIDI_GetProjQNFromPPQPos(
                take, note_info[6]
            )
            note_start_seconds = RPR_MIDI_GetProjTimeFromPPQPos(
                take, note_info[5]
            )
            note_musical = get_musical_position(
                note_start_seconds
            )["musical_position"]
            relative_start_measure = (
                note_musical["measure"]
                - operation["start_measure"]
                + 1
            )
            created_notes.append({
                "note_index": reaper_note_index + 1,
                "pitch": note_info[8],
                "note_name": get_midi_note_name(note_info[8]),
                "velocity": note_info[9],
                "start_measure": relative_start_measure,
                "start_beat": round(
                    note_musical["beat_within_measure"], 10
                ),
                "duration_qn": round(note_end_qn - note_start_qn, 10),
                "start_ppq": note_info[5],
                "end_ppq": note_info[6]
            })

            expected = operation["validated_notes"][reaper_note_index]
            notes_match = notes_match and (
                note_info[8] == expected["pitch"]
                and note_info[9] == expected["velocity"]
                and relative_start_measure == expected["start_measure"]
                and math.isclose(
                    note_musical["beat_within_measure"],
                    expected["start_beat"],
                    rel_tol=1e-9,
                    abs_tol=1e-9
                )
                and math.isclose(
                    note_start_qn,
                    expected["start_qn"],
                    rel_tol=1e-9,
                    abs_tol=1e-9
                )
                and math.isclose(
                    note_end_qn - note_start_qn,
                    expected["duration_qn"],
                    rel_tol=1e-9,
                    abs_tol=1e-9
                )
            )

        success = (
            item_index is not None
            and bool(operation["item_guid"])
            and RPR_TakeIsMIDI(take)
            and notes_match
            and math.isclose(
                applied_position, operation["position_seconds"],
                rel_tol=1e-9, abs_tol=1e-9
            )
            and math.isclose(
                applied_end, operation["end_seconds"],
                rel_tol=1e-9, abs_tol=1e-9
            )
        )

        if not success:
            raise RuntimeError(
                "MIDI item read-back verification failed: "
                + json.dumps({
                    "item_index": item_index,
                    "item_guid": operation["item_guid"],
                    "take_is_midi": bool(RPR_TakeIsMIDI(take)),
                    "note_count": counts[2],
                    "expected_note_count": len(operation["validated_notes"]),
                    "notes_match": notes_match,
                    "applied_position": applied_position,
                    "expected_position": operation["position_seconds"],
                    "applied_end": applied_end,
                    "expected_end": operation["end_seconds"]
                })
            )

        return {
            "track_index": context["track_index"],
            "track_name": context["track_name"],
            "item_index": item_index,
            "item_guid": operation["item_guid"],
            "start_measure": operation["start_measure"],
            "end_measure": operation["end_measure"],
            "position_seconds": applied_position,
            "end_seconds": applied_end,
            "duration_seconds": applied_duration,
            "note_count": len(created_notes),
            "available_duration_qn": operation["available_duration_qn"],
            "notes": created_notes,
            "success": True
        }
    except Exception as readback_error:
        cleanup_succeeded = (
            delete_created_item(
                context["track"], item, operation["item_guid"]
            )
            if item
            else find_item_index(
                context["track"], operation["item_guid"]
            ) is None
        )
        return {
            "error": "midi_item_creation_failed",
            "message": str(readback_error),
            "cleanup_succeeded": cleanup_succeeded
        }

def get_take_index(item, take):
    for reaper_take_index in range(RPR_CountTakes(item)):
        if RPR_GetTake(item, reaper_take_index) == take:
            return reaper_take_index + 1

    return None

def get_midi_event_counts(take):
    counts = RPR_MIDI_CountEvts(take, 0, 0, 0)
    return {
        "note_count": counts[2],
        "cc_count": counts[3],
        "text_sysex_count": counts[4],
        "event_count": counts[2] + counts[3] + counts[4]
    }

def clear_all_midi_events(take):
    counts = get_midi_event_counts(take)

    for event_index in range(counts["note_count"] - 1, -1, -1):
        if not RPR_MIDI_DeleteNote(take, event_index):
            raise RuntimeError("REAPER failed to delete a MIDI note")

    for event_index in range(counts["cc_count"] - 1, -1, -1):
        if not RPR_MIDI_DeleteCC(take, event_index):
            raise RuntimeError("REAPER failed to delete a MIDI CC event")

    for event_index in range(counts["text_sysex_count"] - 1, -1, -1):
        if not RPR_MIDI_DeleteTextSysex(take, event_index):
            raise RuntimeError("REAPER failed to delete a MIDI text/sysex event")

def read_replacement_notes(take, start_measure):
    counts = get_midi_event_counts(take)
    notes = []

    for reaper_note_index in range(counts["note_count"]):
        note_info = RPR_MIDI_GetNote(
            take, reaper_note_index,
            False, False, 0.0, 0.0, 0, 0, 0
        )

        if not note_info[0]:
            raise RuntimeError("REAPER failed to read a replacement note")

        note_start_qn = RPR_MIDI_GetProjQNFromPPQPos(take, note_info[5])
        note_end_qn = RPR_MIDI_GetProjQNFromPPQPos(take, note_info[6])
        note_start_seconds = RPR_MIDI_GetProjTimeFromPPQPos(
            take, note_info[5]
        )
        musical = get_musical_position(
            note_start_seconds
        )["musical_position"]
        notes.append({
            "note_index": reaper_note_index + 1,
            "note_name": get_midi_note_name(note_info[8]),
            "pitch": note_info[8],
            "start_measure": musical["measure"] - start_measure + 1,
            "start_beat": round(musical["beat_within_measure"], 10),
            "duration_qn": round(note_end_qn - note_start_qn, 10),
            "velocity": note_info[9],
            "start_ppq": note_info[5],
            "end_ppq": note_info[6],
            "start_qn": note_start_qn
        })

    return notes, counts

def handle_replace_midi_item_content(request):
    context, error = resolve_item_by_guid(request)

    if error is not None:
        return error

    requested_notes = request.get("notes")
    item = context["item"]
    take = RPR_GetActiveTake(item)

    if not take or not RPR_TakeIsMIDI(take):
        return {
            "error": "item_is_not_midi",
            "item_guid": context["item_guid"]
        }

    position_seconds = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
    duration_seconds = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
    end_seconds = position_seconds + duration_seconds
    start_measure = get_musical_position(
        position_seconds
    )["musical_position"]["measure"]
    validated_notes, validation_error = validate_midi_note_payload(
        requested_notes, position_seconds, end_seconds, start_measure
    )

    if validation_error is not None:
        return validation_error

    take_index = get_take_index(item, take)
    take_name = RPR_GetTakeName(take)
    previous_counts = get_midi_event_counts(take)
    original_guid = get_item_identity(item)
    original_muted = bool(RPR_GetMediaItemInfo_Value(item, "B_MUTE"))
    original_locked = bool(RPR_GetMediaItemInfo_Value(item, "C_LOCK"))
    chunk_info = RPR_GetItemStateChunk(item, "", 4194304, False)

    if not chunk_info[0]:
        return {"error": "midi_content_snapshot_failed"}

    original_chunk = chunk_info[2]

    try:
        clear_all_midi_events(take)

        for note in validated_notes:
            if not RPR_MIDI_InsertNote(
                take,
                False,
                False,
                RPR_MIDI_GetPPQPosFromProjQN(take, note["start_qn"]),
                RPR_MIDI_GetPPQPosFromProjQN(take, note["end_qn"]),
                0,
                note["pitch"],
                note["velocity"],
                True
            ):
                raise RuntimeError("REAPER failed to insert a replacement note")

        RPR_MIDI_Sort(take)
        RPR_UpdateArrange()
        applied_guid = get_item_identity(item)
        applied_position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        applied_duration = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
        applied_notes, applied_counts = read_replacement_notes(
            take, start_measure
        )
        notes_match = len(applied_notes) == len(validated_notes)

        for applied, expected in zip(applied_notes, validated_notes):
            notes_match = notes_match and (
                applied["pitch"] == expected["pitch"]
                and applied["velocity"] == expected["velocity"]
                and applied["start_measure"] == expected["start_measure"]
                and math.isclose(
                    applied["start_beat"], expected["start_beat"],
                    rel_tol=1e-9, abs_tol=1e-9
                )
                and math.isclose(
                    applied["start_qn"], expected["start_qn"],
                    rel_tol=1e-9, abs_tol=1e-9
                )
                and math.isclose(
                    applied["duration_qn"], expected["duration_qn"],
                    rel_tol=1e-9, abs_tol=1e-9
                )
            )

        item_unchanged = (
            applied_guid == original_guid
            and math.isclose(
                applied_position, position_seconds,
                rel_tol=1e-9, abs_tol=1e-9
            )
            and math.isclose(
                applied_duration, duration_seconds,
                rel_tol=1e-9, abs_tol=1e-9
            )
            and bool(RPR_GetMediaItemInfo_Value(item, "B_MUTE"))
            == original_muted
            and bool(RPR_GetMediaItemInfo_Value(item, "C_LOCK"))
            == original_locked
        )
        stale_events_cleared = (
            applied_counts["cc_count"] == 0
            and applied_counts["text_sysex_count"] == 0
        )

        if not notes_match or not item_unchanged or not stale_events_cleared:
            raise RuntimeError("MIDI replacement read-back verification failed")

        for note in applied_notes:
            note.pop("start_qn", None)

        return {
            "track_index": context["track_index"],
            "track_name": context["track_name"],
            "item_guid": applied_guid,
            "take_index": take_index,
            "take_name": take_name,
            "previous_event_count": previous_counts["event_count"],
            "previous_note_count": previous_counts["note_count"],
            "new_note_count": applied_counts["note_count"],
            "item_position_seconds": applied_position,
            "item_end_seconds": applied_position + applied_duration,
            "notes": applied_notes,
            "success": True
        }
    except Exception as replacement_error:
        rollback_succeeded = bool(
            RPR_SetItemStateChunk(item, original_chunk, False)
        )
        RPR_UpdateArrange()
        return {
            "error": "midi_content_replacement_failed",
            "message": str(replacement_error),
            "rollback_succeeded": rollback_succeeded
        }

def handle_get_fx_presets(request):
    fx_context, error = resolve_track_fx(request)

    if error is not None:
        return error

    current_preset_info = RPR_TrackFX_GetPreset(
        fx_context["track"],
        fx_context["reaper_fx_index"],
        "",
        1024
    )
    preset_index_info = RPR_TrackFX_GetPresetIndex(
        fx_context["track"],
        fx_context["reaper_fx_index"],
        0
    )

    return {
        "track_index": fx_context["track_index"],
        "track_name": fx_context["track_name"],
        "fx_index": fx_context["fx_index"],
        "fx_name": fx_context["fx_name"],
        "current_preset": (
            current_preset_info[3]
            if current_preset_info[0]
            else None
        ),
        "preset_count": preset_index_info[3]
    }

def receive_request(client):
    chunks = []
    byte_count = 0

    while True:
        try:
            chunk = client.recv(REQUEST_CHUNK_SIZE)
        except socket.timeout:
            if chunks:
                break
            raise

        if not chunk:
            break

        byte_count += len(chunk)

        if byte_count > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds maximum size")

        chunks.append(chunk)

    return b"".join(chunks)

def loop():
    try:
        client, address = server.accept()
        client.settimeout(0.1)

        data = receive_request(client)

        if data:
            response = process_request(data.decode("utf-8"))
            client.sendall(json.dumps(response).encode("utf-8"))

        client.close()

    except BlockingIOError:
        pass
    except Exception as error:
        RPR_ShowConsoleMsg(f"MCP bridge error: {error}\n")

    RPR_defer("loop()")

def resolve_recording_track(request, field="track_index", guid_field="track_guid"):
    context, error = resolve_track({"track_index": request.get(field)})
    if error:
        return None, error
    track = context["track"]
    if not RPR_ValidatePtr2(0, track, "MediaTrack*"):
        return None, {"error": "Track pointer is no longer valid"}
    guid = recording_track_guid(track)
    if request.get(guid_field) is not None and request[guid_field] != guid:
        return None, {"error": f"{guid_field} does not match track identity"}
    return {**context, "track_guid": guid}, None


def recording_track_guid(track):
    return RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]


def recording_identity(context):
    return {key: context[key] for key in ("track_index", "track_name", "track_guid")}


def read_track_color(track):
    raw = int(RPR_GetMediaTrackInfo_Value(track, "I_CUSTOMCOLOR"))
    rgb = RPR_ColorFromNative(raw & 0xffffff, 0, 0, 0)
    return {"color_raw": raw, "custom": bool(raw & 0x1000000),
            "rgb": list(rgb[1:4]) if raw & 0x1000000 else None}


def handle_get_track_color(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    return {**recording_identity(context), **read_track_color(context["track"])}


def write_recording_value(context, attribute, value, label):
    track = context["track"]
    before = RPR_GetMediaTrackInfo_Value(track, attribute)
    RPR_Undo_BeginBlock2(0)
    try:
        if not RPR_SetMediaTrackInfo_Value(track, attribute, value):
            raise RuntimeError("REAPER rejected the write")
        applied = RPR_GetMediaTrackInfo_Value(track, attribute)
        if applied != value or recording_track_guid(track) != context["track_guid"]:
            raise RuntimeError("Track write read-back verification failed")
        RPR_TrackList_AdjustWindows(False)
        return {"success": True, **recording_identity(context),
                "requested_raw": value, "applied_raw": int(applied)}
    except Exception as error:
        try:
            RPR_SetMediaTrackInfo_Value(track, attribute, before)
            restored = RPR_GetMediaTrackInfo_Value(track, attribute) == before
        except Exception:
            restored = False
        return {"error": str(error), "rollback_succeeded": restored}
    finally:
        RPR_Undo_EndBlock2(0, label, -1)


def handle_set_track_color(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    raw = request.get("color_raw")
    if request.get("source_track_index") is not None:
        if raw is not None:
            return {"error": "Specify color_raw or source_track_index, not both"}
        source, error = resolve_recording_track(request, "source_track_index", "source_track_guid")
        if error:
            return error
        raw = read_track_color(source["track"])["color_raw"]
    if type(raw) is not int or not (raw == 0 or 0x1000000 <= raw <= 0x1ffffff):
        return {"error": "color_raw must be 0 (default) or a native custom color with 0x1000000 set"}
    result = write_recording_value(context, "I_CUSTOMCOLOR", raw, "Set track color")
    if result.get("success"):
        result.update(read_track_color(context["track"]))
    return result


def describe_record_input(raw):
    if raw == -1:
        return {"record_input_raw": raw, "kind": "none", "available": True, "name": "No input"}
    if raw & 4096:
        channel, device = raw & 31, (raw >> 5) & 63
        available = 0 <= raw <= 8191 and channel <= 16
        if device in (62, 63):
            name = "Virtual MIDI keyboard" if device == 62 else "All MIDI inputs"
        else:
            info = RPR_GetMIDIInputName(device, "", 512)
            available = available and bool(info[0])
            name = info[2]
        return {"record_input_raw": raw, "kind": "midi", "available": available,
                "name": f"{name}, channel {channel or 'all'}"}
    stereo = bool(raw & 1024)
    start = raw & 1023
    count = 2 if stereo else 1
    available = 0 <= raw < 2048 and start < 512 and start + count <= RPR_GetNumAudioInputs()
    names = [RPR_GetInputChannelName(i) for i in range(start, start + count)] if available else []
    return {"record_input_raw": raw, "kind": "stereo" if stereo else "mono",
            "available": available, "name": " / ".join(names) if names else "Unavailable audio input"}


def handle_get_track_record_input(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    raw = int(RPR_GetMediaTrackInfo_Value(context["track"], "I_RECINPUT"))
    return {**recording_identity(context), **describe_record_input(raw)}


def handle_set_track_record_input(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    raw = request.get("record_input_raw")
    if request.get("source_track_index") is not None:
        if raw is not None:
            return {"error": "Specify record_input_raw or source_track_index, not both"}
        source, error = resolve_recording_track(request, "source_track_index", "source_track_guid")
        if error:
            return error
        raw = int(RPR_GetMediaTrackInfo_Value(source["track"], "I_RECINPUT"))
    if type(raw) is not int or raw < -1:
        return {"error": "record_input_raw must be -1 or a supported REAPER input integer"}
    state = describe_record_input(raw)
    if not state["available"]:
        return {"error": "Recording input is unavailable on the current device", **state}
    result = write_recording_value(context, "I_RECINPUT", raw, "Set track recording input")
    if result.get("success"):
        result.update(handle_get_track_record_input(request))
    return result


def handle_get_track_record_monitoring(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    raw = int(RPR_GetMediaTrackInfo_Value(context["track"], "I_RECMON"))
    return {**recording_identity(context), "record_monitoring_raw": raw,
            "mode": {0: "off", 1: "on", 2: "auto"}.get(raw, "unknown")}


def handle_set_track_record_monitoring(request):
    context, error = resolve_recording_track(request)
    if error:
        return error
    mode = request.get("mode")
    if mode not in ("off", "on", "auto"):
        return {"error": "mode must be off, on, or auto (tape style)"}
    result = write_recording_value(context, "I_RECMON", {"off": 0, "on": 1, "auto": 2}[mode], "Set input monitoring")
    if result.get("success"):
        result.update(handle_get_track_record_monitoring(request))
    return result


def read_recording_chunk(track):
    # REAPER's Python rpr_packs allocates 4 MiB regardless of the requested size.
    # Never tell the native API it has a larger buffer than the wrapper allocates.
    size = 4 * 1024 * 1024
    result = RPR_GetTrackStateChunk(track, "", size, False)
    if not result[0] or len(result[2].encode("utf-8")) >= size - 1:
        raise RuntimeError("Track state unavailable or exceeds safe 4 MiB Python chunk limit")
    return result[2]


def chunk_block_span(chunk, name):
    lines = chunk.splitlines(keepends=True)
    depth, offset, start = 0, 0, None
    for line in lines:
        text = line.strip()
        if depth == 1 and text == "<" + name:
            start = offset
        if text.startswith("<"):
            depth += 1
        elif text == ">":
            depth -= 1
            if start is not None and depth == 1:
                return start, offset + len(line)
        offset += len(line)
    return None


def recording_fx_chunk(chunk):
    span = chunk_block_span(chunk, "FXCHAIN")
    return chunk[slice(*span)] if span else ""


def portable_fx_chunk(chunk):
    # Track envelopes live outside FXCHAIN; parameter envelopes live within it.
    # Omit automation and reject external modulation links rather than retargeting them.
    lines, skip, output = chunk.splitlines(keepends=True), 0, []
    for line in lines:
        text = line.strip()
        if text.startswith("PLINK ") and not skip:
            raise RuntimeError("FX parameter links are unsupported; remove links before copying")
        if not skip and text.startswith(("<PARMENV", "<PROGRAMENV")):
            skip = 1
            continue
        if skip:
            skip += int(text.startswith("<")) - int(text == ">")
            continue
        if text.startswith("FXID "):
            line = "FXID {" + str(uuid.uuid4()).upper() + "}\n"
        output.append(line)
    return "".join(output)


def comparable_fx_chunk(chunk):
    # Only generated instance identity and window placement are irrelevant to sound.
    return "\n".join(line.strip() for line in chunk.splitlines()
                     if not line.strip().startswith(("FXID ", "FLOATPOS ", "SHOW ", "LASTSEL ")))


def comparable_recording_source(chunk):
    return "\n".join(line for line in chunk.splitlines()
                     if not line.strip().startswith(("FLOATPOS ", "SHOW ", "LASTSEL ")))


def handle_copy_track_fx_chain(request):
    destination, error = resolve_recording_track(request)
    if error:
        return error
    source, error = resolve_recording_track(request, "source_track_index", "source_track_guid")
    if error:
        return error
    src, dst = source["track"], destination["track"]
    if source["track_guid"] == destination["track_guid"]:
        return {"error": "Source and destination must be different tracks"}
    if RPR_TrackFX_GetCount(dst) or RPR_TrackFX_GetRecCount(dst):
        return {"error": "Destination must have no normal or input FX"}
    try:
        original = read_recording_chunk(dst)
        source_before = read_recording_chunk(src)
        fx = recording_fx_chunk(source_before)
        portable = portable_fx_chunk(fx)
        if comparable_fx_chunk(portable) != comparable_fx_chunk(fx):
            return {"error": "Source FX parameter automation/modulation is unsupported; copy would also transfer automation"}
        if not fx or not RPR_TrackFX_GetCount(src):
            return {"error": "Source has no normal FX chain"}
        channels = int(RPR_GetMediaTrackInfo_Value(src, "I_NCHAN"))
        original_channels = int(RPR_GetMediaTrackInfo_Value(dst, "I_NCHAN"))
        source_count = RPR_TrackFX_GetCount(src)
    except Exception as error:
        return {"error": str(error)}
    RPR_Undo_BeginBlock2(0)
    try:
        if not RPR_SetMediaTrackInfo_Value(dst, "I_NCHAN", channels):
            raise RuntimeError("REAPER failed to apply channel count")
        for index in range(source_count):
            RPR_TrackFX_CopyToTrack(src, index, dst, index, False)
            if RPR_TrackFX_GetCount(dst) != index + 1:
                raise RuntimeError(f"REAPER failed to copy FX {index + 1}")
        applied = read_recording_chunk(dst)
        verification = {
            "identity": recording_track_guid(dst) == destination["track_guid"],
            "fx_count": RPR_TrackFX_GetCount(dst) == source_count,
            "fx_state": comparable_fx_chunk(recording_fx_chunk(applied)) == comparable_fx_chunk(fx),
            "channels": int(RPR_GetMediaTrackInfo_Value(dst, "I_NCHAN")) == channels,
            "source_unchanged": comparable_recording_source(read_recording_chunk(src)) == comparable_recording_source(source_before),
        }
        if not all(verification.values()):
            raise RuntimeError(f"Full FX state read-back verification failed: {verification}")
        # Verify all non-FX destination state, including MIDI/items and routing.
        def without_fx(value):
            block = recording_fx_chunk(value)
            return re.sub(r"(?m)^NCHAN \d+", "NCHAN", value.replace(block, "", 1) if block else value)
        if without_fx(applied) != without_fx(original):
            raise RuntimeError("Non-FX destination state changed")
        return {"success": True, **recording_identity(destination),
                "source": recording_identity(source), "fx_count": RPR_TrackFX_GetCount(dst),
                "channels": channels, "verified_full_state": True}
    except Exception as error:
        try:
            for index in reversed(range(RPR_TrackFX_GetCount(dst))):
                if not RPR_TrackFX_Delete(dst, index):
                    raise RuntimeError("REAPER failed to remove a partially copied FX")
            restored = bool(RPR_SetMediaTrackInfo_Value(dst, "I_NCHAN", original_channels))
            rollback_chunk = read_recording_chunk(dst)
            restored = (restored and RPR_TrackFX_GetCount(dst) == 0
                        and rollback_chunk.replace(recording_fx_chunk(rollback_chunk), "", 1)
                        == original.replace(recording_fx_chunk(original), "", 1))
        except Exception:
            restored = False
        return {"error": str(error), "rollback_succeeded": restored}
    finally:
        RPR_Undo_EndBlock2(0, "Copy track FX chain", -1)


def handle_save_project(request):
    project, _, path, _ = RPR_EnumProjects(-1, "", 32768)
    if not path:
        return {"error": "Active project has no path; save it once explicitly before using save_project"}
    RPR_Main_SaveProject(project, False)
    after, _, applied_path, _ = RPR_EnumProjects(-1, "", 32768)
    dirty = bool(RPR_IsProjectDirty(project))
    verified = after == project and applied_path == path and not dirty
    result = {"success": verified, "project_id": str(project),
              "project_path": applied_path, "dirty": dirty}
    if not verified:
        result["error"] = "Project save read-back verification failed"
    return result


COMMAND_HANDLERS = {
    "get_track_color": handle_get_track_color,
    "set_track_color": handle_set_track_color,
    "copy_track_fx_chain": handle_copy_track_fx_chain,
    "get_track_record_input": handle_get_track_record_input,
    "set_track_record_input": handle_set_track_record_input,
    "get_track_record_monitoring": handle_get_track_record_monitoring,
    "set_track_record_monitoring": handle_set_track_record_monitoring,
    "save_project": handle_save_project,
    "get_track_count": handle_get_track_count,
    "get_project_info": handle_get_project_info,
    "get_tempo_map": handle_get_tempo_map,
    "set_project_tempo": handle_set_project_tempo,
    "set_project_time_signature": handle_set_project_time_signature,
    "set_tempo_map_event": handle_set_tempo_map_event,
    "get_markers_regions": handle_get_markers_regions,
    "create_region": handle_create_region,
    "rename_region": handle_rename_region,
    "get_tracks": handle_get_tracks,
    "create_named_track": handle_create_named_track,
    "rename_track": handle_rename_track,
    "create_track_folder": handle_create_track_folder,
    "move_track_into_folder": handle_move_track_into_folder,
    "get_track_routing": handle_get_track_routing,
    "get_track_items": handle_get_track_items,
    "get_selected_tracks": handle_get_selected_tracks,
    "get_item_info": handle_get_item_info,
    "get_item_takes": handle_get_item_takes,
    "get_midi_summary": handle_get_midi_summary,
    "get_midi_notes": handle_get_midi_notes,
    "get_track_envelopes": handle_get_track_envelopes,
    "get_envelope_points": handle_get_envelope_points,
    "get_track_channels": handle_get_track_channels,
    "get_master_track": handle_get_master_track,
    "get_master_fx": handle_get_master_fx,
    "get_project_time_selection": handle_get_project_time_selection,
    "get_cursor_position": handle_get_cursor_position,
    "get_current_context": handle_get_current_context,
    "get_take_fx": handle_get_take_fx,
    "get_track_fx": handle_get_track_fx,
    "ensure_track_fx": handle_ensure_track_fx,
    "get_fx_parameters": handle_get_fx_parameters,
    "get_fx_parameter": handle_get_fx_parameter,
    "get_fx_presets": handle_get_fx_presets,
    "diagnose_fx_parameter_formatter": (
        handle_diagnose_fx_parameter_formatter
    ),
    "set_fx_parameter": handle_set_fx_parameter,
    "set_fx_enabled": handle_set_fx_enabled,
    "set_track_volume": handle_set_track_volume,
    "set_track_pan": handle_set_track_pan,
    "set_track_mute": handle_set_track_mute,
    "set_track_record_arm": handle_set_track_record_arm,
    "set_track_solo": handle_set_track_solo,
    "create_note_item": handle_create_note_item,
    "delete_item": handle_delete_item,
    "set_item_end_measure": handle_set_item_end_measure,
    "create_click_source_item": handle_create_click_source_item,
    "create_midi_item": handle_create_midi_item,
    "replace_midi_item_content": handle_replace_midi_item_content,
}

loop()
