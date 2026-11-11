"""FRAME styles: frame-style/1 validation, deterministic plans and headless apply.

A style is saved as an asset-library recipe (kind='style'). `plan()` is a pure
function of (style, source bytes, transcript words): the same inputs always give
the same ops and digest. No model runs here. Ops use original-source seconds, so
the Swarmcut editor and the headless applier interpret them identically.
"""
import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import quick_asset_library as library
import quick_studio as studio
import quick_timeline as timeline

FORMAT = 'frame-style/1'
PLAN_FORMAT = 'frame-plan/1'
COMPILER_VERSION = 1
ID = r'[a-f0-9]{32}'
TOP = {'format', 'name', 'revision', 'parent_style_id', 'provenance', 'frame', 'look', 'audio',
       'pacing', 'captions', 'broll', 'slots', 'locked', 'evidence', 'owned'}
HEX = r'#[0-9a-fA-F]{6}'
CAPTION_STYLES = ('lime', 'stack', 'karaoke', 'minimal')
CAPTION_FONTS = ('inter', 'grotesk', 'bebas', 'marker', 'fraunces')
METHODS = ('measured', 'extracted', 'user_set', 'feedback')
JOBS = {}
JOB_LOCK = threading.Lock()


# ---------------------------------------------------------------- validation

def _num(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('%s must be a number from %s to %s.' % (label, low, high))
    return float(value)


def _obj(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object.')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError('Unknown %s setting: %s.' % (label, ', '.join(sorted(unknown))))
    return value


def _text(value, label, limit=500, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit:
        raise ValueError('%s must be text of up to %d characters.' % (label, limit))
    return value.strip()


def _ident(value, label):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise ValueError(label + ' must be a 32-character identifier.')
    return value


def _get(style, path):
    node = style
    for part in path.split('.'):
        if isinstance(node, list):
            node = next((x for x in node if isinstance(x, dict) and x.get('id') == part), None)
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
        if node is None:
            return None
    return node


def validate(style):
    s = copy.deepcopy(_obj(style, TOP, 'style'))
    if s.get('format') != FORMAT:
        raise ValueError('Style format must be ' + FORMAT + '.')
    s['name'] = _text(s.get('name'), 'Style name', 120)
    s['revision'] = s.get('revision', 1)
    if type(s['revision']) is not int or s['revision'] < 1:
        raise ValueError('Style revision must be a positive integer.')
    if s.get('parent_style_id') is not None:
        _ident(s['parent_style_id'], 'Parent style')
    p = _obj(s.get('provenance'), {'source_kind', 'reference_project_ids', 'reference_sha256', 'use_scope', 'rights_note', 'starter'}, 'provenance')
    if p.get('source_kind') not in ('brand_reference', 'own_video', 'starter', 'frame_starter'):
        raise ValueError('Every style needs a source: brand_reference, own_video, starter or frame_starter.')
    refs = p.setdefault('reference_project_ids', [])
    if not isinstance(refs, list) or len(refs) > 20:
        raise ValueError('Use up to 20 reference projects.')
    for r in refs:
        _ident(r, 'Reference project')
    shas = p.setdefault('reference_sha256', [])
    if not isinstance(shas, list) or any(not isinstance(x, str) or not re.fullmatch('[a-f0-9]{64}', x) for x in shas):
        raise ValueError('Reference digests must be SHA-256 hex strings.')
    scope = _obj(p.setdefault('use_scope', {'type': 'creator'}), {'type', 'brand'}, 'use_scope')
    if scope.get('type') not in ('creator', 'brand'):
        raise ValueError('use_scope.type must be creator or brand.')
    if scope['type'] == 'brand':
        scope['brand'] = _text(scope.get('brand'), 'Brand name', 120)
    elif 'brand' in scope:
        raise ValueError('Only brand-scoped styles name a brand.')
    p['rights_note'] = _text(p.get('rights_note', ''), 'Rights note', 500, empty=True)
    if p['source_kind'] == 'starter':
        st = _obj(p.get('starter'), {'style_id', 'min_changed_fields'}, 'starter')
        _ident(st.get('style_id'), 'Starter style')
        st['min_changed_fields'] = st.get('min_changed_fields', 5)
        if type(st['min_changed_fields']) is not int or not 1 <= st['min_changed_fields'] <= 50:
            raise ValueError('min_changed_fields must be 1–50.')
    elif p.get('starter') is not None:
        raise ValueError('Only starter styles carry starter details.')
    if 'frame' in s:
        f = _obj(s['frame'], {'aspect', 'fit'}, 'frame')
        if 'aspect' in f and f['aspect'] not in ('source', '9:16', '16:9', '1:1'):
            raise ValueError('frame.aspect must be source, 9:16, 16:9 or 1:1.')
        if 'fit' in f and f['fit'] not in ('contain', 'cover'):
            raise ValueError('frame.fit must be contain or cover.')
    if 'look' in s:
        l = _obj(s['look'], {'brightness', 'contrast', 'saturation'}, 'look')
        for k, lo, hi in (('brightness', -.3, .3), ('contrast', .5, 2), ('saturation', 0, 2)):
            if k in l:
                l[k] = _num(l[k], lo, hi, 'look.' + k)
    if 'audio' in s:
        a = _obj(s['audio'], {'voice_volume', 'music'}, 'audio')
        if 'voice_volume' in a:
            a['voice_volume'] = _num(a['voice_volume'], 0, 2, 'audio.voice_volume')
        if 'music' in a:
            m = _obj(a['music'], {'slot', 'volume'}, 'audio.music')
            m['slot'] = _text(m.get('slot'), 'Music slot', 80)
            m['volume'] = _num(m.get('volume', .18), 0, 2, 'audio.music.volume')
    if 'pacing' in s:
        pc = _obj(s['pacing'], {'remove_pauses', 'min_pause_s', 'pad_s', 'cut_first_s', 'remove_retakes'}, 'pacing')
        for k in ('remove_pauses', 'remove_retakes'):
            if k in pc and not isinstance(pc[k], bool):
                raise ValueError('pacing.%s must be true or false.' % k)
        for k, lo, hi in (('min_pause_s', .15, 3), ('pad_s', 0, .5), ('cut_first_s', 0, 30)):
            if k in pc:
                pc[k] = _num(pc[k], lo, hi, 'pacing.' + k)
    if 'captions' in s:
        c = _obj(s['captions'], {'source', 'max_words', 'max_s', 'x', 'y', 'size', 'color', 'emphasis_color', 'case', 'style', 'font', 'font_slot'}, 'captions')
        if c.get('source', 'speech') != 'speech':
            raise ValueError('captions.source must be speech.')
        c['source'] = 'speech'
        if 'max_words' in c and (type(c['max_words']) is not int or not 1 <= c['max_words'] <= 8):
            raise ValueError('captions.max_words must be 1–8.')
        for k, lo, hi in (('max_s', .3, 5), ('x', 0, 1), ('y', 0, 1), ('size', .015, .12)):
            if k in c:
                c[k] = _num(c[k], lo, hi, 'captions.' + k)
        for k in ('color', 'emphasis_color'):
            if k in c and (not isinstance(c[k], str) or not re.fullmatch(HEX, c[k])):
                raise ValueError('captions.%s must be a hex color.' % k)
        if 'case' in c and c['case'] not in ('upper', 'sentence', 'as_spoken'):
            raise ValueError('captions.case must be upper, sentence or as_spoken.')
        if 'style' in c and c['style'] not in CAPTION_STYLES:
            raise ValueError('captions.style must be one of ' + ', '.join(CAPTION_STYLES) + '.')
        if 'font' in c and c['font'] not in CAPTION_FONTS:
            raise ValueError('captions.font must be one of ' + ', '.join(CAPTION_FONTS) + '.')
    if 'broll' in s:
        b = _obj(s['broll'], {'per_10s', 'max_s', 'placement', 'source'}, 'broll')
        if 'source' in b and b['source'] not in ('user_selected', 'slot'):
            raise ValueError('broll.source must be user_selected or slot.')
        for k, lo, hi in (('per_10s', 0, 5), ('max_s', .3, 10)):
            if k in b:
                b[k] = _num(b[k], lo, hi, 'broll.' + k)
        if 'placement' in b:
            _placement(b['placement'])
    if 'slots' in s:
        if not isinstance(s['slots'], list) or len(s['slots']) > 12:
            raise ValueError('Use up to 12 asset slots.')
        seen = set()
        for slot in s['slots']:
            _obj(slot, {'id', 'kind', 'required', 'asset_id', 'placement'}, 'slot')
            if not isinstance(slot.get('id'), str) or not re.fullmatch('[a-z0-9_]{1,40}', slot['id']) or slot['id'] in seen:
                raise ValueError('Each slot needs a unique lowercase id.')
            seen.add(slot['id'])
            if slot.get('kind') not in ('image', 'audio', 'clip', 'font'):
                raise ValueError('Slot kind must be image, audio, clip or font.')
            slot['required'] = bool(slot.get('required', False))
            if slot.get('asset_id') is not None:
                _ident(slot['asset_id'], 'Slot asset')
            else:
                slot['asset_id'] = None
            if 'placement' in slot:
                _placement(slot['placement'])
    if 'locked' in s:
        if not isinstance(s['locked'], list) or len(s['locked']) > 50:
            raise ValueError('Use up to 50 locked fields.')
        for path in s['locked']:
            if not isinstance(path, str) or _get(s, path) is None:
                raise ValueError('Locked field %r is not set in this style.' % (path,))
    if 'evidence' in s:
        if not isinstance(s['evidence'], dict) or len(s['evidence']) > 100:
            raise ValueError('Evidence must be an object of up to 100 fields.')
        for path, ev in s['evidence'].items():
            _obj(ev, {'method', 'reference', 'at_s', 'note', 'feedback_id', 'value'}, 'evidence')
            if ev.get('method') not in METHODS:
                raise ValueError('Evidence method must be one of ' + ', '.join(METHODS) + '.')
            if 'note' in ev:
                ev['note'] = _text(ev['note'], 'Evidence note', 300)
    if 'owned' in s and not isinstance(s['owned'], bool):
        raise ValueError('owned must be true or false.')
    library._json(s, 'Style')  # finite and size-limited
    return s


def _placement(value):
    pl = _obj(value, {'x', 'y', 'width'}, 'placement')
    for k, lo, hi in (('x', 0, 1), ('y', 0, 1), ('width', .05, 1)):
        if k in pl:
            pl[k] = _num(pl[k], lo, hi, 'placement.' + k)
    return pl


def canonical(style):
    return json.dumps(style, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


CREATIVE = ('frame', 'look', 'audio', 'pacing', 'captions', 'broll', 'slots')


def _leaves(node, prefix=''):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, prefix + ('.' if prefix else '') + k)
    elif isinstance(node, list) and all(isinstance(x, dict) and 'id' in x for x in node):
        for x in node:
            yield from _leaves({k: v for k, v in x.items() if k != 'id'}, prefix + '.' + x['id'])
    else:
        yield prefix, node


def changed_fields(a, b):
    left = dict(x for k in CREATIVE for x in _leaves(a.get(k, {}), k))
    right = dict(x for k in CREATIVE for x in _leaves(b.get(k, {}), k))
    return sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))


# ---------------------------------------------------------------- storage

def save(app, style, project_id=None, parent_style_id=None, unlock=()):
    s = validate(style)
    if project_id is not None:
        _ident(project_id, 'Project')
    if parent_style_id:
        parent = get(app, parent_style_id, project_id)['style']
        unlock = set(unlock or ())
        for path in parent.get('locked', []):
            if path not in unlock and _get(parent, path) != _get(s, path):
                raise ValueError('“%s” is locked in this style. Unlock it explicitly to change it.' % path)
        s['parent_style_id'] = parent_style_id
        s['revision'] = parent.get('revision', 1) + 1
    if s['provenance']['source_kind'] == 'starter':
        starter = get(app, s['provenance']['starter']['style_id'], project_id)['style']
        s['owned'] = len(changed_fields(starter, s)) >= s['provenance']['starter']['min_changed_fields']
    else:
        s['owned'] = s['provenance']['source_kind'] != 'frame_starter'
    tags = ['frame-style', s['provenance']['source_kind']]
    if s['provenance']['use_scope']['type'] == 'brand':
        tags.append('brand:' + s['provenance']['use_scope']['brand'][:70])
    record = library.save_recipe(app, name=s['name'], kind='style', recipe=s, tags=tags, project_id=project_id)
    return {'style_id': record['id'], 'style': record['recipe'], 'scope': record['scope']}


def get(app, style_id, project_id=None):
    record = library.get(app, _ident(style_id, 'Style'))
    if record['kind'] != 'style' or not isinstance(record.get('recipe'), dict) or record['recipe'].get('format') != FORMAT:
        raise ValueError('That library item is not a frame-style/1 style.')
    if record['project_id'] not in (None, project_id):
        raise ValueError('This style belongs to a different project.')
    return {'style_id': record['id'], 'style': record['recipe'], 'scope': record['scope'], 'created_at': record.get('created_at')}


STARTERS = [{
    'format': FORMAT, 'name': 'Starter · Clean talking head',
    'provenance': {'source_kind': 'frame_starter', 'use_scope': {'type': 'creator'},
                   'rights_note': 'FRAME starter. Change it and save it as your own style.'},
    'frame': {'aspect': '9:16', 'fit': 'cover'},
    'pacing': {'remove_pauses': True, 'min_pause_s': .35, 'pad_s': .12, 'remove_retakes': True},
    'captions': {'max_words': 3, 'max_s': 1.6, 'y': .72, 'size': .055, 'color': '#FFFFFF', 'case': 'upper', 'style': 'lime', 'font': 'inter'},
}]


def seed_starters(app):
    for starter in STARTERS:
        save(app, copy.deepcopy(starter))  # identical recipe is stored once (library fingerprint)
    # Styles documented in a recipe kit (recipes/<kit>/specifications/style-*.json) are offered too,
    # so a style written up alongside a production is pickable without re-entering it.
    kits = Path(__file__).resolve().parents[2] / 'recipes'
    for path in sorted(kits.glob('*/specifications/style-*.json')) if kits.is_dir() else []:
        try:
            save(app, json.loads(path.read_text()))
        except (OSError, ValueError):
            continue


def list_styles(app, project_id=None):
    seed_starters(app)
    rows = library.search(app, kind='style', project_id=project_id, limit=200)
    return [{'style_id': r['id'], 'name': r['name'], 'revision': r['recipe'].get('revision', 1),
             'source_kind': r['recipe']['provenance']['source_kind'], 'owned': r['recipe'].get('owned', True),
             'use_scope': r['recipe']['provenance']['use_scope'], 'scope': r['scope'], 'created_at': r.get('created_at')}
            for r in rows if isinstance(r.get('recipe'), dict) and r['recipe'].get('format') == FORMAT]


def _resolve_style(app, pid, body):
    if body.get('style_id'):
        return get(app, body['style_id'], pid)['style']
    if body.get('style') is not None:
        return validate(body['style'])
    raise ValueError('Supply style_id or style.')


# ---------------------------------------------------------------- transcript

def _folder(app, pid):
    _ident(pid, 'Project')
    folder = Path(app.WORK) / pid
    if not (folder / 'input.mp4').is_file():
        raise ValueError('Project video not found.')
    return folder


def words(app, pid):
    """Word timings in original-source seconds: [{'w','s','e'}], sorted."""
    folder = _folder(app, pid)
    segments, source = None, None
    for name in ('transcript.json', 'analysis.json'):
        path = folder / name
        if path.exists():
            try:
                segments = json.loads(path.read_text()).get('transcript')
            except (OSError, ValueError):
                segments = None
            if segments:
                source = name
                break
    out = []
    for seg in segments or []:
        for w in (seg.get('words') or [seg]):
            text = str(w.get('text', w.get('w', ''))).strip()
            if text and isinstance(w.get('start', w.get('s')), (int, float)):
                s = float(w.get('start', w.get('s'))); e = float(w.get('end', w.get('e', s)))
                out.append({'w': text, 's': round(s, 3), 'e': round(max(e, s + .02), 3)})
    out.sort(key=lambda w: (w['s'], w['e']))
    with JOB_LOCK:
        job = copy.deepcopy(JOBS.get(pid))
    return {'words': out, 'source': source, 'job': job}


def store_words(app, pid, rows, label='imported'):
    folder = _folder(app, pid)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('Supply 1–20000 timed words.')
    clean = []
    for w in rows:
        if not isinstance(w, dict):
            raise ValueError('Each word must be an object.')
        text = _text(w.get('w', w.get('text')), 'Word', 200)
        s = _num(w.get('s', w.get('start')), 0, 86400, 'Word start')
        e = _num(w.get('e', w.get('end')), 0, 86400, 'Word end')
        if e < s:
            raise ValueError('Word end precedes its start.')
        clean.append({'start': round(s, 3), 'end': round(e, 3), 'text': text})
    clean.sort(key=lambda w: w['start'])
    doc = {'transcript': [{'start': clean[0]['start'], 'end': clean[-1]['end'], 'text': ' '.join(w['text'] for w in clean), 'words': clean}],
           'source': label, 'saved_at': time.time()}
    temp = folder / 'transcript.tmp'
    temp.write_text(json.dumps(doc))
    temp.replace(folder / 'transcript.json')
    return words(app, pid)


def _whisper(path):
    """Use the cached small.en model; download it once if this Mac doesn't have it yet."""
    import editor
    try:
        return editor.transcribe(path)
    except Exception as first:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError('Transcription needs faster-whisper installed in Frame\'s .venv.') from first
        with editor.TRANSCRIBE_LOCK:
            if editor.MODEL is None:
                editor.MODEL = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=4)
        return editor.transcribe(path)


