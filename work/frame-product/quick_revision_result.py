"""Record a saved note's result after a verified export in a derived project.

The source project and its timeline stay intact. The result links the exact
finished Frame export, so subsequent handoffs do not repeat the applied request.
"""
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlparse
import quick_timeline as timeline
import quick_continuation
from editor import probe


def record(app, pid, args):
    with timeline.LOCK:
        doc = timeline.load(app, pid)
        note = next((n for n in doc.get('notes', []) if n['id'] == args.get('note_id')), None)
        if not note:
            raise ValueError('Saved revision note not found.')
        target_id, export_id = args.get('result_project_id'), args.get('export_id')
        if not all(isinstance(v, str) and re.fullmatch(timeline.ID, v) for v in (target_id, export_id)):
            raise ValueError('Use valid result project and export identifiers.')
        previous = note.get('result', {})
        if note.get('status') == 'applied':
            if previous.get('project_id') == target_id and previous.get('export_id') == export_id:
                quick_continuation.ensure(app, doc)
                timeline.write(app.WORK / pid / 'timeline.json', doc)
                return timeline.public(doc)
            raise ValueError('This note already has an applied result. Save a new revision for further changes.')
        if type(args.get('expected_version')) is not int or args['expected_version'] != doc['version']:
            raise timeline.Conflict('Source project changed. Reconcile the saved revision before recording its result.')
        if note.get('included') is False or note.get('status') == 'removed':
            raise ValueError('This revision is excluded or removed.')
        if any(p.get('status') in ('planning', 'rendering') and note['id'] in [n['id'] for n in p.get('frozen_notes', [])] for p in doc.get('proposals', [])):
            raise ValueError('Wait for the active revision set before recording an external result.')
        target = timeline.load(app, target_id)
        if type(args.get('result_version')) is not int or args['result_version'] != target['version']:
            raise timeline.Conflict('Result project changed. Inspect its latest export before recording the result.')
        export = timeline.completed_export(target, export_id)
        if not export or export.get('status') != 'done' or export.get('section_id') or export.get('timeline_version') != target['version']:
            raise ValueError('Choose a completed full-video export of the current result timeline.')
        message = args.get('message')
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError('Provide a concise result description of 1–2000 characters.')
        path = app.WORK / target_id / 'versions' / export_id / 'edited.mp4'
        if not path.is_file() or not 0 < path.stat().st_size <= 700 * 1024 * 1024:
            raise ValueError('The completed output file is unavailable.')
        measured = probe(path)
        expected_duration = sum(c['end'] - c['start'] for c in target['clips'])
        if abs(measured['duration'] - expected_duration) > .1 or target['audio'] and not measured['audio']:
            raise ValueError('Output duration or audio does not match the result timeline.')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result = {'status': 'implemented', 'project_id': target_id, 'export_id': export_id,
                  'timeline_version': target['version'], 'sha256': digest.hexdigest(),
                  'message': message, 'recorded_at': time.time()}
        note.update(status='applied', result=result)
        doc['version'] += 1
        doc.setdefault('accepted_edits', []).append({'id': uuid.uuid4().hex, 'provider': 'verified_result',
            'operation': 'record_revision_result', 'arguments': {'note_id': note['id'], 'result': result},
            'timeline_version': doc['version'], 'accepted_at': time.time()})
        quick_continuation.ensure(app, doc)
        timeline.write(app.WORK / pid / 'timeline.json', doc)
        timeline.activity(app, pid, 'revision_result', message + ' · Result project ' + target_id, 'done')
        return timeline.public(timeline.load(app, pid))


def route(handler, app, method):
    match = re.fullmatch('/api/quick/projects/(' + timeline.ID + ')/revision-result', urlparse(handler.path).path)
    if method != 'POST' or not match:
        return False
    try:
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 8000:
            raise ValueError('Result request is too large.')
        args = json.loads(handler.rfile.read(length))
        if not isinstance(args, dict):
            raise ValueError('Expected a result object.')
        handler.json(200, record(app, match[1], args))
    except timeline.Conflict as exc:
        handler.json(409, {'error': str(exc)})
    except (ValueError, OSError, TypeError, KeyError) as exc:
        handler.json(400, {'error': str(exc)})
    return True
