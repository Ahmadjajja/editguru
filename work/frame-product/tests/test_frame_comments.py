import copy
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from PIL import Image
import quick_timeline as timeline
import quick_annotations as q
import quick_mcp

class FrameComments(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.pid='a'*32;root=Path(temp.name);(root/self.pid).mkdir()
        self.app=types.SimpleNamespace(WORK=root,project=lambda _: {'name':'Fixture','current_segments':None})
        mock=patch.object(timeline,'probe',return_value={'duration':14,'audio':True});mock.start();self.addCleanup(mock.stop)
        self.doc=timeline.load(self.app,self.pid)
        self.body={'expected_version':1,'clip_id':self.doc['clips'][0]['id'],'source_time':2,'region':{'x':.2,'y':.1,'width':.3,'height':.2},'note':'Make this title larger.'}
        image=Image.new('RGB',(160,90),'white');out=io.BytesIO();image.save(out,format='PNG')
        mock=patch.object(q.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=out.getvalue()));mock.start();self.addCleanup(mock.stop)
    def test_saved_comment_does_not_change_timeline(self):
        before=copy.deepcopy(self.doc);comment=q.create(self.app,self.pid,self.body)
        self.assertEqual(timeline.load(self.app,self.pid),before)
        self.assertFalse(comment['video_changed']);self.assertEqual(comment['status'],'comment_saved')
        self.assertEqual(q.read(self.app,self.pid)[0]['region'],self.body['region'])
        image=Image.open(self.app.WORK/self.pid/'frame-comments'/(comment['id']+'.png'))
        self.assertEqual(image.getpixel((32,9)),(216,121,84))
    def test_stale_anchor_and_bad_region_rejected(self):
        for change in [{'expected_version':0},{'source_time':14},{'region':{'x':.9,'y':0,'width':.2,'height':.2}},{'note':' '},{'region':{'x':0,'y':0,'width':float('nan'),'height':.2}}]:
            with self.subTest(change=change),self.assertRaises(ValueError):q.create(self.app,self.pid,dict(self.body,**change))
        self.assertEqual(q.read(self.app,self.pid),[])
    def test_comment_tools_are_read_only_and_versionless(self):
        for tool in quick_mcp.tools():
            if tool['name'] in ('get_frame_comments','get_frame_comment'):
                self.assertTrue(tool['annotations']['readOnlyHint'])
                self.assertNotIn('expected_version',tool['inputSchema']['properties'])

if __name__=='__main__':unittest.main()