def transcribe(app, pid):
    folder = _folder(app, pid)
    with JOB_LOCK:
        if (JOBS.get(pid) or {}).get('status') == 'working':
            return JOBS[pid]
        JOBS[pid] = {'status': 'working', 'started_at': time.time()}

    def work():
        try:
            with app.WORKERS:
                segments = _whisper(folder / 'input.mp4')
            flat = [w for seg in segments for w in (seg.get('words') or [])]
            if not flat:
                raise RuntimeError('No speech was recognized in this video.')
            store_words(app, pid, flat, 'faster-whisper')
            result = {'status': 'done', 'count': len(flat)}
        except Exception as exc:
            result = {'status': 'failed', 'error': str(exc)[-500:]}
        with JOB_LOCK:
            JOBS[pid] = dict(result, finished_at=time.time())
    threading.Thread(target=work, daemon=True).start()
    with JOB_LOCK:
        return copy.deepcopy(JOBS[pid])


# ---------------------------------------------------------------- deterministic compiler

def pause_ranges(ws, duration, min_pause, pad):
    """Same rule as the Swarmcut editor: cut silence between words, keep pad around speech."""
    pad_in, pad_out = pad + .03, pad
    out = []
    if not ws:
        return out
    if ws[0]['s'] - pad_in >= min_pause:
        out.append((0.0, ws[0]['s'] - pad_in))
    for a, b in zip(ws, ws[1:]):
        x, y = a['e'] + pad_out, b['s'] - pad_in
        if b['s'] - a['e'] >= min_pause and y - x >= .15:
            out.append((x, y))
    if duration - ws[-1]['e'] >= min_pause:
        out.append((ws[-1]['e'] + pad_out, duration))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > .05]


