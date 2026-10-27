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


class TemplateFidelityTests(unittest.TestCase):
 def setUp(self):
  self.n=load_functions({})
  self.source='<TRACK\nNAME "Guitar"\nFREEMODE 2\nFIXEDLANES 9 0 0 0 0\nLANESOLO 3 0 0 0 0 0 0 0\nREC 1 1 1 0 0 0 0 0\nVOLPAN 0.4 0 1 -1\n>\n'
  self.copy=self.source.replace('LANESOLO', 'LANEREC -1 -1 -1 0\nLANESOLO')
 def compare(self,a,b,items=False):
  return self.n['template_non_fx_comparison'](a,b,items)
 def test_native_implicit_lane_default_only(self):
  a,b,normalized=self.compare(self.source,self.copy)
  self.assertEqual(a,b); self.assertEqual(len(normalized),1)
  self.assertNotEqual(*self.compare(self.copy,self.source)[:2])
 def test_nondefault_duplicate_other_mode_and_nested_are_rejected(self):
  for value in ('LANEREC 0 -1 -1 0','LANEREC -1 0 -1 0','LANEREC -1 -1 0 0','LANEREC -1 -1 -1 1','LANEREC -1 -1 -1 0 0','LANEREC -1 -1 -1 0\nLANEREC -1 -1 -1 0'):
   with self.subTest(value=value):
    a,b,_=self.compare(self.source,self.copy.replace('LANEREC -1 -1 -1 0',value))
    self.assertNotEqual(a,b)
  a,b,_=self.compare(self.source.replace('FREEMODE 2','FREEMODE 1'),self.copy.replace('FREEMODE 2','FREEMODE 1'))
  self.assertNotEqual(a,b)
  a,b,_=self.compare(self.source,self.source.replace('VOLPAN','<EXTENSION\nLANEREC -1 -1 -1 0\n>\nVOLPAN'))
  self.assertNotEqual(a,b)
 def test_real_state_changes_remain_strict(self):
  for old,new in [('VOLPAN 0.4','VOLPAN 0.5'),('REC 1 1 1','REC 1 2 1'),('REC 1 1 1','REC 1 1 0'),('FIXEDLANES 9','FIXEDLANES 8'),('LANESOLO 3','LANESOLO 2')]:
   with self.subTest(field=old):
    a,b,_=self.compare(self.source,self.copy.replace(old,new))
    self.assertNotEqual(a,b)
  a,b,_=self.compare(self.source,self.copy.replace('VOLPAN','UNKNOWN 123\nVOLPAN'))
  self.assertNotEqual(a,b)
 def test_only_authorized_arm_and_solo_changes(self):
  source=self.source.replace('VOLPAN','MUTESOLO 0 1 0\nVOLPAN')
  copy=self.copy.replace('REC 1','REC 0').replace('VOLPAN','MUTESOLO 0 0 0\nVOLPAN')
  self.assertEqual(*self.compare(source,copy)[:2])
 def test_included_item_data_is_not_normalized(self):
  item='<ITEM\n<SOURCE MIDI\nLANEREC -1 -1 -1 0\n>\n>\n'
  a,b,_=self.compare(self.source+item,self.copy+item.replace('-1 -1 -1 0','0 -1 -1 0'),True)
  self.assertNotEqual(a,b)
 def test_diagnostics_values_locations_privacy_and_limit(self):
  result=self.n['template_difference_diagnostics'](self.source,self.copy.replace('VOLPAN 0.4','VOLPAN 0.5'))
  entries=[d['observed'] for d in result['differences'] if d['observed']]
  self.assertTrue(any(e.get('value')=='LANEREC -1 -1 -1 0' and e['path']=='TRACK' for e in entries))
  self.assertTrue(any(e.get('value')=='VOLPAN 0.5 0 1 -1' for e in entries))
  secret='OPAQUE_PAYLOAD'
  result=self.n['template_difference_diagnostics']('<TRACK\n>','<TRACK\n<FXCHAIN\n<VST "secret plugin"\n'+secret+'\n>\n>\n>')
  self.assertNotIn(secret,str(result));self.assertNotIn('secret plugin',str(result))
  result=self.n['template_difference_diagnostics']('', '\n'.join('PRIVATE '+str(i) for i in range(30)))
  self.assertEqual(len(result['differences']),16);self.assertTrue(result['truncated'])
