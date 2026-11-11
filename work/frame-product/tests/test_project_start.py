import io,json,tempfile,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
import quick_start as start
import quick_timeline as q
import quick_revision as revision

class StartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.session='a'*32;self.raw=b'generated-video-fixture'
        self.app=types.SimpleNamespace(WORK=self.root,probe=lambda _: {'duration':2,'audio':True})
        self.app.project=lambda pid:json.loads((self.root/pid/'project.json').read_text())
        self.mock=patch.object(q,'probe',return_value={'duration':2,'audio':True});self.mock.start();self.addCleanup(self.mock.stop)
    def handler(self,raw=None,**headers):
        raw=self.raw if raw is None else raw
        h=types.SimpleNamespace(headers={'Origin':'http://127.0.0.1:12345','Content-Length':str(len(raw)),'X-Filename':'My%20new%20video.mov',**headers},server=types.SimpleNamespace(server_port=12345),connection=types.SimpleNamespace(settimeout=lambda _:None),rfile=io.BytesIO(raw),close_connection=False)
        def respond(status,result):h.result=(status,result)
        h.json=respond;return h
    def upload(self,h=None,session=None):
        h=h or self.handler();start.upload(h,self.app,session or self.session);return h.result
    def test_complete_project_is_ready_to_edit_and_scoped_to_session(self):
        status,result=self.upload();self.assertEqual(status,200);pid=result['project_id'];d=q.load(self.app,pid)
        self.assertEqual((self.root/pid/'input.mp4').read_bytes(),self.raw)
        self.assertEqual(d['work_project']['upload_session_id'],self.session);self.assertEqual(d['name'],'My new video.mov');self.assertEqual(d['clips'][0]['end'],2)
        self.assertFalse(list((self.root/'.incoming').iterdir()))
    def test_lost_confirmation_retry_preserves_subsequent_edits(self):
        _,result=self.upload();pid=result['project_id'];d=q.load(self.app,pid);revision.act(self.app,pid,{'action':'add_general_note','expected_version':d['version'],'instruction':'Keep the new opening'})
        before=(self.root/pid/'timeline.json').read_bytes();_,replay=self.upload()
        self.assertEqual(replay['project_id'],pid);self.assertEqual((self.root/pid/'timeline.json').read_bytes(),before)
        self.assertEqual(len([p for p in self.root.iterdir() if len(p.name)==32]),1)
    def test_different_payload_cannot_overwrite_a_completed_upload(self):
        _,result=self.upload();self.assertEqual(self.upload(self.handler(b'different'))[0],400)
        self.assertEqual((self.root/result['project_id']/'input.mp4').read_bytes(),self.raw)
    def test_distinct_upload_actions_make_distinct_projects(self):
        _,a=self.upload();_,b=self.upload(session='b'*32);self.assertNotEqual(a['project_id'],b['project_id'])
    def test_interrupted_and_invalid_video_never_publish_partial_projects(self):
        h=self.handler(**{'Content-Length':'1000'});self.assertEqual(self.upload(h)[0],400)
        with patch.object(self.app,'probe',side_effect=ValueError('Not a video')):self.assertEqual(self.upload()[0],400)
        self.assertFalse([p for p in self.root.iterdir() if len(p.name)==32]);self.assertFalse(list((self.root/'.incoming').iterdir()))
    def test_failed_initialization_does_not_publish_and_can_retry(self):
        with patch.object(q,'load',side_effect=OSError('disk unavailable')):self.assertEqual(self.upload()[0],400)
        self.assertFalse([p for p in self.root.iterdir() if len(p.name)==32]);self.assertEqual(self.upload()[0],200)
    def test_origin_limits_and_invalid_session_rejected(self):
        for origin in ['https://example.com',None]:self.assertEqual(self.upload(self.handler(Origin=origin))[0],403)
        for size in ['0',str(start.MAX_BYTES+1),'bad']:self.assertEqual(self.upload(self.handler(**{'Content-Length':size}))[0],400)
        self.assertEqual(self.upload(session='../escape')[0],400)
    def test_concurrent_retries_publish_once(self):
        results=[];workers=[threading.Thread(target=lambda:results.append(self.upload())) for _ in range(2)]
        for t in workers:t.start()
        for t in workers:t.join()
        self.assertEqual([r[0] for r in results],[200,200]);self.assertEqual(results[0][1]['project_id'],results[1][1]['project_id'])