def audio_pauses(folder, duration, min_pause, pad):
    """Quiet spans measured once per source file and cached, so plans stay reproducible."""
    cache = folder / 'silence.json'
    key = _sha_file(folder / 'input.mp4')
    regions = None
    if cache.exists():
        try:
            saved = json.loads(cache.read_text())
            regions = saved['regions'] if saved.get('sha256') == key else None
        except (OSError, ValueError, KeyError):
            regions = None
    if regions is None:
        from editor import detect_silence
        regions = [[round(a, 3), round(b, 3)] for a, b in detect_silence(folder / 'input.mp4')]
        cache.write_text(json.dumps({'sha256': key, 'regions': regions}))
    out = []
    for a, b in regions:
        x = 0.0 if a <= .05 else a + pad
        y = duration if b >= duration - .05 else b - pad
        if b - a >= min_pause and y - x >= .15:
            out.append((round(x, 3), round(y, 3)))
    return out


def _norm(text):
    return re.sub('[^a-z0-9]', '', text.lower().replace("'", '').replace('’', ''))


def _lcs(a, b):
    dp = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b, 1):
            dp[j], prev = (prev + 1 if x == y else max(dp[j], dp[j - 1])), dp[j]
    return dp[-1]


def retake_ranges(ws):
    """A phrase mostly repeated by a later phrase that opens the same way is an earlier take."""
    if len(ws) < 6:
        return []
    segs, cur = [], []
    for i, w in enumerate(ws):
        if cur and w['s'] - ws[i - 1]['e'] > .7:
            segs.append(cur); cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    toks = [[t for t in (_norm(w['w']) for w in sg) if t] for sg in segs]
    out = []
    for i, ti in enumerate(toks):
        if len(ti) < 3:
            continue
        for j in range(i + 1, len(segs)):
            tj = toks[j]
            if len(tj) < 3 or ti[0] not in tj[:3]:
                continue
            if _lcs(ti, tj) / len(ti) >= .8:
                out.append((round(max(0, segs[i][0]['s'] - .2), 3), round(segs[i][-1]['e'] + .2, 3),
                            ' '.join(w['w'] for w in segs[i])))
                break
    return out


