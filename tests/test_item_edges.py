import asyncio
import math
import unittest
from unittest.mock import patch
from mcp.server.mcpserver.exceptions import ToolError

from reaper_mcp import server
from test_recording_setup import load_functions


class ItemEdgesTests(unittest.TestCase):
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
