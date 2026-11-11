import copy
from pathlib import Path
import tempfile
import threading
import types
import unittest
import quick_timeline as q
import quick_studio as s
from editor import run, probe

class StudioTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.pid='b'*32;self.folder=self.root/self.pid;self.folder.mkdir()
  self.app=types.SimpleNamespace(WORK=self.root,WORKERS=threading.Semaphore(1),project=lambda _: {'name':'Studio fixture','current_segments':None})
  run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=320x240:r=30:d=3','-c:v','libx264','-pix_fmt','yuv420p',str(self.folder/'input.mp4')])
  self.doc=q.load(self.app,self.pid)
 def cmd(self,op,**args):
  self.doc=q.execute(self.app,self.pid,op,dict(expected_version=self.doc['version'],**args));return self.doc
 def studio(self):
  return {**copy.deepcopy(s.DEFAULT),'aspect':'1:1','captions':[{'id':'caption','text':'Frame test','start':.5,'end':1.5,'x':.5,'y':.8,'size':.045,'color':'#ffffff'}]}
 def add(self,name,kind,aid):
  path=self.folder/name
  if kind=='image':
   from PIL import Image
   Image.new('RGB',(100,100),'red').save(path)
  else:run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2',str(path)])
  d=q.load(self.app,self.pid);d.setdefault('assets',[]).append({'id':aid,'path':name,'mime_type':kind+'/test','name':name});q.write(self.folder/'timeline.json',d)
 def test_saved_undo_redo_and_restore_checkpoint(self):
  original=self.doc['clips'][0]['id'];self.cmd('set_studio',studio=self.studio());checkpoint=self.doc['current_checkpoint_id']
  self.cmd('split_clip',clip_id=original,source_time=1);self.cmd('undo');self.assertEqual(len(self.doc['clips']),1);self.assertTrue(self.doc['studio']['captions'])
  self.cmd('undo');self.assertEqual(self.doc['studio'],{});self.cmd('redo');self.assertEqual(self.doc['studio']['aspect'],'1:1')
  self.assertEqual(q.load(self.app,self.pid)['studio']['captions'][0]['text'],'Frame test')
  import quick_sections
  result=quick_sections.act(self.app,self.pid,{'action':'restore_checkpoint','checkpoint_id':checkpoint,'expected_version':self.doc['version']})
  self.assertEqual(result['studio']['aspect'],'1:1')
 def test_validation_and_conflict_preserve_saved_state(self):
  self.cmd('set_studio',studio=self.studio());before=(self.folder/'timeline.json').read_bytes()
  for invalid in [{**self.studio(),'brightness':float('nan')},{**self.studio(),'captions':[{'id':'x','text':'x','start':2,'end':1}]},{**self.studio(),'layers':[{'id':'x','asset_id':'missing','kind':'video','start':0,'end':1}]}]:
   with self.assertRaises(ValueError):self.cmd('set_studio',studio=invalid)
   self.assertEqual((self.folder/'timeline.json').read_bytes(),before)
  with self.assertRaises(q.Conflict):q.execute(self.app,self.pid,'set_studio',{'expected_version':1,'studio':{}})
 def test_real_render_overlay_caption_and_delayed_audio(self):
  self.add('red.png','image','image');self.add('tone.wav','audio','audio');studio=self.studio()
  studio['layers']=[{'id':'image-layer','asset_id':'image','kind':'image','start':1,'end':2,'x':.5,'y':.5,'width':.4},{'id':'music-layer','asset_id':'audio','kind':'audio','start':.5,'end':2.5,'volume':.2}]
  self.cmd('set_studio',studio=studio);export='c'*32
  self.doc=q.load(self.app,self.pid);self.doc['exports'].append({'id':export,'status':'working','timeline_version':self.doc['version'],'url':'/media/'+self.pid+'/versions/'+export+'/edited.mp4'});q.write(self.folder/'timeline.json',self.doc)
  q.export_worker(self.app,self.pid,copy.deepcopy(self.doc),export)
  result=q.load(self.app,self.pid);self.assertEqual(result['exports'][-1]['status'],'done',result['exports'][-1])
  out=self.folder/'versions'/export/'edited.mp4';info=probe(out,False);self.assertEqual((info['width'],info['height']),(1080,1080));self.assertTrue(info['audio']);self.assertAlmostEqual(info['duration'],3,delta=.06)
  from PIL import Image
  for time,color in [(.2,'blue'),(1.2,'red'),(2.8,'blue')]:
   frame=self.folder/('frame-'+str(time)+'.png');run(['ffmpeg','-y','-v','error','-ss',str(time),'-i',str(out),'-frames:v','1',str(frame)])
   with Image.open(frame) as im:
    pixel=im.getpixel((540,540));self.assertGreater(pixel[0] if color=='red' else pixel[2],180);self.assertLess(pixel[2] if color=='red' else pixel[0],40)
  self.assertEqual(result['rendered']['studio'],result['studio'])
 def test_asset_bounds(self):
  self.add('tone.wav','audio','audio');studio=self.studio();studio['layers']=[{'id':'a','asset_id':'audio','kind':'audio','start':0,'end':3}]
  with self.assertRaisesRegex(ValueError,'exceeds'):self.cmd('set_studio',studio=studio)

if __name__=='__main__':unittest.main()

class CaptionMappingTests(unittest.TestCase):
 def test_words_follow_reordered_trimmed_clips(self):
  transcript=[{'start':0,'end':4,'text':'one two three four','words':[{'start':0,'end':.5,'text':'one'},{'start':1,'end':1.5,'text':'two'},{'start':2,'end':2.5,'text':'three'},{'start':3,'end':3.5,'text':'four'}]}]
  cues=s.transcript_captions([{'start':2,'end':4},{'start':0,'end':1}],transcript)
  self.assertEqual([c['text'] for c in cues],['three four','one']);self.assertEqual(cues[1]['start'],2);self.assertEqual(cues[1]['end'],2.5)
 def test_stale_transcription_keeps_current_edits_and_offers_captions(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);pid='d'*32;(root/pid).mkdir()
   app=types.SimpleNamespace(WORK=root,WORKERS=threading.Semaphore(1),project=lambda _:{'name':'Speech','current_segments':None})
   from unittest.mock import patch
   with patch.object(q,'probe',return_value={'duration':4,'audio':True}):
    doc=q.load(app,pid)
    with patch.object(threading,'Thread') as thread:
     q.execute(app,pid,'generate_studio_captions',{'expected_version':doc['version']});args=thread.call_args.kwargs['args']
    q.execute(app,pid,'trim_clip',{'expected_version':doc['version'],'clip_id':doc['clips'][0]['id'],'start':1,'end':4})
    with patch('editor.transcribe',return_value=[{'start':0,'end':2,'text':'spoken test'}]):s.caption_worker(*args)
    saved=q.load(app,pid);self.assertEqual(saved['clips'][0]['start'],1);self.assertEqual(saved['caption_job']['status'],'ready');self.assertNotIn('studio',saved)
