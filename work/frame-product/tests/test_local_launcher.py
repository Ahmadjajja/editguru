import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'start-local.sh'
FAKE_PYTHON = '''#!/bin/sh
case "$1" in
 -c) test -f "$FIXTURE/ready" ;;
 -m)
   printf 'pip\\n' >> "$FIXTURE/actions"
   if test -f "$FIXTURE/fail-pip"; then exit 1; fi
   touch "$FIXTURE/ready" ;;
 *) printf 'app:%s\\n' "$PORT" >> "$FIXTURE/actions" ;;
esac
'''
WRAPPER = '''
command() { if [ "$1" = -v ]; then [ "$2" != "${MISSING_TOOL:-}" ]; else return 1; fi; }
python3() {
 if [ "$1" = -c ]; then [ "${OLD_PYTHON:-0}" != 1 ]; return; fi
 mkdir -p "$3/bin"; cp "$FIXTURE/fake-python" "$3/bin/python"; chmod +x "$3/bin/python"
}
. "$0"
'''

class LocalLauncherTests(unittest.TestCase):
    def setup_fixture(self, folder, existing=True, ready=False):
        root = Path(folder)
        shutil.copyfile(SCRIPT, root / 'start-local.sh')
        fake = root / 'fake-python'
        fake.write_text(FAKE_PYTHON)
        fake.chmod(0o755)
        if existing:
            target = root / '.venv/bin/python'
            target.parent.mkdir(parents=True)
            shutil.copyfile(fake, target)
            target.chmod(0o755)
        if ready:
            (root / 'ready').touch()
        return root

    def launch(self, root, **env):
        return subprocess.run(['/bin/sh', '-c', WRAPPER, str(root / 'start-local.sh')],
                              env={**os.environ, 'FIXTURE': str(root), 'PORT': '12345', **env},
                              capture_output=True, text=True, timeout=10)

    def test_missing_prerequisites_explain_recovery_without_starting(self):
        for tool, message in [('python3', 'Python 3.9'), ('ffmpeg', 'brew install ffmpeg'), ('ffprobe', 'brew install ffmpeg')]:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as folder:
                root = self.setup_fixture(folder)
                result = self.launch(root, MISSING_TOOL=tool)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse((root / 'actions').exists())

    def test_old_python_is_rejected_before_environment_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.setup_fixture(folder, existing=False)
            result = self.launch(root, OLD_PYTHON='1')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Update Python', result.stderr)
            self.assertFalse((root / '.venv').exists())

    def test_ready_environment_starts_without_installing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.setup_fixture(folder, ready=True)
            result = self.launch(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'actions').read_text(), 'app:12345\n')
            self.assertIn('http://127.0.0.1:12345/frame',result.stdout)

    def test_fresh_and_interrupted_setups_install_and_start(self):
        for existing in [False, True]:
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as folder:
                root = self.setup_fixture(folder, existing=existing)
                result = self.launch(root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'actions').read_text(), 'pip\napp:12345\n')

    def test_failed_install_can_be_retried_without_losing_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.setup_fixture(folder)
            saved = root / 'jobs/project/input.mp4'
            saved.parent.mkdir(parents=True)
            saved.write_bytes(b'original footage')
            (root / 'fail-pip').touch()
            result = self.launch(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('run this launcher again', result.stderr)
            self.assertNotIn('app:', (root / 'actions').read_text())
            (root / 'fail-pip').unlink()
            self.assertEqual(self.launch(root).returncode, 0)
            self.assertEqual(saved.read_bytes(), b'original footage')

if __name__ == '__main__':
    unittest.main()
