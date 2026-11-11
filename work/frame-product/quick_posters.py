"""Small, cached project-library images; never transport an entire video for a thumbnail."""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import parse_qs, urlparse
import quick_timeline as timeline

MAX_POSTER = 98304
WORKERS = threading.BoundedSemaphore(2)


def poster(app, pid, export_id=None):
    if not re.fullmatch(timeline.ID, pid):
        raise ValueError('Invalid project.')
    doc = timeline.load(app, pid)
    folder = app.WORK / pid
    if export_id:
        if not re.fullmatch(timeline.ID, export_id):
            raise ValueError('Invalid saved video.')
        output = timeline.completed_export(doc, export_id)
        if not output or output.get('section_id'):
            raise ValueError('Choose a completed full-video version.')
        source = folder / 'versions' / export_id / 'edited.mp4'
        duration = output.get('duration') or sum(c['end']-c['start'] for c in output.get('clips', []))
    else:
        source = folder / 'input.mp4'
        duration = doc['source_duration']
    if not source.is_file():
        raise ValueError('Saved video is unavailable.')
    stat = source.stat()
    at = min(1.0, max(0.0, float(duration or 0)*.1))
    key = hashlib.sha256(json.dumps([pid, export_id, stat.st_size, stat.st_mtime_ns, at, '320x180-v1']).encode()).hexdigest()
    cache = app.WORK / '.poster-cache'
    cache.mkdir(exist_ok=True)
    target = cache / (key+'.jpg')
    with (cache / (key+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_file():
            raw = target.read_bytes()
            if 0 < len(raw) <= MAX_POSTER and raw.startswith(b'\xff\xd8'):
                return raw
        with WORKERS:
            result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', '-ss', str(at), '-i', str(source),
                '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2',
                '-filter_threads', '1', '-q:v', '6', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                capture_output=True, timeout=15)
        raw = result.stdout
        if result.returncode or not 0 < len(raw) <= MAX_POSTER or not raw.startswith(b'\xff\xd8'):
            raise ValueError('A preview image could not be prepared. The saved video is unchanged.')
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(raw)
        temporary.replace(target)
        return raw


def route(handler, app, method):
    if method != 'GET':
        return False
    parsed = urlparse(handler.path)
    match = re.fullmatch('/api/quick/projects/('+timeline.ID+')/poster', parsed.path)
    if not match:
        return False
    try:
        query = parse_qs(parsed.query, keep_blank_values=True)
        if set(query)-{'export_id'} or any(len(values)!=1 for values in query.values()):
            raise ValueError('Invalid preview selection.')
        raw = poster(app, match[1], query.get('export_id', [None])[0])
        handler.send(200, raw, 'image/jpeg')
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        handler.json(400, {'error': str(error) if not isinstance(error, subprocess.TimeoutExpired) else 'Preview preparation timed out. Open the saved video instead.'})
    return True
