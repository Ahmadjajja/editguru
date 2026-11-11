"""Real HTTP + FFmpeg acceptance of a new story; no live store or service restart."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import app
import quick_recipe_apply as recipe
import quick_timeline as timeline
import quick_style as style
from editor import probe


class RecipeTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.pid = 'e' * 32
        folder = cls.root / cls.pid
        folder.mkdir()
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=green:s=320x180:r=30:d=3', '-f', 'lavfi', '-i',
                        'sine=frequency=330:duration=3', '-shortest', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(folder / 'input.mp4')], check=True)
        cls.patcher = patch.object(app, 'WORK', cls.root)
        cls.patcher.start()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.patcher.stop(); cls.temp.cleanup()

    def request(self, path, body=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def call(self, action, **body):
        return self.request('/api/recipe-apply/' + self.pid + '/' + action, body)

    def doc(self):
        return self.request('/api/quick/projects/' + self.pid)

    def test_new_story_pause_edit_resume_reload_export(self):
        with urllib.request.urlopen(self.url + '/recipe-apply') as response:
            self.assertIn(b'Review plan', response.read())
        version = self.doc()['version']
        body = {'expected_version': version, 'script': 'Save the rain. Grow a garden tomorrow.'}
        plan = self.call('plan', **body)
        self.assertEqual(plan, self.call('plan', **body))
        self.assertIn('estimated', plan['timing'])
        different = self.call('plan', **{**body, 'script': 'An entirely different garden story.'})
        self.assertNotEqual(plan['digest'], different['digest'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('start', **body, digest=different['digest'])
        self.assertEqual(error.exception.code, 409)
        run = self.call('start', **body, digest=plan['digest'])
        rid = run['id']
        run = self.call('step', run_id=rid, expected_version=version, next=0)
        self.assertEqual(run['next'], 1)
        d = self.doc(); self.assertEqual(d['studio']['aspect'], '9:16')
        duplicate = self.call('step', run_id=rid, expected_version=d['version'], next=0)
        self.assertEqual(duplicate['next'], 1)
        run = self.call('pause', run_id=rid, expected_version=d['version'])
        with self.assertRaises(urllib.error.HTTPError):
            self.call('step', run_id=rid, expected_version=d['version'], next=1)
        # Real manual edit while paused: trim the beginning and change grade.
        d = self.request('/api/quick/projects/' + self.pid + '/commands',
                         {'operation': 'sync_editor_state', 'expected_version': d['version'],
                          'clips': [{**d['clips'][0], 'start': 1}], 'studio': {**d['studio'], 'contrast': 1.2}, 'editor_state': None})
        restored = self.call('get', run_id=rid)
        self.assertEqual(restored['status'], 'paused')
        self.assertEqual(restored, json.loads((self.root/self.pid/'timeline.json').read_text())['recipe_runs'][-1])
        run = self.call('resume', run_id=rid, expected_version=d['version'])
        run = self.call('step', run_id=rid, expected_version=d['version'], next=1)
        self.assertEqual(run['status'], 'done')
        d = self.doc(); self.assertEqual(d['studio']['contrast'], 1.2)
        self.assertEqual(d['clips'][0]['start'], 1)
        captions = d['studio']['captions']
        self.assertTrue(captions)
        self.assertTrue(all(0 <= c['start'] < c['end'] <= 2.001 for c in captions))
        self.assertNotIn('student', ' '.join(c['text'] for c in captions))
        self.assertFalse(d['studio']['layers'])
        d = self.request('/api/quick/projects/' + self.pid + '/commands',
                         {'operation': 'export_video', 'expected_version': d['version']})
        eid = d['exports'][-1]['id']
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            d = self.doc(); exported = next(e for e in d['exports'] if e['id'] == eid)
            if exported['status'] != 'working': break
            time.sleep(.1)
        self.assertEqual(exported['status'], 'done', exported)
        manifest = self.request('/api/recipe-apply/'+self.pid+'/exports/'+eid)
        self.assertEqual(manifest['runs'][-1]['plan']['digest'], plan['digest'])
        self.assertEqual(manifest['timeline_version'], d['version'])
        output = self.root/self.pid/'versions'/eid/'edited.mp4'
        self.assertEqual(recipe.source_sha(output), manifest['video_sha256'])
        info = probe(output, False)
        self.assertEqual((info['width'], info['height']), (720, 1280))
        self.assertTrue(info['audio']); self.assertAlmostEqual(info['duration'], 2, delta=.08)
        subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
        # Pixel evidence: source is contained at center, white new-script captions below.
        from PIL import Image
        frame = self.root/'frame.png'
        subprocess.run(['ffmpeg','-y','-v','error','-ss','0.6','-i',str(output),'-frames:v','1',str(frame)],check=True)
        with Image.open(frame).convert('RGB') as image:
            self.assertGreater(image.getpixel((360,640))[1], 70)
            self.assertLess(max(image.getpixel((360,100))), 10)
            white = sum(min(p)>180 for p in image.crop((0,980,720,1100)).getdata())
            self.assertGreater(white, 30)
        # Undo restores pre-caption state; plan receipts remain historical provenance.
        d = self.request('/api/quick/projects/'+self.pid+'/commands',{'operation':'undo','expected_version':d['version']})
        self.assertEqual(d['studio']['captions'], [])
        self.assertEqual(d['recipe_runs'][-1]['plan']['digest'], plan['digest'])


class ReconciliationTests(unittest.TestCase):
    def test_concurrent_changes_and_user_captions_are_kept(self):
        import types
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pid='f'*32;(root/pid).mkdir();(root/pid/'input.mp4').write_bytes(b'new footage')
            service=types.SimpleNamespace(WORK=root,project=lambda _: {'name':'test'})
            with patch.object(timeline,'probe',return_value={'duration':3,'audio':True}):
                d=timeline.load(service,pid)
                style.store_words(service,pid,[{'w':'New','s':0,'e':1},{'w':'garden','s':1,'e':2}])
                b={'expected_version':d['version']};p=recipe.run_action(service,pid,'plan',b)
                r=recipe.run_action(service,pid,'start',{**b,'digest':p['digest']});rid=r['id']
                st={**studio_defaults(),'captions':[{'id':'manual','text':'My edit','start':0,'end':2}]}
                d=timeline.execute(service,pid,'set_studio',{'expected_version':1,'studio':st})
                with self.assertRaises(timeline.Conflict):
                    recipe.run_action(service,pid,'step',{'run_id':rid,'expected_version':d['version'],'next':0})
                for action in ('pause','resume'):
                    recipe.run_action(service,pid,action,{'run_id':rid,'expected_version':d['version']})
                for n in range(2):
                    r=recipe.run_action(service,pid,'step',{'run_id':rid,'expected_version':d['version'],'next':n})
                    d=timeline.load(service,pid)
                self.assertEqual(d['studio']['captions'][0]['text'],'My edit')
                self.assertEqual(r['receipts'][-1]['kept_user_fields'],['captions'])


def studio_defaults():
    import quick_studio
    return copy.deepcopy(quick_studio.DEFAULT)

if __name__=='__main__': unittest.main()
