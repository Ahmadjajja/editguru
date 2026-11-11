import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import quick_presenter as p
import quick_timeline as q


class PresenterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.app=types.SimpleNamespace(WORK=self.root,project=lambda pid:json.loads((self.root/pid/'project.json').read_text()))
        self.brief={'name':'Creator story','script':'Keep these exact words.','character':'Use my attached portrait.',
                    'voice':'Use my sample.','style':'Warm light; readable kinetic captions.','duration':30,'aspect_ratio':'9:16','captions':True}

    def call(self,name,**args):return p.execute(self.app,name,args)
    def create(self):
        self.job=self.call('save_presenter_brief',request_id='a'*32,brief=self.brief)['presenter_job']
        return self.job
    def current(self):
        self.job=self.call('get_presenter_video',creation_id=self.job['creation_id'])['presenter_job'];return self.job
    def change(self,name,**args):
        result=self.call(name,creation_id=self.job['creation_id'],expected_version=self.current()['version'],receipt_token=self.token,**args)
        self.job=result['presenter_job'];return result
    def start(self):
        self.create()
        r=self.call('begin_presenter_handoff',creation_id=self.job['creation_id'],expected_version=self.job['version'])
        self.token=p.read(self.app,self.job['creation_id'])['receipt_token']
        self.job=self.call('acknowledge_presenter_run',creation_id=self.job['creation_id'],receipt_token=self.token)['presenter_job']
        return r
    def approve(self):
        self.start()
        self.change('quote_presenter_video',credits=100,plan='One presenter, native voice, three takes plus music.',references=[{'media_id':'actual-user-portrait','role':'presenter'}])
        r=self.call('approve_presenter_quote',creation_id=self.job['creation_id'],expected_version=self.job['version'],quote_id=self.job['quote']['id'])
        self.token=p.read(self.app,self.job['creation_id'])['receipt_token'];self.current()
        self.call('acknowledge_presenter_run',creation_id=self.job['creation_id'],receipt_token=self.token);self.current()
        return r
    def step(self,status='submitting',**extra):
        return self.change('update_presenter_run',stage='Generating presenter',step={'id':'take-01','status':status,'description':'Presenter take','credits':60,**extra})

    def test_save_is_idempotent_literal_and_versioned(self):
        first=self.create();again=self.create();self.assertEqual(first,again)
        self.assertNotIn('receipt_token',first)
        with self.assertRaises(ValueError):self.call('save_presenter_brief',request_id='a'*32,brief={**self.brief,'script':'Changed'})
        with self.assertRaises(q.Conflict):self.call('save_presenter_brief',request_id='b'*32,creation_id=first['creation_id'],expected_version=0,brief=self.brief)
        self.assertEqual(self.current()['brief']['script'],self.brief['script'])
        self.assertEqual(len(list((self.root/'presenter-creations').glob('*.json'))),1)

    def test_parallel_handoffs_reserve_once_and_ambiguous_delivery_never_resends(self):
        self.create();args={'creation_id':self.job['creation_id'],'expected_version':self.job['version']}
        def reserve(_):
            try:return self.call('begin_presenter_handoff',**args)
            except q.Conflict:return {'may_send':False}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(reserve,range(8)))
        self.assertEqual(sum(r['may_send'] for r in rows),1)
        r=next(r for r in rows if r['may_send'])
        self.call('finish_presenter_handoff',creation_id=self.job['creation_id'],handoff_id=r['handoff_id'],status='uncertain')
        r=self.call('begin_presenter_handoff',creation_id=self.job['creation_id'],expected_version=self.current()['version'])
        self.assertFalse(r['may_send']);self.assertIn('quote_presenter_video',r['prompt'])
        self.assertEqual(self.current()['status'],'requested')

    def test_definitively_unsent_can_retry_but_received_cannot_be_downgraded(self):
        self.create();r=self.call('begin_presenter_handoff',creation_id=self.job['creation_id'],expected_version=1)
        self.call('finish_presenter_handoff',creation_id=self.job['creation_id'],handoff_id=r['handoff_id'],status='not_sent')
        r=self.call('begin_presenter_handoff',creation_id=self.job['creation_id'],expected_version=self.current()['version']);self.assertTrue(r['may_send'])
        token=p.read(self.app,self.job['creation_id'])['receipt_token']
        self.call('acknowledge_presenter_run',creation_id=self.job['creation_id'],receipt_token=token)
        r=self.call('finish_presenter_handoff',creation_id=self.job['creation_id'],handoff_id=r['handoff_id'],status='submitted')
        self.assertEqual(r['delivery_status'],'received')

    def test_plan_requires_approval_before_any_attempt(self):
        self.start()
        with self.assertRaises(ValueError):self.step()
        self.change('quote_presenter_video',credits=100,plan='Three takes')
        with self.assertRaises(ValueError):self.step()
        with self.assertRaises(ValueError):self.call('approve_presenter_quote',creation_id=self.job['creation_id'],expected_version=self.job['version'],quote_id='wrong')
        with self.assertRaises(ValueError):self.call('save_presenter_brief',request_id='b'*32,creation_id=self.job['creation_id'],expected_version=self.job['version'],brief=self.brief)

    def test_attempts_job_ids_and_total_budget_survive_reloads(self):
        self.approve();self.step();self.step('submitted',job_id='provider-real-001');self.step('done')
        with self.assertRaises(ValueError):self.step('submitting')
        with self.assertRaises(ValueError):self.step('done',job_id='replacement-job')
        with self.assertRaises(ValueError):self.change('update_presenter_run',stage='Next',step={'id':'take-02','status':'submitting','description':'Second take','credits':50})
        reloaded=json.loads(p.path(self.app,self.job['creation_id']).read_text())
        self.assertEqual(reloaded['steps'][0]['job_id'],'provider-real-001');self.assertEqual(reloaded['steps'][0]['credits'],60)
        self.assertEqual(reloaded['quote']['references'][0]['media_id'],'actual-user-portrait')

    def test_uncertain_attempt_blocks_completion_and_requote(self):
        self.approve();self.step();self.step('uncertain')
        with self.assertRaises(ValueError):self.change('quote_presenter_video',credits=100,plan='Try again')
        with self.assertRaises(ValueError):self.change('complete_presenter_video',result_project_id='f'*32,sha256='f'*64,review='Not rendered')
        with self.assertRaises(ValueError):self.step('submitting')

    def test_requotes_preserve_approved_history_and_count_failed_attempts(self):
        self.approve();self.step();self.step('failed')
        with self.assertRaises(ValueError):self.change('quote_presenter_video',credits=50,plan='Smaller')
        self.change('quote_presenter_video',credits=120,plan='Replacement take plus already allocated 60 credits')
        self.assertIn('approved_at',self.job['previous_quotes'][0]);self.assertEqual(self.job['steps'][0]['status'],'failed')
        with self.assertRaises(ValueError):self.step()

    def test_receipt_scope_and_stale_versions_cannot_mutate(self):
        self.start()
        with self.assertRaises(ValueError):self.call('acknowledge_presenter_run',creation_id=self.job['creation_id'],receipt_token='other-chat')
        with self.assertRaises(q.Conflict):self.call('update_presenter_run',creation_id=self.job['creation_id'],receipt_token=self.token,expected_version=0,stage='Wrong')
        with self.assertRaises(ValueError):self.call('get_presenter_video',creation_id='../escape')

    def test_real_mp4_result_opens_editable_project_and_completion_is_idempotent(self):
        self.approve();self.step();self.step('submitted',job_id='fixture-job');self.step('done')
        pid='f'*32;folder=self.root/pid;folder.mkdir()
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=160x284:d=1',
                        '-f','lavfi','-i','sine=frequency=440:duration=1','-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(folder/'input.mp4')],check=True)
        q.write(folder/'project.json',{'id':pid,'name':'Generated fixture.mp4','versions':[],'history':[],'current_segments':None})
        digest=hashlib.sha256((folder/'input.mp4').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.change('complete_presenter_video',result_project_id=pid,sha256='0'*64,review='Fixture only')
        args=dict(result_project_id=pid,sha256=digest,review='Synthetic fixture validates import and editing; no generated presenter or creative review claimed.')
        before=self.current()['version'];r=self.change('complete_presenter_video',**args)
        self.assertEqual(r['project']['presenter_creation_id'],self.job['creation_id'])
        self.assertEqual(r['presenter_job']['status'],'complete');doc=r['project']
        repeat=self.call('complete_presenter_video',creation_id=self.job['creation_id'],receipt_token=self.token,expected_version=before,**args)
        self.assertEqual(repeat['presenter_job']['version'],self.job['version'])
        edited=q.execute(self.app,pid,'trim_clip',{'expected_version':doc['version'],'clip_id':doc['clips'][0]['id'],'start':0,'end':.5})
        self.assertAlmostEqual(edited['duration'],.5,places=2)
        (folder/'input.mp4').write_bytes(b'changed source')
        with self.assertRaises(ValueError):self.call('complete_presenter_video',creation_id=self.job['creation_id'],receipt_token=self.token,expected_version=before,**args)

    def test_actual_http_mcp_call_reaches_server_and_has_no_project_requirement(self):
        import app
        import quick_mcp
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.shutdown)
        with patch.object(app,'WORK',self.root),patch.object(quick_mcp,'BASE','http://127.0.0.1:'+str(server.server_port)):
            tool=next(t for t in quick_mcp.tools() if t['name']=='save_presenter_brief')
            self.assertNotIn('project_id',tool['inputSchema']['required'])
            response=quick_mcp.dispatch({'id':1,'method':'tools/call','params':{'name':'save_presenter_brief','arguments':{'request_id':'a'*32,'brief':self.brief}}})['result']
            self.assertFalse(response['isError']);self.assertEqual(response['structuredContent']['presenter_job']['brief']['script'],self.brief['script'])
            self.assertIn('ui',next(t for t in quick_mcp.tools() if t['name']=='open_presenter_studio')['_meta'])

    def test_provider_result_import_uses_exact_bytes_once_and_recovers_lost_response(self):
        self.approve();self.step();self.step('submitted',job_id='real-fixture-job');self.step('done')
        source=self.root/'verified-final.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=purple:s=160x284:d=1',
            '-f','lavfi','-i','sine=frequency=550:duration=1','-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        args={'download_url':'https://provider.example/actual-tool-result.mp4','media_id':'confirmed-final-media',
              'sha256':digest,'review':'Real MP4 transport fixture; creative presenter generation is untested.'}
        def download(url,stream):
            self.assertEqual(url,args['download_url']);stream.write(source.read_bytes())
        with patch('quick_import.download',side_effect=download) as transfer:
            version=self.current()['version'];r=self.change('import_presenter_video',**args)
            replay=self.call('import_presenter_video',creation_id=self.job['creation_id'],receipt_token=self.token,expected_version=version,**args)
            self.assertEqual(transfer.call_count,1)
        self.assertEqual(r['project']['project_id'],replay['project']['project_id'])
        self.assertEqual((self.root/r['project_id']/'input.mp4').read_bytes(),source.read_bytes())
        self.assertEqual(self.job['final_media']['media_id'],'confirmed-final-media')
        self.assertEqual(len(list(self.root.glob('*/input.mp4'))),1)
        self.assertFalse(list(self.root.glob('*.presenter.mp4')))

    def test_import_hash_failure_and_private_url_leave_no_project(self):
        self.approve();self.step();self.step('submitted',job_id='fixture');self.step('done')
        args={'download_url':'https://127.0.0.1/private','media_id':'final','sha256':'0'*64,'review':'Fixture'}
        with self.assertRaises(ValueError):self.change('import_presenter_video',**args)
        with patch('quick_import.download',side_effect=lambda url,stream:stream.write(b'wrong bytes')):
            with self.assertRaisesRegex(ValueError,'does not match'):self.change('import_presenter_video',**args)
        self.assertEqual(self.current()['status'],'generating');self.assertFalse(list(self.root.glob('*/input.mp4')))
        self.assertFalse(list(self.root.glob('*.presenter.mp4')))


if __name__=='__main__':unittest.main()
