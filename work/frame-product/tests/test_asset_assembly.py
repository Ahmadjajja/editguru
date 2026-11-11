import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import quick_asset_assembly as assembly
import quick_asset_library as library
import quick_studio as studio
import quick_timeline as timeline


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pid = 'b' * 32
        (self.root / self.pid).mkdir()
        self.app = types.SimpleNamespace(WORK=self.root, project=lambda _: {'name': 'Assembly fixture'})
        with patch.object(timeline, 'probe', return_value={'duration': 8, 'audio': True}):
            self.doc = timeline.load(self.app, self.pid)
        self.image = self.root / 'poster.png'
        from PIL import Image
        Image.new('RGB', (16, 16), 'red').save(self.image)
        self.asset = library.register_file(self.app, self.image, kind='image', tags=['poster'])

    def item(self, **values):
        return {'asset_id': self.asset['id'], 'start': 1, 'end': 3, **values}

    def saved(self):
        return (self.root / self.pid / 'timeline.json').read_bytes()

    def test_plan_does_not_copy_or_save_and_apply_is_one_revision(self):
        before = self.saved()
        plan = assembly.plan_assembly(self.app, self.pid, 1, [self.item(), self.item(start=4, end=6)])
        self.assertFalse(plan['applied'])
        self.assertEqual(before, self.saved())
        self.assertFalse((self.root / self.pid / 'assets').exists())
        result = assembly.apply_assembly(self.app, self.pid, 1, [self.item(), self.item(start=4, end=6)])
        self.assertEqual(result['version'], 2)
        self.assertEqual(len(result['assets']), 1)
        self.assertEqual(len(result['studio']['layers']), 2)
        self.assertEqual(result['clips'], self.doc['clips'])
        restored = timeline.execute(self.app, self.pid, 'undo', {'expected_version': 2})
        self.assertEqual(restored['studio'], {})
        redone = timeline.execute(self.app, self.pid, 'redo', {'expected_version': 3})
        self.assertEqual(len(redone['studio']['layers']), 2)

    def test_conflict_invalid_range_and_private_assets_preserve_project(self):
        before = self.saved()
        for version, item in [(0, self.item()), (1, self.item(end=9)), (1, self.item(start=3, end=2)), (1, self.item(width=float('nan')))]:
            with self.assertRaises(ValueError):
                assembly.apply_assembly(self.app, self.pid, version, [item])
            self.assertEqual(before, self.saved())
        private = library.register_file(self.app, self.image, kind='image', project_id='d' * 32)
        with self.assertRaisesRegex(ValueError, 'different project'):
            assembly.plan_assembly(self.app, self.pid, 1, [self.item(asset_id=private['id'])])
        self.assertEqual(before, self.saved())

    def test_styles_templates_and_media_bounds(self):
        style = library.save_recipe(self.app, name='Muted', kind='style', recipe={'saturation': .3})
        template = library.save_recipe(self.app, name='Poster layout', kind='template', recipe={
            'studio': {'aspect': '9:16'}, 'items': [self.item()]})
        result = assembly.apply_assembly(self.app, self.pid, 1, [], style_id=style['id'], template_id=template['id'])
        self.assertEqual(result['studio']['aspect'], '9:16')
        self.assertEqual(result['studio']['saturation'], .3)
        audio = self.root / 'audio.wav'
        audio.write_bytes(b'fixture')
        record = library.register_file(self.app, audio, kind='sound_effect')
        before = self.saved()
        with patch.object(studio, 'media_info', return_value={'audio': True, 'video': False, 'duration': .5}):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                assembly.apply_assembly(self.app, self.pid, 2, [self.item(asset_id=record['id'])])
        self.assertEqual(before, self.saved())

    def test_failed_copy_does_not_commit_partial_metadata(self):
        before = self.saved()
        with patch.object(assembly.shutil, 'copyfileobj', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):
                assembly.apply_assembly(self.app, self.pid, 1, [self.item()])
        self.assertEqual(before, self.saved())
        self.assertEqual(list((self.root / self.pid / 'assets').iterdir()), [])

    def test_unknown_commit_outcome_preserves_copied_dependencies(self):
        real_write = timeline.write
        def uncertain(path, doc):
            real_write(path, doc)
            raise OSError('Directory sync failed')
        with patch.object(timeline, 'write', side_effect=uncertain):
            with self.assertRaises(OSError):
                assembly.apply_assembly(self.app, self.pid, 1, [self.item()])
        doc = json.loads(self.saved())
        self.assertEqual(doc['version'], 2)
        self.assertTrue((self.root / self.pid / doc['assets'][0]['path']).is_file())


if __name__ == '__main__':
    unittest.main()
