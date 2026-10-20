import asyncio
import math
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from mcp.server.mcpserver.exceptions import ToolError

from reaper_mcp import server
from test_recording_setup import load_functions


class ItemEdgesTests(unittest.TestCase):
    def source_namespace(self, filename, length=7.4755625, online=True):
        source = '(PCM_source*)0x0000000112345678'
        ns = load_functions({
            'math': math, 'RPR_ValidatePtr2': lambda *args: True,
            'RPR_GetMediaSourceLength': lambda pointer, is_qn: (length, pointer, 0),
            'RPR_GetMediaSourceParent': lambda *args: '(PCM_source*)0x0000000000000000',
            'RPR_GetMediaSourceFileName': lambda *args: (source, filename, 32768),
            'RPR_GetMediaSourceType': lambda *args: (source, 'WAVE', 256),
            'RPR_GetMediaSourceSampleRate': lambda *args: 96000 if length else 0,
            'RPR_GetMediaSourceNumChannels': lambda *args: 1,
        })
        ns['item_edges_source_online'] = lambda *args: online
        return ns, source

    def test_native_seconds_tuple_and_file_availability_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exists.wav'
            path.write_bytes(b'file presence cannot substitute native metadata')
            ns, source = self.source_namespace(str(path))
            state = ns['item_edges_source_state'](source)
            self.assertEqual(state['source_length'], 7.4755625)
            self.assertFalse(state['source_length_is_qn'])
            self.assertEqual(ns['item_edges_source_error'](state), (None, None))
            ns, source = self.source_namespace(str(path), length=0, online=False)
            state = ns['item_edges_source_state'](source)
            self.assertTrue(state['source_file_exists'])
            self.assertTrue(state['source_file_readable'])
            self.assertEqual(state['source_length'], 0)
            self.assertEqual(ns['item_edges_source_error'](state)[0], 'source_offline')
            state['source_online'] = None
            self.assertEqual(ns['item_edges_source_error'](state)[0], 'source_offline_or_unavailable')
            state['source_online'] = True
            self.assertEqual(ns['item_edges_source_error'](state)[0], 'source_metadata_unavailable')

    def test_invalid_source_is_not_dereferenced(self):
        ns = load_functions({'RPR_ValidatePtr2': lambda *args: False})
        state = ns['item_edges_source_state']('(PCM_source*)0x0000000000000000')
        self.assertFalse(state['source_pointer_valid'])
        self.assertEqual(ns['item_edges_source_error'](state)[0], 'invalid_source_pointer')

    def test_missing_file_and_musical_units_are_rejected(self):
        ns, source = self.source_namespace('nonexistent-source-fixture.wav')
        state = ns['item_edges_source_state'](source)
        self.assertEqual(ns['item_edges_source_error'](state)[0], 'source_file_unavailable')
        state.update(source_file_exists=True, source_file_readable=True, source_length_is_qn=True)
        self.assertEqual(ns['item_edges_source_error'](state)[0], 'source_length_not_seconds')

    def test_sws_is_optional_and_units_output_is_checked(self):
        ns = load_functions({'RPR_APIExists': lambda name: False})
        self.assertIsNone(ns['item_edges_source_online']('unused'))
        ns, source = self.source_namespace('unused')
        ns['RPR_GetMediaSourceLength'] = lambda *args: (7.4755625, source, 2)
        with self.assertRaisesRegex(RuntimeError, 'invalid source/unit'):
            ns['item_edges_source_state'](source)

    def test_only_authorized_serialized_tokens_are_ignored(self):
        ns = load_functions({'math': math})
        residual = ns['item_edges_residual']
        chunk = '<ITEM\nPOSITION 5\nLENGTH 3\nSOFFS 4\nFADEIN 1 0.01 0 1 0 0 0\nPLAYRATE 1 1 0\n<SOURCE WAVE\nLENGTH 20\n>\n>\n'
        changed = chunk.replace('POSITION 5', 'POSITION 4').replace('SOFFS 4', 'SOFFS 3')
        self.assertEqual(residual(chunk, {}), residual(changed, {}))
        for old, new in [('LENGTH 20', 'LENGTH 19'), ('PLAYRATE 1', 'PLAYRATE 2'), ('FADEIN 1 0.01', 'FADEIN 1 0.02')]:
            self.assertNotEqual(residual(chunk, {}), residual(chunk.replace(old, new), {}))
        fade = chunk.replace('FADEIN 1 0.01', 'FADEIN 1 0.02')
        self.assertEqual(residual(chunk, {'FADEIN': .02}), residual(fade, {'FADEIN': .02}))
        self.assertNotEqual(residual(chunk, {'FADEIN': .02}), residual(chunk.replace('FADEIN 1', 'FADEIN 2'), {'FADEIN': .02}))

    def test_mcp_defaults_and_identity_are_forwarded(self):
        with patch.object(server, 'send_reaper_command', return_value={'success': True}) as send:
            server.set_item_edges('{ITEM}', 1, 3, track_guid='{TRACK}')
        self.assertEqual(send.call_args.args, ('set_item_edges',))
        self.assertIsNone(send.call_args.kwargs['fade_in_seconds'])
        self.assertIsNone(send.call_args.kwargs['track_index'])
        self.assertEqual(send.call_args.kwargs['track_guid'], '{TRACK}')

    def test_failure_raises_mcp_error_with_rollback(self):
        with patch.object(server, 'send_reaper_command', return_value={'error': 'failed', 'rollback': {'verified': True}}):
            with self.assertRaisesRegex(ToolError, 'rollback'):
                server.set_item_edges('{I}', 1, 2, track_index=1)

    def test_registered_contract(self):
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'set_item_edges')
        self.assertEqual(set(tool.input_schema['required']), {'item_guid', 'start_seconds', 'end_seconds'})


if __name__ == '__main__':
    unittest.main()
