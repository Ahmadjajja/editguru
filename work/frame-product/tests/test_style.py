import copy
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import editor
import quick_asset_library as library
import quick_style as style
import quick_timeline as timeline

WORDS = [('so', 0.5, 0.7), ('today', 0.72, 1.0), ('we', 1.05, 1.2), ('edit', 1.22, 1.5),
         ('so', 3.0, 3.2), ('today', 3.22, 3.5), ('we', 3.52, 3.7), ('edit', 3.72, 4.0), ('video', 4.02, 4.4),
         ('fast', 5.6, 6.0), ('and', 6.05, 6.2), ('clean', 6.25, 6.6)]


def base_style(**extra):
    s = {'format': 'frame-style/1', 'name': 'Brand X spec',
         'provenance': {'source_kind': 'brand_reference', 'use_scope': {'type': 'brand', 'brand': 'Brand X'}},
         'frame': {'aspect': '9:16', 'fit': 'cover'},
         'look': {'brightness': .02, 'contrast': 1.08, 'saturation': 1.1},
         'pacing': {'remove_pauses': True, 'min_pause_s': .35, 'pad_s': .1, 'remove_retakes': True},
         'captions': {'max_words': 3, 'max_s': 1.5, 'y': .72, 'size': .055, 'color': '#FFFFFF', 'case': 'upper', 'style': 'lime'},
         'locked': ['captions.case']}
    s.update(extra)
    return s


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pid = 'a' * 32
        (self.root / self.pid).mkdir()
        (self.root / self.pid / 'input.mp4').write_bytes(b'fixture-bytes')
        self.app = types.SimpleNamespace(WORK=self.root, project=lambda _: {'name': 'Style fixture'}, WORKERS=threading.Semaphore(1))
        self.patcher = patch.object(timeline, 'probe', return_value={'duration': 8, 'audio': True})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        timeline.load(self.app, self.pid)
        style.store_words(self.app, self.pid, [{'w': w, 's': a, 'e': b} for w, a, b in WORDS])

    def version(self):
        with timeline.LOCK:
            return timeline.load(self.app, self.pid)['version']

    def test_validation_requires_a_source_and_rejects_unknown_fields(self):
        style.validate(base_style())
        broken = base_style(); broken.pop('provenance')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            style.validate(broken)
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            style.validate(base_style(sparkle=True))
        with self.assertRaisesRegex(ValueError, 'Locked field'):
            style.validate(base_style(locked=['captions.font']))

    def test_plan_is_deterministic_and_only_uses_fields_the_style_sets(self):
        first = style.plan(self.app, self.pid, base_style())
        second = style.plan(self.app, self.pid, copy.deepcopy(base_style()))
        self.assertEqual(first, second)
        kinds = [op['kind'] for op in first['ops']]
        self.assertIn('cut', kinds)
        self.assertEqual(kinds.count('captions'), 1)
        retake = [op for op in first['ops'] if 'earlier take' in op['label']]
        self.assertEqual(len(retake), 1)
        self.assertAlmostEqual(retake[0]['source'][0], 0.3)
        minimal = style.plan(self.app, self.pid, {'format': 'frame-style/1', 'name': 'Only look',
                                                  'provenance': {'source_kind': 'own_video'}, 'look': {'contrast': 1.2}})
        self.assertEqual([op['kind'] for op in minimal['ops']], ['look'])
        self.assertNotEqual(minimal['digest'], first['digest'])

    def test_headless_apply_is_one_version_per_op_and_undoable(self):
        v0 = self.version()
        result = style.apply(self.app, self.pid, base_style(), v0)
        self.assertEqual([a['version'] for a in result['applied']], list(range(v0 + 1, v0 + 1 + len(result['applied']))))
        project = result['project']
        self.assertGreater(len(project['clips']), 1)
        self.assertLess(project['duration'], 8)
        self.assertEqual(project['studio']['aspect'], '9:16')
        self.assertTrue(all(c['text'] == c['text'].upper() for c in project['studio']['captions']))
        undone = timeline.execute(self.app, self.pid, 'undo', {'expected_version': project['version']})
        self.assertEqual(undone['studio'].get('captions', []), [])
        with self.assertRaises(timeline.Conflict):
            style.apply(self.app, self.pid, base_style(), v0)

    def test_locked_fields_need_explicit_unlock_and_revisions_increment(self):
        saved = style.save(self.app, base_style())
        changed = base_style(); changed['captions']['case'] = 'sentence'
        with self.assertRaisesRegex(ValueError, 'locked'):
            style.save(self.app, changed, parent_style_id=saved['style_id'])
        child = style.save(self.app, changed, parent_style_id=saved['style_id'], unlock=['captions.case'])
        self.assertEqual(child['style']['revision'], 2)
        self.assertEqual(child['style']['parent_style_id'], saved['style_id'])
        mine = [x for x in style.list_styles(self.app) if x['name'] == 'Brand X spec']
        self.assertEqual(len(mine), 2)  # two revisions; starter and recipe-kit styles are listed too

    def test_starter_is_not_owned_until_enough_fields_change(self):
        starter = style.save(self.app, base_style())
        derived = base_style(provenance={'source_kind': 'starter', 'starter': {'style_id': starter['style_id'], 'min_changed_fields': 3}})
        self.assertFalse(style.save(self.app, derived)['style']['owned'])
        derived['look'] = {'brightness': 0, 'contrast': 1.2, 'saturation': .9}
        self.assertTrue(style.save(self.app, derived)['style']['owned'])

    def test_editor_state_saves_without_a_new_video_version(self):
        v = self.version()
        doc = timeline.execute(self.app, self.pid, 'sync_editor_state', {'expected_version': v, 'clips': [{'start': 0, 'end': 3}, {'start': 4, 'end': 8}],
                               'studio': {'contrast': 1.1}, 'editor_state': {'p': {'caps': {'style': 'lime'}}}})
        self.assertEqual(doc['version'], v + 1)
        self.assertEqual(doc['duration'], 7)
        same = timeline.execute(self.app, self.pid, 'sync_editor_state', {'expected_version': v + 1, 'clips': [{'id': c['id'], 'start': c['start'], 'end': c['end']} for c in doc['clips']],
                                'studio': doc['studio'], 'editor_state': {'p': {'caps': {'style': 'karaoke'}}}})
        self.assertEqual(same['version'], v + 1)
        saved = json.loads((self.root / self.pid / 'timeline.json').read_text())
        self.assertEqual(saved['editor_state']['p']['caps']['style'], 'karaoke')
        many = [{'start': i * .1, 'end': i * .1 + .07} for i in range(80)]
        self.assertEqual(len(timeline.execute(self.app, self.pid, 'sync_editor_state', {'expected_version': v + 1, 'clips': many})['clips']), 80)

    def test_brand_assets_only_enter_matching_projects(self):
        image = self.root / 'logo.png'
        from PIL import Image
        Image.new('RGB', (8, 8), 'white').save(image)
        asset = library.register_file(self.app, image, kind='image', metadata={'provenance': {'use_scope': {'type': 'brand', 'brand': 'Brand X'}}})
        s = base_style(slots=[{'id': 'logo', 'kind': 'image', 'required': True, 'asset_id': asset['id'], 'placement': {'x': .88, 'y': .08, 'width': .14}}])
        op = next(o for o in style.plan(self.app, self.pid, s)['ops'] if o['kind'] == 'overlay')
        with self.assertRaisesRegex(ValueError, 'Brand X'):
            style.apply_op(self.app, self.pid, op, self.version())
        with timeline.LOCK:
            doc = timeline.load(self.app, self.pid); doc['brand'] = 'Brand X'
            timeline.write(self.root / self.pid / 'timeline.json', doc)
        version = style.apply_op(self.app, self.pid, op, self.version())
        with timeline.LOCK:
            self.assertEqual(len(timeline.load(self.app, self.pid)['studio']['layers']), 1)
        self.assertEqual(version, self.version())


class ManyCutRenderTest(unittest.TestCase):
    def test_hundred_cuts_render_with_exact_duration_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); src = tmp / 'src.mp4'
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x568:rate=30:duration=20',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(src)], check=True)
            keep = [(i * .2, i * .2 + .1) for i in range(100)]
            measured = editor.render_timeline(src, tmp, keep, True, lambda _: None)
            self.assertAlmostEqual(measured, 10.0, delta=.05)
            streams = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,duration', '-of', 'json', str(tmp / 'edited.mp4')], capture_output=True, text=True).stdout)['streams']
            self.assertEqual(sorted(s['codec_type'] for s in streams), ['audio', 'video'])


if __name__ == '__main__':
    unittest.main()
