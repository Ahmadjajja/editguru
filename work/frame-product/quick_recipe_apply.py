"""Small reusable recipe slice. Plans and execution receipts live in timeline.json.

No old production media is imported. Each step commits its cursor and video edit
in one atomic timeline write; optimistic versions protect concurrent editors.
"""
import copy
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import quick_recipe
import quick_style as style
import quick_studio as studio
import quick_timeline as timeline

RECIPE = 'chatgpt-mastery-9x16'
COMPILER = 'recipe-transfer/1'


def source_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(style.canonical(value).encode()).hexdigest()


def template():
    root = quick_recipe._root(RECIPE)
    return json.loads((root / 'transfer.json').read_text())


def compile_plan(app, pid, body):
    spec = template()
    with timeline.LOCK:
        doc = timeline.load(app, pid)
        if type(body.get('expected_version')) is not int or body['expected_version'] != doc['version']:
            raise timeline.Conflict('Timeline changed. Review a new plan.')
        if not 0 < doc['source_duration'] <= 300:
            raise ValueError('This slice supports footage up to five minutes.')
        source = source_sha(Path(app.WORK) / pid / 'input.mp4')
        ws = style.words(app, pid)['words']
        timing = 'saved word timings'
        if body.get('script'):
            script = body['script']
            if not isinstance(script, str) or len(script) > 12000:
                raise ValueError('Script must be text of up to 12000 characters.')
            tokens = script.split()
            if not 1 <= len(tokens) <= 600:
                raise ValueError('Use 1–600 script words.')
            span = doc['source_duration'] / len(tokens)
            if span < 1 / 30:
                raise ValueError('Too many script words for this footage.')
            ws = [{'w': w, 's': round(i * span, 6), 'e': round((i + 1) * span, 6)} for i, w in enumerate(tokens)]
            timing = 'estimated: script words distributed evenly across source; no speech alignment'
        if not ws:
            raise ValueError('Paste a new script or save a timed transcript in the editor first.')
        if any(w['s'] < 0 or w['e'] > doc['source_duration'] + .01 for w in ws):
            raise ValueError('Transcript extends beyond this footage.')
        identity = spec['identity']
        ops = [{'id': 'portrait', 'fields': identity['frame']},
               {'id': 'captions', 'caption_rules': identity['captions']}]
        plan = {'compiler': COMPILER, 'recipe': RECIPE, 'template': spec,
                'source_sha256': source, 'words': ws, 'timing': timing,
                'clips': copy.deepcopy(doc['clips']), 'ops': ops,
                'base_version': doc['version'], 'project_id': pid}
        # Clip identifiers are incidental, but time/order/position affect the plan.
        plan['clips'] = [{k: v for k, v in c.items() if k not in ('id', 'origin_id')} for c in plan['clips']]
        plan['digest'] = digest(plan)
        return plan


