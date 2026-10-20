from reaper_python import *
import ast, base64, difflib, hashlib, json, math, re, traceback, uuid
from pathlib import Path
ROOT=Path(RPR_GetExtState('reaper-template-validation','repository'))
OUT=ROOT/'.local/template-validation'
report={}
try:
 assert Path(RPR_GetResourcePath()).resolve()==OUT.resolve()
 assert RPR_CountTracks(0)==0
 tree=ast.parse((ROOT/'reaper/mcp_bridge.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'bridge','exec'),globals())
 for i in range(8):
  RPR_InsertTrackAtIndex(i,False)
  assert RPR_SetTrackStateChunk(RPR_GetTrack(0,i),(OUT/f'track-{i+1}.txt').read_text(),False)
 for idx in (3,7,8):
  RPR_InsertTrackAtIndex(RPR_CountTracks(0),False)
  src=RPR_GetTrack(0,idx-1); dst=RPR_GetTrack(0,RPR_CountTracks(0)-1)
  a=recording_fx_chunk(read_recording_chunk(src))
  for f in range(RPR_TrackFX_GetCount(src)): RPR_TrackFX_CopyToTrack(src,f,dst,f,False)
  b=recording_fx_chunk(read_recording_chunk(dst))
  changes=[]
  for line in difflib.unified_diff(comparable_fx_chunk(a).splitlines(),comparable_fx_chunk(b).splitlines(),n=0):
   if line.startswith(('@@','---','+++')): changes.append(line)
   else: changes.append({'side':line[:1],'length':len(line)-1,'sha256':hashlib.sha256(line[1:].encode()).hexdigest(),'record':line[1:].split(' ')[0] if ' ' in line else 'opaque'})
  report[str(idx)]={'verification':verify_copied_fx_state(src,dst,a,b),'diff':changes}
  (OUT/f'copy-{idx}-source.txt').write_text(a); (OUT/f'copy-{idx}-dest.txt').write_text(b)
 report['success']=True
except Exception: report['exception']=traceback.format_exc()
(OUT/'diagnosis.json').write_text(json.dumps(report,indent=2))
