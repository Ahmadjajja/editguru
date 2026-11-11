"""Activate a prepared Frame revision without changing its installation's projects."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import quick_runtime


class StopPending(RuntimeError):
    """A sent stop has no verified terminal outcome yet."""


def atomic_write(path, raw):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def live_servers(state):
    """Preflight every recorded port before sending any stop request."""
    by_url = {}
    for config in state.glob('endpoint-*.json'):
        digest = config.stem[len('endpoint-'):]
        if not re.fullmatch('[a-f0-9]{64}', digest):
            continue
        url = quick_runtime.loopback(json.loads(config.read_text())['url'])
        frame = (state/'runtimes'/digest/'frame').resolve()
        identity = hashlib.sha256(str(frame).encode()).hexdigest()
        by_url.setdefault(url, {})[identity] = frame
    live = []
    for url, candidates in by_url.items():
        try:
            with urllib.request.urlopen(url+'/api/health', timeout=2) as response:
                health = json.load(response)
        except urllib.error.URLError as error:
            if isinstance(error.reason, ConnectionRefusedError):
                continue
            raise RuntimeError('Cannot verify the recorded Frame server. No stop attempted.') from error
        frame = candidates.get(health.get('runtime_id')) if isinstance(health, dict) else None
        if not frame or not health.get('ok') or quick_runtime.installation(frame) != state:
            raise RuntimeError('Another installation owns a recorded port. No stop attempted.')
        live.append({'url':url, 'identity':health['runtime_id'], 'frame':str(frame)})
    return live


def stop_owned_servers(state):
    servers = live_servers(state)
    for server in servers:
        request = urllib.request.Request(server['url']+'/api/frame/stop', data=b'', headers={'X-Frame-Runtime':server['identity']})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                acknowledgement=json.load(response)
                if not isinstance(acknowledgement,dict) or not acknowledgement.get('stopping'):
                    raise StopPending('Frame stop was not acknowledged. Wait and verify the server before retrying.')
        except urllib.error.HTTPError as error:
            if error.code in (403,409):
                raise RuntimeError('Frame did not stop: '+error.read(2000).decode()) from error
            raise StopPending('Frame stop outcome is unverified. Wait and inspect the server before retrying.') from error
        except (urllib.error.URLError,ConnectionResetError,TimeoutError,ValueError) as error:
            raise StopPending('Frame stop outcome is unverified. Wait and inspect the server before retrying.') from error
        for _ in range(40):
            try:
                urllib.request.urlopen(server['url']+'/api/health', timeout=.2).close()
            except urllib.error.URLError as error:
                if isinstance(error.reason, ConnectionRefusedError):
                    break
            except (ConnectionResetError, TimeoutError):
                pass
            time.sleep(.1)
        else:
            raise StopPending('Stop was acknowledged but the server still responds. Wait before activating.')
    return {'stopped':True, 'servers':servers}


def verify_payload(runtime, manifest_raw):
    if hashlib.sha256(manifest_raw).hexdigest() != runtime.name:
        raise RuntimeError('The activation manifest does not match this runtime.')
    for entry in json.loads(manifest_raw)['files']:
        name = Path(entry['path'])
        if name.is_absolute() or '..' in name.parts or set(name.parts)&{'jobs','studio-jobs','.venv'}:
            raise RuntimeError('Invalid activation payload path.')
        path = runtime/name
        if any(p.is_symlink() for p in [path, *path.parents] if p==runtime or runtime in p.parents):
            raise RuntimeError('Symlink in activation code payload.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('Prepared runtime code changed. No server stopped.')


def activate(runtime, endpoint, manifest_raw):
    runtime = runtime.resolve()
    frame = runtime/'frame'
    state = quick_runtime.installation(frame)
    if not state:
        raise RuntimeError('Activation requires a prepared installed Frame runtime.')
    endpoint = quick_runtime.loopback(endpoint)
    verify_payload(runtime, manifest_raw)
    with (state/'activation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = state/'active-runtime.json'
        if marker.is_symlink():
            raise RuntimeError('Invalid Frame activation record.')
        previous_raw = marker.read_bytes() if marker.exists() else None
        if previous_raw is not None and len(previous_raw)>16384:
            raise RuntimeError('Invalid Frame activation record.')
        previous = json.loads(previous_raw) if previous_raw else {}
        if not isinstance(previous,dict):
            raise RuntimeError('Invalid Frame activation record. No server stopped.')
        record = {'schema_version':1, 'protocol_version':quick_runtime.PROTOCOL,
                  'status':'updating', 'manifest_sha256':runtime.name, 'url':endpoint}
        # A timed-out startup is an observation failure, not permission to restart it.
        pid = previous.get('startup_pid')
        if type(pid) is int and pid>0:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            if alive:
                if previous.get('manifest_sha256')==runtime.name and quick_runtime.health(previous['url'], frame, True):
                    record.update(status='ready',url=previous['url'])
                    quick_runtime.write_activation(state,record)
                    return {'activated':True, 'recovered':True, **record}
                raise RuntimeError('The previous Frame startup is still running. Wait and inspect it before retrying activation.')
        atomic_write(runtime/'MANIFEST.json',manifest_raw)
        quick_runtime.write_activation(state, record)
        try:
            # Same lock as setup/stop, with a separate activation lease for the whole transition.
            with (state/'install.lock').open('a') as install_lock:
                fcntl.flock(install_lock, fcntl.LOCK_EX)
                stopped = stop_owned_servers(state)
        except StopPending:
            record.update(status='failed',phase='stopping')
            quick_runtime.write_activation(state,record)
            raise
        except BaseException:
            if previous_raw is None:
                marker.unlink()
            else:
                atomic_write(marker,previous_raw)
            raise
        if len(stopped['servers'])==1:
            endpoint = stopped['servers'][0]['url']  # Preserve browser bookmarks across updates.
        record['url'] = endpoint
        quick_runtime.write_activation(state, record)
        atomic_write(state/('endpoint-'+runtime.name+'.json'),(json.dumps({'url':endpoint})+'\n').encode())
        try:
            quick_runtime.ensure_server(endpoint, follow_active=False)
            if not quick_runtime.health(endpoint, frame, True):
                raise RuntimeError('New Frame runtime is not ready.')
        except BaseException:
            record['status']='failed'
            process = quick_runtime._starting.get((endpoint,str(frame),False))
            if process is not None and process.poll() is None:
                record['startup_pid']=process.pid
            quick_runtime.write_activation(state,record)
            raise
        record['status']='ready'
        quick_runtime.write_activation(state,record)
        return {'activated':True, **record, 'projects':str(state/'projects')}


if __name__=='__main__':
    try:
        runtime=Path(sys.argv[1]).resolve()
        if runtime/'frame' != Path(__file__).resolve().parent:
            raise RuntimeError('Use this runtime’s installed activation command.')
        result=activate(runtime,sys.argv[2],Path(sys.argv[3]).read_bytes())
        print(json.dumps(result))
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        raise SystemExit(str(error))