def run_action(app, pid, action, body):
    with timeline.LOCK:
        doc = timeline.load(app, pid)
        if action == 'plan':
            return compile_plan(app, pid, body)
        runs = doc.setdefault('recipe_runs', [])
        if action == 'start':
            plan = compile_plan(app, pid, body)
            if body.get('digest') != plan['digest']:
                raise timeline.Conflict('Inputs changed. Review the plan again before starting.')
            if any(r['status'] in ('running', 'paused') for r in runs):
                raise ValueError('Finish the current recipe run before starting another.')
            if len(runs) >= 20:
                raise ValueError('This project has 20 recipe runs; start a new project.')
            run = {'id': uuid.uuid4().hex, 'plan': plan, 'status': 'running', 'next': 0,
                   'version': doc['version'], 'baseline': copy.deepcopy(doc.get('studio', {})), 'receipts': []}
            runs.append(run)
        else:
            run = next((r for r in runs if r['id'] == body.get('run_id')), None)
            if run is None:
                raise ValueError('Recipe run not found.')
            if action == 'get':
                return copy.deepcopy(run)
            if type(body.get('expected_version')) is not int or body['expected_version'] != doc['version']:
                raise timeline.Conflict('Timeline changed. Reload before continuing.')
            if run['status'] == 'done':
                return copy.deepcopy(run)
            if action == 'pause':
                run['status'] = 'paused'
            elif action == 'resume':
                if run['status'] != 'paused':
                    raise ValueError('Pause the run before reconciling edits.')
                run['version'] = doc['version']
                run['status'] = 'running'
            elif action == 'step':
                # Idempotency token: a retried request cannot advance twice.
                if body.get('next') != run['next']:
                    return copy.deepcopy(run)
                if run['status'] != 'running':
                    raise ValueError('Resume the paused recipe first.')
                if run['version'] != doc['version']:
                    raise timeline.Conflict('An editor changed this video. Pause and resume to keep those edits.')
                if source_sha(Path(app.WORK) / pid / 'input.mp4') != run['plan']['source_sha256']:
                    raise timeline.Conflict('Source footage changed. Start a new project and plan.')
                op = run['plan']['ops'][run['next']]
                current = {**copy.deepcopy(studio.DEFAULT), **copy.deepcopy(doc.get('studio', {}))}
                baseline = {**copy.deepcopy(studio.DEFAULT), **run['baseline']}
                before = studio.snapshot(doc)
                kept = []
                if op['id'] == 'portrait':
                    for key, value in op['fields'].items():
                        if current[key] != baseline[key]:
                            kept.append(key)
                        else:
                            current[key] = value
                elif current['captions'] != baseline['captions']:
                    kept.append('captions')
                else:
                    current['captions'] = [c for c in current['captions'] if c.get('origin') != 'speech'] + style.caption_cues(doc['clips'], run['plan']['words'], op['caption_rules'])
                doc['studio'] = studio.validate(app, pid, doc, current)
                changed = before != studio.snapshot(doc)
                if changed:
                    doc['undo'] = (doc['undo'] + [before])[-100:]
                    doc['redo'] = []
                    doc.pop('editor_state', None)
                    doc['version'] += 1
                    doc.setdefault('accepted_edits', []).append({'id': uuid.uuid4().hex, 'provider': COMPILER,
                        'operation': op['id'], 'timeline_version': doc['version'], 'accepted_at': time.time(),
                        'arguments': {'run_id': run['id'], 'plan_digest': run['plan']['digest']}})
                run['receipts'].append({'op': op['id'], 'version': doc['version'], 'kept_user_fields': kept,
                    'execution_clips': copy.deepcopy(doc['clips']), 'changed': changed})
                run['next'] += 1
                run['version'] = doc['version']
                if run['next'] == len(run['plan']['ops']):
                    run['status'] = 'done'
            else:
                raise ValueError('Unknown recipe action.')
        timeline.validate(doc)
        timeline.write(Path(app.WORK) / pid / 'timeline.json', doc)
        return copy.deepcopy(run)


def route(handler, app, method):
    path = urlparse(handler.path).path
    if method == 'GET' and path == '/recipe-apply':
        handler.send(200, (Path(__file__).parent / 'swarm' / 'recipe-apply.html').read_bytes(), 'text/html; charset=utf-8')
        return True
    export = re.fullmatch(r'/api/recipe-apply/([a-f0-9]{32})/exports/([a-f0-9]{32})', path)
    if method == 'GET' and export:
        with timeline.LOCK:
            try:
                doc = timeline.load(app, export[1])
                record = timeline.completed_export(doc, export[2])
                if not record or 'recipe_provenance' not in record:
                    raise ValueError('No recipe provenance for this export.')
                handler.json(200, record['recipe_provenance'])
            except (ValueError, OSError) as exc:
                handler.json(404, {'error': str(exc)})
        return True
    m = re.fullmatch(r'/api/recipe-apply/([a-f0-9]{32})/(plan|start|get|step|pause|resume)', path)
    if not m:
        return False
    try:
        if method != 'POST':
            raise ValueError('Use POST for recipe actions.')
        handler.json(200, run_action(app, m[1], m[2], style._body(handler)))
    except timeline.Conflict as exc:
        handler.json(409, {'error': str(exc)})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        handler.json(400, {'error': str(exc)})
    return True
