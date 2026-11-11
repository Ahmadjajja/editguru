"""v3 editor engine tests: plan, timeline edits, overlays, live channel, saved styles, render smoke.

Self-contained: makes its own synthetic footage with FFmpeg, so it runs on any machine with ffmpeg + the
FRAME venv (numpy, Pillow; OpenCV/SciPy for the render test). From work/frame-product:

    .venv/bin/python -m unittest tests.test_v3 -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import quick_v3  # noqa: E402

SCRIPT = ("Here is the new thing. It makes commercials in one prompt. Here's how it works: open the app, then connect it, "
          "then upload a photo. It is free for three days. Comment SETUP below.")


def make_words():
    words, t = [], 1.0
    for tok in SCRIPT.split():
        words.append({'w': tok, 's': round(t, 3), 'e': round(t + .32, 3)})
        t += .38 + (.55 if tok.endswith(('.', ':')) else 0)
    return words


def make_aroll(path, words, dur):
    """1080x1920 test pattern + a tone burst under every word, so the speech envelope finds real islands."""
    expr = '+'.join('between(t,%.3f,%.3f)' % (w['s'], w['e']) for w in words)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=1080x1920:r=30:d=%.2f' % dur,
                    '-f', 'lavfi', '-i', 'sine=f=220:d=%.2f' % dur, '-af', "volume='0.6*(%s)':eval=frame" % expr,
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(path)], check=True)


def make_clip(path, dur=3.0, size='1280x720'):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=s=%s:r=30:d=%.1f' % (size, dur),
                    '-c:v', 'libx264', '-preset', 'ultrafast', str(path)], check=True)


class App:
    pass


class V3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='v3test-'))
        cls.words = make_words()
        cls.dur = cls.words[-1]['e'] + 1.0
        cls.aroll = cls.tmp / 'aroll.mp4'
        make_aroll(cls.aroll, cls.words, cls.dur)
        # a kit like recipes/<kit>/ with one media-kit clip
        cls.kits = cls.tmp / 'recipes'
        kit = cls.kits / 'test-kit'
        (kit / 'media-kit').mkdir(parents=True)
        make_clip(kit / 'media-kit' / 'demo.mp4')
        cls.vmap = {'format': 'frame-visual-map/1', 'title': 'Test kit', 'template': 'higgsfield-v3', 'caption_max_words': 3,
                    'end_hold_s': 1.0, 'hot_words': ['commercials', 'free'],
                    'visuals': [{'anchor': 'commercials', 'kind': 'split', 'media': 'media-kit/demo.mp4', 'media_in': 0, 'label': 'ADS', 'chip': 'made with x'},
                                {'anchor': "here's", 'kind': 'card', 'head': "HERE'S HOW",
                                 'rows': [{'anchor': 'open', 'num': '01', 'title': 'OPEN'}, {'anchor': 'connect', 'num': '02', 'title': 'CONNECT'}]},
                                {'anchor': 'free', 'kind': 'offer', 'white': ['ALL OF IT'], 'lime': ['FREE'], 'note': 'new users'},
                                {'anchor': 'comment', 'kind': 'cta', 'land_on': 'setup', 'keyword': 'SETUP', 'sub': 'for the guide'}]}
        (kit / 'visual-map.json').write_text(json.dumps(cls.vmap))
        cls._kits0, cls._styles0, cls._pw0 = quick_v3.KITS, quick_v3.STYLES, quick_v3.project_words
        quick_v3.KITS = cls.kits
        quick_v3.STYLES = cls.kits / '_styles'
        quick_v3.project_words = lambda app, pid: cls.words
        cls.plan = quick_v3.build_plan(str(cls.aroll), cls.words, cls.vmap)

    @classmethod
    def tearDownClass(cls):
        quick_v3.KITS, quick_v3.STYLES, quick_v3.project_words = cls._kits0, cls._styles0, cls._pw0
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- plan
    def test_plan_places_every_visual_on_its_word(self):
        kinds = [s['kind'] for s in self.plan['segments']]
        self.assertEqual(kinds, ['face', 'split', 'card', 'offer', 'cta'])
        W = self.plan['words']
        for s in self.plan['segments'][1:]:
            w = W[s['anchor_word_index']]
            self.assertAlmostEqual(s['t0'], max(0, w['s'] - .06), places=2)
        self.assertTrue(self.plan['captions'])
        self.assertTrue(any(t['hot'] for c in self.plan['captions'] for t in c['tokens']))
        self.assertEqual(self.plan, quick_v3.build_plan(str(self.aroll), self.words, self.vmap), 'same inputs, same plan')

    # ---- timeline edits
    def timeline(self, **over):
        lines = [{'src_in': l['src_in'], 'src_out': l['src_out'], 'out': l['out']} for l in self.plan['lines']]
        segs = [dict(s) for s in self.plan['segments'] if s['kind'] != 'face']
        tl = {'lines': lines, 'segments': segs, 'captions': self.plan['captions'], 'caption_y': 1500}
        tl.update(over)
        return tl

    def test_timeline_gap_on_aroll_is_refused(self):
        tl = self.timeline()
        tl['lines'][1] = dict(tl['lines'][1], out=tl['lines'][1]['out'] + 1.0)
        with self.assertRaisesRegex(ValueError, 'gap on the A-roll'):
            quick_v3.apply_timeline(App, 'p' * 32, self.plan, tl, self.kits / 'test-kit')

    def test_later_section_wins_and_earlier_resumes(self):
        tl = self.timeline()
        offer = next(s for s in tl['segments'] if s['kind'] == 'offer')
        mid = (offer['t0'] + offer['t1']) / 2
        tl['segments'].append({'kind': 'split', 't0': mid, 't1': mid + .4, 'media': 'media-kit/demo.mp4', 'media_in': 0, 'label': 'X'})
        p = quick_v3.apply_timeline(App, 'p' * 32, self.plan, tl, self.kits / 'test-kit')
        kinds = [(s['kind'], s['t0']) for s in p['segments']]
        i = next(n for n, k in enumerate(kinds) if k[0] == 'split' and abs(k[1] - mid) < .01)
        self.assertEqual(kinds[i - 1][0], 'offer')
        self.assertEqual(kinds[i + 1][0], 'offer', 'offer resumes after the inserted split')
        self.assertGreater(p['segments'][i + 1].get('u0', 0), 0)
        self.assertEqual(p['caption_y'], 1500)

    def test_kit_comments_never_reach_the_renderer(self):
        tl = self.timeline()
        tl['segments'][0]['note'] = 'x' * 500            # a long kit-map comment on a split
        p = quick_v3.apply_timeline(App, 'p' * 32, self.plan, tl, self.kits / 'test-kit')
        self.assertNotIn('note', next(s for s in p['segments'] if s['kind'] == 'split'))

    def test_graphics_are_validated_and_kept(self):
        tl = self.timeline(graphics_mode=True, graphics=[{'type': 'cta', 'keyword': 'SETUP', 't0': 1, 't1': 3, 'x': 540, 'y': 1100, 'k': .8},
                                                          {'type': 'bogus', 't0': 0, 't1': 1}])
        p = quick_v3.apply_timeline(App, 'p' * 32, self.plan, tl, self.kits / 'test-kit')
        self.assertTrue(p['graphics_mode'])
        self.assertEqual([g['type'] for g in p['graphics']], ['cta'])
        self.assertEqual(p['graphics'][0]['y'], 1100)

    def test_screen_time_ignores_steps_outside_the_section(self):
        seg = {'t0': 10, 't1': 20, 'media_in': 0, 'media_out': 9,
               'rows': [{'t': 8, 'media_t': 5}, {'t': 15, 'media_t': 2}, {'t': 25, 'media_t': 8}]}
        self.assertAlmostEqual(quick_v3.screen_time(seg, 12.5), 1.0)
        self.assertAlmostEqual(quick_v3.screen_time(seg, 20), 9.0)

    # ---- live channel
    def test_live_channel_round_trip(self):
        d = self.tmp / 'proj-live'; d.mkdir()
        quick_v3.push_live(d, {'type': 'say', 'text': 'hi'})
        quick_v3.push_live(d, {'type': 'seek', 't': 3})
        r = quick_v3.read_live(d, 1)
        self.assertEqual([e['type'] for e in r['events']], ['seek'])
        with self.assertRaises(ValueError):
            quick_v3.push_live(d, {'type': 'rm -rf'})

    # ---- styles
    def test_style_round_trip_gives_a_first_cut_on_new_footage(self):
        app = App(); app.WORK = self.tmp / 'work'
        pid = 'a' * 32
        (app.WORK / pid / 'assets' / 'c1').mkdir(parents=True)
        (app.WORK / pid / 'assets' / 's1').mkdir(parents=True)
        make_clip(app.WORK / pid / 'assets' / 'c1' / 'product_shot.mp4')
        make_clip(app.WORK / pid / 'assets' / 's1' / 'setup.mp4', dur=4, size='720x1280')
        moved_cta = {'tr': 'g1', 'start': 1, 'dur': 2, 'g': {'type': 'cta', 'keyword': 'SETUP', 'sub': 'for the guide'}, 'y': 1150}
        doc = {'version': 3, 'assets': [{'id': 'c1', 'name': 'product_shot.mp4', 'path': 'assets/c1/product_shot.mp4'},
                                         {'id': 's1', 'name': 'setup.mp4', 'path': 'assets/s1/setup.mp4'}],
               'editor_state': {'p': {'v3': {'kit': 'test-kit', 'overrides': {'captions': {'y': 1520}}, 'gfx': True}, 'clips': [moved_cta]}}}
        (app.WORK / pid / 'timeline.json').write_text(json.dumps(doc))
        st = quick_v3.save_style(app, pid, 'Test Discovery')
        self.assertEqual(st['captions']['y'], 1520)
        self.assertEqual(st['graphics']['cta']['y'], 1150)
        self.assertEqual([s['kind'] for s in st['sections']], ['split', 'card', 'offer', 'cta'])
        self.assertIn('test-discovery', [s['slug'] for s in quick_v3.list_styles()])
        r = quick_v3.first_cut(app, pid, 'test-discovery', [{'asset_id': 'c1', 'role': 'split', 'cue': 'commercials'},
                                                            {'asset_id': 's1', 'role': 'screen'}])
        vm = json.loads((self.kits / r['kit'] / 'visual-map.json').read_text())
        placed = {v['kind']: v for v in vm['visuals']}
        self.assertEqual(placed['split']['anchor'], 'commercials')
        self.assertEqual(placed['screen']['anchor'].lower(), "here's")
        self.assertEqual(placed['offer']['anchor'], 'free')
        self.assertEqual(placed['cta']['keyword'], 'SETUP')
        self.assertEqual(vm['caption_y'], 1520)
        plan = quick_v3.build_plan(str(self.aroll), self.words, vm)
        self.assertEqual(plan['graphic_defaults']['cta']['y'], 1150)
        self.assertEqual([s['kind'] for s in plan['segments']], ['face', 'split', 'screen', 'offer', 'cta'])
        self.assertGreaterEqual(len(next(s for s in plan['segments'] if s['kind'] == 'screen')['rows']), 2)
        self.assertIn(r['kit'], [k['kit'] for k in quick_v3.list_kits(pid)])
        self.assertNotIn(r['kit'], [k['kit'] for k in quick_v3.list_kits('b' * 32)], 'a first-cut kit stays in its project')

    # ---- render smoke (needs OpenCV)
    def test_render_matches_the_timeline(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest('OpenCV not installed (the editor installs it on first render)')
        tl = self.timeline(graphics_mode=True, graphics=[{'type': 'text', 'text': 'HELLO', 't0': .2, 't1': 1.5, 'y': 400}])
        p = quick_v3.apply_timeline(App, 'p' * 32, self.plan, tl, self.kits / 'test-kit')
        out = self.tmp / 'r.mp4'
        n = quick_v3.render(p, str(self.aroll), self.kits / 'test-kit', out, log=lambda m: None)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v', '-show_entries', 'stream=nb_read_frames,width,height',
                                '-of', 'json', str(out)], capture_output=True, text=True).stdout
        st = json.loads(probe)['streams'][0]
        self.assertEqual((st['width'], st['height']), (1080, 1920))
        self.assertEqual(int(st['nb_read_frames']), n)


if __name__ == '__main__':
    unittest.main()