def _sha_file(path):
    cache = path.parent / (path.name + '.sha256')
    stat = path.stat()
    key = '%d:%d' % (stat.st_size, int(stat.st_mtime))
    if cache.exists():
        saved = cache.read_text().split()
        if len(saved) == 2 and saved[0] == key:
            return saved[1]
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    cache.write_text(key + ' ' + h.hexdigest())
    return h.hexdigest()


def plan(app, pid, style):
    """Compile a style into ordered ops. Only fields the style sets produce ops."""
    s = validate(style)
    folder = _folder(app, pid)
    with timeline.LOCK:
        doc = timeline.load(app, pid)
    duration = float(doc['source_duration'])
    ws = words(app, pid)['words']
    ops, warnings = [], []

    def add(lane, kind, label, **data):
        ops.append(dict(id='%s-%02d' % (lane, sum(o['lane'] == lane for o in ops) + 1), lane=lane, kind=kind, label=label, **data))

    pc = s.get('pacing', {})
    if pc.get('cut_first_s'):
        add('razor', 'cut', 'cut the first %.2f s' % pc['cut_first_s'], source=[0.0, round(min(pc['cut_first_s'], duration - .5), 3)])
    if pc.get('remove_retakes'):
        if ws:
            for a, b, text in retake_ranges(ws):
                add('razor', 'cut', 'removed an earlier take: “%s…”' % ' '.join(text.split()[:6]), source=[a, b])
        else:
            warnings.append('Retakes need a transcript; none is saved for this video.')
    if pc.get('remove_pauses'):
        if ws:
            for a, b in pause_ranges(ws, duration, pc.get('min_pause_s', .35), pc.get('pad_s', .12)):
                add('razor', 'cut', 'cut %.2f s pause' % (b - a), source=[a, b])
        elif doc.get('audio'):
            for a, b in audio_pauses(folder, duration, pc.get('min_pause_s', .35), pc.get('pad_s', .12)):
                add('razor', 'cut', 'cut %.2f s quiet gap (audio level)' % (b - a), source=[a, b])
            warnings.append('No transcript yet, so pauses were found by audio level. Transcribe for word-accurate cuts and captions.')
        else:
            warnings.append('Pause cutting needs a transcript or an audio track.')
    if 'frame' in s:
        add('frame', 'frame', 'frame → ' + ', '.join('%s %s' % kv for kv in sorted(s['frame'].items())), **s['frame'])
    if 'look' in s:
        add('grade', 'look', 'look → ' + ', '.join('%s %g' % kv for kv in sorted(s['look'].items())), **s['look'])
    if 'captions' in s:
        if ws:
            c = s['captions']
            look = c.get('style') or ('%s emphasis' % c['emphasis_color'] if c.get('emphasis_color') else 'minimal')
            add('caps', 'captions', 'captions: %d words per line, %s, %s' % (c.get('max_words', 3), c.get('case', 'as spoken').replace('_', ' '), look), **c)
        else:
            warnings.append('Captions need a transcript; none is saved for this video.')
    audio = s.get('audio', {})
    if 'voice_volume' in audio:
        add('mix', 'voice', 'voice volume → %g' % audio['voice_volume'], volume=audio['voice_volume'])
    slots = {x['id']: x for x in s.get('slots', [])}
    if 'music' in audio:
        slot = slots.get(audio['music']['slot'])
        if slot and slot.get('asset_id'):
            add('mix', 'music', 'music bed → slot %s' % slot['id'], slot=slot['id'], asset_id=slot['asset_id'], volume=audio['music']['volume'])
        else:
            warnings.append('Music slot “%s” has no asset yet.' % audio['music']['slot'])
    for slot in s.get('slots', []):
        if slot['kind'] == 'image' and slot.get('asset_id'):
            pl = {'x': .5, 'y': .5, 'width': .3, **slot.get('placement', {})}
            add('gfx', 'overlay', 'placed %s overlay' % slot['id'], slot=slot['id'], asset_id=slot['asset_id'], **pl)
        elif slot['required'] and not slot.get('asset_id') and slot['kind'] != 'audio':
            warnings.append('Required slot “%s” has no asset yet.' % slot['id'])
    digest = hashlib.sha256(json.dumps([COMPILER_VERSION, canonical(s), _sha_file(folder / 'input.mp4'),
                                        canonical(ws)], separators=(',', ':')).encode()).hexdigest()
    return {'format': PLAN_FORMAT, 'compiler_version': COMPILER_VERSION, 'digest': digest, 'style_name': s['name'],
            'style_revision': s['revision'], 'source_duration': duration, 'word_count': len(ws),
            'ops': ops, 'warnings': warnings}


