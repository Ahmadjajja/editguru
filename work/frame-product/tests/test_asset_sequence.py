import array
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from editor import probe, run
import quick_asset_library as library
import quick_asset_sequence as sequence
import quick_timeline as timeline


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = types.SimpleNamespace(WORK=self.root)
        red = self.root / 'red.mp4'
        green = self.root / 'green.mp4'
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=30:d=1',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-shortest', str(red)])
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=lime:s=200x120:r=30:d=1',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(green)])
        self.red = library.register_file(self.app, red, kind='clip')
        self.green = library.register_file(self.app, green, kind='render')

    def test_two_real_clips_preserve_order_audio_and_originals(self):
        result = sequence.create_video_from_library(self.app, [
            {'asset_id': self.red['id'], 'duration': .8},
            {'asset_id': self.green['id'], 'inpoint': .1, 'duration': .8}], name='Library sequence')
        folder = self.root / result['project_id']
        info = probe(folder / 'input.mp4')
        self.assertAlmostEqual(info['duration'], 1.6, delta=.07)
        self.assertTrue(info['audio'])
        self.assertEqual((info['width'], info['height']), (160, 120))
        self.assertEqual(len(result['clips']), 2)
        self.assertEqual(len(result['assets']), 2)
        self.assertEqual(result['library_sequence']['items'][1]['output_start'], .8)
        for asset in result['assets']:
            self.assertTrue((folder / asset['path']).is_file())
            self.assertIn(asset['library_asset_id'], (self.red['id'], self.green['id']))
        from PIL import Image
        for when, channel in [(.3, 0), (1.2, 1)]:
            frame = folder / ('frame-' + str(when) + '.png')
            run(['ffmpeg', '-y', '-v', 'error', '-ss', str(when), '-i', str(folder / 'input.mp4'), '-frames:v', '1', str(frame)])
            with Image.open(frame) as image:
                pixel = image.getpixel((80, 60))
                self.assertGreater(pixel[channel], 200)
                self.assertLess(pixel[1 - channel], 30)
        rms = []
        for when in (.2, 1.1):
            audio = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(when), '-i', str(folder / 'input.mp4'),
                                    '-t', '0.2', '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                                   check=True, capture_output=True).stdout
            samples = array.array('h', audio)
            rms.append((sum(x*x for x in samples) / len(samples)) ** .5)
        self.assertGreater(rms[0], 500)
        self.assertLess(rms[1], 10)
        self.assertEqual(json.loads((folder / 'project.json').read_text())['name'], 'Library sequence')
        self.assertEqual(json.loads((folder / 'library-sequence.json').read_text())['format'], 'frame-library-sequence/1')
        self.assertFalse(list(self.root.glob('.sequence-*')))

    def test_muted_audio_and_shared_style(self):
        style = library.save_recipe(self.app, name='Square', kind='style', recipe={'aspect': '1:1', 'saturation': .2})
        result = sequence.create_video_from_library(self.app, [{'asset_id': self.red['id'], 'include_audio': False, 'duration': .5}], style_id=style['id'])
        self.assertFalse(probe(self.root / result['project_id'] / 'input.mp4')['audio'])
        self.assertEqual(result['studio']['aspect'], '1:1')
        self.assertEqual(result['studio']['saturation'], .2)

    def test_invalid_private_and_failed_render_publish_nothing(self):
        initial = set(self.root.iterdir())
        for items in ([], [{'asset_id': self.red['id'], 'duration': 2}], [{'asset_id': self.red['id'], 'include_audio': 'yes'}]):
            with self.assertRaises(ValueError):
                sequence.create_video_from_library(self.app, items)
            self.assertEqual(set(self.root.iterdir()), initial)
        private = library.register_file(self.app, self.root / 'red.mp4', kind='clip', project_id='a' * 32)
        with self.assertRaisesRegex(ValueError, 'shared'):
            sequence.create_video_from_library(self.app, [{'asset_id': private['id']}])
        with patch.object(sequence, 'run', side_effect=RuntimeError('FFmpeg failed')):
            with self.assertRaises(RuntimeError):
                sequence.create_video_from_library(self.app, [{'asset_id': self.red['id']}])
        self.assertEqual(set(self.root.iterdir()), initial)


if __name__ == '__main__':
    unittest.main()
