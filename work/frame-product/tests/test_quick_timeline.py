"""Behavior tests for concurrent edits, durable undo, and immutable export snapshots."""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_timeline as q
import quick_mcp

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pid='a'*32;root=Path(self.temp.name);(root/self.pid).mkdir()
        self.app=types.SimpleNamespace(WORK=root,project=lambda _: {'name':'Fixture','current_segments':None})
        self.probe=patch.object(q,'probe',return_value={'duration':14,'audio':True});self.probe.start();self.addCleanup(self.probe.stop)
        self.doc=q.execute(self.app,self.pid,'get_project',{})
    def cmd(self,op,**args):
        self.doc=q.execute(self.app,self.pid,op,dict(expected_version=self.doc['version'],**args));return self.doc
    def test_split_trim_delete_undo_redo(self):
        cid=self.doc['clips'][0]['id'];self.cmd('split_clip',clip_id=cid,source_time=3)
        self.assertEqual(len(self.doc['clips']),2)
        self.cmd('delete_segment',clip_id=cid);self.assertEqual(self.doc['duration'],11)
        self.cmd('undo');self.assertEqual(self.doc['duration'],14)
        self.cmd('redo');self.assertEqual(self.doc['duration'],11)
        self.cmd('trim_clip',clip_id=self.doc['clips'][0]['id'],start=4,end=13);self.assertEqual(self.doc['duration'],9)
    def test_stale_mutation_preserves_timeline(self):
        self.cmd('split_clip',clip_id=self.doc['clips'][0]['id'],source_time=3)
        with self.assertRaises(q.Conflict):q.execute(self.app,self.pid,'undo',{'expected_version':1})
        self.assertEqual(q.load(self.app,self.pid)['version'],2)
    def test_invalid_edits_do_not_change_saved_version(self):
        for start,end in [(-1,2),(2,1),(0,15),(float('nan'),5),(True,5)]:
            with self.assertRaises(ValueError):self.cmd('trim_clip',clip_id=self.doc['clips'][0]['id'],start=start,end=end)
        self.assertEqual(q.load(self.app,self.pid)['version'],1)
    def test_reorder_persists(self):
        self.cmd('split_clip',clip_id=self.doc['clips'][0]['id'],source_time=3)
        self.cmd('move_segment',clip_id=self.doc['clips'][0]['id'],position=1)
        self.assertEqual(q.load(self.app,self.pid)['clips'][0]['start'],3)
    def test_edit_after_undo_clears_redo(self):
        cid=self.doc['clips'][0]['id'];self.cmd('split_clip',clip_id=cid,source_time=3);self.cmd('undo')
        self.cmd('trim_clip',clip_id=cid,start=1,end=14);self.assertFalse(self.doc['can_redo'])
    def test_empty_timeline_restores(self):
        self.cmd('delete_segment',clip_id=self.doc['clips'][0]['id']);self.assertEqual(self.doc['duration'],0)
        with self.assertRaises(ValueError):self.cmd('export_video')
        self.cmd('undo');self.assertEqual(self.doc['duration'],14)
    def test_cut_opening_across_splits(self):
        self.cmd('split_clip',clip_id=self.doc['clips'][0]['id'],source_time=2)
        self.cmd('tighten_pacing',cut_first_seconds=3,remove_pauses=False)
        self.assertEqual(self.doc['clips'][0]['start'],3);self.assertEqual(self.doc['duration'],11)
    def test_silence_measurement_and_undo(self):
        with patch.object(q,'detect_silence',return_value=[[5,6.5],[9,10.5]]):self.cmd('tighten_pacing',cut_first_seconds=3)
        self.assertEqual(len(self.doc['clips']),3);self.assertLess(self.doc['duration'],9)
        self.cmd('undo');self.assertEqual(self.doc['duration'],14)
    def test_frame_quantization_is_persisted(self):
        self.cmd('trim_clip',clip_id=self.doc['clips'][0]['id'],start=.04,end=1.04)
        c=self.doc['clips'][0];self.assertAlmostEqual(c['start'],1/30);self.assertAlmostEqual(c['end'],31/30)
    def test_export_snapshot_is_immutable(self):
        with patch.object(q.threading,'Thread') as thread:
            self.cmd('export_video');snapshot=copy.deepcopy(thread.call_args.kwargs['args'][2])
            self.cmd('delete_segment',clip_id=self.doc['clips'][0]['id'])
        self.assertEqual(snapshot['clips'][0]['end'],14);self.assertEqual(self.doc['clips'],[])
    def test_recovery_marks_interrupted_export_failed(self):
        with patch.object(q.threading,'Thread'):self.cmd('export_video')
        q.recover(self.app);self.assertEqual(q.load(self.app,self.pid)['exports'][0]['status'],'failed')
    def test_mcp_tool_discovery(self):
        r=quick_mcp.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        names={t['name'] for t in r['result']['tools']}
        self.assertTrue(set(q.OPERATIONS)<=names)
    def test_position_survives_split_pacing_and_undo(self):
        cid=self.doc['clips'][0]['id'];self.cmd('position_clip',clip_id=cid,x=.1,y=-.05)
        self.cmd('split_clip',clip_id=cid,source_time=3)
        self.assertTrue(all(c['x']==.1 and c['y']==-.05 for c in self.doc['clips']))
        self.cmd('tighten_pacing',cut_first_seconds=1,remove_pauses=False)
        self.assertTrue(all(c['x']==.1 for c in self.doc['clips']))
        self.cmd('undo');self.cmd('undo');self.cmd('undo')
        self.assertNotIn('x',self.doc['clips'][0])
        self.cmd('redo');self.assertEqual(self.doc['clips'][0]['x'],.1)
    def test_invalid_position_does_not_save(self):
        before=copy.deepcopy(self.doc)
        for x in [.51,float('nan'),True,'right']:
            with self.subTest(x=x),self.assertRaises(ValueError):self.cmd('position_clip',clip_id=self.doc['clips'][0]['id'],x=x,y=0)
            self.assertEqual({k:v for k,v in q.public(q.load(self.app,self.pid)).items() if k not in ('activity','creative_memory')},{k:v for k,v in before.items() if k not in ('activity','creative_memory')})
    def test_mcp_notifications_do_not_respond(self):
        self.assertIsNone(quick_mcp.dispatch({'jsonrpc':'2.0','method':'notifications/initialized'}))


class RealExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        if not shutil.which('ffmpeg'):raise unittest.SkipTest('FFmpeg required')
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        from editor import run
        cls.source=cls.root/'input.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=5',
             '-f','lavfi','-i','sine=sample_rate=48000:duration=5','-c:v','libx264','-preset','ultrafast',
             '-pix_fmt','yuv420p','-c:a','aac',str(cls.source)])
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_many_tiny_cuts_have_no_cumulative_av_padding(self):
        from editor import render_timeline,run
        doc={'source_duration':5,'clips':[q.clip(i/10,i/10+.04) for i in range(48)]}
        q.validate(doc);keep=[(c['start'],c['end']) for c in doc['clips']]
        folder=self.root/'tiny';folder.mkdir()
        render_timeline(self.source,folder,keep,True,lambda _:None)
        info=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(folder/'edited.mp4')]))
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        audio=next(s for s in info['streams'] if s['codec_type']=='audio')
        self.assertEqual(int(video['nb_frames']),48)
        self.assertAlmostEqual(float(video['duration']),1.6,places=5)
        self.assertAlmostEqual(float(audio['duration']),1.6,places=5)
        self.assertEqual(float(video['start_time']),0)
        self.assertEqual(float(audio['start_time']),0)
    def test_positioned_video_has_black_margin_without_audio_retiming(self):
        from editor import render_timeline,run
        import numpy as np
        folder=self.root/'position';folder.mkdir()
        self.assertAlmostEqual(render_timeline(self.source,folder,[(0,1),(1,2)],True,lambda _:None,positions=[(.1,0),(-.1,0)]),2,places=5)
        def pixels(at):
            import subprocess
            raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',str(folder/'edited.mp4'),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
            return np.frombuffer(raw,dtype=np.uint8).reshape(90,160,3)
        self.assertLess(pixels(.5)[:,:12].max(),12)
        self.assertLess(pixels(1.5)[:,-12:].max(),12)
        info=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(folder/'edited.mp4')]))
        for stream in info['streams']:
            self.assertAlmostEqual(float(stream['duration']),2,places=5)
            self.assertEqual(float(stream['start_time']),0)
    def test_short_audio_fills_every_retained_video_clip(self):
        from editor import render_timeline,run
        import subprocess
        import numpy as np
        source=self.root/'short-audio.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=4',
             '-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=1',
             '-c:v','libx264','-c:a','aac',str(source)])
        for name,keep in [('short-tail',[(0,1),(2,4)]),('empty-head',[(2,4),(0,1)])]:
            with self.subTest(order=name):
                folder=self.root/name;folder.mkdir()
                render_timeline(source,folder,keep,True,lambda _:None)
                info=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(folder/'edited.mp4')]))
                for stream in info['streams']:
                    self.assertAlmostEqual(float(stream['duration']),3,places=5)
                    self.assertEqual(float(stream['start_time']),0)
                raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(folder/'edited.mp4'),'-vn','-f','f32le','-ac','1','-ar','48000','-'])
                samples=np.frombuffer(raw,dtype=np.float32)
                silent=samples[int((1.5 if name=='short-tail' else .5)*48000):int((1.8 if name=='short-tail' else .8)*48000)]
                audible=samples[int((.2 if name=='short-tail' else 2.2)*48000):int((.5 if name=='short-tail' else 2.5)*48000)]
                self.assertLess(float(np.sqrt(np.mean(silent**2))),.005)
                self.assertGreater(float(np.sqrt(np.mean(audible**2))),.03)

    def test_delayed_source_audio_keeps_its_initial_silence(self):
        from editor import render_timeline,run
        import subprocess
        import numpy as np
        source=self.root/'delayed-audio.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=2',
             '-itsoffset','0.5','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=1',
             '-c:v','libx264','-c:a','aac',str(source)])
        folder=self.root/'delayed';folder.mkdir()
        render_timeline(source,folder,[(0,2)],True,lambda _:None)
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(folder/'edited.mp4'),'-vn','-f','f32le','-ac','1','-ar','48000','-'])
        samples=np.frombuffer(raw,dtype=np.float32)
        self.assertLess(float(np.sqrt(np.mean(samples[int(.1*48000):int(.3*48000)]**2))),.005)
        self.assertGreater(float(np.sqrt(np.mean(samples[int(.7*48000):int(.9*48000)]**2))),.03)

    def test_non_square_pixels_keep_display_shape_in_both_export_paths(self):
        from editor import render,render_timeline,run,probe
        from PIL import Image
        source=self.root/'wide-pixels.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30:duration=1',
             '-vf','setsar=2','-c:v','libx264',str(source)])
        for name,method in [('wide-sections',render),('wide-timeline',render_timeline)]:
            with self.subTest(path=name):
                folder=self.root/name;folder.mkdir()
                method(source,folder,[(0,1)],False,lambda _:None)
                info=probe(folder/'edited.mp4')
                self.assertEqual((info['width'],info['height']),(320,90))
                metadata=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(folder/'edited.mp4')]))
                self.assertEqual(metadata['streams'][0]['sample_aspect_ratio'],'1:1')
                run(['ffmpeg','-v','error','-i',str(folder/'edited.mp4'),'-frames:v','1',str(folder/'display.png')])
                with Image.open(folder/'display.png') as image:self.assertEqual(image.size,(320,90))

    def test_reordered_video_without_audio(self):
        from editor import render_timeline,probe
        folder=self.root/'silent';folder.mkdir()
        measured=render_timeline(self.source,folder,[(3,4),(0,1)],False,lambda _:None)
        self.assertAlmostEqual(measured,2,places=5)
        self.assertFalse(probe(folder/'edited.mp4')['audio'])

if __name__=='__main__':unittest.main()
