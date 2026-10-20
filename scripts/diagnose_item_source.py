"""Read the reported live source only; never call the edge mutation handler."""
from reaper_python import *
import ast
import json
import math
import re
import traceback
import wave
from pathlib import Path

ROOT = Path(RPR_GetExtState('reaper-source-diagnostic', 'repository'))
report = {}
try:
    tree = ast.parse((ROOT / 'reaper/mcp_bridge.py').read_text())
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), 'bridge', 'exec'), globals())
    track = template_track_by_guid('{DB7D7DF9-A322-476F-901A-A1B72A1A47EF}')
    item = find_item_by_guid(track, '{B19B1EFB-5752-48D4-91EE-A512981D7751}')
    assert item
    before = item_edges_chunk(item)
    take = RPR_GetTake(item, 0)
    source = RPR_GetMediaItemTake_Source(take)
    report.update(source_pointer=source, source_valid=bool(RPR_ValidatePtr2(0, source, 'PCM_source*')),
                  source_type=RPR_GetMediaSourceType(source, '', 256)[1],
                  parent=RPR_GetMediaSourceParent(source),
                  length_return_false=RPR_GetMediaSourceLength(source, False),
                  length_return_true=RPR_GetMediaSourceLength(source, True),
                  sample_rate=RPR_GetMediaSourceSampleRate(source), channels=RPR_GetMediaSourceNumChannels(source),
                  state=item_edges_state(item))
    report['source_validation'] = item_edges_source_error(report['state'])
    file = Path(report['state']['source_file'])
    report['file_exists'] = file.is_file()
    with wave.open(str(file), 'rb') as audio:
        report['file_only'] = dict(frames=audio.getnframes(), sample_rate=audio.getframerate(),
                                   channels=audio.getnchannels(), sample_bytes=audio.getsampwidth(),
                                   length_seconds=audio.getnframes() / audio.getframerate())
    report['item_unchanged'] = before == item_edges_chunk(item)
    assert report['item_unchanged']
except Exception:
    report['exception'] = traceback.format_exc()
(ROOT / '.local/source-length/python.json').write_text(json.dumps(report, indent=2))
