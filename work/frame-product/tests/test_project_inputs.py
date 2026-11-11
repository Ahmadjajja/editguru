import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import quick_timeline as timeline
import quick_revision
import quick_project_inputs as inputs

class ProjectInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.pid='a'*32;self.folder=self.root/self.pid;self.folder.mkdir();(self.folder/'input.mp4').write_bytes(b'old source')
        def metadata(pid):
            file=self.root/pid/'project.json'
            return json.loads(file.read_text()) if file.exists() else {'id':pid,'name':'Project.mp4','current_segments':None}
        self.app=types.SimpleNamespace(WORK=self.root,WORKERS=threading.Semaphore(1),project=metadata)
        mock=patch.object(timeline,'probe',return_value={'duration':8,'audio':True,'width':320,'height':180});mock.start();self.addCleanup(mock.stop)
        self.doc=timeline.load(self.app,self.pid);self.doc['work_project']={'id':self.pid,'title':'Same project','role':'cut'}
        self.asset={'id':'b'*32,'path':'assets/'+'b'*32+'/new-take.mp4','name':'new-take.mp4','mime_type':'video/mp4','size':8,'sha256':hashlib.sha256(b'new take').hexdigest()}
        source=self.folder/self.asset['path'];source.parent.mkdir(parents=True);source.write_bytes(b'new take');self.doc['assets']=[self.asset];timeline.write(self.folder/'timeline.json',self.doc)
        self.doc=quick_revision.act(self.app,self.pid,{'action':'add_general_note','expected_version':self.doc['version'],'instruction':'Earlier project context'})
    def start(self,**extra):return inputs.start_revision(self.app,self.pid,{'expected_version':self.doc['version'],'asset_id':self.asset['id'],'request_id':'new-direction-request','brief':'Use this re-recording for a different opening',**extra})
    def test_new_take_creates_nested_cut_and_preserves_previous_work(self):
        before=timeline.load(self.app,self.pid);result=self.start();child=result['project'];parent=timeline.load(self.app,self.pid)
        self.assertEqual(child['work_project']['id'],self.pid);self.assertEqual(child['revision_parent']['project_id'],self.pid);self.assertEqual((self.root/child['project_id']/'input.mp4').read_bytes(),b'new take');self.assertEqual((self.folder/'input.mp4').read_bytes(),b'old source')
        for key in ['clips','pins','notes','exports','checkpoints','assets']:self.assertEqual(parent[key],before[key])
        self.assertEqual(child['notes'][0]['instruction'],'Use this re-recording for a different opening');self.assertEqual(child['notes'][0]['scope'],'general');self.assertEqual(child['project_context']['previous_general_notes'][0]['instruction'],'Earlier project context');self.assertEqual(child['project_context']['assets'][0]['project_id'],self.pid)
    def test_retry_reuses_exact_branch_even_after_parent_version_changes(self):
        first=self.start();second=self.start(expected_version=-1);self.assertEqual(first['project_id'],second['project_id']);self.assertTrue(second['reused']);self.assertEqual(len(timeline.load(self.app,self.pid)['revision_branches']),1)
        with self.assertRaisesRegex(ValueError,'different new cut'):self.start(brief='Different request')
    def test_parent_save_failure_retry_preserves_initialized_child_and_later_edits(self):
        original=timeline.write;failed=False
        def interrupted(path,value):
            nonlocal failed
            if path==self.folder/'timeline.json' and value.get('revision_branches') and not failed:
                failed=True;raise OSError('parent save interrupted')
            return original(path,value)
        with patch.object(timeline,'write',side_effect=interrupted),self.assertRaises(OSError):self.start()
        target=next(p for p in self.root.iterdir() if p.is_dir() and p!=self.folder)
        child=timeline.load(self.app,target.name)
        self.assertEqual(len(child['notes']),1)
        child['video_references']=[{'project_id':'c'*32,'label':'Added after interrupted save'}]
        child['clips'][0]['start']=1
        timeline.write(target/'timeline.json',child)
        before=(target/'timeline.json').read_bytes()
        result=self.start()
        self.assertEqual(result['project_id'],target.name)
        self.assertEqual((target/'timeline.json').read_bytes(),before,'retry must not write or reinitialize the existing child')
        self.assertEqual(len(result['project']['notes']),1)
        self.assertEqual(len(timeline.load(self.app,self.pid)['revision_branches']),1)

    def test_child_setup_failure_leaves_no_visible_or_partial_project(self):
        original=(self.folder/'timeline.json').read_bytes()
        with patch.object(quick_revision,'act',side_effect=OSError('child note save interrupted')),self.assertRaises(OSError):self.start()
        self.assertEqual(list(self.root.iterdir()),[self.folder])
        self.assertEqual((self.folder/'timeline.json').read_bytes(),original)
        self.assertEqual(len(self.start()['project']['notes']),1)

    def test_unrecognized_destination_is_never_overwritten(self):
        import uuid
        child_id=uuid.uuid5(uuid.NAMESPACE_URL,'frame:direction:'+self.pid+':new-direction-request').hex
        target=self.root/child_id;target.mkdir();sentinel=target/'timeline.json';sentinel.write_text('{"clips":[],"notes":["foreign"]}')
        before=sentinel.read_bytes()
        with self.assertRaisesRegex(ValueError,'another or incomplete request'):self.start()
        self.assertEqual(sentinel.read_bytes(),before)
        self.assertEqual(list(target.iterdir()),[sentinel])

    def test_stale_request_and_changed_asset_do_not_create_cuts(self):
        with self.assertRaises(timeline.Conflict):self.start(expected_version=-1)
        (self.folder/self.asset['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'footage changed'):self.start()
        self.assertEqual(len([p for p in self.root.iterdir() if p.is_dir()]),1)
    def test_unrelated_project_asset_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'project family'):self.start(asset_project_id='c'*32)
    def test_add_existing_file_is_idempotent_and_never_changes_cut(self):
        file=self.folder/self.asset['path'];doc=timeline.public(timeline.load(self.app,self.pid))
        with patch.object(inputs,'request',return_value=doc):
            result=inputs.add_asset('http://127.0.0.1:12345',{'project_id':self.pid,'source_path':str(file)})
        self.assertTrue(result['reused']);self.assertEqual(result['project']['clips'],doc['clips'])
    def test_invalid_brief_and_request_are_actionable(self):
        for args in [{'brief':None},{'request_id':'bad'},{'brief':'x'*2001}]:
            with self.assertRaises(ValueError):self.start(**args)

if __name__=='__main__':unittest.main()
