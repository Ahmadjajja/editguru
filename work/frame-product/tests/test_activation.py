import io
import json
import hashlib
from unittest.mock import patch
import unittest
import quick_activation as activation
import quick_runtime as runtime
from test_active_runtime import RuntimeFixture

class ActivationTests(RuntimeFixture):
    def test_activation_keeps_browser_address_and_publishes_only_after_health(self):
        self.activate(self.own);before=(self.state/'active-runtime.json').read_bytes()
        sentinel=self.state/'projects/saved.txt';sentinel.write_text('saved work')
        def stopped(state):
            with self.assertRaisesRegex(RuntimeError,'updating'):runtime.active_target('http://127.0.0.1:12345')
            return {'stopped':True,'servers':[{'url':'http://127.0.0.1:12345'}]}
        with patch.object(activation,'stop_owned_servers',side_effect=stopped),patch.object(runtime,'ensure_server',return_value='http://127.0.0.1:12345') as ensure,patch.object(runtime,'health',return_value=True):
            result=activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
        self.assertEqual(result['url'],'http://127.0.0.1:12345');self.assertEqual(result['status'],'ready');ensure.assert_called_once_with('http://127.0.0.1:12345',follow_active=False)
        self.assertEqual(sentinel.read_text(),'saved work');self.assertNotEqual((self.state/'active-runtime.json').read_bytes(),before)

    def test_busy_stop_restores_previous_activation(self):
        self.activate(self.own);before=(self.state/'active-runtime.json').read_bytes()
        with patch.object(activation,'stop_owned_servers',side_effect=RuntimeError('Frame is busy')),patch.object(runtime,'ensure_server') as ensure:
            with self.assertRaisesRegex(RuntimeError,'busy'):activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
            ensure.assert_not_called()
        self.assertEqual((self.state/'active-runtime.json').read_bytes(),before)

    def test_unverified_stop_blocks_fallback_and_new_startup(self):
        self.activate(self.own)
        with patch.object(activation,'stop_owned_servers',side_effect=activation.StopPending('still responding')),patch.object(runtime,'ensure_server') as ensure:
            with self.assertRaisesRegex(activation.StopPending,'responding'):activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
            ensure.assert_not_called()
        record=json.loads((self.state/'active-runtime.json').read_text());self.assertEqual(record['status'],'failed');self.assertEqual(record['phase'],'stopping')
        with self.assertRaisesRegex(RuntimeError,'interrupted'):runtime.active_target('http://127.0.0.1:12345')

    def test_failed_start_is_durable_and_does_not_fall_back(self):
        self.activate(self.own)
        with patch.object(activation,'stop_owned_servers',return_value={'servers':[]}),patch.object(runtime,'ensure_server',side_effect=RuntimeError('startup failed')):
            with self.assertRaisesRegex(RuntimeError,'startup failed'):activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
        self.assertEqual(json.loads((self.state/'active-runtime.json').read_text())['status'],'failed')
        with patch.object(runtime.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'interrupted'):runtime.ensure_server('http://127.0.0.1:12345')
            spawn.assert_not_called()

    def test_pending_startup_is_observed_without_restart(self):
        self.activate(self.next,url='http://127.0.0.1:23456',status='failed')
        record=json.loads((self.state/'active-runtime.json').read_text());record['startup_pid']=123;runtime.write_activation(self.state,record)
        with patch.object(activation.os,'kill'),patch.object(runtime,'health',return_value=False),patch.object(activation,'stop_owned_servers') as stop,patch.object(runtime,'ensure_server') as ensure:
            with self.assertRaisesRegex(RuntimeError,'still running'):activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
            stop.assert_not_called();ensure.assert_not_called()
        with patch.object(activation.os,'kill'),patch.object(runtime,'health',return_value=True),patch.object(activation,'stop_owned_servers') as stop:
            result=activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
            self.assertTrue(result['recovered']);stop.assert_not_called()

    def test_duplicate_version_records_share_one_verified_endpoint(self):
        for frame in [self.own,self.next]:(self.state/('endpoint-'+frame.parent.name+'.json')).write_text(json.dumps({'url':'http://127.0.0.1:12345'}))
        health={'ok':True,'runtime_id':hashlib.sha256(str(self.next).encode()).hexdigest()}
        with patch.object(activation.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(health).encode())) as opened:
            result=activation.live_servers(self.state);self.assertEqual(len(result),1);self.assertEqual(opened.call_count,1)
        with patch.object(activation.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'ok':True,'runtime_id':'unrelated'}).encode())):
            with self.assertRaisesRegex(RuntimeError,'Another installation'):activation.live_servers(self.state)

    def test_changed_code_is_rejected_before_any_stop(self):
        (self.next/'app.py').write_text('changed')
        with patch.object(activation,'stop_owned_servers') as stop:
            with self.assertRaisesRegex(RuntimeError,'code changed'):activation.activate(self.next.parent,'http://127.0.0.1:23456',(self.next.parent/'MANIFEST.json').read_bytes())
            stop.assert_not_called()

if __name__=='__main__':unittest.main()
