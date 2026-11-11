import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import quick_runtime as runtime

class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name).resolve()/'installation';(self.state/'projects').mkdir(parents=True)
        self.own=self.make_runtime('old');self.next=self.make_runtime('new')
        for name,value in [('__file__',str(self.own/'quick_runtime.py')),('_healthy_until',0),('_healthy_base',None),('_starting',{})]:
            mock=patch.object(runtime,name,value);mock.start();self.addCleanup(mock.stop)
        mock=patch.object(Path,'home',return_value=Path(self.temp.name)/'home');mock.start();self.addCleanup(mock.stop)

    def make_runtime(self,label):
        content=('pass # '+label).encode();page=('editor-'+label).encode();manifest=json.dumps({'files':[{'path':'frame/app.py','sha256':hashlib.sha256(content).hexdigest()},{'path':'frame/frame_widget.html','sha256':hashlib.sha256(page).hexdigest()}]}).encode();digest=hashlib.sha256(manifest).hexdigest()
        root=self.state/'runtimes'/digest;frame=root/'frame';frame.mkdir(parents=True);(frame/'app.py').write_bytes(content);(frame/'frame_widget.html').write_bytes(page);(root/'MANIFEST.json').write_bytes(manifest);(frame/'jobs').symlink_to(self.state/'projects',target_is_directory=True)
        return frame

    def activate(self,frame=None,url='http://127.0.0.1:12345',status='ready',protocol=runtime.PROTOCOL):
        runtime.write_activation(self.state,{'schema_version':1,'status':status,'protocol_version':protocol,'manifest_sha256':(frame or self.next).parent.name,'url':url})

class ActiveRuntimeTests(RuntimeFixture):
    def test_same_connection_follows_new_runtime_even_on_same_port(self):
        self.activate(self.own)
        with patch.object(runtime,'health',return_value=True) as health,patch.object(runtime.subprocess,'Popen') as spawn:
            self.assertEqual(runtime.ensure_server('http://127.0.0.1:12345'),'http://127.0.0.1:12345')
            runtime.ensure_server('http://127.0.0.1:12345');self.assertEqual(health.call_count,1)
            self.activate(self.next);self.assertEqual(runtime.ensure_server('http://127.0.0.1:12345'),'http://127.0.0.1:12345');self.assertEqual(health.call_count,2);self.assertEqual(health.call_args.args[1],self.next)
            self.activate(self.next,url='http://127.0.0.1:23456');self.assertEqual(runtime.ensure_server('http://127.0.0.1:12345'),'http://127.0.0.1:23456')
            spawn.assert_not_called()

    def test_different_project_store_is_rejected(self):
        (self.next/'jobs').unlink();other=Path(self.temp.name)/'unrelated';other.mkdir();(self.next/'jobs').symlink_to(other,target_is_directory=True);self.activate()
        with patch.object(runtime,'health') as health,patch.object(runtime.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'project'):runtime.ensure_server('http://127.0.0.1:12345')
            health.assert_not_called();spawn.assert_not_called()

    def test_transitional_or_failed_update_never_spawns_old_code(self):
        for status in ['updating','failed']:
            with self.subTest(status=status):
                self.activate(status=status)
                with patch.object(runtime,'health') as health,patch.object(runtime.subprocess,'Popen') as spawn:
                    with self.assertRaisesRegex(RuntimeError,'updating|interrupted'):runtime.ensure_server('http://127.0.0.1:12345')
                    health.assert_not_called();spawn.assert_not_called()

    def test_manifest_or_protocol_tampering_fails_closed(self):
        self.activate(protocol=runtime.PROTOCOL+1)
        with self.assertRaisesRegex(RuntimeError,'connector needs an update'):runtime.active_target('http://127.0.0.1:12345')
        self.activate();(self.next.parent/'MANIFEST.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'metadata'):runtime.active_target('http://127.0.0.1:12345')

    def test_identity_and_live_protocol_must_match_selected_runtime(self):
        self.activate()
        for identity,protocol in [(hashlib.sha256(str(self.own).encode()).hexdigest(),runtime.PROTOCOL),(hashlib.sha256(str(self.next).encode()).hexdigest(),runtime.PROTOCOL+1)]:
            data={'ok':True,'operations':['frame_product'],'runtime_id':identity,'frame_connector_protocol':protocol}
            with self.subTest(identity=identity,protocol=protocol),patch.object(runtime.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())),patch.object(runtime.subprocess,'Popen') as spawn:
                with self.assertRaises(RuntimeError):runtime.ensure_server('http://127.0.0.1:12345')
                spawn.assert_not_called()

    def test_uninstalled_checkout_keeps_its_explicit_endpoint(self):
        self.activate();standalone=Path(self.temp.name).resolve()/'checkout/quick_runtime.py'
        with patch.object(runtime,'__file__',str(standalone)):
            self.assertEqual(runtime.active_target('http://127.0.0.1:34567'),('http://127.0.0.1:34567',standalone.parent,False))

    def test_editor_resource_follows_active_manifest_and_detects_changed_bundle(self):
        self.activate()
        self.assertEqual(runtime.active_editor('http://127.0.0.1:12345'),('http://127.0.0.1:12345','editor-new'))
        (self.next/'frame_widget.html').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'bundle changed'):runtime.active_editor('http://127.0.0.1:12345')

    def test_dangling_activation_link_is_rejected(self):
        (self.state/'active-runtime.json').symlink_to(self.state/'absent')
        with self.assertRaisesRegex(RuntimeError,'activation record'):runtime.active_target('http://127.0.0.1:12345')

    def test_bad_record_or_nonlocal_address_never_connects(self):
        for value in ['broken',json.dumps({'schema_version':1,'status':'ready','protocol_version':runtime.PROTOCOL,'manifest_sha256':self.next.parent.name,'url':'https://example.com'})]:
            (self.state/'active-runtime.json').write_text(value)
            with self.subTest(value=value),patch.object(runtime,'health') as health:
                with self.assertRaises(RuntimeError):runtime.ensure_server('http://127.0.0.1:12345')
                health.assert_not_called()

if __name__=='__main__':unittest.main()