# ---------------------------------------------------------------- headless apply (same semantics as the editor)

def cut_source(clips, a, b):
    out = []
    for c in clips:
        if c['end'] <= a or c['start'] >= b:
            out.append(c); continue
        if a - c['start'] >= 1 / 30:
            out.append(dict(c, end=round(a * 30) / 30))
        if c['end'] - b >= 1 / 30:
            out.append(dict(c, id=uuid.uuid4().hex if a - c['start'] >= 1 / 30 else c['id'], start=round(b * 30) / 30))
    return out


def caption_cues(clips, ws, c):
    """Group words into cues after cuts; output time, like quick_studio.transcript_captions."""
    per, span = c.get('max_words', 3), c.get('max_s', 1.6)
    case = c.get('case', 'as_spoken')
    cues, offset = [], 0.0
    for clip in clips:
        group = []

        def flush():
            if not group:
                return
            text = ' '.join(w['text'] for w in group)
            text = text.upper() if case == 'upper' else (text[:1].upper() + text[1:]) if case == 'sentence' else text
            cues.append({'id': 'style_%d' % len(cues), 'origin': 'speech', 'text': text[:500],
                         'start': round(group[0]['start'], 3), 'end': round(max(group[-1]['end'], group[0]['start'] + 1 / 30), 3),
                         'x': c.get('x', .5), 'y': c.get('y', .72), 'size': c.get('size', .055), 'color': c.get('color', '#ffffff')})
        for w in ws:
            lo, hi = max(clip['start'], w['s']), min(clip['end'], w['e'])
            if hi <= lo:
                continue
            item = {'start': offset + lo - clip['start'], 'end': offset + hi - clip['start'], 'text': w['w']}
            if group and (len(group) >= per or item['end'] - group[0]['start'] > span):
                flush(); group = []
            group.append(item)
        flush()
        offset += clip['end'] - clip['start']
    if len(cues) > 150:
        raise ValueError('This edit needs more than 150 caption cues. Trim it first.')
    return cues


