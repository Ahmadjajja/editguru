import os
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import quick_runtime as runtime


class DesktopStartupTests(unittest.TestCase):
    def test_minimal_desktop_path_finds_installed_ffmpeg_without_empty_cwd_entry(self):
        candidates=['/opt/homebrew/bin','/usr/local/bin','/usr/bin','/bin']
        if not any(shutil.which('ffmpeg',path=p) for p in candidates):
            self.skipTest('FFmpeg is required for Frame runtime verification')
        with tempfile.TemporaryDirectory() as folder:
            for desktop_path in ['/usr/bin:/bin','']:
                with self.subTest(PATH=desktop_path),patch.dict(os.environ,{'PATH':desktop_path}),patch.object(Path,'home',return_value=Path(folder)),patch.object(runtime,'_healthy_until',0),patch.object(runtime,'health',side_effect=[False,True]),patch.object(runtime,'read_startup',return_value=None),patch.object(runtime.subprocess,'Popen') as spawned:
                    spawned.return_value.pid=987654321
                    runtime._starting.clear()
                    runtime.ensure_server('http://127.0.0.1:65534')
                    env=spawned.call_args.kwargs['env']
                    self.assertEqual(env['PORT'],'65534')
                    self.assertNotIn('',env['PATH'].split(os.pathsep))
                    self.assertIsNotNone(shutil.which('ffmpeg',path=env['PATH']))
                    self.assertIsNotNone(shutil.which('ffprobe',path=env['PATH']))


class RuntimeIdentityTests(unittest.TestCase):
    def response(self, identity):
        return io.BytesIO(json.dumps({'ok': True, 'operations': ['frame_product'], 'runtime_id': identity}).encode())

    def test_only_exact_runtime_is_healthy(self):
        expected=hashlib.sha256(str(Path(runtime.__file__).resolve().parent).encode()).hexdigest()
        with patch.object(runtime.urllib.request,'urlopen',return_value=self.response(expected)):
            self.assertTrue(runtime.health('http://127.0.0.1:12345'))
        for identity in ['other-installation',None]:
            with self.subTest(identity=identity),patch.object(runtime.urllib.request,'urlopen',return_value=self.response(identity)):
                with self.assertRaisesRegex(RuntimeError,'different Frame installation'):
                    runtime.health('http://127.0.0.1:12345')

    def test_cached_health_does_not_authorize_another_endpoint(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'home',return_value=Path(folder)),patch.object(runtime,'_healthy_until',0),patch.object(runtime,'_healthy_base',None),patch.object(runtime,'health',return_value=True) as checked,patch.object(runtime.subprocess,'Popen') as spawned:
            runtime.ensure_server('http://127.0.0.1:12345')
            runtime.ensure_server('http://127.0.0.1:12345')
            self.assertEqual(checked.call_count,1)
            runtime.ensure_server('http://127.0.0.1:23456')
            self.assertEqual(checked.call_count,2)
            spawned.assert_not_called()
            with self.assertRaises(ValueError):runtime.ensure_server('https://example.com:12345')

    def test_wrong_runtime_is_never_restarted_or_adopted(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'home',return_value=Path(folder)),patch.object(runtime,'_healthy_until',0),patch.object(runtime,'health',side_effect=RuntimeError('different Frame installation')),patch.object(runtime.subprocess,'Popen') as spawned:
            with self.assertRaisesRegex(RuntimeError,'different Frame installation'):
                runtime.ensure_server('http://127.0.0.1:12345')
            spawned.assert_not_called()


