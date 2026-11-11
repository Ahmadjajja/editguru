import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_timeline as q
import quick_revision_result as result


class RevisionResultTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.pid='a'*32;self.target='b'*32;self.eid='c'*32;self.nid='d'*32
        for pid in [self.pid,self.target]:(self.root/pid).mkdir()
        self.app=types.SimpleNamespace(WORK=self.root,project=lambda _: {'name':'Test','current_segments':None})
        p=patch.object(q,'probe',return_value={'duration':4,'audio':True});p.start();self.addCleanup(p.stop)
        p=patch.object(result,'probe',return_value={'duration':4,'audio':True});self.probe=p.start();self.addCleanup(p.stop)
        doc=q.load(self.app,self.pid);doc['notes']=[{'id':self.nid,'status':'queued','included':True,'instruction':'Make animation'}];q.write(self.root/self.pid/'timeline.json',doc)
        target=q.load(self.app,self.target);target['exports']=[{'id':self.eid,'status':'done','timeline_version':1}];q.write(self.root/self.target/'timeline.json',target)
        out=self.root/self.target/'versions'/self.eid;out.mkdir(parents=True);(out/'edited.mp4').write_bytes(b'verified fixture bytes')
        self.args=dict(expected_version=1,note_id=self.nid,result_project_id=self.target,result_version=1,export_id=self.eid,message='Animated full-canvas result')

    def test_record_links_exact_result_preserves_timeline_and_is_idempotent(self):
        before=q.load(self.app,self.pid)['clips'];d=result.record(self.app,self.pid,self.args)
        self.assertEqual(d['clips'],before);self.assertEqual(d['version'],2);self.assertEqual(d['notes'][0]['status'],'applied')
        self.assertEqual(d['notes'][0]['result']['project_id'],self.target);self.assertEqual(len(d['notes'][0]['result']['sha256']),64)
        self.assertEqual(result.record(self.app,self.pid,self.args)['version'],2)

    def test_stale_source_or_result_is_rejected_before_note_changes(self):
        for key in ['expected_version','result_version']:
            with self.subTest(key=key),self.assertRaises(q.Conflict):result.record(self.app,self.pid,dict(self.args,**{key:0}))
        self.assertEqual(q.load(self.app,self.pid)['notes'][0]['status'],'queued')

    def test_failed_export_or_missing_file_cannot_mark_applied(self):
        path=self.root/self.target/'timeline.json';doc=json.loads(path.read_text());doc['exports'][0]['status']='failed';q.write(path,doc)
        with self.assertRaises(ValueError):result.record(self.app,self.pid,self.args)
        doc['exports'][0]['status']='done';q.write(path,doc);(self.root/self.target/'versions'/self.eid/'edited.mp4').unlink()
        with self.assertRaises(ValueError):result.record(self.app,self.pid,self.args)
        self.assertEqual(q.load(self.app,self.pid)['notes'][0]['status'],'queued')

    def test_bad_duration_or_missing_audio_cannot_mark_applied(self):
        for measured in [dict(duration=3,audio=True),dict(duration=4,audio=False)]:
            self.probe.return_value=measured
            with self.assertRaises(ValueError):result.record(self.app,self.pid,self.args)
        self.assertEqual(q.load(self.app,self.pid)['notes'][0]['status'],'queued')

    def test_final_result_imports_exact_export_as_editable_source_once(self):
        before=q.load(self.app,self.pid)
        d=result.record(self.app,self.pid,self.args)
        child=q.load(self.app,d['next_revision']['project_id'])
        self.assertEqual((self.root/child['project_id']/'input.mp4').read_bytes(),b'verified fixture bytes')
        self.assertIsNone(child['rendered'])
        self.assertEqual([(c['start'],c['end']) for c in child['clips']],[(0,4)])
        self.assertEqual(child['notes'],[])
        self.assertEqual(child['pins'],[])
        self.assertEqual(child['revision_parent']['project_id'],self.pid)
        self.assertEqual(d['clips'],before['clips'])
        child['notes']=[{'id':'new','instruction':'Another revision','status':'queued'}]
        q.write(self.root/child['project_id']/'timeline.json',child)
        again=result.record(self.app,self.pid,self.args)
        self.assertEqual(again['next_revision'],d['next_revision'])
        self.assertEqual(q.load(self.app,child['project_id'])['notes'][0]['instruction'],'Another revision')
        self.assertEqual(len(list(self.root.glob('*/input.mp4'))),1)

    def test_waits_for_batch_and_does_not_reopen_after_new_manual_edit(self):
        doc=q.load(self.app,self.pid)
        doc['notes'].append({'id':'e'*32,'status':'queued','included':True,'instruction':'Second change'})
        q.write(self.root/self.pid/'timeline.json',doc)
        first=result.record(self.app,self.pid,self.args)
        self.assertNotIn('next_revision',first)
        done=result.record(self.app,self.pid,dict(self.args,note_id='e'*32,expected_version=2))
        self.assertIn('next_revision',done)
        import quick_continuation
        doc=q.load(self.app,self.pid);doc['version']+=1
        doc['accepted_edits'].append({'operation':'trim_clip'})
        q.write(self.root/self.pid/'timeline.json',doc)
        self.assertFalse(quick_continuation.eligible(doc))
        self.assertEqual(quick_continuation.resolve(doc,lambda _:self.fail('must not follow stale result'))['project_id'],self.pid)

    def test_tampered_export_cannot_be_reimported(self):
        result.record(self.app,self.pid,self.args)
        (self.root/self.target/'versions'/self.eid/'edited.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):result.record(self.app,self.pid,self.args)


if __name__=='__main__':unittest.main()
