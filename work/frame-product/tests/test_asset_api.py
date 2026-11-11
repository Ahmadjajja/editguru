import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_asset_api as api
import quick_asset_library as library
import quick_timeline as timeline


class AssetAPITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.pid = 'a'*32; self.other = 'b'*32
        root = Path(temp.name)
        for pid in (self.pid,self.other):
            (root/pid).mkdir(); (root/pid/'input.mp4').write_bytes(b'original source')
        self.app = types.SimpleNamespace(WORK=root, project=lambda pid:{'name':'Fixture','current_segments':None})
        probe = patch.object(timeline,'probe',return_value={'duration':12,'audio':True}); probe.start(); self.addCleanup(probe.stop)
        timeline.load(self.app,self.pid); timeline.load(self.app,self.other)

    def test_completed_render_preserved_and_shared(self):
        eid = 'c'*32; folder = self.app.WORK/self.pid/'versions'/eid; folder.mkdir(parents=True)
        (folder/'edited.mp4').write_bytes(b'saved render')
        doc = timeline.load(self.app,self.pid)
        doc['exports']=[{'id':eid,'status':'done','timeline_version':doc['version']}]
        timeline.write(self.app.WORK/self.pid/'timeline.json',doc)
        saved = api.execute(self.app,'save_library_asset',{'project_id':self.pid,'export_id':eid})['asset']
        (folder/'edited.mp4').unlink()
        self.assertEqual(library.resolve(self.app,saved['id']).read_bytes(),b'saved render')
        self.assertEqual(saved['kind'],'render')
        self.assertEqual(saved['metadata']['provenance']['export_id'],eid)
        self.assertEqual(api.execute(self.app,'get_library_asset',{'library_asset_id':saved['id']})['asset']['id'],saved['id'])

    def test_legacy_completed_render_can_be_promoted(self):
        eid = 'f'*32; folder = self.app.WORK/self.pid/'versions'/eid; folder.mkdir(parents=True)
        (folder/'edited.mp4').write_bytes(b'legacy render')
        self.app.project = lambda pid:{'name':'Fixture','versions':[{'id':eid}]}
        saved=api.execute(self.app,'save_library_asset',{'project_id':self.pid,'export_id':eid,'scope':'shared'})['asset']
        self.assertEqual(saved['kind'],'render')
        self.assertIsNone(saved['project_id'])

    def test_scoped_access_and_cross_project_attach_rejected(self):
        saved = api.execute(self.app,'save_library_asset',{'project_id':self.pid,'export_id':'source','scope':'project'})['asset']
        for args in ({'library_asset_id':saved['id']},{'library_asset_id':saved['id'],'project_id':self.other}):
            with self.assertRaises(ValueError):api.execute(self.app,'get_library_asset',args)
        with self.assertRaises(ValueError):api.execute(self.app,'attach_library_asset',{'library_asset_id':saved['id'],'project_id':self.other,'expected_version':1})
        self.assertEqual(api.execute(self.app,'get_library_asset',{'library_asset_id':saved['id'],'project_id':self.pid})['asset']['id'],saved['id'])

    def test_reject_missing_or_ambiguous_source_and_incomplete_export(self):
        for args in ({},{'asset_id':'d'*32,'export_id':'source'},{'export_id':'d'*32}):
            with self.assertRaises(ValueError):api.execute(self.app,'save_library_asset',{'project_id':self.pid,**args})

    def test_source_paths_cannot_escape_project(self):
        doc = timeline.load(self.app,self.pid); aid='e'*32
        secret=self.app.WORK/'secret.wav';secret.write_bytes(b'not a project asset')
        doc['assets']=[{'id':aid,'name':'secret.wav','path':'../secret.wav'}]
        timeline.write(self.app.WORK/self.pid/'timeline.json',doc)
        with self.assertRaises(ValueError):api.execute(self.app,'save_library_asset',{'project_id':self.pid,'asset_id':aid})
        (self.app.WORK/self.pid/'link.wav').symlink_to(secret)
        doc['assets'][0]['path']='link.wav';timeline.write(self.app.WORK/self.pid/'timeline.json',doc)
        with self.assertRaises(ValueError):api.execute(self.app,'save_library_asset',{'project_id':self.pid,'asset_id':aid})

    def test_attach_conflict_returns_409_without_mutation(self):
        saved=api.execute(self.app,'save_library_asset',{'project_id':self.pid,'export_id':'source'})['asset']
        payload=json.dumps({'operation':'attach_library_asset','library_asset_id':saved['id'],'project_id':self.pid,'expected_version':999}).encode()
        calls=[];handler=types.SimpleNamespace(path='/api/quick/library',headers={'Content-Length':str(len(payload))},rfile=io.BytesIO(payload),json=lambda status,data:calls.append((status,data)))
        before=(self.app.WORK/self.pid/'timeline.json').read_bytes()
        self.assertTrue(api.route(handler,self.app,'POST'));self.assertEqual(calls[0][0],409)
        self.assertEqual((self.app.WORK/self.pid/'timeline.json').read_bytes(),before)

    def test_index_project_backfills_files_and_renders_idempotently(self):
        aid, eid, legacy_id = '1'*32, '2'*32, '3'*32
        doc=timeline.load(self.app,self.pid)
        folder=self.app.WORK/self.pid/'assets'/aid; folder.mkdir(parents=True)
        (folder/'sound.wav').write_bytes(b'saved sound')
        doc['assets']=[{'id':aid,'name':'sound.wav','path':'assets/'+aid+'/sound.wav','kind':'sound_effect','tags':['whoosh']}]
        doc['exports']=[{'id':eid,'status':'done','timeline_version':1},{'id':'4'*32,'status':'working'}]
        for item in (eid,legacy_id):
            folder=self.app.WORK/self.pid/'versions'/item;folder.mkdir(parents=True)
            (folder/'edited.mp4').write_bytes(('render '+item).encode())
        self.app.project=lambda pid:{'name':'Fixture','versions':[{'id':eid},{'id':legacy_id}]}
        timeline.write(self.app.WORK/self.pid/'timeline.json',doc)
        before=(self.app.WORK/self.pid/'timeline.json').read_bytes()
        args={'project_id':self.pid}
        indexed=api.execute(self.app,'index_project_assets',args)
        again=api.execute(self.app,'index_project_assets',args)
        self.assertEqual(indexed['assets'][0]['kind'],'sound_effect')
        self.assertEqual(indexed['assets'][0]['tags'],['whoosh'])
        self.assertEqual(indexed['candidates_count'],3)
        self.assertFalse(indexed['truncated']);self.assertEqual(indexed['errors'],[])
        self.assertEqual([r['id'] for r in indexed['assets']],[r['id'] for r in again['assets']])
        self.assertEqual({r['project_id'] for r in indexed['assets']},{self.pid})
        self.assertEqual(len(library.search(self.app,project_id=self.pid)),3)
        self.assertEqual((self.app.WORK/self.pid/'timeline.json').read_bytes(),before)
        self.assertEqual(library.search(self.app),[])

    def test_index_project_limits_reports_errors_and_source_is_optional(self):
        doc=timeline.load(self.app,self.pid)
        doc['assets']=[{'id':'1'*32,'name':'missing.wav','path':'assets/missing.wav'}]
        timeline.write(self.app.WORK/self.pid/'timeline.json',doc)
        indexed=api.execute(self.app,'index_project_assets',{'project_id':self.pid,'include_source':True,'include_renders':False,'limit':1})
        self.assertTrue(indexed['truncated']);self.assertEqual(indexed['candidates_count'],2)
        self.assertEqual(indexed['assets'],[]);self.assertEqual(indexed['errors'][0]['asset_id'],'1'*32)
        indexed=api.execute(self.app,'index_project_assets',{'project_id':self.pid,'include_source':True,'include_renders':False,'limit':2})
        self.assertEqual(len(indexed['assets']),1);self.assertEqual(len(indexed['errors']),1)
        self.assertEqual(indexed['assets'][0]['metadata']['provenance']['export_id'],'source')

    def test_index_project_validates_boolean_flags_and_limit(self):
        for invalid in ({'include_source':'true'},{'include_renders':1},{'limit':True},{'limit':0},{'limit':201}):
            with self.assertRaises(ValueError):api.execute(self.app,'index_project_assets',{'project_id':self.pid,**invalid})

    def test_request_limit_and_non_object(self):
        for payload,size in ((b'[]',2),(b'{}',1024*1024+1)):
            calls=[];handler=types.SimpleNamespace(path='/api/quick/library',headers={'Content-Length':str(size)},rfile=io.BytesIO(payload),json=lambda status,data:calls.append(status))
            api.route(handler,self.app,'POST');self.assertEqual(calls,[400])

if __name__ == '__main__':unittest.main()
