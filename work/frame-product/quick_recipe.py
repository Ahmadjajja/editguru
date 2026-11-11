"""Documented recipes: replay a finished, fully documented production inside FRAME.

A recipe folder (repo/recipes/<name>/) holds the real production record and a recipe.json
listing its steps. This module serves the recipe and its media, and re-renders the final
cut with explicit parameter changes using the production's own compositor scripts.
"""
import ast
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

RECIPES = Path(__file__).resolve().parents[2] / 'recipes'
NAME = r'[a-z0-9][a-z0-9-]{0,63}'
JOBS = {}
LOCK = threading.Lock()


def _root(name):
    if not re.fullmatch(NAME, name or ''):
        raise ValueError('Unknown recipe.')
    root = (RECIPES / name).resolve()
    if root.parent != RECIPES.resolve() or not (root / 'recipe.json').is_file():
        raise ValueError('Recipe not found.')
    return root


def list_recipes():
    out = []
    if RECIPES.is_dir():
        for d in sorted(RECIPES.iterdir()):
            f = d / 'recipe.json'
            if f.is_file():
                r = json.loads(f.read_text())
                out.append({'name': r['name'], 'title': r.get('title', r['name']), 'steps': len(r.get('steps', [])), 'duration': r.get('duration')})
    return out


def get(name):
    return json.loads((_root(name) / 'recipe.json').read_text())


def media_path(name, rel):
    root = _root(name)
    path = (root / unquote(rel)).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError('Recipe file not found.')
    return path


# ---------------------------------------------------------------- re-render with explicit changes

def _params(recipe, given):
    spec = (recipe.get('rebuild') or {}).get('params') or {}
    out = {}
    for key, rule in spec.items():
        value = given.get(key, rule['default']) if isinstance(given, dict) else rule['default']
        if rule['type'] == 'text':
            if not isinstance(value, str) or not value.strip() or len(value) > rule.get('max', 80):
                raise ValueError('%s must be 1–%d characters.' % (rule['label'], rule.get('max', 80)))
            value = value.strip()
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not rule['min'] <= value <= rule['max']:
                raise ValueError('%s must be between %s and %s.' % (rule['label'], rule['min'], rule['max']))
            value = round(float(value), 4)
        out[key] = value
    return out


class _Patch(ast.NodeTransformer):
    """Map original absolute paths to the copied package and apply the requested values."""
    def __init__(self, mapping, values):
        self.mapping, self.values = mapping, values

    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, str) and v in self.mapping:
            return ast.copy_location(ast.Constant(self.mapping[v]), node)
        if isinstance(v, float) and 'ui_opacity' in self.values:
            if v == .22:
                return ast.copy_location(ast.Constant(self.values['ui_opacity']), node)
            if v == .78:
                return ast.copy_location(ast.Constant(round(1 - self.values['ui_opacity'], 4)), node)
        return node

    def visit_Assign(self, node):
        self.generic_visit(node)
        if 'prompt' in self.values and any(isinstance(t, ast.Name) and t.id == 'COMMAND' for t in node.targets):
            node.value = ast.copy_location(ast.Constant(self.values['prompt']), node.value)
        return node


def _ensure_deps():
    try:
        import cv2, numpy, PIL  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'opencv-python-headless', 'numpy', 'Pillow'], check=True, timeout=600)


def _rebuild_v9(root, values, work):
    mapping = {x['original_path']: str(root / x['package_path']) for x in json.loads((root / 'original-paths.json').read_text()) if x.get('exists')}
    for rel in ('V7/Frame-Export-V7.mp4', 'V8/body-vertical.mp4', 'V8/mix-v8.wav'):
        dst = work / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(root / 'project' / rel, dst)
    for rel in ('V8/build_v8.py', 'V9/build_v9.py'):
        # The prompt lives in V8 (COMMAND); the UI brightness constants live only in V9.
        own = {k: values[k] for k in (('prompt',) if rel.startswith('V8') else ('ui_opacity',)) if k in values}
        tree = _Patch(mapping, own).visit(ast.parse((root / 'project' / rel).read_text()))
        ast.fix_missing_locations(tree)
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(ast.unparse(tree) + '\n')
    _ensure_deps()
    run = subprocess.run([sys.executable, str(work / 'V9/build_v9.py')], capture_output=True, text=True, timeout=900)
    if run.returncode:
        raise RuntimeError((run.stderr or run.stdout)[-1200:])
    return work / 'V9/ChatGPT-Mastery-V9-Vertical.mp4'


def rebuild(name, given):
    root = _root(name)
    recipe = get(name)
    if (recipe.get('rebuild') or {}).get('kind') != 'v9-intro':
        raise ValueError('This recipe has no re-render step.')
    values = _params(recipe, given)
    key = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
    work = root / 'frame-renders' / key
    out = work / 'V9/ChatGPT-Mastery-V9-Vertical.mp4'
    rel = out.relative_to(root).as_posix()
    with LOCK:
        job = JOBS.get((name, key))
        if out.is_file() and (not job or job['status'] != 'working'):
            return {'status': 'done', 'key': key, 'params': values, 'path': rel, 'cached': True}
        if job and job['status'] == 'working':
            return job
        job = JOBS[(name, key)] = {'status': 'working', 'key': key, 'params': values, 'path': rel, 'started_at': time.time()}

    def work_fn():
        try:
            _rebuild_v9(root, values, work)
            result = {'status': 'done'}
        except Exception as exc:
            result = {'status': 'failed', 'error': str(exc)[-800:]}
        with LOCK:
            JOBS[(name, key)].update(result, finished_at=time.time())
    threading.Thread(target=work_fn, daemon=True).start()
    return dict(job)


def job(name, key):
    with LOCK:
        j = JOBS.get((name, key))
        if j:
            return dict(j)
    out = _root(name) / 'frame-renders' / key / 'V9/ChatGPT-Mastery-V9-Vertical.mp4'
    if out.is_file():
        return {'status': 'done', 'key': key, 'path': out.relative_to(_root(name)).as_posix()}
    raise ValueError('Render not found.')


def route(handler, app, method):
    import quick_recipe_apply
    if quick_recipe_apply.route(handler, app, method):
        return True
    path = urlparse(handler.path).path
    if not (path.startswith('/api/recipes') or path.startswith('/recipe-media/')):
        return False
    try:
        m = re.fullmatch('/recipe-media/(' + NAME + ')/(.+)', path)
        if method == 'GET' and m:
            file = media_path(m[1], m[2])
            ctype = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or file.suffix in ('.md', '.txt', '.json'):
                handler.send(200, file.read_bytes(), 'text/plain; charset=utf-8')
            else:
                handler.media(file, ctype)
            return True
        if method == 'GET' and path == '/api/recipes':
            handler.json(200, {'recipes': list_recipes()}); return True
        m = re.fullmatch('/api/recipes/(' + NAME + ')(?:/(rebuild)(?:/([a-f0-9]{16}))?)?', path)
        if not m:
            raise ValueError('Unknown recipe request.')
        if method == 'GET' and not m[2]:
            handler.json(200, get(m[1]))
        elif method == 'GET' and m[3]:
            handler.json(200, job(m[1], m[3]))
        elif method == 'POST' and m[2] and not m[3]:
            length = int(handler.headers.get('Content-Length', '0'))
            body = json.loads(handler.rfile.read(length)) if 0 < length <= 20000 else {}
            handler.json(200, rebuild(m[1], body.get('params') or {}))
        else:
            raise ValueError('Unsupported recipe request.')
    except (ValueError, OSError, KeyError) as exc:
        handler.json(400, {'error': str(exc)})
    return True