def apply(app, pid, style, expected_version, only=None):
    """Apply a plan one op per timeline version. Returns the plan with applied versions."""
    compiled = plan(app, pid, style)
    ws = words(app, pid)['words']
    version = expected_version
    applied = []
    for op in compiled['ops']:
        if only is not None and op['id'] not in only:
            continue
        version = apply_op(app, pid, op, version, ws)
        applied.append({'id': op['id'], 'version': version})
    with timeline.LOCK:
        doc = timeline.public(timeline.load(app, pid))
    return {'plan': compiled, 'applied': applied, 'project': doc}


def apply_op(app, pid, op, version, ws=None):
    with timeline.LOCK:
        doc = timeline.load(app, pid)
        if doc['version'] != version:
            raise timeline.Conflict('Timeline changed. Reload before applying the next style step.')
        clips = copy.deepcopy(doc['clips'])
        st = {**copy.deepcopy(studio.DEFAULT), **copy.deepcopy(doc.get('studio', {}))}
    kind = op['kind']
    if kind in ('music', 'overlay'):
        _check_brand(app, doc, op['asset_id'])
        import quick_asset_assembly as assembly
        total = sum(c['end'] - c['start'] for c in clips)
        item = {'asset_id': op['asset_id'], 'start': 0, 'end': round(min(total, 300), 3)}
        if kind == 'music':
            item['volume'] = op['volume']
        else:
            item.update(x=op['x'], y=op['y'], width=op['width'])
        return assembly.apply_assembly(app, pid, version, [item])['version']
    if kind == 'cut':
        clips = cut_source(clips, *op['source'])
        if not clips:
            raise ValueError('That cut would remove the whole video.')
    elif kind == 'frame':
        st.update({k: op[k] for k in ('aspect', 'fit') if k in op})
    elif kind == 'look':
        st.update({k: op[k] for k in ('brightness', 'contrast', 'saturation') if k in op})
    elif kind == 'voice':
        st['volume'] = op['volume']
    elif kind == 'captions':
        ws = ws if ws is not None else words(app, pid)['words']
        st['captions'] = [c for c in st['captions'] if c.get('origin') != 'speech'] + caption_cues(clips, ws, op)
    else:
        raise ValueError('Unknown style op.')
    result = timeline.execute(app, pid, 'sync_editor_state', {'expected_version': version, 'clips': clips,
                              'studio': st, 'editor_state': None, 'provider': 'style:' + op['id']})
    return result['version']


