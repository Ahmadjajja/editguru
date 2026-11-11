import base64
from email.message import Message
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch,MagicMock
import quick_posters as posters
import quick_widget as widget
import quick_runtime as runtime

PID='a'*32;EID='b'*32
class PosterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.folder=self.root/PID;self.folder.mkdir();(self.folder/'input.mp4').write_bytes(b'fixture')
        self.app=types.SimpleNamespace(WORK=self.root);self.doc={'project_id':PID,'source_duration':8,'clips':[{'id':'clip','start':0,'end':8}],'exports':[{'id':EID,'status':'done','clips':[{'id':'clip','start':0,'end':2}],'duration':2}]}
        mock=patch.object(posters.timeline,'load',return_value=self.doc);mock.start();self.addCleanup(mock.stop)
        self.jpeg=b'\xff\xd8small-jpeg\xff\xd9'
    def test_small_cache_uses_exact_source_without_changing_it(self):
        before=(self.folder/'input.mp4').read_bytes()
        with patch.object(posters.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=self.jpeg)) as run:
            self.assertEqual(posters.poster(self.app,PID),self.jpeg);self.assertEqual(posters.poster(self.app,PID),self.jpeg);run.assert_called_once();self.assertIn(str(self.folder/'input.mp4'),run.call_args.args[0]);self.assertEqual(run.call_args.kwargs['timeout'],15)
        self.assertEqual((self.folder/'input.mp4').read_bytes(),before)
    def test_export_selection_and_cache_identity(self):
        output=self.folder/'versions'/EID/'edited.mp4';output.parent.mkdir(parents=True);output.write_bytes(b'export')
        with patch.object(posters.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=self.jpeg)) as run:
            posters.poster(self.app,PID,EID);self.assertIn(str(output),run.call_args.args[0]);posters.poster(self.app,PID);self.assertEqual(run.call_count,2)
        with self.assertRaises(ValueError):posters.poster(self.app,PID,'c'*32)
        self.doc['exports'][0]['section_id']='section'
        with self.assertRaisesRegex(ValueError,'full-video'):posters.poster(self.app,PID,EID)
    def test_bad_ids_and_oversized_or_failed_images_rejected(self):
        for pid in ['../escape','invalid']:
            with self.assertRaises(ValueError):posters.poster(self.app,pid)
        for result in [types.SimpleNamespace(returncode=1,stdout=b''),types.SimpleNamespace(returncode=0,stdout=b'\xff\xd8'+b'x'*posters.MAX_POSTER)]:
            with patch.object(posters.subprocess,'run',return_value=result),self.assertRaises(ValueError):posters.poster(self.app,PID)
    def test_tool_is_read_only_app_only_and_bounded(self):
        tool=widget.decorate({'name':'read_video_poster','annotations':{}});self.assertEqual(tool['_meta']['ui']['visibility'],['app']);self.assertTrue(tool['annotations']['readOnlyHint'])
        headers=Message();headers['Content-Type']='image/jpeg';response=MagicMock(headers=headers);response.read.return_value=self.jpeg;opened=MagicMock();opened.__enter__.return_value=response
        with patch.object(widget.urllib.request,'urlopen',return_value=opened) as fetch:
            value=widget.call('read_video_poster',{'project_id':PID,'export_id':EID},'http://127.0.0.1:12345',MagicMock())
        self.assertEqual(value['export_id'],EID);self.assertEqual(base64.b64decode(value['_image_base64']),self.jpeg);response.read.assert_called_once_with(posters.MAX_POSTER+1);self.assertIn('?export_id='+EID,fetch.call_args.args[0])
    def test_old_connector_cannot_serve_new_tool_ui(self):
        (self.root/'active-runtime.json').write_text(json.dumps({'schema_version':1,'status':'ready','protocol_version':2,'manifest_sha256':'c'*64,'url':'http://127.0.0.1:12345'}))
        with patch.object(runtime,'installation',return_value=self.root),patch.object(runtime,'PROTOCOL',1),self.assertRaisesRegex(RuntimeError,'connector needs an update'):
            runtime.active_target('http://127.0.0.1:12345')
        self.assertEqual(runtime.PROTOCOL,2)

if __name__=='__main__':unittest.main()
