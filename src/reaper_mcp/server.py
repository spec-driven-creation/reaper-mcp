import json
import socket

from mcp.server.mcpserver import MCPServer


HOST = "127.0.0.1"
PORT = 8765
BRIDGE_TIMEOUT = 30

mcp = MCPServer("reaper-mcp")


def send_reaper_command(command: str, **arguments) -> dict:
    with socket.create_connection(
        (HOST, PORT),
        timeout=BRIDGE_TIMEOUT
    ) as sock:
        request = {
            "command": command,
            **arguments
        }

        sock.sendall(json.dumps(request).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        response_chunks = []

        while True:
            chunk = sock.recv(4096)

            if not chunk:
                break

            response_chunks.append(chunk)

        response = b"".join(response_chunks)

        return json.loads(response.decode("utf-8"))


@mcp.tool()
def get_tracks() -> dict:
    """Return tracks from the current REAPER project."""
    return send_reaper_command("get_tracks")

@mcp.tool()
def get_track_routing(track_index: int) -> dict:
    """Return sends, receives, and hardware outputs for one track."""
    return send_reaper_command(
        "get_track_routing",
        track_index=track_index
    )

@mcp.tool()
def get_track_items(track_index: int) -> dict:
    """Return media items for one track."""
    return send_reaper_command(
        "get_track_items",
        track_index=track_index
    )

@mcp.tool()
def get_selected_tracks() -> dict:
    """Return tracks currently selected in REAPER."""
    return send_reaper_command("get_selected_tracks")

@mcp.tool()
def get_item_info(track_index: int, item_index: int) -> dict:
    """Return information for one media item."""
    return send_reaper_command(
        "get_item_info", track_index=track_index, item_index=item_index
    )

@mcp.tool()
def get_item_takes(track_index: int, item_index: int) -> dict:
    """Return takes for one media item."""
    return send_reaper_command(
        "get_item_takes", track_index=track_index, item_index=item_index
    )

@mcp.tool()
def get_midi_summary(
    track_index: int, item_index: int, take_index: int
) -> dict:
    """Return MIDI event counts for one take."""
    return send_reaper_command(
        "get_midi_summary",
        track_index=track_index,
        item_index=item_index,
        take_index=take_index
    )

@mcp.tool()
def get_midi_notes(
    track_index: int, item_index: int, take_index: int
) -> dict:
    """Return note events for one MIDI take."""
    return send_reaper_command(
        "get_midi_notes",
        track_index=track_index,
        item_index=item_index,
        take_index=take_index
    )

@mcp.tool()
def get_track_envelopes(track_index: int) -> dict:
    """Return automation envelopes for one track."""
    return send_reaper_command(
        "get_track_envelopes",
        track_index=track_index
    )

@mcp.tool()
def get_envelope_points(track_index: int, envelope_index: int) -> dict:
    """Return points for one track envelope."""
    return send_reaper_command(
        "get_envelope_points",
        track_index=track_index,
        envelope_index=envelope_index
    )

@mcp.tool()
def get_track_channels() -> dict:
    """Return channel configuration for project tracks."""
    return send_reaper_command("get_track_channels")

@mcp.tool()
def get_master_track() -> dict:
    """Return mix and channel state for the master track."""
    return send_reaper_command("get_master_track")

@mcp.tool()
def get_master_fx() -> dict:
    """Return the master track FX chain."""
    return send_reaper_command("get_master_fx")

@mcp.tool()
def get_project_time_selection() -> dict:
    """Return the current project time selection."""
    return send_reaper_command("get_project_time_selection")

@mcp.tool()
def get_cursor_position() -> dict:
    """Return the current edit cursor position."""
    return send_reaper_command("get_cursor_position")

@mcp.tool()
def get_current_context() -> dict:
    """Return selected tracks, cursor, and time-selection context."""
    return send_reaper_command("get_current_context")

@mcp.tool()
def get_take_fx(
    track_index: int, item_index: int, take_index: int
) -> dict:
    """Return the FX chain for one media-item take."""
    return send_reaper_command(
        "get_take_fx",
        track_index=track_index,
        item_index=item_index,
        take_index=take_index
    )

@mcp.tool()
def get_markers_regions() -> dict:
    """Return timeline-ordered markers and regions from the current project."""
    return send_reaper_command("get_markers_regions")

@mcp.tool()
def get_tempo_map() -> dict:
    """Return explicit tempo and time-signature changes in timeline order."""
    return send_reaper_command("get_tempo_map")

@mcp.tool()
def set_project_tempo(bpm: float) -> dict:
    """Set and verify the effective initial project tempo in BPM."""
    return send_reaper_command("set_project_tempo", bpm=bpm)

@mcp.tool()
def set_project_time_signature(
    numerator: int, denominator: int
) -> dict:
    """Set and verify the effective initial project time signature."""
    return send_reaper_command(
        "set_project_time_signature",
        numerator=numerator,
        denominator=denominator
    )

@mcp.tool()
def set_tempo_map_event(
    measure: int,
    bpm: float | None = None,
    numerator: int | None = None,
    denominator: int | None = None
) -> dict:
    """Create or update one non-linear internal tempo-map event."""
    return send_reaper_command(
        "set_tempo_map_event",
        measure=measure,
        bpm=bpm,
        numerator=numerator,
        denominator=denominator
    )

@mcp.tool()
def create_region(
    name: str, start_measure: int, end_measure: int
) -> dict:
    """Create a named region using exclusive one-based measure boundaries."""
    return send_reaper_command(
        "create_region",
        name=name,
        start_measure=start_measure,
        end_measure=end_measure
    )

@mcp.tool()
def create_named_track(
    name: str, track_index: int | None = None
) -> dict:
    """Create one named normal track, appending it unless an index is given."""
    return send_reaper_command(
        "create_named_track", name=name, track_index=track_index
    )

@mcp.tool()
def rename_track(track_index: int, new_name: str) -> dict:
    """Rename one existing track identified by its one-based index."""
    return send_reaper_command(
        "rename_track", track_index=track_index, new_name=new_name
    )

@mcp.tool()
def create_track_folder(name: str, children: list[str]) -> dict:
    """Create one native folder track with ordered named child tracks."""
    return send_reaper_command(
        "create_track_folder", name=name, children=children
    )

@mcp.tool()
def move_track_into_folder(
    track_index: int, folder_track_index: int
) -> dict:
    """Move one top-level normal track into a top-level folder."""
    return send_reaper_command(
        "move_track_into_folder",
        track_index=track_index,
        folder_track_index=folder_track_index
    )

@mcp.tool()
def get_track_fx() -> dict:
    """Return the FX chains for all tracks in the current REAPER project."""
    return send_reaper_command("get_track_fx")


@mcp.tool()
def ensure_track_fx(
    track_index: int, fx_name: str, position: int | None = None
) -> dict:
    """Ensure a named FX exists, optionally at a zero-based chain position."""
    return send_reaper_command(
        "ensure_track_fx",
        track_index=track_index,
        fx_name=fx_name,
        position=position
    )


@mcp.tool()
def get_fx_parameters(track_index: int, fx_index: int) -> dict:
    """Return parameters for one FX on a track in the current REAPER project."""
    return send_reaper_command(
        "get_fx_parameters",
        track_index=track_index,
        fx_index=fx_index
    )

@mcp.tool()
def get_fx_parameter(
    track_index: int,
    fx_index: int,
    parameter_index: int
) -> dict:
    """Return one parameter for one FX in the current REAPER project."""
    return send_reaper_command(
        "get_fx_parameter",
        track_index=track_index,
        fx_index=fx_index,
        parameter_index=parameter_index
    )

@mcp.tool()
def get_fx_presets(track_index: int, fx_index: int) -> dict:
    """Return current preset information for one FX."""
    return send_reaper_command(
        "get_fx_presets",
        track_index=track_index,
        fx_index=fx_index
    )

@mcp.tool()
def diagnose_fx_parameter_formatter(
    track_index: int,
    fx_index: int,
    parameter_index: int
) -> dict:
    """Sample REAPER's normalized formatter for one FX parameter."""
    return send_reaper_command(
        "diagnose_fx_parameter_formatter",
        track_index=track_index,
        fx_index=fx_index,
        parameter_index=parameter_index
    )

@mcp.tool()
def set_fx_parameter(
    track_index: int,
    fx_index: int,
    parameter_index: int,
    normalized_value: float | None = None,
    formatted_value: str | None = None
) -> dict:
    """Set one FX parameter from a normalized or formatted value."""
    return send_reaper_command(
        "set_fx_parameter",
        track_index=track_index,
        fx_index=fx_index,
        parameter_index=parameter_index,
        normalized_value=normalized_value,
        formatted_value=formatted_value
    )

@mcp.tool()
def set_fx_parameter_formatted(
    track_index: int,
    fx_index: int,
    parameter_index: int,
    formatted_value: str
) -> dict:
    """Set one FX parameter from its human-readable formatted value."""
    return send_reaper_command(
        "set_fx_parameter",
        track_index=track_index,
        fx_index=fx_index,
        parameter_index=parameter_index,
        formatted_value=formatted_value
    )

@mcp.tool()
def set_fx_enabled(
    track_index: int, fx_index: int, enabled: bool
) -> dict:
    """Enable or bypass one track FX."""
    return send_reaper_command(
        "set_fx_enabled",
        track_index=track_index,
        fx_index=fx_index,
        enabled=enabled
    )

@mcp.tool()
def set_track_volume(
    track_index: int,
    volume_raw: float | None = None,
    volume_db: float | None = None
) -> dict:
    """Set one track's volume from a raw linear or dB value."""
    return send_reaper_command(
        "set_track_volume",
        track_index=track_index,
        volume_raw=volume_raw,
        volume_db=volume_db
    )

@mcp.tool()
def set_track_pan(
    track_index: int,
    pan_raw: float | None = None,
    pan_percent: float | None = None
) -> dict:
    """Set one track's pan from a raw or signed percentage value."""
    return send_reaper_command(
        "set_track_pan",
        track_index=track_index,
        pan_raw=pan_raw,
        pan_percent=pan_percent
    )

@mcp.tool()
def set_track_mute(track_index: int, muted: bool) -> dict:
    """Set one track's mute state."""
    return send_reaper_command(
        "set_track_mute",
        track_index=track_index,
        muted=muted
    )

@mcp.tool()
def set_track_record_arm(track_index: int, armed: bool) -> dict:
    """Set one track's record-arm state."""
    return send_reaper_command(
        "set_track_record_arm",
        track_index=track_index,
        armed=armed
    )

@mcp.tool()
def set_track_solo(track_index: int, solo: bool) -> dict:
    """Set one track's normal solo state."""
    return send_reaper_command(
        "set_track_solo",
        track_index=track_index,
        solo=solo
    )

@mcp.tool()
def create_note_item(
    track_index: int,
    start_measure: int,
    duration_measures: int,
    text: str
) -> dict:
    """Create an empty item with notes at exact measure boundaries."""
    return send_reaper_command(
        "create_note_item",
        track_index=track_index,
        start_measure=start_measure,
        duration_measures=duration_measures,
        text=text
    )

@mcp.tool()
def create_midi_item(
    track_index: int,
    start_measure: int,
    end_measure: int,
    notes: list[dict]
) -> dict:
    """Create independently positioned MIDI notes using relative measures."""
    return send_reaper_command(
        "create_midi_item",
        track_index=track_index,
        start_measure=start_measure,
        end_measure=end_measure,
        notes=notes
    )

@mcp.tool()
def replace_midi_item_content(
    track_index: int,
    item_guid: str,
    notes: list[dict]
) -> dict:
    """Bulk-replace MIDI using legacy or bar/beat/offset note positions."""
    return send_reaper_command(
        "replace_midi_item_content",
        track_index=track_index,
        item_guid=item_guid,
        notes=notes
    )

@mcp.tool()
def ping() -> str:
    """Simple MCP connectivity test."""
    return "pong"

@mcp.tool()
def get_track_count() -> int:
    """Return the number of tracks in the current REAPER project."""
    response = send_reaper_command("get_track_count")
    return response["track_count"]

@mcp.tool()
def get_project_info() -> dict:
    """Return basic information about the current REAPER project."""
    return send_reaper_command("get_project_info")

if __name__ == "__main__":
    mcp.run(transport="stdio")
