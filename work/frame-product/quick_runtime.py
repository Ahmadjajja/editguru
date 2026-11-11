"""Start the exact local editor or follow a verified activation in its installation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

_healthy_until = 0.0
_healthy_base = None
_starting = {}
PROTOCOL = 2


def loopback(base):
    if not isinstance(base, str) or not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost):\d+', base):
        raise ValueError('Frame must use a loopback HTTP address.')
    if not 1 <= int(base.rsplit(':', 1)[1]) <= 65535:
        raise ValueError('Invalid Frame port.')
    return base


def installation(frame=None):
    frame = (frame or Path(__file__).resolve().parent).resolve()
    runtime = frame.parent
    if runtime.parent.name != 'runtimes' or not re.fullmatch('[a-f0-9]{64}', runtime.name):
        return None
    state = runtime.parent.parent
    projects = state / 'projects'
    if projects.is_symlink() or not projects.is_dir():
        raise RuntimeError('Frame installation’s project store could not be verified.')
    if not (frame / 'jobs').is_symlink() or (frame / 'jobs').resolve() != projects.resolve():
        raise RuntimeError('Frame runtime does not match this installation’s saved projects.')
    return state


def checked_runtime(state, digest):
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise RuntimeError('Invalid active Frame runtime. Run the installed launcher again.')
    runtime = state / 'runtimes' / digest
    if runtime.is_symlink() or (runtime / 'frame').is_symlink() or installation(runtime / 'frame') != state:
        raise RuntimeError('Active Frame runtime points to another project store.')
    manifest = runtime / 'MANIFEST.json'
    if not manifest.is_file() or manifest.is_symlink() or hashlib.sha256(manifest.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Active Frame runtime metadata is unavailable or changed. Run the installed launcher again.')
    return runtime / 'frame'


def active_target(base, follow_active=True):
    own = Path(__file__).resolve().parent
    state = installation(own)
    marker = state / 'active-runtime.json' if state else None
    if not follow_active or not marker:
        return loopback(base), own, False
    if marker.is_symlink():
        raise RuntimeError('Invalid Frame activation record.')
    if not marker.exists():
        return loopback(base), own, False
    try:
        with marker.open() as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') != 1:
            raise ValueError
        if value.get('status') != 'ready':
            raise RuntimeError('Frame is updating or its update was interrupted. Retry shortly, or run the installed activation command again. Saved work is preserved.')
        if type(value.get('protocol_version')) is not int or value.get('protocol_version') != PROTOCOL:
            raise RuntimeError('This Frame connector needs an update before using the active editor.')
        target = checked_runtime(state, value.get('manifest_sha256'))
        return loopback(value.get('url')), target, True
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError('Frame activation record could not be verified. Run the installed launcher again.') from exc


def active_editor(base):
    base, frame, activated = active_target(base)
    if not activated:
        return base, None
    entries = json.loads((frame.parent/'MANIFEST.json').read_text())['files']
    expected = next((entry['sha256'] for entry in entries if entry['path']=='frame/frame_widget.html'), None)
    page = frame/'frame_widget.html'
    if page.is_symlink():
        raise RuntimeError('The active Frame editor bundle changed. Run the installed setup command again.')
    raw = page.read_bytes()
    if not expected or hashlib.sha256(raw).hexdigest()!=expected:
        raise RuntimeError('The active Frame editor bundle changed. Run the installed setup command again.')
    return base, raw.decode('utf-8')


def write_activation(state, value):
    atomic_record(state / 'active-runtime.json', value)


def atomic_record(target, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, prefix=target.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()



class ObservedStartup:
    """A verified child started by another connector; never owns or kills it."""
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError as exc:
            raise RuntimeError('Frame startup process could not be verified. Inspect its local editor log before retrying.') from exc
        return None


def startup_command(pid):
    if sys.platform.startswith('linux'):
        try:
            return Path('/proc').joinpath(str(pid), 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        except FileNotFoundError:
            return None
    result = subprocess.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'command='],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def read_startup(target, frame):
    if target.is_symlink():
        raise RuntimeError('Invalid Frame startup record. Inspect its local editor log before retrying.')
    if not target.exists():
        return None
    try:
        with target.open() as stream:
            raw = stream.read(16385)
        value = json.loads(raw) if len(raw) <= 16384 else None
        if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
            raise ValueError
        pid = value.get('pid')
        argv = value.get('argv')
        if type(pid) is not int or pid <= 0 or not isinstance(argv, list) or len(argv) != 2 or not all(isinstance(a, str) and a for a in argv):
            raise ValueError
        process = ObservedStartup(pid)
        if process.poll() is not None:
            return None
        if value.get('frame') != str(frame) or argv[1] != str(frame / 'app.py'):
            raise RuntimeError('A different Frame installation is still starting on this port. Wait before retrying.')
        command = startup_command(pid)
        if command is None and process.poll() is not None:
            return None
        # macOS framework Python rewrites argv[0] to Python.app after exec.
        # Match the exact app argument and verify the reported interpreter name.
        if isinstance(command, list):
            matches = len(command) == 2 and command[1] == argv[1].encode()
            interpreter = os.fsdecode(command[0]) if command else ''
        else:
            suffix = ' ' + argv[1]
            matches = isinstance(command, str) and command.endswith(suffix)
            interpreter = command[:-len(suffix)] if matches else ''
        if not matches or not re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?', Path(interpreter).name, re.IGNORECASE):
            raise RuntimeError('Frame startup process identity could not be verified. Inspect its local editor log before retrying.')
        return process
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        raise RuntimeError('Frame startup record could not be verified. Inspect its local editor log before retrying.') from exc

def health(base, frame=None, require_protocol=False):
    loopback(base)
    try:
        with urllib.request.urlopen(base + '/api/health', timeout=2) as response:
            value = json.load(response)
        if not isinstance(value, dict) or not value.get('ok') or 'frame_product' not in value.get('operations', []):
            raise RuntimeError('Another service owns the Frame port. Choose a different FRAME_URL port.')
        expected = hashlib.sha256(str((frame or Path(__file__).resolve().parent).resolve()).encode()).hexdigest()
        if value.get('runtime_id') != expected:
            raise RuntimeError('A different Frame installation owns this port. Reconnect Frame using this installation’s launcher.')
        if require_protocol and (type(value.get('frame_connector_protocol')) is not int or value.get('frame_connector_protocol') != PROTOCOL):
            raise RuntimeError('The active Frame editor and connector are not compatible. Update Frame before retrying.')
        return True
    except urllib.error.HTTPError as exc:
        raise RuntimeError('Another service owns the Frame port. Choose a different FRAME_URL port.') from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return False
        raise RuntimeError('The Frame service is not responding. Wait, then refresh the connection.') from exc


def ensure_server(base, follow_active=True):
    global _healthy_until, _healthy_base
    loopback(base)  # Validate the caller even when a cached activation is healthy.
    base, frame, require_protocol = active_target(base, follow_active)
    key = (base, str(frame), require_protocol)
    if key == _healthy_base and time.monotonic() < _healthy_until:
        return base
    port = base.rsplit(':', 1)[1]
    state = Path.home() / '.local' / 'state' / 'frame-mcp'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / ('start-' + port + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not health(base, frame, require_protocol):
            env = os.environ.copy()
            env['PORT'] = port
            bins = ['/opt/homebrew/bin', '/usr/local/bin'] if sys.platform == 'darwin' else ['/usr/local/bin', '/usr/bin', '/bin']
            env['PATH'] = os.pathsep.join(dict.fromkeys([*[p for p in env.get('PATH', '').split(os.pathsep) if p], *[p for p in bins if Path(p).is_dir()]]))
            python = sys.executable
            owner = installation(frame)
            if owner:
                requirements = hashlib.sha256((frame.parent / 'requirements.txt').read_bytes()).hexdigest()
                environment = owner / 'environments' / requirements
                receipt = environment / 'requirements.sha256'
                if not (environment / 'bin/python').is_file() or not receipt.is_file() or receipt.read_text().strip() != requirements:
                    raise RuntimeError('The updated Frame environment is not prepared. Run the installed setup command again.')
                python = str(environment / 'bin/python')
            startup = state / ('editor-' + port + '.startup.json')
            process = _starting.get(key)
            if process is not None and process.poll() is not None:
                _starting.pop(key, None)
                process = None
            if process is None:
                process = read_startup(startup, frame)
            if process is None:
                with (state / ('editor-' + port + '.log')).open('ab') as log:
                    process = subprocess.Popen([python, str(frame / 'app.py')], stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=log, start_new_session=True, env=env)
                atomic_record(startup, {'schema_version': 1, 'pid': process.pid,
                                        'frame': str(frame), 'argv': [python, str(frame / 'app.py')]})
            _starting[key] = process
            for _ in range(80):
                if health(base, frame, require_protocol):
                    break
                if process.poll() is not None:
                    raise RuntimeError('Frame could not start. Inspect its local editor log and refresh.')
                time.sleep(.25)
            else:
                raise RuntimeError('Frame is still starting after 20 seconds. Wait and inspect its local editor log before retrying.')
        _healthy_base = key
        _healthy_until = time.monotonic() + 2
        return base
