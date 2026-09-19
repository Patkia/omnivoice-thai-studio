from __future__ import annotations
import hashlib,json,wave
from datetime import datetime,timezone
from pathlib import Path
import numpy as np, soundfile as sf
from novel_chunker import chunk_text
from studio_engine_adapter import StudioEngineAdapter,preview_text

def safe_project_name(name:str)->str:
    cleaned=''.join(c if c.isalnum() or c in '-_' else '_' for c in name).strip('_')
    return cleaned or 'untitled'
class NovelBatch:
 def __init__(self,adapter:StudioEngineAdapter,project:str,source:str,voice:str,speed:float,steps:int,root:Path=Path('output/novel')):
  self.adapter,self.project,self.source,self.voice,self.speed,self.steps=adapter,safe_project_name(project),source,voice,speed,steps; self.dir=root/self.project; self.chunks=chunk_text(source)
 def manifest_path(self): return self.dir/'manifest.json'
 def preview(self):
  return [{'index':i+1,'text':x,'character_count':len(x),'gate':preview_text(x,self.voice)['prepared']['gate'].thai_only_gate_passed} for i,x in enumerate(self.chunks)]
 def run(self,force=False,retry_failed=False):
  self.dir.joinpath('chunks').mkdir(parents=True,exist_ok=True); rows=[]
  for item in self.preview():
   out=self.dir/'chunks'/f"{item['index']:03}.wav"; row={**item,'output':str(out),'status':'BLOCKED' if not item['gate'] else 'PENDING'}
   if item['gate']:
    try:
     r=self.adapter.generate(item['text'],self.voice,self.speed,self.steps,out,force); row.update(status='CACHED' if r['cache_hit'] else 'GENERATED',**r)
    except Exception as e: row.update(status='FAILED',error=str(e))
   rows.append(row)
  manifest={'project_name':self.project,'source_hash':hashlib.sha256(self.source.encode()).hexdigest(),'created_at':datetime.now(timezone.utc).isoformat(),'voice_alias':self.voice,'speed':self.speed,'steps':self.steps,'model':self.adapter.engine['model'],'revision':self.adapter.engine['revision'],'chunk_count':len(rows),'chunks':rows}
  self.manifest_path().write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8'); return manifest
 def merge(self,silence_ms=300):
  data=json.loads(self.manifest_path().read_text(encoding='utf8')); files=[Path(x['output']) for x in data['chunks'] if x['status'] in ('GENERATED','CACHED')]; audio=[]; sr=None
  for path in files:
   a,r=sf.read(path,dtype='float32'); sr=sr or r; audio += [a,np.zeros(int(sr*silence_ms/1000),dtype='float32')]
  if not audio: raise RuntimeError('ไม่มี chunk ที่รวมได้')
  out=self.dir/'merged.wav'; sf.write(out,np.concatenate(audio[:-1]),sr,subtype='PCM_16'); data['merged_output']=str(out); self.manifest_path().write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8'); return out
