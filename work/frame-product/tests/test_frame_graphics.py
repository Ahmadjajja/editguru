"""Behavior checks for the narration-preserving Studio / Motion boundary."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import frame_graphics as bridge


def fixture(folder, words=None, duration=1):
    words = words or ['Your', 'idea', 'moves.']
    samples = int(48000 * duration)
    audio = Path(folder) / 'source.wav'
    # Asymmetric waveform makes accidental normalization/DC removal observable.
    pcm = b''.join(struct.pack('<h', int(1500 + 3500 * math.sin(2 * math.pi * 237 * i / 48000)))
                   for i in range(samples))
    with wave.open(str(audio), 'wb') as out:
        out.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        out.writeframes(pcm)
    interval = duration / len(words)
    text = ' '.join(words)
    narration = {'provider': 'Test fixture', 'audio': str(audio), 'fps': 30,
                 'frames': round(duration * 30), 'duration': duration,
                 'scenes': [{'narration': text, 'start_frame': 0, 'end_frame': round(duration * 30),
                             'words': [{'text': word, 'start': i * interval,
                                        'end': min(duration, (i + .8) * interval)}
                                       for i, word in enumerate(words)]}]}
    plan = {'identity': {'intent': 'Make a new idea tangible.'},
            'scenes': [{'narration': text}], 'delivery': {'arc': 'Quiet to clear', 'beats': []}}
    return narration, plan


def graphic_plan(spec, variant=0):
    return {'title': 'An idea takes shape', 'interpretation': 'The focus moves from an idea to action.',
            'beats': [{'id': s['id'], 'importance': .7, 'energy': .3 if not variant else .85,
                       'focus_word': 1 if not variant else 2, 'headline': 'YOUR IDEA' if not variant else 'MAKE IT MOVE',
                       'intent': 'Show a clear idea', 'reason': 'One focal shape supports the spoken message.',
                       'evidence': ['script'], 'motion': 'settle' if not variant else 'punch',
                       'nodes': [{'shape': 'circle' if not variant else 'box',
                                  'label': 'IDEA' if not variant else 'MOVE',
                                  'x': .5, 'y': .5, 'w': .35, 'h': .4,
                                  'color': 'accent', 'motion': 'reveal'}], 'edges': []}
                      for s in spec['scenes']]}


class NarrationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.narration, self.plan = fixture(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def test_checkpoint_preserves_inputs_and_word_timestamps(self):
        before = copy.deepcopy(self.narration)
        spec = bridge.build_spec(self.narration, self.plan)
        self.assertEqual(before, self.narration)
        self.assertEqual(spec['frames'], 30)
        for actual, expected in zip(spec['scenes'][0]['words'], before['scenes'][0]['words']):
            self.assertEqual((actual['raw_start'], actual['raw_end']), (expected['start'], expected['end']))
        self.assertEqual((spec['sfx'], spec['bed']), (0, 0))

    def test_changed_audio_hash_is_rejected(self):
        self.narration['audio_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'changed'):
            bridge.validate_narration(self.narration, self.plan)

    def test_changed_script_is_rejected(self):
        self.plan['scenes'][0]['narration'] = 'A different voice.'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            bridge.validate_narration(self.narration, self.plan)

    def test_nonfinite_words_and_mismatched_samples_are_rejected(self):
        self.narration['scenes'][0]['words'][0]['start'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'word start'):
            bridge.validate_narration(self.narration, self.plan)
        self.narration['scenes'][0]['words'][0]['start'] = 0
        self.narration['frames'] = 31
        with self.assertRaisesRegex(ValueError, 'samples'):
            bridge.validate_narration(self.narration, self.plan)

    def test_long_scene_splits_at_measured_words_without_losing_words(self):
        words = ['word%02d' % i for i in range(40)]
        narration, plan = fixture(self.folder, words=words, duration=10)
        spec = bridge.build_spec(narration, plan)
        self.assertGreater(len(spec['scenes']), 1)
        self.assertEqual([w['text'] for s in spec['scenes'] for w in s['words']], words)
        self.assertEqual(spec['scenes'][0]['start_frame'], 0)
        self.assertEqual(spec['scenes'][-1]['end_frame'], 300)
        self.assertTrue(all(len(s['text']) <= 180 for s in spec['scenes']))
        self.assertEqual([s['end_frame'] for s in spec['scenes'][:-1]],
                         [s['start_frame'] for s in spec['scenes'][1:]])

    def test_parent_import_does_not_load_motion_modules(self):
        code = 'import sys, frame_graphics; print(any(x in sys.modules for x in ("engine","director","graphics")))'
        out = subprocess.check_output([sys.executable, '-c', code], cwd=ROOT, text=True)
        self.assertEqual(out.strip(), 'False')

    def test_revision_scope_rejects_audio_request(self):
        import frame_graphics_worker as worker
        with patch('studio_director.ask', return_value={'action': 'new_narration',
                                                       'message': 'Changing the speaker needs new narration.'}):
            with self.assertRaisesRegex(ValueError, 'new narration'):
                worker.revision_scope(self.folder, 'Use another speaker')

    def test_feedback_context_carries_delivery_but_prioritizes_revision(self):
        import frame_graphics_worker as worker
        request = {'plan': self.plan, 'idea': 'Make it simple', 'feedback': 'Make the final word the largest',
                   '_folder': str(self.folder)}
        prompt = worker.direction_context(request)
        self.assertIn('LATEST VISUAL FEEDBACK', prompt)
        self.assertIn('Quiet to clear', prompt)
        self.assertLessEqual(len(prompt), 3000)

    def test_spoken_word_cue_has_one_crisp_caption_state(self):
        if not bridge.MOTION_SOURCE.is_dir():
            self.skipTest('Installed Motion Lab engine unavailable')
        sys.path.insert(0, str(bridge.MOTION_SOURCE))
        import director
        from engine import Renderer
        spec = bridge.build_spec(self.narration, self.plan)
        spec = director.apply_plan(spec, graphic_plan(spec))
        frame = spec['scenes'][0]['words'][1]['frame']
        renderer = Renderer(spec)
        bottom = (0, int(renderer.h * .84), renderer.w, renderer.h)
        self.assertEqual(renderer.output_frame(frame).crop(bottom).tobytes(),
                         renderer.frame(frame).crop(bottom).tobytes())

    def test_real_graphics_revision_changes_picture_with_identical_voice(self):
        if not bridge.MOTION_SOURCE.is_dir():
            self.skipTest('Installed Motion Lab engine unavailable')
        source_hash = bridge.sha256(self.narration['audio'])
        script = '''
import json,sys,shutil
from pathlib import Path
import frame_graphics as bridge
import frame_graphics_worker as worker
p=Path(sys.argv[1]); req=json.loads((p/'test-request.json').read_text())
sys.path.insert(0,str(bridge.MOTION_SOURCE))
import director
spec=bridge.build_spec(req['narration'],req['plan'])
spec=director.apply_plan(spec,req['graphics'])
shutil.copyfile(req['narration']['audio'],p/'narration.wav')
req['source_audio_sha256']=bridge.sha256(p/'narration.wav')
worker.render_video(p,spec,req['graphics'],req)
'''
        decoded, pictures = [], []
        for variant in (0, 1):
            output = self.folder / ('version%d' % variant)
            output.mkdir()
            spec = bridge.build_spec(self.narration, self.plan)
            request = {'narration': self.narration, 'plan': self.plan, 'graphics': graphic_plan(spec, variant)}
            (output / 'test-request.json').write_text(json.dumps(request))
            subprocess.run([sys.executable, '-c', script, str(output)], cwd=ROOT,
                           check=True, capture_output=True, timeout=90)
            self.assertEqual(bridge.sha256(output / 'narration.wav'), source_hash)
            verified = json.loads((output / 'graphics-verification.json').read_text())
            self.assertEqual(verified['frames'], 30)
            self.assertEqual(verified['decode'], 'passed')
            audio = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output / 'export.mp4'),
                                             '-map', '0:a', '-f', 's16le', '-acodec', 'pcm_s16le', '-'])
            decoded.append(hashlib.sha256(audio).hexdigest())
            pictures.append(bridge.sha256(output / 'poster.jpg'))
        self.assertEqual(decoded[0], decoded[1])
        self.assertNotEqual(pictures[0], pictures[1])
        self.assertEqual(bridge.sha256(self.narration['audio']), source_hash)


if __name__ == '__main__':
    unittest.main()
