import concurrent.futures
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_asset_library as library
import quick_timeline as timeline


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pid = 'a' * 32
        self.app = types.SimpleNamespace(WORK=self.root / 'jobs', MAX_UPLOAD=1024*1024,
                                         project=lambda _: {'name':'Fixture','current_segments':None})
        (self.app.WORK / self.pid).mkdir(parents=True)
        (self.app.WORK / self.pid / 'input.mp4').write_bytes(b'original')
        self.source = self.root / 'impact.wav'
        self.source.write_bytes(b'original audio bytes')
        mock = patch.object(timeline, 'probe', return_value={'duration':12, 'audio':True})
        mock.start()
        self.addCleanup(mock.stop)
        timeline.load(self.app, self.pid)

    def test_preserves_bytes_across_source_loss_and_deduplicates(self):
        record = library.register_file(self.app, self.source, kind='sound_effect', tags=['Impact', 'big'])
        self.assertEqual(record, library.register_file(self.app, self.source, kind='sound_effect', tags=['big', 'impact']))
        self.source.unlink()
        self.assertEqual(library.resolve(self.app, record['id']).read_bytes(), b'original audio bytes')
        self.assertEqual(len(list((self.app.WORK / '.asset-library' / 'blobs').iterdir())), 1)
        self.assertEqual(library.search(self.app, query='impact', tags=['BIG']), [record])

    def test_scope_and_recipe_roundtrip(self):
        shared = library.save_recipe(self.app, name='Clean captions', kind='style', recipe={'volume':0.8}, tags=['clean'])
        private = library.save_recipe(self.app, name='Private template', kind='template', recipe={'layers':[]}, project_id=self.pid)
        self.assertEqual(library.search(self.app), [shared])
        self.assertEqual({r['id'] for r in library.search(self.app, project_id=self.pid)}, {shared['id'], private['id']})
        self.assertEqual(library.search(self.app, project_id='b'*32), [shared])
        self.assertEqual(library.get(self.app, private['id'])['recipe'], {'layers':[]})
        with self.assertRaises(ValueError):library.resolve(self.app, private['id'])

    def test_attach_versioning_and_independent_project_copy(self):
        record = library.register_file(self.app, self.source)
        result = library.attach(self.app, record['id'], self.pid, 1)
        self.assertEqual(result['version'], 2)
        attached = result['assets'][0]
        target = self.app.WORK / self.pid / attached['path']
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        with self.assertRaises(timeline.Conflict):library.attach(self.app, record['id'], self.pid, 1)
        result = library.attach(self.app, record['id'], self.pid, 2)
        self.assertTrue(result['asset_reused'])
        self.assertEqual(result['version'], 2)
        library.resolve(self.app, record['id']).unlink()
        self.assertEqual(target.read_bytes(), self.source.read_bytes())

    def test_rejects_wrong_project_and_integrity_damage(self):
        record = library.register_file(self.app, self.source, project_id='b'*32)
        with self.assertRaises(ValueError):library.attach(self.app, record['id'], self.pid, 1)
        library.resolve(self.app, record['id']).write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'integrity'):library.resolve(self.app, record['id'])

    def test_reused_project_asset_is_integrity_checked(self):
        record = library.register_file(self.app, self.source)
        attached = library.attach(self.app, record['id'], self.pid, 1)['assets'][0]
        (self.app.WORK / self.pid / attached['path']).write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            library.attach(self.app, record['id'], self.pid, 2)
        self.assertEqual(timeline.load(self.app, self.pid)['version'], 2)

    def test_concurrent_register_is_idempotent(self):
        def register(_):return library.register_file(self.app, self.source)['id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            identifiers = list(pool.map(register, range(16)))
        self.assertEqual(len(set(identifiers)), 1)
        self.assertEqual(len(library.search(self.app)), 1)

    def test_symlink_and_invalid_inputs_rejected(self):
        linked = self.root / 'linked.wav'
        linked.symlink_to(self.source)
        with self.assertRaises(ValueError):library.register_file(self.app, linked)
        with self.assertRaises(ValueError):library.register_file(self.app, self.source, name='../..')
        with self.assertRaises(ValueError):library.register_file(self.app, self.source, metadata={'nan':float('nan')})
        with self.assertRaises(ValueError):library.search(self.app, limit=True)
        with self.assertRaises(ValueError):library.get(self.app, '../')

    def test_unknown_metadata_commit_preserves_bytes(self):
        record = library.register_file(self.app, self.source)
        with patch.object(timeline, 'write', side_effect=OSError('unknown commit')), self.assertRaises(OSError):
            library.attach(self.app, record['id'], self.pid, 1)
        self.assertEqual(len(list((self.app.WORK / self.pid / 'assets').rglob('impact.wav'))), 1)


if __name__ == '__main__':unittest.main()
