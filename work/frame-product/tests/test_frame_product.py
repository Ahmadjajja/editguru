"""Frame lifecycle contracts with temporary storage and no external generation.

These tests exercise orchestration, persistence and credit gates. Compositor
output is deliberately fake; real media checks belong to the graphics suite.
"""
import copy
import io
import json
import struct
import sys
import tempfile
import time
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frame_product as frame
import frame_graphics
import studio
import studio_inputs
import studio_mcp_voice as fish
import studio_voice


SCRIPT = 'Make this idea real.'
VOICE = '1' * 32


def plan():
    return {'identity': {
        'name': 'Your idea', 'intent': 'Invite creation', 'audience': 'Creators',
        'feeling': 'Possibility', 'rationale': 'Give the idea a clear focal point.',
        'background': '#101112', 'foreground': '#EEEEDA', 'accent': '#FF281C',
        'style': 'kinetic', 'motion': 'punchy', 'voice': 'confident', 'pace': 1.0,
    }, 'scenes': [{
        'narration': SCRIPT, 'headline': 'Make it real', 'support': '',
        'rationale': 'Focus on the idea.', 'visual': 'spotlight', 'energy': .6,
        'asset_id': None,
    }]}


class Request:
    def __init__(self, path, body=None, raw=None, headers=None):
        self.path = path
        encoded = json.dumps(body).encode() if raw is None else raw
        self.headers = {'Content-Length': str(len(encoded)), **(headers or {})}
        self.rfile = io.BytesIO(encoded)
        self.close_connection = False
        self.response = None

    def json(self, code, body):
        self.response = code, body


class FrameProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.studio_store = self.root / 'studio'
        self.studio_store.mkdir()
        self.store = self.studio_store / 'frame'
        self.store.mkdir()
        self.patches = [
            patch.object(frame, 'STORE', self.store),
            patch.object(studio, 'STORE', self.studio_store),
            patch.object(studio, 'ASSETS', self.studio_store / 'assets'),
            patch.object(studio_inputs, 'VOICES', self.studio_store / 'voices'),
            patch.object(studio_inputs, 'SETTINGS', self.root / 'unused-fish.json'),
            patch.object(fish, 'SETTINGS', self.root / 'unused-voice.json'),
            patch.object(frame, 'launch'),
            patch.object(studio_inputs, 'validate_voice', side_effect=self.valid_voice),
            patch.object(studio_inputs, 'voice_context', return_value={}),
            patch.object(frame, 'direct', return_value=(plan(), {'summary': 'Clear idea.', 'changes': []})),
            patch.object(frame.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=2 * 1024**3)),
            patch.object(fish.mcp, 'call_tool', side_effect=AssertionError('External Fish calls forbidden in product tests')),
            patch.object(fish, 'quote', side_effect=lambda *args, **kwargs: self.quoted()),
            patch.object(fish, 'synthesize_mcp', side_effect=self.synthesize),
            patch.object(studio_voice, 'synthesize_narration', side_effect=self.synthesize),
            patch.object(frame_graphics, 'render_graphics', side_effect=self.render),
        ]
        mocks = [p.start() for p in self.patches]
        self.launch = mocks[6]
        self.validate_voice = mocks[7]
        self.direct = mocks[9]
        self.external = mocks[11]
        self.quote = mocks[12]
        self.fish_speech = mocks[13]
        self.edge_speech = mocks[14]
        self.graphics = mocks[15]

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def valid_voice(self, requested, _script=None):
        provider = requested.get('provider', 'fish-mcp')
        return {'mode': 'ai', 'provider': provider, 'recording_id': None,
                **({'voice_id': VOICE, 'voice_name': 'Fixture voice', 'model': 'drama-3'}
                   if provider == 'fish-mcp' else {})}

    def quoted(self, **overrides):
        value = plan()
        units = fish._compile(frame.voice_units(value), value['identity'], VOICE, 'drama-3')
        quote = {'quote_id': 'e' * 32, 'created_at': time.time(),
                 'request_sha256': fish._digest(units), 'voice_id': VOICE, 'model': 'drama-3',
                 'total_bytes': sum(u['bytes'] for u in units),
                 'units': [{**u, 'credits': 10} for u in units],
                 'total_credits': 10 * len(units), 'available_credits': 1000,
                 'has_sufficient_balance': True}
        quote.update(overrides)
        return quote

    def audio(self, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        wav = output / 'narration.wav'
        with wave.open(str(wav), 'wb') as stream:
            stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            stream.writeframes(struct.pack('<h', 1200) * 48000)
        return {'provider': 'fixture unchanged narration', 'voice': VOICE,
                'audio': str(wav), 'duration': 1.0, 'frames': 30, 'fps': 30,
                'warnings': [], 'scenes': [{
                    'narration': SCRIPT, 'start': 0.0, 'end': 1.0,
                    'start_frame': 0, 'end_frame': 30,
                    'words': [{'text': word, 'start': i * .2, 'end': (i + 1) * .2}
                              for i, word in enumerate(SCRIPT.split())],
                }]}

    def synthesize(self, output, *_args, **_kwargs):
        return self.audio(output)

    def render(self, output, timing, _plan, _idea, **kwargs):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        feedback = kwargs.get('feedback', '')
        (output / 'export.mp4').write_bytes(b'fake-video:' + feedback.encode())
        (output / 'poster.jpg').write_bytes(b'fake-poster')
        return {'duration': 1.0, 'frames': 30, 'width': 1080, 'height': 1920,
                'voice_provider': timing['provider'], 'warnings': [],
                'narration_sha256': frame.sha(timing['audio']),
                'summary': feedback or 'Your idea, clearly shown.',
                'graphics_plan': {'feedback': feedback}}

    def create(self, provider='edge', request_id='create-fixture-001'):
        public = frame.generate({'request_id': request_id, 'idea': 'Make creation feel possible.',
                                 'script': SCRIPT, 'provider': provider})
        return frame.load(public['id'])

    def run_worker(self, project):
        frame.worker(project['id'], project['active_version_id'])
        return frame.load(project['id'])

    def ready_for_quote(self):
        project = self.run_worker(self.create('fish-mcp'))
        self.assertEqual(project['status'], 'awaiting_quote')
        return project

    def complete(self):
        project = self.run_worker(self.create())
        self.assertEqual(project['status'], 'complete')
        return project

    def imported(self):
        sid = 'a' * 32
        timing = self.audio(self.studio_store / sid / 'render')
        frame.write(self.studio_store / sid / 'render' / 'timing.json', timing)
        studio.save({'id': sid, 'name': 'Saved voice', 'status': 'complete',
                     'script': SCRIPT, 'direction': 'An existing idea', 'assets': [],
                     'plan': plan(), 'voice': self.valid_voice({'provider': 'fish-mcp'})})
        public = frame.import_studio({'studio_id': sid, 'request_id': 'import-fixture-001'})
        return frame.load(public['id'])

    def post(self, path, body=None, **kwargs):
        request = Request(path, body, **kwargs)
        self.assertTrue(frame.post(request))
        return request.response

    def paid_attempt(self, project, status='unknown', response=True):
        item = frame.version(project)
        units = fish._compile(frame.voice_units(item['plan']), item['plan']['identity'], VOICE, 'drama-3')
        output = frame.folder(project['id'], item['id']) / 'audio'
        receipt = {'request_sha256': fish._digest(units), 'voice_id': VOICE, 'model': 'drama-3',
                   'units': [{'index': i, 'status': status} for i in range(len(units))]}
        frame.write(output / 'mcp-narration-receipt.json', receipt)
        if response:
            for i, unit in enumerate(units):
                frame.write(output / ('mcp-unit-%02d' % i) / 'provider-result.json',
                            {'request_sha256': fish._digest(unit['payload']),
                             'response': {'structuredContent': {'audio_url': 'https://example.invalid/fixture.mp3'}}})
        return output, receipt

    def recovery_fixture(self, provider='fish-mcp', raw=False):
        project = self.create(provider)
        item = frame.version(project)
        item.update(plan=plan(), status='failed')
        project.update(status='failed')
        frame.save(project)
        output = frame.folder(project['id'], item['id']) / 'audio'
        intent = frame.synthesis_intent(project, item)
        frame.write(output / 'intent.json', intent)
        timing = self.audio(output)
        timing['audio_sha256'] = frame.sha(timing['audio'])
        if raw:
            timing.update(request_sha256=intent['request_sha256'], voice_id=VOICE, model='drama-3')
            name = 'mcp-narration.json'
        else:
            timing.update(generation_fingerprint=intent['fingerprint'],
                          speech_request_sha256=intent['request_sha256'])
            name = 'measured-timing.json'
        frame.write(output / name, timing)
        return project, item, output, timing, intent

    def test_generate_lost_response_replay_keeps_one_project_and_job(self):
        original = self.create()
        self.validate_voice.side_effect = AssertionError('Replay must precede provider validation')
        replay = frame.generate({'request_id': 'create-fixture-001', 'idea': original['idea'],
                                 'script': SCRIPT, 'provider': 'edge'})
        self.assertEqual(replay['id'], original['id'])
        self.assertEqual(replay['active_version_id'], original['active_version_id'])
        self.assertEqual(len(frame.projects()), 1)
        self.launch.assert_called_once()

    def test_reusing_request_id_for_different_inputs_conflicts(self):
        self.create()
        code, _ = self.post('/api/frame/generate', {
            'request_id': 'create-fixture-001', 'idea': 'Different idea',
            'script': SCRIPT, 'provider': 'edge'})
        self.assertEqual(code, 409)
        self.assertEqual(len(frame.projects()), 1)
        self.launch.assert_called_once()

    def test_http_rejects_malformed_nonobject_and_invalid_fields_before_work(self):
        for raw in (b'{', b'[]', b'null', b'42'):
            with self.subTest(raw=raw):
                self.assertEqual(self.post('/api/frame/generate', raw=raw)[0], 400)
        for changes in ({'script': 42}, {'idea': []}, {'request_id': 'bad'},
                        {'script': 'word ' * 81}, {'provider': 'unapproved-provider'}):
            with self.subTest(changes=changes):
                body = {'request_id': 'valid-request-001', 'idea': 'Idea', 'script': SCRIPT, **changes}
                self.assertEqual(self.post('/api/frame/generate', body)[0], 400)
        self.assertEqual(frame.projects(), [])
        self.launch.assert_not_called()
        self.external.assert_not_called()

    def test_planning_requests_free_quote_without_generating_audio(self):
        project = self.ready_for_quote()
        self.assertEqual(frame.version(project)['quote']['total_credits'], 10)
        self.quote.assert_called_once()
        self.fish_speech.assert_not_called()
        self.graphics.assert_not_called()

    def test_quote_rejects_identity_expiry_balance_and_changed_delivery(self):
        project = self.ready_for_quote()
        vid = project['active_version_id']
        cases = [({'created_at': time.time() - 901}, None),
                 ({'created_at': time.time() + 60}, None),
                 ({'has_sufficient_balance': False, 'available_credits': 0}, None),
                 ({'voice_id': '2' * 32}, None),
                 ({'model': 's2.1-pro'}, None),
                 ({'request_sha256': '0' * 64}, None),
                 ({}, {'pace': .9})]
        for changes, identity in cases:
            with self.subTest(changes=changes, identity=identity):
                candidate = copy.deepcopy(project)
                item = frame.version(candidate)
                item['quote'] = self.quoted(**changes)
                if identity:
                    item['plan']['identity'].update(identity)
                frame.save(candidate)
                self.launch.reset_mock()
                code, _ = self.post('/api/frame/projects/' + project['id'] + '/render',
                                    {'version_id': vid, 'quote_id': item['quote']['quote_id']})
                self.assertEqual(code, 400)
                self.assertEqual(frame.load(project['id'])['status'], 'awaiting_quote')
                self.launch.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_approval_idempotency_enqueues_once_then_generates_once(self):
        project = self.ready_for_quote()
        vid = project['active_version_id']
        body = {'version_id': vid, 'quote_id': frame.version(project)['quote']['quote_id']}
        self.launch.reset_mock()
        first = frame.approve(project['id'], body)
        second = frame.approve(project['id'], body)
        self.assertEqual(first, second)
        self.launch.assert_called_once_with(project['id'], vid)
        done = self.run_worker(frame.load(project['id']))
        self.assertEqual(done['status'], 'complete')
        self.fish_speech.assert_called_once()
        frame.approve(project['id'], body)
        self.fish_speech.assert_called_once()
        self.launch.assert_called_once()

    def test_wrong_or_absent_quote_id_never_enqueues_speech(self):
        project = self.ready_for_quote()
        self.launch.reset_mock()
        for quote_id in (None, 'f' * 32):
            code, _ = self.post('/api/frame/projects/' + project['id'] + '/render',
                                {'version_id': project['active_version_id'], 'quote_id': quote_id})
            self.assertEqual(code, 400)
        self.launch.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_failure_after_speech_resumes_from_checkpoint_without_new_speech(self):
        project = self.create()
        self.graphics.side_effect = RuntimeError('Graphics service unavailable')
        failed = self.run_worker(project)
        self.assertEqual(failed['status'], 'failed')
        original = frame.read_checkpoint(failed, frame.version(failed))
        original_sha = frame.sha(original['audio'])
        self.graphics.side_effect = self.render
        frame.retry(project['id'], {'version_id': project['active_version_id']})
        done = self.run_worker(frame.load(project['id']))
        self.assertEqual(done['status'], 'complete')
        self.edge_speech.assert_called_once()
        self.assertEqual(frame.version(done)['result']['narration_sha256'], original_sha)

    def test_import_reuses_saved_speech_and_does_not_need_quote_or_connection(self):
        imported = self.imported()
        self.quote.side_effect = AssertionError('Reuse cannot request a quote')
        self.fish_speech.side_effect = AssertionError('Reuse cannot synthesize')
        done = self.run_worker(imported)
        self.assertEqual(done['status'], 'complete')
        self.quote.assert_not_called()
        self.fish_speech.assert_not_called()
        self.edge_speech.assert_not_called()

    def test_cached_fish_retry_ignores_expired_quote_and_offline_provider(self):
        imported = self.imported()
        self.graphics.side_effect = RuntimeError('Renderer failed after saved voice')
        failed = self.run_worker(imported)
        item = frame.version(failed)
        item['quote'] = self.quoted(created_at=time.time() - 10000)
        item['approved_quote_id'] = item['quote']['quote_id']
        frame.save(failed)
        self.quote.side_effect = AssertionError('Offline provider must be irrelevant')
        self.fish_speech.side_effect = AssertionError('Completed audio must be reused')
        self.graphics.side_effect = self.render
        frame.retry(failed['id'], {'version_id': item['id']})
        done = self.run_worker(frame.load(failed['id']))
        self.assertEqual(done['status'], 'complete')
        self.quote.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_audio_and_timing_tampering_fail_closed(self):
        for target in ('audio', 'timing'):
            with self.subTest(target=target):
                project = self.imported() if not frame.projects() else frame.load(frame.projects()[0]['id'])
                item = frame.version(project)
                path = frame.folder(project['id'], item['id']) / 'audio'
                if target == 'audio':
                    with (path / 'narration.wav').open('ab') as stream:
                        stream.write(b'changed')
                else:
                    # Restore valid source audio/checkpoint, then alter only timing.
                    timing = self.audio(self.root / 'restore')
                    frame.checkpoint(project, item, timing)
                    manifest = json.loads((path / 'checkpoint.json').read_text())
                    manifest['timing']['scenes'][0]['words'][0]['start'] = .1
                    frame.write(path / 'checkpoint.json', manifest)
                frame.update(project['id'], item['id'], status='failed')
                self.launch.reset_mock()
                code, _ = self.post('/api/frame/projects/' + project['id'] + '/retry', {'version_id': item['id']})
                self.assertEqual(code, 400)
                self.launch.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_missing_checkpoint_with_saved_audio_fails_closed(self):
        project = self.imported()
        item = frame.version(project)
        (frame.folder(project['id'], item['id']) / 'audio' / 'checkpoint.json').unlink()
        frame.update(project['id'], item['id'], status='failed')
        self.launch.reset_mock()
        code, _ = self.post('/api/frame/projects/' + project['id'] + '/retry', {'version_id': item['id']})
        self.assertEqual(code, 400)
        self.launch.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_unknown_paid_receipt_blocks_retry_and_requote(self):
        project = self.ready_for_quote()
        item = frame.version(project)
        frame.update(project['id'], item['id'], status='failed')
        self.quote.reset_mock()
        self.launch.reset_mock()
        for status in ('unknown', 'submitted'):
            self.paid_attempt(project, status=status, response=False)
            for action in ('retry', 'quote'):
                with self.subTest(status=status, action=action):
                    code, _ = self.post('/api/frame/projects/' + project['id'] + '/' + action,
                                        {'version_id': item['id']})
                    self.assertEqual(code, 400)
        self.launch.assert_not_called()
        self.quote.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_old_failed_version_cannot_change_active_quote_or_project_state(self):
        project = self.ready_for_quote()
        prior = frame.version(project)
        prior['status'] = 'failed'
        active = frame.new_version(2, plan=plan(), status='awaiting_quote', quote=self.quoted())
        project['versions'].append(active)
        project['active_version_id'] = active['id']
        frame.save(project)
        before = copy.deepcopy(project)
        self.quote.reset_mock()
        code, _ = self.post('/api/frame/projects/' + project['id'] + '/quote', {'version_id': prior['id']})
        self.assertEqual(code, 409)
        self.assertEqual(frame.load(project['id']), before)
        self.quote.assert_not_called()

    def test_durable_provider_response_reconciles_without_resubmitting_speech(self):
        project = self.ready_for_quote()
        item = frame.version(project)
        self.quote.reset_mock()
        for status in ('submitted', 'unknown', 'received'):
            with self.subTest(status=status):
                frame.update(project['id'], item['id'], status='failed')
                output, _ = self.paid_attempt(project, status=status)
                self.launch.reset_mock()
                resumed = frame.retry(project['id'], {'version_id': item['id']})
                saved = json.loads((output / 'mcp-narration-receipt.json').read_text())
                self.assertEqual(saved['units'][0]['status'], 'received')
                self.assertEqual(resumed['status'], 'rendering')
                self.launch.assert_called_once()
        self.fish_speech.assert_not_called()
        self.quote.assert_not_called()
        frame.update(project['id'], item['id'], status='failed')
        output, _ = self.paid_attempt(project, status='unknown')
        quoted = frame.quote_version(project['id'], item['id'])
        self.assertEqual(quoted['status'], 'awaiting_quote')
        self.assertEqual(json.loads((output / 'mcp-narration-receipt.json').read_text())['units'][0]['status'], 'received')
        self.quote.assert_called_once()
        self.fish_speech.assert_not_called()

    def test_mismatched_provider_response_and_receipt_fail_closed(self):
        project = self.ready_for_quote()
        item = frame.version(project)
        frame.update(project['id'], item['id'], status='failed')
        self.quote.reset_mock()
        for fault in ('payload_hash', 'response_type', 'receipt_hash', 'voice', 'unit_count'):
            with self.subTest(fault=fault):
                output, receipt = self.paid_attempt(project)
                response_path = output / 'mcp-unit-00' / 'provider-result.json'
                envelope = json.loads(response_path.read_text())
                if fault == 'payload_hash':
                    envelope['request_sha256'] = '0' * 64
                elif fault == 'response_type':
                    envelope['response'] = ['invalid shape']
                elif fault == 'receipt_hash':
                    receipt['request_sha256'] = '0' * 64
                elif fault == 'voice':
                    receipt['voice_id'] = '2' * 32
                else:
                    receipt['units'] = []
                frame.write(response_path, envelope)
                frame.write(output / 'mcp-narration-receipt.json', receipt)
                self.launch.reset_mock()
                for action in ('retry', 'quote'):
                    code, _ = self.post('/api/frame/projects/' + project['id'] + '/' + action,
                                        {'version_id': item['id']})
                    self.assertEqual(code, 400)
                self.launch.assert_not_called()
        self.quote.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_precheckpoint_crash_recovers_finished_narration_without_synthesis(self):
        project = self.create('edge')
        item = frame.version(project)
        item['plan'] = plan()
        frame.save(project)
        with patch.object(frame, 'checkpoint', side_effect=RuntimeError('Simulated crash before checkpoint')):
            with self.assertRaisesRegex(RuntimeError, 'Simulated crash'):
                frame.prepare_narration(project, item, Mock())
        output = frame.folder(project['id'], item['id']) / 'audio'
        self.assertFalse((output / 'checkpoint.json').exists())
        self.assertTrue((output / 'measured-timing.json').is_file())
        original_hash = frame.sha(output / 'narration.wav')
        frame.update(project['id'], item['id'], status='failed')
        frame.retry(project['id'], {'version_id': item['id']})
        done = self.run_worker(frame.load(project['id']))
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(frame.version(done)['result']['narration_sha256'], original_hash)
        self.assertTrue((output / 'checkpoint.json').is_file())
        self.edge_speech.assert_called_once()

    def test_raw_completed_fish_result_recovers_before_measured_checkpoint(self):
        project, item, output, timing, _intent = self.recovery_fixture(raw=True)
        self.quote.side_effect = AssertionError('Completed audio must not require a new quote')
        self.fish_speech.side_effect = AssertionError('Completed audio must not be synthesized again')
        frame.retry(project['id'], {'version_id': item['id']})
        done = self.run_worker(frame.load(project['id']))
        self.assertEqual(done['status'], 'complete')
        self.assertTrue((output / 'checkpoint.json').is_file())
        self.assertEqual(frame.version(done)['result']['narration_sha256'], timing['audio_sha256'])
        self.quote.assert_not_called()
        self.fish_speech.assert_not_called()

    def test_completed_narration_recovery_rejects_unbound_or_tampered_artifacts(self):
        project, item, output, original_timing, original_intent = self.recovery_fixture()
        for fault in ('intent', 'missing_hash', 'audio', 'missing_audio', 'generation', 'speech_request'):
            with self.subTest(fault=fault):
                self.audio(output)
                timing, intent = copy.deepcopy(original_timing), copy.deepcopy(original_intent)
                if fault == 'intent':
                    intent['fingerprint'] = '0' * 64
                elif fault == 'missing_hash':
                    timing.pop('audio_sha256')
                elif fault == 'audio':
                    with (output / 'narration.wav').open('ab') as stream:
                        stream.write(b'tampered')
                elif fault == 'missing_audio':
                    (output / 'narration.wav').unlink()
                elif fault == 'generation':
                    timing['generation_fingerprint'] = '0' * 64
                else:
                    timing['speech_request_sha256'] = '0' * 64
                frame.write(output / 'intent.json', intent)
                frame.write(output / 'measured-timing.json', timing)
                self.launch.reset_mock()
                code, _ = self.post('/api/frame/projects/' + project['id'] + '/retry', {'version_id': item['id']})
                self.assertEqual(code, 400)
                self.assertFalse((output / 'checkpoint.json').exists())
                self.launch.assert_not_called()
        self.fish_speech.assert_not_called()
        self.edge_speech.assert_not_called()

    def test_raw_fish_recovery_rejects_wrong_voice_model_request_or_unbound_audio(self):
        project, item, output, original_timing, _intent = self.recovery_fixture(raw=True)
        for changes in ({'voice_id': '2' * 32}, {'model': 's2.1-pro'},
                        {'request_sha256': '0' * 64}, {'audio_sha256': None}):
            with self.subTest(changes=changes):
                frame.write(output / 'mcp-narration.json', {**original_timing, **changes})
                code, _ = self.post('/api/frame/projects/' + project['id'] + '/retry', {'version_id': item['id']})
                self.assertEqual(code, 400)
                self.assertFalse((output / 'checkpoint.json').exists())
        self.fish_speech.assert_not_called()

    def test_config_refreshes_existing_authorization_once_without_speech(self):
        import studio_fish_mcp
        not_ready = {'ready': False, 'selected_voice': {'name': 'Fixture voice'}}
        ready = {**not_ready, 'ready': True}
        with patch.object(frame, 'FISH_BOOTSTRAP_ATTEMPTED', False), \
                patch.object(fish, 'capabilities', side_effect=[not_ready, ready, ready]), \
                patch.object(studio_fish_mcp, 'status', return_value={'authorized': True}), \
                patch.object(studio_fish_mcp, 'verify') as verify:
            self.assertTrue(frame.config()['fish_ready'])
            self.assertTrue(frame.config()['fish_ready'])
            verify.assert_called_once()
        with patch.object(frame, 'FISH_BOOTSTRAP_ATTEMPTED', False), \
                patch.object(fish, 'capabilities', return_value=not_ready), \
                patch.object(studio_fish_mcp, 'status', return_value={'authorized': True}), \
                patch.object(studio_fish_mcp, 'verify', side_effect=RuntimeError('Offline')) as verify:
            self.assertFalse(frame.config()['fish_ready'])
            self.assertFalse(frame.config()['fish_ready'])
            verify.assert_called_once()
        with patch.object(frame, 'FISH_BOOTSTRAP_ATTEMPTED', False), \
                patch.object(fish, 'capabilities', return_value=not_ready), \
                patch.object(studio_fish_mcp, 'status', return_value={'authorized': False}), \
                patch.object(studio_fish_mcp, 'verify') as verify:
            self.assertFalse(frame.config()['fish_ready'])
            verify.assert_not_called()
        self.fish_speech.assert_not_called()
        self.external.assert_not_called()

    def test_visual_revision_preserves_audio_script_parent_and_export(self):
        project = self.complete()
        parent = copy.deepcopy(frame.version(project))
        old_output = frame.folder(project['id'], parent['id']) / 'render' / 'export.mp4'
        original_bytes = old_output.read_bytes()
        original_audio = frame.read_checkpoint(project, parent)
        body = {'request_id': 'revise-fixture-001', 'base_version_id': parent['id'],
                'feedback': 'Make the idea more restrained.'}
        self.launch.reset_mock()
        revised = frame.revise(project['id'], body)
        replay = frame.revise(project['id'], body)
        self.assertEqual(revised, replay)
        self.launch.assert_called_once()
        done = self.run_worker(frame.load(project['id']))
        child = frame.version(done)
        self.assertEqual(done['script'], SCRIPT)
        self.assertEqual(len(done['versions']), 2)
        self.assertEqual(frame.version(done, parent['id']), parent)
        self.assertEqual(old_output.read_bytes(), original_bytes)
        self.assertNotEqual((frame.folder(done['id'], child['id']) / 'render' / 'export.mp4').read_bytes(), original_bytes)
        self.assertEqual(child['result']['narration_sha256'], frame.sha(original_audio['audio']))
        self.assertEqual(child['base_version_id'], parent['id'])
        self.assertEqual(done['current_version_id'], child['id'])
        self.edge_speech.assert_called_once()

    def test_earlier_complete_version_cannot_be_approved_or_retried(self):
        project = self.complete()
        old = project['active_version_id']
        frame.revise(project['id'], {'request_id': 'revise-fixture-001',
                     'base_version_id': old, 'feedback': 'Quieter.'})
        self.launch.reset_mock()
        for action in ('render', 'retry'):
            code, _ = self.post('/api/frame/projects/' + project['id'] + '/' + action,
                                {'version_id': old, 'quote_id': None})
            self.assertEqual(code, 409)
        self.launch.assert_not_called()

    def test_failed_revision_keeps_previous_playable_result(self):
        project = self.complete()
        original = project['current_version_id']
        frame.revise(project['id'], {'request_id': 'revise-fixture-001',
                     'base_version_id': original, 'feedback': 'Change the graphics.'})
        self.graphics.side_effect = RuntimeError('Graphics temporarily unavailable')
        failed = self.run_worker(frame.load(project['id']))
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['current_version_id'], original)
        self.assertEqual(frame.version(failed, original)['status'], 'complete')
        self.assertTrue((frame.folder(project['id'], original) / 'render' / 'export.mp4').is_file())

    def test_recover_preserves_completed_output_and_resumes_checkpoint(self):
        project = self.complete()
        original = project['current_version_id']
        frame.revise(project['id'], {'request_id': 'revise-fixture-001',
                     'base_version_id': original, 'feedback': 'More spacious.'})
        frame.recover()
        recovered = frame.load(project['id'])
        self.assertEqual(recovered['status'], 'failed')
        self.assertEqual(frame.version(recovered, original)['status'], 'complete')
        self.assertEqual(recovered['current_version_id'], original)
        self.assertIsNotNone(frame.read_checkpoint(recovered, frame.version(recovered)))
        frame.retry(project['id'], {'version_id': recovered['active_version_id']})
        done = self.run_worker(frame.load(project['id']))
        self.assertEqual(done['status'], 'complete')
        self.edge_speech.assert_called_once()

    def test_recovery_leaves_awaiting_quote_untouched(self):
        project = self.ready_for_quote()
        before = copy.deepcopy(frame.version(project))
        frame.recover()
        after = frame.load(project['id'])
        self.assertEqual(after['status'], 'awaiting_quote')
        self.assertEqual(frame.version(after), before)


if __name__ == '__main__':
    unittest.main()