class StartupObservationTests(unittest.TestCase):
    def test_timeout_reuses_live_startup_and_restarts_only_after_exit(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'home',return_value=Path(folder)),patch.object(runtime,'_healthy_until',0),patch.object(runtime,'_starting',{}),patch.object(runtime,'health',return_value=False),patch.object(runtime.time,'sleep'),patch.object(runtime,'read_startup',return_value=None),patch.object(runtime.subprocess,'Popen') as spawn:
            spawn.return_value.pid=987654321
            spawn.return_value.poll.return_value=None
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError,'still starting'):runtime.ensure_server('http://127.0.0.1:23456')
            self.assertEqual(spawn.call_count,1,'live startup handle must be reused after an observation timeout')
            spawn.return_value.poll.return_value=1
            with self.assertRaisesRegex(RuntimeError,'could not start'):runtime.ensure_server('http://127.0.0.1:23456')
            self.assertEqual(spawn.call_count,2,'terminal startup may be replaced')


class CrossConnectorStartupTests(unittest.TestCase):
    def test_another_connector_reuses_durable_live_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(Path,'home',return_value=Path(folder)), patch.object(runtime,'_healthy_until',0), patch.object(runtime,'_starting',{}), patch.object(runtime,'health',return_value=False), patch.object(runtime.time,'sleep'), patch.object(runtime.subprocess,'Popen') as spawn:
            spawn.return_value.pid=987654321
            spawn.return_value.poll.return_value=None
            with self.assertRaisesRegex(RuntimeError,'still starting'):
                runtime.ensure_server('http://127.0.0.1:23456')
            record=Path(folder)/'.local/state/frame-mcp/editor-23456.startup.json'
            argv=json.loads(record.read_text())['argv']
            runtime._starting.clear()  # Independent connector has no Python child handle.
            with patch.object(runtime.os,'kill'), patch.object(runtime,'startup_command',return_value=' '.join(argv)):
                with self.assertRaisesRegex(RuntimeError,'still starting'):
                    runtime.ensure_server('http://127.0.0.1:23456')
            self.assertEqual(spawn.call_count,1)
            self.assertEqual(record.stat().st_mode & 0o777,0o600)

    def test_live_wrong_installation_and_unverified_pid_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'startup.json'
            frame=Path('/frame path')
            value={'schema_version':1,'pid':123,'frame':str(frame),'argv':['/python',str(frame/'app.py')]}
            runtime.atomic_record(record,value)
            with patch.object(runtime.os,'kill'), patch.object(runtime,'startup_command',return_value='other command'):
                with self.assertRaisesRegex(RuntimeError,'identity could not be verified'):
                    runtime.read_startup(record,frame)
                with self.assertRaisesRegex(RuntimeError,'different Frame installation'):
                    runtime.read_startup(record,Path('/another'))
            with patch.object(runtime.os,'kill',side_effect=ProcessLookupError):
                self.assertIsNone(runtime.read_startup(record,frame))

    def test_framework_python_and_linux_argv_match_exact_app_path(self):
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'startup.json'
            frame=Path('/frame path')
            runtime.atomic_record(record,{'schema_version':1,'pid':123,'frame':str(frame),'argv':['/python3',str(frame/'app.py')]})
            commands=['/Frameworks/Python.app/Contents/MacOS/Python '+str(frame/'app.py'),[b'/usr/bin/python3',str(frame/'app.py').encode()]]
            for command in commands:
                with self.subTest(command=command), patch.object(runtime.os,'kill'), patch.object(runtime,'startup_command',return_value=command):
                    self.assertEqual(runtime.read_startup(record,frame).pid,123)
            with patch.object(runtime.os,'kill'), patch.object(runtime,'startup_command',return_value='/usr/bin/python3 '+str(frame/'app.py')+' --another-port'):
                with self.assertRaisesRegex(RuntimeError,'identity could not be verified'):
                    runtime.read_startup(record,frame)

    def test_malformed_and_dangling_symlink_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            record=Path(folder)/'startup.json'
            record.write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'record could not be verified'):
                runtime.read_startup(record,Path(folder))
            record.unlink()
            record.symlink_to(Path(folder)/'missing')
            with self.assertRaisesRegex(RuntimeError,'Invalid Frame startup record'):
                runtime.read_startup(record,Path(folder))


if __name__=='__main__':unittest.main()
