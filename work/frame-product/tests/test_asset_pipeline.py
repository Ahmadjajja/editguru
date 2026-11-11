"""Real FFmpeg coverage of catalog -> assembly -> export -> reusable render."""
from pathlib import Path
import subprocess
import tempfile
import threading
import types
import unittest
import quick_timeline as timeline
import quick_asset_library as library
import quick_asset_assembly as assembly
import quick_assets
from editor import probe

class AssetPipelineTests(unittest.TestCase):
    def test_reused_media_style_export_and_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pid='c'*32;project=root/pid;project.mkdir()
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=160x160:r=30:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(project/'input.mp4')],check=True)
            audio=root/'impact.wav'
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1',str(audio)],check=True)
            app=types.SimpleNamespace(WORK=root,MAX_UPLOAD=700*1024*1024,WORKERS=threading.Semaphore(1),project=lambda _: {'name':'Pipeline','current_segments':None})
            doc=timeline.load(app,pid)
            asset=library.register_file(app,audio,kind='sound_effect',tags=['impact'])
            style=library.save_recipe(app,name='Muted',kind='style',recipe={'saturation':0.2,'aspect':'1:1'})
            items=[{'asset_id':asset['id'],'start':0,'end':0.8,'volume':0.25}]
            before=(project/'timeline.json').read_bytes()
            plan=assembly.plan_assembly(app,pid,doc['version'],items,style_id=style['id'])
            self.assertFalse(plan['applied']);self.assertEqual(before,(project/'timeline.json').read_bytes())
            updated=assembly.apply_assembly(app,pid,doc['version'],items,style_id=style['id'])
            self.assertEqual(updated['version'],doc['version']+1)
            eid='f'*32;snapshot=timeline.load(app,pid)
            snapshot.setdefault('exports',[]).append({'id':eid,'status':'working','timeline_version':snapshot['version'],'url':'/media/'+pid+'/versions/'+eid+'/edited.mp4'})
            timeline.write(project/'timeline.json',snapshot)
            timeline.export_worker(app,pid,snapshot,eid)
            saved=timeline.load(app,pid);export=saved['exports'][-1]
            self.assertEqual(export['status'],'done',export)
            self.assertIn('library_asset_id',export,export)
            render=library.get(app,export['library_asset_id'])
            self.assertEqual(render['kind'],'render');self.assertEqual(render['project_id'],pid)
            output=library.resolve(app,render['id']);info=probe(output,False)
            self.assertTrue(info['audio']);self.assertAlmostEqual(info['duration'],1,delta=.06)
            self.assertEqual((info['width'],info['height']),(1080,1080))
            subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
            bundle=quick_assets.bundle(app,pid);Path(bundle).unlink()
            undone=timeline.execute(app,pid,'undo',{'expected_version':saved['version']})
            self.assertEqual(undone['studio'],{})

if __name__=='__main__':unittest.main()
