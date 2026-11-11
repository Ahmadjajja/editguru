"""Saved reference associations and visual requests are versioned together."""
import base64,io,unittest
import quick_revision
from PIL import Image
import test_quick_timeline as fixtures
import quick_sections as sections
import quick_timeline as timeline

class ReferenceTests(unittest.TestCase):
    setUp=fixtures.TimelineTests.setUp
    def test_reference_moment_survives_reopen_and_unlink(self):
        rid='b'*32;(self.app.WORK/rid).mkdir();(self.app.WORK/rid/'input.mp4').write_bytes(b'fixture video')
        source=timeline.load(self.app,rid)
        self.doc=sections.act(self.app,self.pid,{'action':'add_video_reference','expected_version':self.doc['version'],'reference_project_id':rid})
        self.doc=quick_revision.act(self.app,self.pid,{'action':'add_pin','expected_version':self.doc['version'],'time':1,'clip_id':self.doc['clips'][0]['id'],'start':1,'end':4})
        out=io.BytesIO();Image.new('RGB',(32,20),'red').save(out,format='JPEG')
        args={'action':'add_reference_moment','expected_version':self.doc['version'],'section_id':self.doc['pins'][0]['id'],'reference_project_id':rid,'reference_time':2.5,'instruction':'Use this title spacing','name':'reference.jpg','image_base64':base64.b64encode(out.getvalue()).decode()}
        version=self.doc['version'];self.doc=sections.act(self.app,self.pid,args)
        reopened=timeline.load(self.app,self.pid)
        self.assertEqual(reopened['version'],version+1)
        self.assertEqual(reopened['notes'][-1]['video_reference']['time'],2.5)
        self.assertEqual(reopened['pins'][0]['references'][0]['video_reference']['project_id'],rid)
        asset=self.app.WORK/self.pid/reopened['assets'][0]['path'];self.assertTrue(asset.exists())
        with self.assertRaises(timeline.Conflict):sections.act(self.app,self.pid,args)
        self.assertEqual(len(timeline.load(self.app,self.pid)['notes']),1)
        sections.act(self.app,self.pid,{'action':'remove_video_reference','expected_version':self.doc['version'],'reference_project_id':rid})
        self.assertTrue(asset.exists());self.assertEqual(timeline.load(self.app,self.pid)['notes'][0]['instruction'],'Use this title spacing')
        self.assertEqual(timeline.load(self.app,rid)['clips'],source['clips'])
    def test_bad_reference_does_not_save_partial_request(self):
        rid='b'*32;(self.app.WORK/rid).mkdir();(self.app.WORK/rid/'input.mp4').write_bytes(b'fixture video')
        self.doc=sections.act(self.app,self.pid,{'action':'add_video_reference','expected_version':self.doc['version'],'reference_project_id':rid})
        self.doc=quick_revision.act(self.app,self.pid,{'action':'add_pin','expected_version':self.doc['version'],'time':1,'clip_id':self.doc['clips'][0]['id'],'start':1,'end':4})
        for t in [-1,14,float('nan')]:
            with self.assertRaises(ValueError):sections.act(self.app,self.pid,{'action':'add_reference_moment','expected_version':self.doc['version'],'section_id':self.doc['pins'][0]['id'],'reference_project_id':rid,'reference_time':t,'instruction':'Title spacing','image_base64':'bad'})
        self.assertEqual(timeline.load(self.app,self.pid)['version'],self.doc['version'])
        self.assertEqual(timeline.load(self.app,self.pid)['notes'],[])