def _check_brand(app, doc, asset_id):
    record = library.get(app, asset_id)
    scope = ((record.get('metadata') or {}).get('provenance') or {}).get('use_scope') or {}
    if scope.get('type') == 'brand' and scope.get('brand') != doc.get('brand'):
        raise ValueError('“%s” is a %s asset. Set this project’s brand to %s to use it.' % (record['name'], scope.get('brand'), scope.get('brand')))


# ---------------------------------------------------------------- reference measurement

def _stats(path, seconds=60):
    import subprocess
    run = subprocess.run(['ffmpeg', '-hide_banner', '-t', str(seconds), '-i', str(path), '-vf',
                          'fps=2,scale=320:-2,signalstats,metadata=print:file=-', '-an', '-f', 'null', '-'],
                         capture_output=True, text=True, timeout=180)
    vals = {}
    for key in ('YAVG', 'YLOW', 'YHIGH', 'SATAVG'):
        found = [float(x) for x in re.findall(r'lavfi\.signalstats\.%s=([0-9.]+)' % key, run.stdout)]
        vals[key] = sum(found) / len(found) if found else None
    cuts = subprocess.run(['ffmpeg', '-hide_banner', '-t', str(seconds), '-i', str(path), '-vf',
                           'scdet=threshold=12,metadata=print:file=-', '-an', '-f', 'null', '-'],
                          capture_output=True, text=True, timeout=180)
    vals['cuts'] = [float(x) for x in re.findall(r'lavfi\.scd\.time=([0-9.]+)', cuts.stdout)]
    return vals


