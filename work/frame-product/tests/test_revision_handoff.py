"""Delivery state must survive reloads without duplicating or applying edits."""
import concurrent.futures
import json
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch
import quick_timeline as q
import quick_mcp


class HandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pid = 'a' * 32
        root = Path(temp.name)
        (root / self.pid).mkdir()
        self.app = types.SimpleNamespace(WORK=root, project=lambda _: {'name': 'Fixture'})
        probe = patch.object(q, 'probe', return_value={'duration': 4, 'audio': True})
        probe.start()
        self.addCleanup(probe.stop)
        (root / self.pid / 'input.mp4').write_bytes(b'saved-video-fixture')
        self.doc = q.load(self.app, self.pid)
        self.original = (root / self.pid / 'timeline.json').read_bytes()

    def call(self, op, **args):
        return q.execute(self.app, self.pid, op, args)

    def begin(self, text='Trim source 0–1 seconds.'):
        return self.call('begin_revision_handoff', expected_version=1, prompt=text)

    def finish(self, row, status):
        return self.call('finish_revision_handoff', handoff_id=row['id'], attempt=row['attempt'], status=status)

    def test_reservation_survives_reload_and_concurrent_clicks(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: self.begin(), range(8)))
        self.assertEqual(sum(r['may_send'] for r in rows), 1)
        self.assertEqual(len({r['id'] for r in rows}), 1)
        self.assertFalse(self.begin()['may_send'])
        restored=q.public(q.load(self.app,self.pid))['revision_handoffs'][-1]
        self.assertEqual(restored['status'],'sending')
        self.assertNotIn('prompt',restored)
        self.assertNotIn('receipt_token',restored)
        self.assertEqual(len(q.load(self.app,self.pid)['checkpoints']),2)
        saved=q.load(self.app,self.pid)['checkpoints'][-1]
        self.assertEqual(saved['kind'],'prompt')
        self.assertEqual(saved['saved_video_id'],'source')

    def test_ambiguous_send_is_never_automatically_retried(self):
        row = self.begin()
        self.finish(row, 'uncertain')
        self.assertFalse(self.begin()['may_send'])
        changed = self.begin('Trim a different source range.')
        self.assertTrue(changed['may_send'])
        self.assertNotEqual(row['id'], changed['id'])

    def test_explicit_rejection_allows_retry_but_old_response_cannot_change_it(self):
        row = self.begin()
        self.finish(row, 'not_sent')
        retry = self.begin()
        self.assertTrue(retry['may_send'])
        self.assertEqual(retry['id'], row['id'])
        self.assertEqual(retry['attempt'], 2)
        with self.assertRaises(q.Conflict):
            self.finish(row, 'submitted')

    def test_host_submission_is_not_receipt_and_receipt_wins_transport_race(self):
        row = self.begin()
        self.assertEqual(self.finish(row, 'submitted')['status'], 'submitted')
        self.assertFalse(self.begin()['may_send'])
        token = re.search(r'receipt_token="([a-f0-9]{32})"', row['prompt'])[1]
        with self.assertRaises(ValueError):
            self.call('acknowledge_revision_handoff', handoff_id=row['id'], receipt_token='bad')
        result = self.call('acknowledge_revision_handoff', handoff_id=row['id'], receipt_token=token)
        self.assertEqual(result['status'], 'received')
        self.assertNotIn('receipt_token', result)
        self.assertEqual(self.finish(row, 'uncertain')['status'], 'received')
        self.assertEqual(len(q.load(self.app,self.pid)['checkpoints']),2)
        saved=q.load(self.app,self.pid)['checkpoints'][-1]
        self.assertEqual(saved['kind'],'prompt')
        self.assertEqual(saved['saved_video_id'],'source')

    def test_prompt_snapshot_is_immutable_and_stale_video_is_rejected(self):
        row=self.begin()
        saved=q.load(self.app,self.pid)['checkpoints'][-1]
        self.assertEqual(row['checkpoint_id'],saved['id'])
        import hashlib
        self.assertEqual(saved['video_sha256'],hashlib.sha256(b'saved-video-fixture').hexdigest())
        self.assertEqual(saved['prompt'],'Trim source 0–1 seconds.')
        doc=q.load(self.app,self.pid)
        doc['notes']=[{'id':'note','instruction':'Later change'}]
        doc['pins']=[{'id':'pin','start':0,'end':1}]
        q.write(self.app.WORK/self.pid/'timeline.json',doc)
        reloaded=q.load(self.app,self.pid)
        self.assertEqual(reloaded['checkpoints'][-1],saved)
        reloaded['clips'][0]['start']=1
        q.write(self.app.WORK/self.pid/'timeline.json',reloaded)
        with self.assertRaisesRegex(ValueError,'Export'):
            self.begin('New prompt with an unsaved timeline')
        self.assertEqual(len(q.load(self.app,self.pid)['revision_handoffs']),1)

    def test_stale_snapshot_oversize_and_unknown_ids_are_rejected(self):
        for args in [dict(expected_version=0, prompt='x'), dict(expected_version=True, prompt='x'),
                     dict(expected_version=1, prompt=''), dict(expected_version=1, prompt='☃' * 43000)]:
            with self.subTest(args=str(args)[:80]), self.assertRaises(ValueError):
                self.call('begin_revision_handoff', **args)
        with self.assertRaises(ValueError):
            self.call('get_revision_handoff', handoff_id='b' * 32)

    def test_tool_visibility_and_receipt_does_not_require_timeline_version(self):
        tools = {t['name']: t for t in quick_mcp.tools()}
        for name in ('begin_revision_handoff', 'finish_revision_handoff'):
            self.assertEqual(tools[name]['_meta']['ui']['visibility'], ['app'])
        self.assertIn('model', tools['acknowledge_revision_handoff']['_meta']['ui']['visibility'])
        self.assertNotIn('expected_version', tools['acknowledge_revision_handoff']['inputSchema']['required'])
        self.assertTrue(tools['get_revision_handoff']['annotations']['readOnlyHint'])


if __name__ == '__main__':
    unittest.main()
