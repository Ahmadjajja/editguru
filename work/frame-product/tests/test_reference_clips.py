import hashlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import quick_timeline as timeline
import quick_revision as revision
import quick_sections as sections

class ReferenceClipTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.pid='a'*32;self.rid='b'*32;self.root=Path(self.temp.name)
  for pid in (self.pid,self.rid):
   (self.root/pid).mkdir();(self.root/pid/'input.mp4').write_bytes(b'source video')
  asset=self.root/self.pid/'assets/clip.mp4';asset.parent.mkdir();asset.write_bytes(b'asset video')
  self.app=types.SimpleNamespace(WORK=self.root,project=lambda _: {'name':'Fixture','current_segments':None})
  probe=patch.object(timeline,'probe',return_value={'duration':4,'audio':True});probe.start();self.addCleanup(probe.stop)
  self.act('add_general_note',instruction='Use this motion.')
  doc=timeline.load(self.app,self.pid);doc['video_references']=[{'project_id':self.rid,'name':'Ref','duration':4,'sha256':'abc'}]
  doc['assets']=[{'id':'c'*32,'path':'assets/clip.mp4','mime_type':'video/mp4','name':'Folder clip','sha256':'def'}]
  timeline.write(self.root/self.pid/'timeline.json',doc);self.nid=doc['notes'][0]['id']
 def act(self,action,**args):
  doc=timeline.load(self.app,self.pid)
  return revision.act(self.app,self.pid,dict(action=action,expected_version=doc['version'],**args))
 def test_range_saved_on_exact_revision_and_frozen(self):
  self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.rid,start=.75,end=3.25)
  doc=timeline.load(self.app,self.pid);ref=doc['notes'][0]['reference_clips'][0]
  self.assertEqual((ref['start'],ref['end']),(.75,3.25));self.assertEqual(ref['project_id'],self.rid)
  sections.checkpoint(doc,'Frozen','frozen');timeline.write(self.root/self.pid/'timeline.json',doc)
  self.act('remove_reference_clip',note_id=self.nid,reference_id=ref['id'])
  doc=timeline.load(self.app,self.pid);self.assertEqual(doc['notes'][0]['reference_clips'],[])
  self.assertEqual(next(c for c in doc['checkpoints'] if c['id']=='frozen')['notes'][0]['reference_clips'],[ref])
 def test_invalid_ranges_unlinked_sources_and_wrong_note_rejected(self):
  for start,end in [(2,1),(-1,2),(0,5),(1,1)]:
   with self.assertRaises(ValueError):self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.rid,start=start,end=end)
  with self.assertRaises((ValueError,FileNotFoundError)):self.act('attach_reference_clip',note_id=self.nid,reference_project_id='d'*32,start=0,end=2)
  with self.assertRaises(ValueError):self.act('attach_reference_clip',note_id='missing',reference_project_id=self.rid,start=0,end=2)
 def test_project_asset_association(self):
  self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.pid,asset_id='c'*32,start=0,end=4)
  ref=timeline.load(self.app,self.pid)['notes'][0]['reference_clips'][0]
  self.assertEqual(ref['asset_id'],'c'*32);self.assertEqual(ref['sha256'],hashlib.sha256(b'asset video').hexdigest())
  with self.assertRaises(ValueError):self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.rid,asset_id='c'*32,start=0,end=2)

 def test_current_video_and_unlinked_library_project_are_selectable(self):
  doc=timeline.load(self.app,self.pid);doc['video_references']=[];timeline.write(self.root/self.pid/'timeline.json',doc)
  for rid in (self.pid,self.rid):
   self.act('attach_reference_clip',note_id=self.nid,reference_project_id=rid,start=.5,end=2.5)
  refs=timeline.load(self.app,self.pid)['notes'][0]['reference_clips']
  self.assertEqual([r['project_id'] for r in refs],[self.pid,self.rid])
  self.assertTrue(all(r['sha256']==hashlib.sha256(b'source video').hexdigest() for r in refs))
 def test_exact_completed_export_and_edit_range_keep_identity(self):
  eid='e'*32;doc=timeline.load(self.app,self.rid);doc['exports']=[{'id':eid,'status':'done','duration':4}];timeline.write(self.root/self.rid/'timeline.json',doc)
  path=self.root/self.rid/'versions'/eid/'edited.mp4';path.parent.mkdir(parents=True);path.write_bytes(b'export video')
  self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.rid,export_id=eid,start=1,end=3)
  doc=timeline.load(self.app,self.pid);ref=doc['notes'][0]['reference_clips'][0];sections.checkpoint(doc,'Frozen','frozen');timeline.write(self.root/self.pid/'timeline.json',doc)
  self.act('attach_reference_clip',note_id=self.nid,reference_id=ref['id'],reference_project_id=self.rid,export_id=eid,start=1.5,end=2.5)
  doc=timeline.load(self.app,self.pid);self.assertEqual(len(doc['notes'][0]['reference_clips']),1);self.assertEqual(doc['notes'][0]['reference_clips'][0]['id'],ref['id']);self.assertEqual(doc['notes'][0]['reference_clips'][0]['start'],1.5)
  self.assertEqual(next(c for c in doc['checkpoints'] if c['id']=='frozen')['notes'][0]['reference_clips'][0]['start'],1)
  self.assertEqual(ref['sha256'],hashlib.sha256(b'export video').hexdigest())
  with self.assertRaises(ValueError):self.act('attach_reference_clip',note_id=self.nid,reference_project_id=self.rid,export_id='f'*32,start=0,end=1)

if __name__=='__main__':unittest.main()
