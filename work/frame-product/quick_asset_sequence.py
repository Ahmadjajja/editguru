"""Create an editable Frame base video from an ordered reusable clip sequence.

The normalized base input is flattened; each selected clip remains a separate
source interval and original library bytes plus selection provenance are retained.
No existing project is modified. A complete staged project is published by rename.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
import types
import uuid

from editor import probe, run
import quick_asset_library as library
import quick_studio as studio
import quick_timeline as timeline


def _sync(path):
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def _sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy(source, target, digest):
    target.parent.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256()
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
            checksum.update(chunk)
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if checksum.hexdigest() != digest:
        raise ValueError('Library source changed while creating this video.')


def create_video_from_library(app, items, name='Library video', style_id=None):
    """Build a new project from 1–48 shared library clip/render placements.

    Each item accepts asset_id, inpoint (seconds), duration and include_audio.
    Selections are quantized down to whole 30fps frames and capped at 300 seconds.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 180 or '\x00' in name:
        raise ValueError('Video name must contain 1–180 characters.')
    if not isinstance(items, list) or not 1 <= len(items) <= 48:
        raise ValueError('Choose 1–48 clips for the new video.')
    style = {}
    if style_id is not None:
        record = library.get(app, style_id)
        if record['project_id'] is not None or record['kind'] != 'style':
            raise ValueError('Choose a shared library style.')
        style = copy.deepcopy(record['recipe'])
        if not isinstance(style, dict) or set(style) - (set(studio.DEFAULT) - {'captions', 'layers'}):
            raise ValueError('Style supports framing, color and volume settings only.')
        # No media paths involved; validate before beginning costly rendering.
        style = studio.validate(app, '', {}, style)
    selected = []
    total_frames = 0
    for item in items:
        if not isinstance(item, dict) or set(item) - {'asset_id', 'inpoint', 'duration', 'include_audio'}:
            raise ValueError('Unknown clip sequence setting.')
        record = library.get(app, item.get('asset_id'))
        if record['project_id'] is not None or record['kind'] not in ('clip', 'render'):
            raise ValueError('New videos require shared library clips or renders.')
        path = library.resolve(app, record['id'])
        info = probe(path, False)
        inpoint = studio.num(item.get('inpoint', 0), 0, info['duration'], 'Source inpoint')
        duration = studio.num(item.get('duration', min(300, info['duration'] - inpoint)), 1 / 30, 300, 'Duration')
        if inpoint + duration > info['duration'] + .000001:
            raise ValueError('Clip selection exceeds source duration.')
        include_audio = item.get('include_audio', True)
        if type(include_audio) is not bool:
            raise ValueError('include_audio must be true or false.')
        frames = math.floor(duration * 30 + 1e-7)
        total_frames += frames
        if total_frames > 9000:
            raise ValueError('The new video must be at most 300 seconds.')
        selected.append({'record': record, 'path': path, 'info': info,
                         'inpoint': inpoint, 'duration': frames / 30,
                         'include_audio': include_audio, 'frames': frames})
    first = selected[0]['info']
    factor = min(1, 1280 / max(first['width'], first['height']))
    width = max(2, round(first['width'] * factor / 2) * 2)
    height = max(2, round(first['height'] * factor / 2) * 2)
    has_audio = any(row['include_audio'] and row['info']['audio'] for row in selected)
    pid = uuid.uuid4().hex
    root = Path(app.WORK).resolve()
    staging_root = Path(tempfile.mkdtemp(prefix='.sequence-', dir=str(root)))
    folder = staging_root / pid
    folder.mkdir()
    try:
        assets = []
        attached = {}
        manifest = []
        elapsed_frames = 0
        parts = []
        for index, row in enumerate(selected):
            record = row['record']
            if record['id'] not in attached:
                aid = uuid.uuid4().hex
                original = folder / 'assets' / aid / record['name']
                _copy(row['path'], original, record['sha256'])
                assets.append({'id': aid, 'name': record['name'], 'path': original.relative_to(folder).as_posix(),
                               'size': original.stat().st_size, 'sha256': record['sha256'],
                               'mime_type': record['mime_type'], 'kind': record['kind'], 'created_at': time.time(),
                               'library_asset_id': record['id'],
                               'url': '/api/quick/projects/' + pid + '/assets/' + aid + '/download'})
                attached[record['id']] = (aid, original)
            aid, source = attached[record['id']]
            part = folder / ('sequence-%03d.mkv' % index)
            cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', str(row['inpoint']),
                   '-t', str(row['duration']), '-i', str(source)]
            audio_source = row['include_audio'] and row['info']['audio']
            if has_audio and not audio_source:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            cmd += ['-map', '0:v:0', '-vf',
                    'scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30' % (width, height, width, height),
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2']
            if has_audio:
                cmd += ['-map', '0:a:0' if audio_source else '1:a:0', '-af',
                        'aresample=48000,apad,atrim=duration=%.9f,asetpts=PTS-STARTPTS' % row['duration'],
                        '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2']
            else:
                cmd += ['-an']
            cmd += ['-t', str(row['duration']), str(part)]
            run(cmd)
            parts.append(part)
            manifest.append({'library_asset_id': record['id'], 'project_asset_id': aid,
                             'inpoint': row['inpoint'], 'duration': row['duration'],
                             'include_audio': row['include_audio'], 'source_has_audio': row['info']['audio'],
                             'output_start': elapsed_frames / 30,
                             'output_end': (elapsed_frames + row['frames']) / 30})
            elapsed_frames += row['frames']
        concat = folder / 'sequence.txt'
        concat.write_text(''.join("file '%s'\n" % p.name for p in parts))
        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '1', '-i', str(concat),
               '-map', '0:v:0', '-c:v', 'copy']
        if has_audio:
            cmd += ['-map', '0:a:0', '-c:a', 'aac', '-ar', '48000', '-ac', '2']
        else:
            cmd += ['-an']
        cmd += ['-t', str(total_frames / 30), '-movflags', '+faststart', str(folder / 'input.mp4')]
        run(cmd)
        result_info = probe(folder / 'input.mp4')
        if abs(result_info['duration'] - total_frames / 30) > .07 or result_info['audio'] != has_audio:
            raise RuntimeError('Assembled video failed duration/audio verification.')
        data = {'id': pid, 'name': name.strip(), 'created': time.time(), 'versions': [], 'history': [],
                'current_segments': [[row['output_start'], row['output_end']] for row in manifest], 'current_version': None}
        timeline.write(folder / 'project.json', data)
        proxy = types.SimpleNamespace(WORK=staging_root, project=lambda _: data)
        doc = timeline.load(proxy, pid)
        doc['assets'] = assets
        doc['library_sequence'] = {'format': 'frame-library-sequence/1', 'items': manifest,
                                   'base_input': 'normalized_flattened_sequence', 'originals_retained': True,
                                   'width': width, 'height': height, 'fps': 30, 'style_id': style_id}
        if style:
            doc['studio'] = studio.validate(proxy, pid, doc, style)
        timeline.write(folder / 'timeline.json', doc)
        timeline.write(folder / 'library-sequence.json', doc['library_sequence'])
        for part in parts:
            part.unlink()
        concat.unlink()
        # Flush bytes and directory entries before making this project discoverable.
        for item in folder.rglob('*'):
            if item.is_file():
                _sync(item)
        for item in sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            _sync_dir(item)
        _sync_dir(folder)
        folder.rename(root / pid)
        _sync_dir(root)
        return timeline.public(doc)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
