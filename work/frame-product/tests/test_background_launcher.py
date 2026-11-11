import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'restart-local.sh'
WRAPPER='''
health_count=0
launchctl() {
 case "$1" in
  list) return 1 ;;
  submit) printf 'submit\\n' >> "$FIXTURE/actions" ;;
  remove) printf 'remove\\n' >> "$FIXTURE/actions" ;;
 esac
}
sleep() { :; }
python3() {
 health_count=$((health_count + 1))
 printf 'probe\\n' >> "$FIXTURE/probes"
 if [ "${FOREIGN_SERVICE:-0}" = 1 ]; then printf 'A different Frame installation owns this port.\\n' >&2; return 2; fi
 [ "$health_count" -ge "${READY_AFTER:-1}" ]
}
. "$0"
'''

class BackgroundLauncherTests(unittest.TestCase):
 def run_fixture(self,**extra):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);shutil.copy2(SCRIPT,root/'restart-local.sh')
   saved=root/'jobs/kept/input.mp4';saved.parent.mkdir(parents=True);saved.write_bytes(b'original footage')
   result=subprocess.run(['/bin/sh','-c',WRAPPER,str(root/'restart-local.sh')],env={**os.environ,'FIXTURE':str(root),'PORT':'8876','XDG_STATE_HOME':str(root/'state'),**extra},capture_output=True,text=True,timeout=5)
   self.assertEqual(saved.read_bytes(),b'original footage')
   actions=(root/'actions').read_text().splitlines() if (root/'actions').exists() else [];probes=(root/'probes').read_text().splitlines() if (root/'probes').exists() else []
   return result,actions,probes
 def test_delayed_readiness_waits_for_same_background_job(self):
  result,actions,probes=self.run_fixture(READY_AFTER='4')
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(actions,['submit'])
  self.assertEqual(len(probes),4)
  self.assertIn('http://127.0.0.1:8876/frame',result.stdout)
 def test_timeout_does_not_stop_or_restart_job_or_claim_success(self):
  result,actions,probes=self.run_fixture(READY_AFTER='99')
  self.assertEqual(result.returncode,2)
  self.assertEqual(actions,['submit'])
  self.assertEqual(len(probes),20)
  self.assertNotIn('FRAME running',result.stdout)
  self.assertIn('setup may still be running',result.stderr)
  self.assertIn('has not been stopped',result.stderr)
 def test_custom_port_is_used_in_editor_address(self):
  result,actions,probes=self.run_fixture(PORT='12345')
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('http://127.0.0.1:12345/frame',result.stdout)
  self.assertEqual(actions,['submit'])
 def test_invalid_port_does_not_launch_job(self):
  for port in ['0','65536','nope','8876/path','12345678901234567890']:
   with self.subTest(port=port):
    result,actions,probes=self.run_fixture(PORT=port)
    self.assertEqual(result.returncode,1)
    self.assertEqual(actions,[])
    self.assertEqual(probes,[])
    self.assertIn('between 1 and 65535',result.stderr)
 def test_foreign_service_is_never_reported_as_ready(self):
  result,actions,probes=self.run_fixture(FOREIGN_SERVICE='1')
  self.assertEqual(result.returncode,1)
  self.assertEqual(actions,['submit'])
  self.assertEqual(len(probes),1)
  self.assertIn('different Frame installation',result.stderr)
  self.assertNotIn('FRAME running',result.stdout)

if __name__=='__main__':unittest.main()
