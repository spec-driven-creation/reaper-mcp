from reaper_python import *
import ast, base64, difflib, hashlib, json, math, re, traceback, uuid
from pathlib import Path
ROOT=Path(RPR_GetExtState('reaper-template-validation','repository')); OUT=ROOT/'.local/template-validation'
report={'checks':[]}
def check(label, value):
 report['checks'].append({'check':label,'result':value}); (OUT/'validation.json').write_text(json.dumps(report,indent=2))
 assert value.get('success') if isinstance(value,dict) else value
def native_fx_state(track, fx):
 io=RPR_TrackFX_GetIOSize(track,fx,0,0)
 pins=[]
 for direction,count in ((0,io[3]),(1,io[4])):
  for pin in range(count):
   for bank in (0,0x1000000):
    value=RPR_TrackFX_GetPinMappings(track,fx,direction,pin|bank,0)
    pins.append((value[0]&0xffffffff,value[5]&0xffffffff))
 return {'name':RPR_TrackFX_GetFXName(track,fx,'',512)[3],
         'preset':RPR_TrackFX_GetPreset(track,fx,'',512)[3],
         'preset_index':RPR_TrackFX_GetPresetIndex(track,fx,0)[0],
         'enabled':RPR_TrackFX_GetEnabled(track,fx),'offline':RPR_TrackFX_GetOffline(track,fx),
         'parameters':[RPR_TrackFX_GetParamNormalized(track,fx,p) for p in range(RPR_TrackFX_GetNumParams(track,fx))],
         'io':io[3:5],'pins':pins}
