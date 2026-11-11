import io
import json
from pathlib import Path
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch
import quick_assets as assets
import quick_timeline as timeline

class CreativeStorageTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.pid='d'*32;root=Path(t.name);(root/self.pid).mkdir();(root/self.pid/'input.mp4').write_bytes(b'original unit fixture')
        self.app=types.SimpleNamespace(WORK=root,MAX_UPLOAD=700*1024*1024,project=lambda _: {'name':'Fixture','current_segments':None})
        mock=patch.object(timeline,'probe',return_value={'duration':12,'audio':True});mock.start();self.addCleanup(mock.stop)
        self.doc=timeline.load(self.app,self.pid)
    def upload(self,name,data,length=None):
        h=types.SimpleNamespace(headers={'Content-Length':str(len(data) if length is None else length),'X-Filename':name},rfile=io.BytesIO(data),connection=types.SimpleNamespace(settimeout=lambda _:None))
        return assets.upload(h,self.app,self.pid)
    def test_upload_preserves_bytes_and_uses_safe_paths(self):
        d=self.upload('../../image.png',b'image bytes');a=d['assets'][0]
        self.assertEqual(a['name'],'image.png');self.assertEqual((self.app.WORK/self.pid/a['path']).read_bytes(),b'image bytes')
        self.assertEqual(d['revision_id'],self.doc['revision_id']);self.assertEqual((self.app.WORK/self.pid/'input.mp4').read_bytes(),b'original unit fixture')
    def test_interrupted_upload_does_not_corrupt_project(self):
        before=(self.app.WORK/self.pid/'timeline.json').read_bytes()
        with self.assertRaises(ValueError):self.upload('broken.wav',b'abc',50)
        self.assertEqual((self.app.WORK/self.pid/'timeline.json').read_bytes(),before)
    def test_error_after_metadata_commit_keeps_bytes_and_retry_reuses_asset(self):
        sync=assets.os.fsync;directory_inode=(self.app.WORK/self.pid).stat().st_ino
        def failed_directory_sync(fd):
            if assets.os.fstat(fd).st_ino==directory_inode:raise OSError('directory sync failed after commit')
            return sync(fd)
        with patch.object(assets.os,'fsync',side_effect=failed_directory_sync),self.assertRaises(OSError):
            self.upload('saved.wav',b'uploaded audio')
        doc=timeline.load(self.app,self.pid);self.assertEqual(len(doc['assets']),1)
        asset=doc['assets'][0]
        self.assertEqual((self.app.WORK/self.pid/asset['path']).read_bytes(),b'uploaded audio')
        retry=self.upload('saved.wav',b'uploaded audio')
        self.assertEqual(retry['uploaded_asset_id'],asset['id'])
        self.assertTrue(retry['asset_reused'])
        self.assertEqual(retry['version'],doc['version'])
        bundle=assets.bundle(self.app,self.pid)
        try:
            with zipfile.ZipFile(bundle) as archive:self.assertEqual(archive.read(asset['path']),b'uploaded audio')
        finally:Path(bundle).unlink()

    def test_error_before_metadata_commit_cleans_unreferenced_bytes(self):
        path=self.app.WORK/self.pid/'timeline.json';before=path.read_bytes()
        with patch.object(timeline,'write',side_effect=OSError('write failed')),self.assertRaises(OSError):
            self.upload('unsaved.wav',b'uploaded audio')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(list((self.app.WORK/self.pid/'assets').iterdir()),[])

    def test_uncertain_commit_keeps_bytes_if_saved_metadata_cannot_be_read(self):
        read=Path.read_text;uncertain=False
        def failed_write(path,value):
            nonlocal uncertain
            uncertain=True;raise OSError('write outcome unknown')
        def unavailable(path,*args,**kwargs):
            if uncertain and path==self.app.WORK/self.pid/'timeline.json':raise PermissionError('metadata read failed')
            return read(path,*args,**kwargs)
        with patch.object(timeline,'write',side_effect=failed_write),patch.object(Path,'read_text',unavailable),self.assertRaises(OSError):
            self.upload('uncertain.wav',b'uploaded audio')
        files=list((self.app.WORK/self.pid/'assets').rglob('uncertain.wav'))
        self.assertEqual(len(files),1)
        self.assertEqual(files[0].read_bytes(),b'uploaded audio')

    def test_bundle_has_manifest_source_and_arbitrary_creative_data(self):
        d=self.upload('notes.tmp',b'creative notes');self.upload('audio.wav',b'audio fixture')
        name=assets.bundle(self.app,self.pid)
        try:
            with zipfile.ZipFile(name) as z:
                self.assertEqual(z.read('input.mp4'),b'original unit fixture')
                self.assertEqual(z.read(d['assets'][0]['path']),b'creative notes')
                manifest=json.loads(z.read('project.frameproj.json'))
                self.assertEqual(manifest['format'],'frame-project/1');self.assertEqual(len(manifest['revision']['assets']),2)
                self.assertEqual(manifest['revision']['revision_id'],self.doc['revision_id'])
        finally:Path(name).unlink()
    def test_bundle_never_follows_external_symlinks(self):
        outside=self.app.WORK/'private.txt';outside.write_text('outside fixture');(self.app.WORK/self.pid/'linked.txt').symlink_to(outside)
        name=assets.bundle(self.app,self.pid)
        try:
            with zipfile.ZipFile(name) as z:self.assertNotIn('linked.txt',z.namelist())
        finally:Path(name).unlink()

if __name__=='__main__':unittest.main()