def extract(app, pid, reference_pid, source_kind='brand_reference', brand=None, name=None):
    """Measure a reference video. Returns a draft for the user to review; nothing is saved."""
    from editor import probe, detect_silence
    _folder(app, pid)
    ref = _folder(app, reference_pid) / 'input.mp4'
    tgt = Path(app.WORK) / pid / 'input.mp4'
    info = probe(ref, False)
    evidence, measurements, draft = {}, {}, {}
    ratio = info['width'] / info['height']
    aspect = next((a for a, r in (('9:16', 9 / 16), ('16:9', 16 / 9), ('1:1', 1.0)) if abs(ratio - r) / r < .03), 'source')
    draft['frame'] = {'aspect': aspect, 'fit': 'cover'}
    evidence['frame.aspect'] = {'method': 'measured', 'reference': reference_pid, 'note': '%dx%d' % (info['width'], info['height'])}
    rws = words(app, reference_pid)['words']
    gaps = sorted(b['s'] - a['e'] for a, b in zip(rws, rws[1:])) if len(rws) > 1 else []
    if gaps:
        keep = gaps[int(len(gaps) * .95) - 1 if len(gaps) > 20 else -1]
        draft['pacing'] = {'remove_pauses': True, 'min_pause_s': round(min(1.0, max(.2, keep + .05)), 2), 'pad_s': .12}
        evidence['pacing.min_pause_s'] = {'method': 'measured', 'reference': reference_pid, 'note': 'longest kept gap between words %.2f s' % keep}
    elif info.get('audio'):
        quiet = [b - a for a, b in detect_silence(ref) if a > .3 and b < info['duration'] - .3]
        longest = max(quiet) if quiet else .2
        draft['pacing'] = {'remove_pauses': True, 'min_pause_s': round(min(1.0, max(.2, longest + .05)), 2), 'pad_s': .12}
        evidence['pacing.min_pause_s'] = {'method': 'measured', 'reference': reference_pid, 'note': 'longest pause inside the reference %.2f s (audio level)' % longest}
    r, t = _stats(ref), _stats(tgt)
    look = {}
    if r['YAVG'] is not None and t['YAVG'] is not None:
        look['brightness'] = round(max(-.3, min(.3, (r['YAVG'] - t['YAVG']) / 255)), 3)
    if None not in (r['YLOW'], r['YHIGH'], t['YLOW'], t['YHIGH']) and t['YHIGH'] - t['YLOW'] > 1:
        look['contrast'] = round(max(.7, min(1.5, (r['YHIGH'] - r['YLOW']) / (t['YHIGH'] - t['YLOW']))), 3)
    if r['SATAVG'] and t['SATAVG']:
        look['saturation'] = round(max(.5, min(1.6, r['SATAVG'] / t['SATAVG'])), 3)
    if look:
        draft['look'] = look
        for k in look:
            evidence['look.' + k] = {'method': 'measured', 'reference': reference_pid, 'note': 'matched to the reference average over its first minute'}
    shots = [b - a for a, b in zip([0.0] + r['cuts'], r['cuts'] + [min(60, info['duration'])])]
    measurements.update(reference_duration=info['duration'], shot_count=len(shots),
                        median_shot_s=round(sorted(shots)[len(shots) // 2], 2) if shots else None,
                        reference_words=len(rws), reference_luma=r['YAVG'], target_luma=t['YAVG'])
    provenance = {'source_kind': source_kind, 'reference_project_ids': [reference_pid], 'reference_sha256': [_sha_file(ref)],
                  'use_scope': {'type': 'brand', 'brand': brand} if brand else {'type': 'creator'}, 'rights_note': ''}
    style = validate({'format': FORMAT, 'name': name or ('%s style' % (brand or 'Reference')), 'provenance': provenance,
                      **draft, 'evidence': evidence})
    return {'style': style, 'measurements': measurements,
            'not_measured': ['captions (set them by hand)', 'music and logo assets (add them as slots)', 'b-roll'],
            'saved': False}


# ---------------------------------------------------------------- HTTP

def _body(handler, limit=600000):
    length = int(handler.headers.get('Content-Length', '0'))
    if not 0 < length <= limit:
        raise ValueError('Request body is empty or too large.')
    handler.connection.settimeout(30)
    body = json.loads(handler.rfile.read(length))
    if not isinstance(body, dict):
        raise ValueError('Expected a JSON object.')
    return body


SWARM = Path(__file__).resolve().parent / 'swarm'
STATIC = {'frame-bridge.js': 'text/javascript; charset=utf-8'}


def route(handler, app, method):
    parsed = urlparse(handler.path)
    path, query = parsed.path, parse_qs(parsed.query)
    if method == 'GET' and path in ('/swarm', '/swarm/'):
        handler.send(200, (SWARM / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        return True
    m = re.fullmatch(r'/swarm/(frame-bridge\.js)', path)
    if method == 'GET' and m:
        handler.send(200, (SWARM / m[1]).read_bytes(), STATIC[m[1]])
        return True
    m = re.fullmatch(r'/swarm/media/([a-z0-9_]+\.(mp4|jpg))', path)
    if method == 'GET' and m:
        handler.media(SWARM / 'media' / m[1], 'video/mp4' if m[2] == 'mp4' else 'image/jpeg')
        return True
    if not path.startswith('/api/style/'):
        return False
    try:
        project = (query.get('project') or [None])[0]
        if method == 'GET' and path == '/api/style/styles':
            return handler.json(200, {'styles': list_styles(app, project)}) or True
        m = re.fullmatch('/api/style/styles/(' + ID + ')', path)
        if method == 'GET' and m:
            return handler.json(200, get(app, m[1], project)) or True
        if method == 'POST' and path == '/api/style/styles':
            b = _body(handler)
            return handler.json(200, save(app, b.get('style'), b.get('project_id'), b.get('parent_style_id'), b.get('unlock') or ())) or True
        m = re.fullmatch('/api/style/projects/(' + ID + ')/(words|transcribe|plan|apply|extract|brand)', path)
        if not m:
            raise ValueError('Unknown style request.')
        pid, action = m[1], m[2]
        if method == 'GET' and action == 'words':
            return handler.json(200, words(app, pid)) or True
        if method != 'POST':
            raise ValueError('Use POST for this style action.')
        b = _body(handler)
        if action == 'words':
            result = store_words(app, pid, b.get('words'), 'editor import')
        elif action == 'transcribe':
            result = transcribe(app, pid)
        elif action == 'plan':
            result = plan(app, pid, _resolve_style(app, pid, b))
        elif action == 'apply':
            only = b.get('op_ids')
            result = apply(app, pid, _resolve_style(app, pid, b), b.get('expected_version'), set(only) if isinstance(only, list) else None)
        elif action == 'extract':
            result = extract(app, pid, _ident(b.get('reference_project_id'), 'Reference project'),
                             b.get('source_kind', 'brand_reference'), b.get('brand') or None, b.get('name'))
        else:
            brand = b.get('brand')
            brand = None if brand in (None, '') else _text(brand, 'Brand', 120)
            with timeline.LOCK:
                doc = timeline.load(app, pid)
                if b.get('expected_version') != doc['version']:
                    raise timeline.Conflict('Timeline changed. Reload and retry.')
                doc['brand'] = brand
                timeline.write(Path(app.WORK) / pid / 'timeline.json', doc)
                result = timeline.public(doc)
        handler.json(200, result)
    except timeline.Conflict as exc:
        handler.json(409, {'error': str(exc)})
    except (ValueError, KeyError, TypeError, FileNotFoundError, RuntimeError) as exc:
        handler.json(400, {'error': str(exc)})
    return True