try:
 assert Path(RPR_GetResourcePath()).resolve()==OUT.resolve()
 assert RPR_CountTracks(0)==0
 tree=ast.parse((ROOT/'reaper/mcp_bridge.py').read_text())
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'bridge','exec'),globals())
 for i in range(8):
  RPR_InsertTrackAtIndex(i,False); assert RPR_SetTrackStateChunk(RPR_GetTrack(0,i),(OUT/f'track-{i+1}.txt').read_text(),False)
 for idx in (3,7,8):
  RPR_InsertTrackAtIndex(RPR_CountTracks(0),False); dest=RPR_CountTracks(0)
  check('copy-'+str(idx),handle_copy_track_fx_chain({'source_track_index':idx,'track_index':dest}))
  src=RPR_GetTrack(0,idx-1); destination=RPR_GetTrack(0,dest-1)
  check('original-live-state-'+str(idx),verify_copied_fx_state(src,destination,recording_fx_chunk((OUT/f'track-{idx}.txt').read_text()),recording_fx_chunk(read_recording_chunk(destination)))[0])
  check('independent-native-state-'+str(idx),all(native_fx_state(src,f)==native_fx_state(destination,f) for f in range(RPR_TrackFX_GetCount(src))))
  dst=RPR_GetTrack(0,dest-1)
  for f in reversed(range(RPR_TrackFX_GetCount(dst))): RPR_TrackFX_Delete(dst,f)
  native=RPR_TrackFX_CopyToTrack
  def fail(s,i,d,j,m):
   native(s,i,d,j,m); raise RuntimeError('Injected partial copy failure')
  RPR_TrackFX_CopyToTrack=fail
  result=handle_copy_track_fx_chain({'source_track_index':idx,'track_index':dest})
  RPR_TrackFX_CopyToTrack=native
  check('copy-rollback-'+str(idx),'error' in result and result['rollback_succeeded'] and result['source_unchanged'])
  def corrupt(s,i,d,j,m):
   native(s,i,d,j,m)
   if i==0: RPR_TrackFX_SetEnabled(d,j,not RPR_TrackFX_GetEnabled(s,i))
  RPR_TrackFX_CopyToTrack=corrupt
  failed=handle_copy_track_fx_chain({'source_track_index':idx,'track_index':dest})
  RPR_TrackFX_CopyToTrack=native
  check('sonic-mismatch-rollback-'+str(idx),'error' in failed and failed['rollback_succeeded'] and failed['source_unchanged'] and bool(failed['diagnostics']['differences']))
 # Additional isolated fixtures: nested hierarchy, audio items, input FX,
 # armed/solo source and an unavailable saved input.
 notes=RPR_GetTrack(0,5); guitar=RPR_GetTrack(0,6)
 RPR_SetMediaTrackInfo_Value(notes,'I_FOLDERDEPTH',1)
 RPR_SetMediaTrackInfo_Value(guitar,'I_FOLDERDEPTH',-1)
 RPR_SetMediaTrackInfo_Value(notes,'I_RECINPUT',999)
 RPR_SetMediaTrackInfo_Value(guitar,'I_RECARM',1)
 RPR_SetMediaTrackInfo_Value(guitar,'I_SOLO',1)
 assert RPR_TrackFX_AddByName(guitar,'JS: utility/volume',True,1)>=0
 item=RPR_AddMediaItemToTrack(guitar); take=RPR_AddTakeToMediaItem(item)
 import wave
 with wave.open(str(OUT/'host-fixture.wav'),'wb') as f:
  f.setnchannels(1); f.setsampwidth(2); f.setframerate(48000); f.writeframes(b'\0\0'*480)
 fixture=str(OUT/'host-fixture.wav').replace('\\','/')
 assert RPR_SetItemStateChunk(item,'<ITEM\nPOSITION 0\nLENGTH 0.01\n<SOURCE WAVE\nFILE "'+fixture+'"\n>\n>\n',False)
 report['fixture_source']=RPR_GetMediaSourceFileName(RPR_GetMediaItemTake_Source(RPR_GetTake(item,0)),'',4096)[1]
 check('wave-fixture-reference',bool(report['fixture_source']))
 # Native internal and external routes, all in isolated project.
 src=RPR_GetTrack(0,6); midi=RPR_GetTrack(0,7); outside=RPR_GetTrack(0,0)
 RPR_CreateTrackSend(src,0)
 RPR_CreateTrackSend(midi,src); RPR_CreateTrackSend(src,outside); RPR_CreateTrackSend(outside,midi)
 check('internal-route-fixture',len(template_internal_routes([src,midi]))==1)
 request={'source_track_guid':recording_track_guid(RPR_GetTrack(0,4)),'new_name':'TEST-FOLDER','include_descendants':True,'descendant_names':{recording_track_guid(notes):'TEST-NOTES',recording_track_guid(src):'TEST-GTR',recording_track_guid(midi):'TEST-MIDI'}}
 folder_result=handle_duplicate_tracks(request)
 check('folder',folder_result)
 check('unavailable-input-warning',bool(folder_result['warnings']) and folder_result['warnings'][0]['requested_record_input_raw']==999)
 copied=template_track_by_guid(folder_result['created_tracks'][2]['track_guid'])
 check('safe-defaults-and-input-fx',RPR_GetMediaTrackInfo_Value(copied,'I_RECARM')==0 and RPR_GetMediaTrackInfo_Value(copied,'I_SOLO')==0 and RPR_TrackFX_GetRecCount(copied)==1)
 check('excluded-items',RPR_CountTrackMediaItems(copied)==0)
 request={'source_track_guid':recording_track_guid(src),'new_name':'TEST-NORMAL','include_items':True,'insert_before_track_guid':recording_track_guid(outside)}
 normal_result=handle_duplicate_tracks(request)
 check('normal-with-items',normal_result)
 copied=template_track_by_guid(normal_result['created_tracks'][0]['track_guid'])
 copied_item=RPR_GetTrackMediaItem(copied,0)
 copied_source=RPR_GetMediaItemTake_Source(RPR_GetTake(copied_item,0))
 check('shared-audio-file',Path(RPR_GetMediaSourceFileName(copied_source,'',4096)[1]).resolve()==(OUT/'host-fixture.wav').resolve())
 before_undo=RPR_CountTracks(0)
 RPR_Undo_DoUndo2(0)
 check('native-undo',RPR_CountTracks(0)==before_undo-1 and all(recording_track_guid(t)!=normal_result['created_tracks'][0]['track_guid'] for t in template_tracks()))
 native=RPR_GetSetMediaTrackInfo_String
 def fail_name(track,key,value,setvalue):
  if key=='P_NAME' and setvalue: raise RuntimeError('Injected rename failure')
  return native(track,key,value,setvalue)
 RPR_GetSetMediaTrackInfo_String=fail_name
 failed=handle_duplicate_tracks(request)
 RPR_GetSetMediaTrackInfo_String=native
 check('duplicate-rollback','error' in failed and failed['rollback_succeeded'] and failed['source_unchanged'])
 report['success']=True
except Exception: report['exception']=traceback.format_exc()
(OUT/'validation.json').write_text(json.dumps(report,indent=2))
