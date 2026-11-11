"""Video history survives reload, branching and failed/stale writes."""
import copy
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_timeline as q
import quick_sections as sections


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.pid='a'*32;(self.root/self.pid).mkdir()
        self.app=types.SimpleNamespace(WORK=self.root,project=lambda _: {'name':'Video','current_segments':None})
        p=patch.object(q,'probe',return_value={'duration':10,'audio':True});p.start();self.addCleanup(p.stop)
        self.doc=q.load(self.app,self.pid)

    def edit(self,op,**args):
        self.doc=q.execute(self.app,self.pid,op,dict(expected_version=self.doc['version'],**args))

    def test_each_video_edit_and_branch_survives_reload_without_export(self):
        cid=self.doc['clips'][0]['id']
        self.edit('trim_clip',clip_id=cid,start=1,end=10)
        first=copy.deepcopy(self.doc['checkpoints'][-1])
        self.edit('position_clip',clip_id=cid,x=.2,y=0)
        self.edit('undo')
        saved=q.load(self.app,self.pid)
        self.assertEqual(len(saved['checkpoints']),4)
        self.assertEqual(saved['checkpoints'][1],first)
        restored=sections.act(self.app,self.pid,dict(action='restore_checkpoint',checkpoint_id=first['id'],expected_version=saved['version']))
        self.assertEqual(restored['clips'],first['clips'])
        self.assertEqual(len(restored['checkpoints']),5)
        self.assertEqual(restored['checkpoints'][:4],saved['checkpoints'])
        self.assertEqual(restored['checkpoints'][-1]['parent_id'],first['id'])
        self.assertEqual(q.load(self.app,self.pid)['checkpoints'],restored['checkpoints'])

    def test_metadata_reads_and_failed_edits_do_not_create_revisions(self):
        before=copy.deepcopy(self.doc['checkpoints'])
        for _ in range(3):q.load(self.app,self.pid)
        self.edit('log_activity',message='Reading video')
        with self.assertRaises(q.Conflict):q.execute(self.app,self.pid,'undo',dict(expected_version=-1))
        with self.assertRaises(ValueError):self.edit('trim_clip',clip_id=self.doc['clips'][0]['id'],start=-1,end=10)
        self.assertEqual(q.load(self.app,self.pid)['checkpoints'],before)

    def test_export_completed_after_new_edit_keeps_both_versions(self):
        import threading
        self.app.WORKERS=threading.Semaphore(1)
        with patch.object(q.threading,'Thread') as thread:
            self.edit('export_video')
            snapshot=copy.deepcopy(thread.call_args.kwargs['args'][2])
        export_id=self.doc['exports'][-1]['id']
        self.edit('trim_clip',clip_id=self.doc['clips'][0]['id'],start=2,end=10)
        head=self.doc['current_checkpoint_id']
        with patch.object(q,'render_timeline',return_value=10):q.export_worker(self.app,self.pid,snapshot,export_id)
        saved=q.load(self.app,self.pid)
        self.assertEqual(saved['clips'][0]['start'],2)
        self.assertEqual(saved['current_checkpoint_id'],head)
        exported=next(c for c in saved['checkpoints'] if c['id']==export_id)
        self.assertEqual(exported['clips'][0]['start'],0)
        self.assertEqual(exported['rendered']['proposal_id'],export_id)


if __name__=='__main__':unittest.main()
