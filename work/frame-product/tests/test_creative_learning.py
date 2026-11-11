import importlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_timeline as q
import quick_learning as learning
import quick_mcp

class CreativeLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.pid='a'*32;self.other='b'*32;self.eid='c'*32
        self.app=types.SimpleNamespace(WORK=self.root,project=lambda _: {'name':'Test','current_segments':None})
        p=patch.object(q,'probe',return_value={'duration':4,'audio':True});p.start();self.addCleanup(p.stop)
        for pid in (self.pid,self.other):
            folder=self.root/pid;folder.mkdir();(folder/'input.mp4').write_bytes(b'original source')
            doc=q.load(self.app,pid);doc['exports']=[{'id':self.eid,'timeline_version':1,'status':'done','duration':4,'url':'/media/'+pid+'/versions/'+self.eid+'/edited.mp4'}]
            q.write(folder/'timeline.json',doc)
            out=folder/'versions'/self.eid;out.mkdir(parents=True);(out/'edited.mp4').write_bytes(b'actual rendered output')
        self.args=dict(request_id='rating-0001',export_id=self.eid,export_version=1,verdict='reject',reason='The dialogue cut is too abrupt. Keep a little breathing room.',category='pacing',scope='creator',reviewed=True)
    def record(self,**kwargs):return learning.record(self.app,self.pid,{**self.args,**kwargs})
    def memory(self,pid=None,query=''):
        return learning.memory(self.app,q.load(self.app,pid or self.pid),query)
    def test_no_learning_from_render_or_execution_acceptance(self):
        doc=q.load(self.app,self.pid);doc['accepted_edits']=[{'status':'accepted'}];q.write(self.root/self.pid/'timeline.json',doc)
        self.assertEqual(self.memory()['examples'],[])
    def test_persistent_cross_project_retrieval_with_exact_evidence_and_unchanged_timeline(self):
        before=(self.root/self.pid/'timeline.json').read_bytes();r=self.record()['feedback']
        self.assertEqual(r['evidence']['after']['sha256'],learning.digest(self.root/self.pid/'versions'/self.eid/'edited.mp4'))
        self.assertNotEqual(r['evidence']['after']['sha256'],r['evidence']['before']['sha256'])
        importlib.reload(learning)
        self.assertEqual(self.memory(self.other)['examples'][0]['reason'],self.args['reason'])
        self.assertEqual((self.root/self.pid/'timeline.json').read_bytes(),before)
        self.assertEqual(q.execute(self.app,self.other,'get_project',{})['creative_memory']['total_examples'],1)
    def test_project_scope_and_store_isolation(self):
        self.record(scope='project');self.assertEqual(self.memory(self.other)['examples'],[])
        with tempfile.TemporaryDirectory() as tmp:
            other=types.SimpleNamespace(WORK=Path(tmp));self.assertEqual(learning.memory(other,{'project_id':self.pid})['examples'],[])
    def test_idempotency_conflict_and_updated_rating(self):
        self.record();self.assertTrue(self.record()['replayed']);self.assertEqual(self.memory()['total_examples'],1)
        with self.assertRaises(q.Conflict):self.record(verdict='accept')
        self.record(request_id='rating-0002',verdict='accept',reason='This pacing is right after review.')
        self.assertEqual(self.memory()['total_examples'],1);self.assertEqual(self.memory()['examples'][0]['verdict'],'accept')
        self.assertFalse(self.record()['active']) # Retried old request must not resurrect old judgment.
    def test_invalid_output_review_and_stale_export_rejected(self):
        for args in [dict(reviewed=False),dict(export_version=2),dict(export_version=True),dict(export_id='../escape'),dict(reason=''),dict(verdict='done')]:
            with self.subTest(args=args),self.assertRaises(ValueError):self.record(**args)
        doc=q.load(self.app,self.pid);doc['exports'][0]['status']='working';q.write(self.root/self.pid/'timeline.json',doc)
        with self.assertRaises(ValueError):self.record()
        self.assertEqual(self.memory()['total_examples'],0)
    def test_review_old_export_is_independent_of_current_timeline(self):
        doc=q.load(self.app,self.pid);doc['version']=5;q.write(self.root/self.pid/'timeline.json',doc)
        self.record();self.assertEqual(self.memory()['examples'][0]['export_version'],1)
    def test_forget_removes_guidance_and_requires_owning_project(self):
        self.record()
        with self.assertRaises(ValueError):learning.execute(self.app,self.other,'forget_edit_feedback',{'feedback_id':'rating-0001'})
        learning.execute(self.app,self.pid,'forget_edit_feedback',{'feedback_id':'rating-0001'})
        self.assertEqual(self.memory(self.other)['examples'],[])
    def test_query_prioritizes_relevant_example(self):
        self.record();self.record(request_id='rating-0002',export_id=self.eid,reason='Use brighter captions.',category='captions')
        # Independent output so the earlier judgment remains active.
        doc=q.load(self.app,self.pid);doc['exports'].append({**doc['exports'][0],'id':'d'*32});q.write(self.root/self.pid/'timeline.json',doc)
        folder=self.root/self.pid/'versions'/('d'*32);folder.mkdir();(folder/'edited.mp4').write_bytes(b'new media')
        self.record(request_id='rating-0003',export_id='d'*32,reason='Keep the dialogue pacing gentle.',category='pacing')
        self.assertEqual(self.memory(query='captions')['examples'][0]['category'],'captions')
    def test_internal_planner_receives_relevant_feedback(self):
        import quick_revision
        self.record()
        doc=q.load(self.app,self.pid);clip=doc['clips'][0]
        operation={'operation':'position_clip','start':0,'end':4,'x':.1,'y':0,'message':'Move right'}
        response=types.SimpleNamespace(returncode=0,stdout=json.dumps({'structured_output':operation}),stderr='')
        with patch.object(quick_revision.subprocess,'run',return_value=response) as run:
            quick_revision.interpret(doc,{'clip_id':clip['id'],'start':0,'end':4,'instruction':'Adjust the pacing'},self.app)
        context=json.loads(run.call_args.args[0][-1])
        self.assertEqual(context['creative_memory']['examples'][0]['reason'],self.args['reason'])
        self.assertIn('current instructions override',run.call_args.args[0][-2])

    def test_mcp_tools_require_exact_user_judgment_without_current_version(self):
        tools={t['name']:t for t in quick_mcp.tools()}
        self.assertTrue(tools['get_creative_memory']['annotations']['readOnlyHint'])
        self.assertFalse(tools['record_edit_feedback']['annotations']['readOnlyHint'])
        self.assertIn('reviewed',tools['record_edit_feedback']['inputSchema']['required'])
        self.assertNotIn('expected_version',tools['record_edit_feedback']['inputSchema']['required'])

if __name__=='__main__':unittest.main()
