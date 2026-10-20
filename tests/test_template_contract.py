import asyncio
import unittest
from unittest.mock import patch
from mcp.server.mcpserver.exceptions import ToolError
from reaper_mcp import server
from test_recording_setup import load_functions

class TemplateMCPTests(unittest.TestCase):
 def test_routing_pointer_and_hardware_offset(self):
  track='(MediaTrack*)0x0000000123456780'
  address=int(track.split('0x')[1],16)
  calls=[]
  def read(t,category,index,attribute):
   calls.append((category,index));return float(address)
  n=load_functions({'math':__import__('math'),'RPR_GetTrackSendInfo_Value':read,'RPR_GetTrackNumSends':lambda *args:2})
  n['template_tracks']=lambda:[track]
  self.assertEqual(n['template_route_peer'](track,0,0,'P_DESTTRACK'),track)
  self.assertEqual(calls,[(0,2)])
  n['template_route_peer'](track,-1,0,'P_SRCTRACK')
  self.assertEqual(calls[-1],(-1,0))
  n['RPR_GetTrackSendInfo_Value']=lambda *args:0.0
  with self.assertRaisesRegex(RuntimeError,'invalid'):
   n['template_route_peer'](track,0,0,'P_DESTTRACK')
 def test_bridge_error_is_tool_error_with_diagnostics(self):
  with patch.object(server,'send_reaper_command',return_value={'error':'verification failed','rollback_succeeded':True,'diagnostics':{'source_line':3}}):
   with self.assertRaisesRegex(ToolError,'rollback_succeeded'):
    server.copy_track_fx_chain(3,11)
 def test_duplicate_contract_forwards_explicit_defaults(self):
  with patch.object(server,'send_reaper_command',return_value={'success':True}) as send:
   server.duplicate_tracks('{SRC}','Copy')
   args=send.call_args.kwargs
   self.assertFalse(args['include_items']); self.assertFalse(args['preserve_record_arm']); self.assertFalse(args['preserve_solo'])
 def test_mcp_registry_exposes_new_tool(self):
  tools=asyncio.run(server.mcp.list_tools())
  tool=next(t for t in tools if t.name=='duplicate_tracks')
  self.assertIn('source_track_guid',tool.input_schema['required'])
