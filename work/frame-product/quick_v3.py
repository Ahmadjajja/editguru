"""Higgsfield v3 Discovery look as reusable FRAME templates.

Ported from Dante's accepted v3 compositor (codex-handoff/reference_code/higgsfield_reel/hf_render_v3.py,
hf_render_v2.py, hf_mix_v3.py): same colours, type, layouts, motion and sound design. Instead of hand-written
per-video drawing code, a deterministic plan places every template:

  measured speech (energy envelope) -> dialogue EDL -> output word times -> visual map anchors -> segments.

Same footage + same transcript + same visual map = same plan and the same render.
"""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

WD, HT, FPS = 1080, 1920, 30
HALF_Y = 520            # lower-half crop of the speaker (face centred for a chest-up selfie framing)
LIME = (226, 253, 86)
WHITE = (255, 255, 255)
INK = (10, 11, 9)
ENGINE_VERSION = 1
KITS = Path(__file__).resolve().parents[2] / 'recipes'


# ------------------------------------------------------------------ measured dialogue EDL (v3 rule 1)

def _pcm(path, sr=16000):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', str(sr), '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, sr


def measured_lines(path, words, pad_on=.05, pad_off=.08, join_gap=.30):
    """Speech islands from a 10 ms RMS envelope; ASR decides WHICH words, energy decides WHERE to cut.

    Islands closer than join_gap merge (keeps natural phrasing); islands with no ASR word are noise.
    Cut = onset - 50 ms, decay tail + 80 ms (the v3 EDL rule).
    """
    a, sr = _pcm(path)
    hop = sr // 100
    n = len(a) // hop
    env = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    floor = float(np.percentile(env, 10))
    peak = float(np.percentile(env, 95))
    thr = floor + max(8.0, (peak - floor) * .28)
    raw = env > thr
    # 60 ms hangover so consonant gaps don't split words (computed on the raw mask, not propagated)
    on = raw.copy()
    for k in range(1, 7):
        on[k:] |= raw[:-k]
    islands, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            islands.append([start / 100, i / 100]); start = None
    merged = []
    for s, e in islands:
        if merged and s - merged[-1][1] < join_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    dur = n / 100
    lines = []
    for s, e in merged:
        if e - s < .15 or not any(w['s'] < e and w['e'] > s for w in words):
            continue
        lines.append([round(max(0, s - pad_on), 3), round(min(dur, e + pad_off), 3)])
    out, t = [], 0.0
    for s, e in lines:
        out.append({'src_in': s, 'src_out': e, 'out': round(t, 3)})
        t += e - s
    # frame-align output starts so picture and audio cut on the same frame
    return out, {'threshold_db': round(thr, 1), 'floor_db': round(floor, 1), 'islands': len(merged)}


def to_output(lines, t):
    for ln in lines:
        if ln['src_in'] <= t <= ln['src_out']:
            return ln['out'] + t - ln['src_in']
    return None


# ------------------------------------------------------------------ plan

def _norm(w):
    return re.sub(r"[^\w.]", '', w.lower()).strip('.')


def build_plan(aroll, words, vmap):
    """words: [{'w','s','e'}] in source seconds. vmap: the kit's visual-map.json."""
    lines, measure = measured_lines(aroll, words)
    total_speech = lines[-1]['out'] + lines[-1]['src_out'] - lines[-1]['src_in']
    hold = float(vmap.get('end_hold_s', 1.15))
    total = round(total_speech + hold, 3)
    W = []
    for w in words:
        mid = (w['s'] + w['e']) / 2
        ln = next((l for l in lines if l['src_in'] <= mid <= l['src_out']), None) or \
            next((l for l in lines if l['src_in'] <= w['e'] and w['s'] <= l['src_out']), None)
        if ln is None:
            continue                                    # word fell in a cut (noise/breath): not shown
        s0 = to_output(lines, min(max(w['s'], ln['src_in']), ln['src_out']))
        e0 = to_output(lines, min(max(w['e'], ln['src_in']), ln['src_out']))
        W.append({'w': w['w'], 's': round(s0, 3), 'e': round(max(e0, s0 + .03), 3), 'line': lines.index(ln), 'src': w['s']})
    W.sort(key=lambda x: x['s'])

    def find(anchor, after):
        toks = [_norm(x) + ('*' if x.endswith('*') else '') for x in anchor.split()]
        for i in range(len(W) - len(toks) + 1):
            if W[i]['s'] + 1e-6 < after:
                continue
            if all((_norm(W[i + k]['w']).startswith(toks[k][:-1]) if toks[k].endswith('*') else _norm(W[i + k]['w']) == toks[k])
                   for k in range(len(toks))):
                return i
        raise ValueError('Anchor "%s" was not found in the transcript after %.2f s.' % (anchor, after))

    def find_at(at_s, after):                     # a style's first cut anchors by source time, not by words
        for i, w in enumerate(W):
            if w['src'] >= float(at_s) - .02 and w['s'] + 1e-6 >= after:
                return i
        raise ValueError('No spoken word after %.2f s for a section.' % float(at_s))

    def locate(item, key, akey, after):
        return find_at(item[akey], after) if item.get(akey) is not None else find(item[key], after)

    segs, cursor = [], 0.0
    for item in vmap['visuals']:
        i = locate(item, 'anchor', 'at_s', cursor)
        t0 = max(0.0, W[i]['s'] - float(item.get('lead_s', .06)))
        seg = {k: v for k, v in item.items() if k not in ('anchor', 'rows')}
        seg.update(t0=round(t0, 3), anchor=item['anchor'], anchor_word_index=i)
        if item.get('rows'):
            rows, c = [], i
            for r in item['rows']:
                j = locate(r, 'anchor', 'at_s', W[c]['s'])
                row = {'num': r['num'], 'title': r['title'], 't': round(W[j]['s'] - .05, 3)}
                if 'media_t' in r:
                    row['media_t'] = float(r['media_t'])
                rows.append(row); c = j
            seg['rows'] = rows
        if item.get('land_on') or item.get('land_at_s') is not None:
            j = locate(item, 'land_on', 'land_at_s', W[i]['s'])
            seg['land_t'] = round(W[j]['s'] - .04, 3)
        segs.append(seg)
        cursor = W[i]['s']
    if not segs or segs[0]['t0'] > 0:
        segs.insert(0, {'kind': 'face', 't0': 0.0, 'anchor': None})
    for a, b in zip(segs, segs[1:]):
        a['t1'] = b['t0']
    segs[-1]['t1'] = total
    for s in segs:
        if 'max_s' in s and s['t1'] - s['t0'] > s['max_s']:
            pass  # a split runs to the next anchor; length is the speaker's, not a choice
    # captions: max words, never across a scene cut, skipped where a graphic carries the words
    hot = {h.lower() for h in vmap.get('hot_words', [])}
    cuts = sorted({s['t0'] for s in segs} | {total_speech})
    skip = [(s['t0'], s['t1']) for s in segs if s['kind'] in ('card', 'screen')]
    cta = next((s for s in segs if s['kind'] == 'cta'), None)
    if cta and cta.get('land_t'):
        skip.append((cta['land_t'] - .1, total))
    chunks, cur = [], []
    maxw = int(vmap.get('caption_max_words', 3))

    def flush():
        if cur:
            chunks.append(list(cur)); cur.clear()
    for k, w in enumerate(W):
        if cur and (len(cur) >= maxw or w['line'] != cur[-1]['line'] or any(cur[0]['s'] < c <= w['s'] for c in cuts)
                    or re.search(r'[.!?,]$', cur[-1]['w'])):
            flush()
        cur.append(w)
    flush()
    caps = []
    for ci, ch in enumerate(chunks):
        st = max(0.0, ch[0]['s'] - .06)
        nx = chunks[ci + 1][0]['s'] - .06 if ci + 1 < len(chunks) else 1e9
        en = min(nx, ch[-1]['e'] + .3)
        en = min([en] + [c for c in cuts if c > st + .05])
        if any(a - .01 <= st < b for a, b in skip):
            continue
        toks = [{'text': re.sub(r"[,!?]+$", '', x['w']).upper().rstrip('.') if not re.match(r'^\d', x['w']) else x['w'].rstrip('.,'),
                 'hot': _norm(x['w']) in hot} for x in ch]
        caps.append({'t0': round(st, 3), 't1': round(en, 3), 'tokens': toks})
    plan = {'format': 'frame-v3-plan/1', 'engine_version': ENGINE_VERSION, 'canvas': [WD, HT], 'fps': FPS,
            'total': total, 'speech_end': round(total_speech, 3), 'lines': lines, 'measure': measure,
            'words': W, 'segments': segs, 'captions': caps, 'caption_y': int(vmap.get('caption_y', 1220)),
            'graphic_defaults': vmap.get('graphics') or {}}
    plan['digest'] = hashlib.sha256(json.dumps([plan, vmap], sort_keys=True).encode()).hexdigest()
    return plan


# ------------------------------------------------------------------ drawing (v2/v3 helpers)

_fonts = {}


def font(size, weight='Heavy'):
    from PIL import ImageFont
    k = (size, weight)
    if k in _fonts:
        return _fonts[k]
    f = None
    sf = Path('/System/Library/Fonts/SFNS.ttf')
    if sf.exists():
        try:
            f = ImageFont.truetype(str(sf), size); f.set_variation_by_name(weight)
        except Exception:
            f = None
    if f is None:
        files = {'Black': 'Inter-Black.otf', 'Heavy': 'Inter-ExtraBold.otf', 'Bold': 'Inter-Bold.otf', 'Semibold': 'Inter-SemiBold.otf'}
        for root in ('/usr/share/fonts/opentype/inter', str(Path(__file__).parent / 'fonts')):
            p = Path(root) / files.get(weight, 'Inter-Bold.otf')
            if p.exists():
                f = ImageFont.truetype(str(p), size); break
    _fonts[k] = f or ImageFont.load_default()
    return _fonts[k]


def font_name():
    return 'SF Pro (system)' if Path('/System/Library/Fonts/SFNS.ttf').exists() else 'Inter (fallback: SF Pro not on this machine)'


def ease(x):
    x = min(1, max(0, x)); return 1 - (1 - x) ** 3


def ramp(u, a, d):
    return ease((u - a) / d) if d > 0 else float(u >= a)


def over(dst, src, x, y, op=1.0):
    h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(WD, x + w), min(HT, y + h)
    if x1 <= x0 or y1 <= y0 or op <= 0:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    a = s[..., 3:4] / 255 * op
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a


def place(dst, rgba, cx, cy, k=1.0, op=1.0):
    import cv2
    h, w = rgba.shape[:2]
    if abs(k - 1) > 1e-3:
        rgba = cv2.resize(rgba, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    h, w = rgba.shape[:2]
    over(dst, rgba, int(round(cx - w / 2)), int(round(cy - h / 2)), op)


def zoom(fr, k, cx, cy):
    import cv2
    if k <= 1.0005:
        return fr.astype(np.float32)
    h, w = fr.shape[:2]
    cw, ch = w / k, h / k
    x0 = min(max(0, cx - cw / 2), w - cw); y0 = min(max(0, cy - ch / 2), h - ch)
    crop = fr[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)


def pill(text, size=28, style='dark'):
    from PIL import Image, ImageDraw
    f = font(size, 'Bold'); tw = int(f.getlength(text)); h = int(size * 1.85); w = tw + int(size * 1.4)
    im = Image.new('RGBA', (w + 40, h + 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if style == 'lime':
        d.rounded_rectangle([20, 20, 20 + w, 20 + h], h // 2, fill=LIME + (255,)); fg = INK
    else:
        d.rounded_rectangle([20, 20, 20 + w, 20 + h], h // 2, fill=(10, 11, 12, 215), outline=(255, 255, 255, 55), width=2); fg = (232, 234, 228)
    d.text((20 + int(size * .7), 20 + h // 2), text, font=f, fill=fg, anchor='lm')
    return np.asarray(im).copy()


def label_card(text):
    """Category name for a showcase clip: v3 step-card shape (dark, lime edge), one line."""
    from PIL import Image, ImageDraw, ImageFilter
    ft = font(58, 'Black'); tw = int(ft.getlength(text)); w, h = tw + 96, 118
    im = Image.new('RGBA', (w + 80, h + 80), (0, 0, 0, 0)); sh = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 52, 40 + w, 52 + h], 26, fill=(0, 0, 0, 170)); im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(im); d.rounded_rectangle([40, 40, 40 + w, 40 + h], 26, fill=(12, 13, 11, 228), outline=(255, 255, 255, 46), width=2)
    d.rounded_rectangle([40, 40, 52, 40 + h], 6, fill=LIME + (255,))
    d.text((40 + 56, 40 + h / 2 + 2), text, font=ft, fill=WHITE + (255,), anchor='lm')
    return np.asarray(im).copy()


def caption_img(tokens, k=1.0):
    from PIL import Image, ImageDraw, ImageFilter
    FC, FH = font(max(12, int(66 * k)), 'Heavy'), font(max(12, int(74 * k)), 'Black')
    toks = [(t['text'], t['hot']) for t in tokens if t['text']]

    def fw(t):
        return FH if t[1] else FC
    lines, cur, wsum = [], [], 0
    for t in toks:
        l = fw(t).getlength(t[0] + ' ')
        if cur and wsum + l > 900:
            lines.append(cur); cur, wsum = [], 0
        cur.append(t); wsum += l
    lines.append(cur)
    LH = int(92 * k)
    H = 60 + LH * len(lines)
    txt = Image.new('RGBA', (WD, H), (0, 0, 0, 0)); d = ImageDraw.Draw(txt)
    for li, line in enumerate(lines):
        y = H / 2 + (li - (len(lines) - 1) / 2) * LH
        x = 540 - sum(fw(t).getlength(t[0] + ' ') for t in line) / 2 + fw(line[-1]).getlength(' ') / 2
        for t in line:
            d.text((x, y), t[0], font=fw(t), fill=(LIME if t[1] else WHITE) + (255,), anchor='lm', stroke_width=2, stroke_fill=(0, 0, 0, 255))
            x += fw(t).getlength(t[0] + ' ')
    sh = np.asarray(txt.filter(ImageFilter.GaussianBlur(14))).astype(np.float32); sh[..., :3] = 0; sh[..., 3] = np.minimum(255, sh[..., 3] * 1.6)
    base = np.zeros((H, WD, 4), np.float32)
    for lay in (sh, np.asarray(txt).astype(np.float32)):
        a = lay[..., 3:4] / 255; base[..., :3] = base[..., :3] * (1 - a) + lay[..., :3] * a; base[..., 3:4] = np.maximum(base[..., 3:4], lay[..., 3:4])
    return np.clip(base, 0, 255).astype(np.uint8)


def card_bg():
    yy, xx = np.mgrid[0:HT, 0:WD].astype(np.float32)
    bg = np.zeros((HT, WD, 3), np.float32) + np.array([9, 10, 8], np.float32)
    g = np.exp(-(((xx - 180) ** 2 + (yy - 420) ** 2) / (1100 ** 2)) * 2.0)[..., None] * .16
    return bg * (1 - g) + np.array(LIME, np.float32) * g


def card_head(text):
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (WD, 120), (0, 0, 0, 0)); d = ImageDraw.Draw(im); fk = font(50, 'Black'); x = 84
    for ch in text:
        d.text((x, 60), ch, font=fk, fill=WHITE + (255,), anchor='lm'); x += fk.getlength(ch) + 6
    return np.asarray(im).copy(), x


def card_row(num, title, size=64):
    from PIL import Image, ImageDraw
    fn, ft = font(110, 'Black'), font(size, 'Heavy')
    while ft.getlength(title) > 1000 - 84 - fn.getlength(num) - 40 and size > 40:
        size -= 2; ft = font(size, 'Heavy')
    r = Image.new('RGBA', (WD, 200), (0, 0, 0, 0)); dr = ImageDraw.Draw(r)
    dr.line([(84, 4), (996, 4)], fill=(255, 255, 255, 46), width=2); dr.text((84, 104), num, font=fn, fill=LIME + (255,), anchor='lm')
    dr.text((84 + fn.getlength(num) + 40, 108), title, font=ft, fill=WHITE + (255,), anchor='lm')
    return np.asarray(r).copy()


def offer_panel(lines_white, lines_lime, note):
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (WD, 900), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    y = 200
    for t in lines_white:
        f = font(76, 'Black')
        while f.getlength(t) > 940:
            f = font(f.size - 2, 'Black')
        d.text((540, y), t, font=f, fill=WHITE + (255,), anchor='mm'); y += 96
    y += 24
    for t in lines_lime:
        f = font(96, 'Black')
        while f.getlength(t) > 960:
            f = font(f.size - 2, 'Black')
        d.text((540, y), t, font=f, fill=LIME + (255,), anchor='mm'); y += 112
    if note:
        p = pill(note, 30)
        ph, pw = p.shape[:2]
        im.alpha_composite(Image.fromarray(p), (int(540 - pw / 2), int(y + 10)))
    return np.asarray(im).copy()


def cta_panel(keyword, sub, sub2):
    from PIL import Image, ImageDraw
    f1, f2, f3 = font(104, 'Black'), font(37, 'Bold'), font(31, 'Semibold'); w, h = 900, 300
    im = Image.new('RGBA', (w + 60, h + 60), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([30, 30, 30 + w, 30 + h], 44, fill=(9, 10, 9, 232), outline=LIME + (235,), width=4)
    t1, t2 = 'COMMENT ', keyword.upper(); x = 30 + (w - f1.getlength(t1 + t2)) / 2
    d.text((x, 120), t1, font=f1, fill=WHITE + (255,), anchor='lm'); d.text((x + f1.getlength(t1), 120), t2, font=f1, fill=LIME + (255,), anchor='lm')
    d.text((30 + w / 2, 222), sub, font=f2, fill=(240, 242, 236, 255), anchor='mm')
    if sub2:
        d.text((30 + w / 2, 276), sub2, font=f3, fill=(190, 205, 150, 255), anchor='mm')
    return np.asarray(im).copy()


def blur_bg(fr, dim=.45):
    import cv2
    s = cv2.resize(fr.astype(np.uint8), (WD // 8, HT // 8), interpolation=cv2.INTER_AREA)
    s = cv2.GaussianBlur(s, (0, 0), 6)
    return cv2.resize(s, (WD, HT), interpolation=cv2.INTER_LINEAR).astype(np.float32) * (1 - dim)


# ------------------------------------------------------------------ video readers

class Reader:
    """Sequential RGB frames from ffmpeg at the output frame rate."""

    def __init__(self, args, w, h):
        self.w, self.h = w, h
        self.p = subprocess.Popen(['ffmpeg', '-v', 'quiet'] + args + ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
        self.last = np.zeros((h, w, 3), np.uint8)

    def read(self):
        b = self.p.stdout.read(self.w * self.h * 3)
        if len(b) == self.w * self.h * 3:
            self.last = np.frombuffer(b, np.uint8).reshape(self.h, self.w, 3)
        return self.last

    def close(self):
        try:
            self.p.stdout.close(); self.p.kill()
        except Exception:
            pass


def aroll_reader(path, lines, total_frames):
    picks = '+'.join('between(t,%.4f,%.4f)' % (l['src_in'], l['src_out'] - 1 / 60) for l in lines)
    vf = ("fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,select='%s',setpts=N/(30*TB),"
          "tpad=stop_mode=clone:stop_duration=5" % picks)
    return Reader(['-i', str(path), '-vf', vf, '-frames:v', str(total_frames)], WD, HT)


def clip_reader(path, start, frames, h=960):
    vf = 'fps=30,scale=1080:%d:force_original_aspect_ratio=increase,crop=1080:%d' % (h, h)
    return Reader(['-stream_loop', '-1', '-ss', '%.3f' % start, '-i', str(path), '-vf', vf, '-frames:v', str(frames), '-an'], WD, h)


# ------------------------------------------------------------------ render

def screen_time(seg, t):
    """Recording time shown at output time t: piecewise-linear through the step anchors (each step lands on its word)."""
    pts = [(seg['t0'], float(seg.get('media_in', 0)))] + [(r['t'], r['media_t']) for r in seg.get('rows', [])
                                                           if 'media_t' in r and seg['t0'] < r['t'] < seg.get('t1', 1e9)]
    if seg.get('media_out') is not None:
        pts.append((seg['t1'], float(seg['media_out'])))
    if t <= pts[0][0]:
        return pts[0][1]
    for (a, x), (b, y) in zip(pts, pts[1:]):
        if t <= b:
            return x + (y - x) * (t - a) / max(1e-6, b - a)
    return pts[-1][1]


def step_label(seg, t):
    """The step chip on a screen recording: the head until the first step, then the latest step reached."""
    cur = None
    for r in seg.get('rows', []):
        if r['t'] <= t:
            cur = r
    return (cur['num'] + '  ' + cur['title'], cur['t']) if cur else (seg.get('head') or '', seg['t0'])


GRAPHIC_TYPES = ('label', 'chip', 'step', 'offer', 'cta', 'cardhead', 'cardrow', 'text')
GRAPHIC_HOME = {'label': (540, 820), 'chip': (44, 60), 'step': (540, 1010), 'offer': (540, 470), 'cta': (540, 1380),
                'cardhead': (540, 520), 'cardrow': (0, 640), 'text': (540, 960)}


def graphic_img(g, cache):
    """RGBA for one overlay. Same drawing as the baked templates, so a detached overlay looks identical."""
    ty = g['type']
    key = (ty, json.dumps({k: g.get(k) for k in ('text', 'white', 'lime', 'note', 'keyword', 'sub', 'sub2', 'num', 'title')}, sort_keys=True))
    if key not in cache:
        if ty in ('label', 'step', 'text'):
            cache[key] = label_card(g.get('text', ''))
        elif ty == 'chip':
            cache[key] = pill(g.get('text', ''), 24)
        elif ty == 'offer':
            cache[key] = offer_panel(g.get('white', []), g.get('lime', []), g.get('note'))
        elif ty == 'cta':
            cache[key] = cta_panel(g.get('keyword', ''), g.get('sub', ''), g.get('sub2', ''))
        elif ty == 'cardhead':
            cache[key] = card_head(g.get('text', ''))[0]
        elif ty == 'cardrow':
            cache[key] = card_row(g.get('num', ''), g.get('title', ''))
    return cache[key]


def draw_graphic(fr, g, t, cache):
    import cv2
    img = graphic_img(g, cache)
    h, w = img.shape[:2]
    u = t - g['t0']; k = float(g.get('k', 1.0)); ty = g['type']
    hx, hy = GRAPHIC_HOME[ty]
    x, y = g.get('x', hx), g.get('y', hy)
    if ty == 'label':
        e = ease((u - .08) / .22)
        if e > 0:
            place(fr, img, x - 60 * (1 - e), y, (.96 + .04 * e) * k, e)
    elif ty in ('step', 'text'):
        e = ease(u / .2)
        place(fr, img, x - 50 * (1 - e), y, (.96 + .04 * e) * k, max(.001, e))
    elif ty == 'chip':                      # anchor = the pill's top-left corner
        place(fr, img, x - 20 + w * k / 2, y - 20 + h * k / 2, k, ramp(u, .15, .2))
    elif ty == 'offer':
        e = ease(u / .22)
        place(fr, img, x, y + 40 * (1 - e), (1.04 - .04 * e) * k, e)
    elif ty == 'cta':
        e = ease(u / .2); pulse = 1 + .06 * math.exp(-((u - .1) / .12) ** 2)
        place(fr, img, x, y + 50 * (1 - e), (.95 + .05 * e) * pulse * k, e)
    elif ty == 'cardhead':
        place(fr, img, x, y, ((1.06 - .06 * ease(u / .10)) if u < .10 else 1.0 + .02 * u) * k, 1.0)
        bar = ease(u / .18); bx, by = int(x - 540 + 84), int(y + 52)
        cv2.rectangle(fr, (bx, by), (bx + int(380 * bar * k), by + 8), LIME, -1)
    elif ty == 'cardrow':                   # anchor = the row's top-left
        pr = ease(u / .14)
        if pr > 0:
            place(fr, img, x + 70 * (1 - pr) + w * k / 2, y + h * k / 2, k, pr)


def render(plan, aroll, media_root, out_path, log=print):
    import cv2
    total = plan['total']; NF = int(round(total * FPS)); speech_end = plan['speech_end']
    segs = plan['segments']
    ar = aroll_reader(aroll, plan['lines'], NF)
    yy = np.arange(HT, dtype=np.float32)[:, None, None]
    seam = (np.exp(-((yy - 960) / 120.0) ** 2) * .55)
    grad_low = np.clip((yy - 1050) / 380, 0, 1) * .78
    CB = card_bg()
    cache = {}
    cap_imgs = [caption_img(c['tokens'], float(c.get('k', 1.0))) for c in plan['captions']]
    readers = {}
    for i, s in enumerate(segs):
        if s['kind'] in ('split',):
            readers[i] = None
    GRAPHICS = plan.get('graphics') or []
    GFX = bool(plan.get('graphics_mode'))
    cta = next((s for s in segs if s['kind'] == 'cta'), None)
    CTA = cta_panel(cta['keyword'], cta.get('sub', ''), cta.get('sub2', '')) if cta else None
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (WD, HT), '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-colorspace', 'bt709',
                          '-color_primaries', 'bt709', '-color_trc', 'bt709', str(out_path)], stdin=subprocess.PIPE)
    last_frame = None
    try:
        for f in range(NF):
            t = f / FPS
            arf = ar.read()
            si = max(i for i, s in enumerate(segs) if s['t0'] <= t + 1e-6)
            s = segs[si]; u = t - s['t0'] + s.get('u0', 0); d = max(.1, s.get('d_full', s['t1'] - s['t0']))
            if t >= speech_end:                                   # end hold: blurred face + CTA
                if last_frame is None:
                    last_frame = arf.copy()
                fr = blur_bg(last_frame, .45) * .55 + CB * .45
                if CTA is not None and not GFX:
                    place(fr, CTA, 540, 960, 1.0, 1.0)
            elif s['kind'] == 'face':
                fr = zoom(arf, 1.0 + .06 * u / d, 540, 620)
                fr = fr * (1 - grad_low * .35)
            elif s['kind'] in ('split', 'offer'):
                fr = np.zeros((HT, WD, 3), np.float32)
                if s['kind'] == 'split':
                    if readers.get(si) is None:
                        for k in [k for k in readers if k != si and readers[k] is not None]:
                            readers[k].close(); readers[k] = None
                        readers[si] = clip_reader(Path(media_root) / s['media'], float(s.get('media_in', 0)), int(round(d * FPS)) + 2)
                    top = readers[si].read()
                    fr[:960] = zoom(top, 1.0 + .05 * u / d, 540, 480)
                    if u < .12:
                        fr[:960] = fr[:960] * (.6 + .4 * u / .12) + 255 * .4 * (1 - u / .12)
                    if s.get('label') and not s.get('bare'):
                        key = ('lab', s['label'])
                        if key not in cache:
                            cache[key] = label_card(s['label'])
                        e = ease((u - .08) / .22)
                        if e > 0:
                            place(fr, cache[key], 540 - 60 * (1 - e), 820, .96 + .04 * e, e)
                    if s.get('chip') and not s.get('bare'):
                        key = ('chip', s['chip'])
                        if key not in cache:
                            cache[key] = pill(s['chip'], 24)
                        over(fr, cache[key], 24, 40, ramp(u, .15, .2))
                else:
                    key = ('offer', json.dumps(s.get('white')), json.dumps(s.get('lime')), s.get('note'))
                    if key not in cache:
                        cache[key] = offer_panel(s.get('white', []), s.get('lime', []), s.get('note'))
                    top = CB[:960].copy() * (1.0 + .0 * u)
                    fr[:960] = top
                    e = ease(u / .22)
                    if not s.get('bare'):
                        place(fr, cache[key], 540, 470 + 40 * (1 - e), 1.04 - .04 * e, e)
                    if u < .08:
                        fr[:960] = fr[:960] * (1 - .5 * (1 - u / .08)) + 255 * .5 * (1 - u / .08)
                half = zoom(arf, 1.0 + .03 * u / d, 540, 1000)[HALF_Y:HALF_Y + 960]
                fr[960:] = half
                fr = fr * (1 - seam)
            elif s['kind'] == 'screen':
                if readers.get(si) is None:
                    for k in [k for k in readers if k != si and readers[k] is not None]:
                        readers[k].close(); readers[k] = None
                    readers[si] = Reader(['-i', str(Path(media_root) / s['media']), '-vf', 'fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920', '-an'], WD, HT)
                    readers[si].pos = -1
                want = int(round(screen_time(s, t) * 30))
                while readers[si].pos < want:
                    readers[si].read(); readers[si].pos += 1
                fr = zoom(readers[si].last, 1.0 + .03 * u / d, 540, 960)
                if u < .06:
                    fr = fr * (1 - .5 * (1 - u / .06)) + 255 * .5 * (1 - u / .06)
                text, since = step_label(s, t) if not s.get('bare') else ('', 0)
                if text:
                    key = ('lab', text)
                    if key not in cache:
                        cache[key] = label_card(text)
                    e = ease((t - since) / .2)
                    place(fr, cache[key], 540 - 50 * (1 - e), int(s.get('label_y', 1010)), .96 + .04 * e, max(.001, e))
            elif s['kind'] == 'card':
                fr = CB.copy(); k = 1.0 + .02 * u
                key = ('head', s.get('head'))
                if key not in cache:
                    cache[key] = card_head(s.get('head', ''))
                head, hx = cache[key]
                if not s.get('bare'):
                    place(fr, head, 540, 520, (1.06 - .06 * ease(u / .10)) if u < .10 else k, 1.0)
                    bar = ease(u / .18)
                    cv2.rectangle(fr, (84, 572), (84 + int(380 * bar), 580), LIME, -1)
                rows = s.get('rows', []) if not s.get('bare') else []
                for ri, r in enumerate(rows):
                    key = ('row', r['num'], r['title'])
                    if key not in cache:
                        cache[key] = card_row(r['num'], r['title'])
                    pr = ease((t - r['t']) / .14)
                    if pr > 0:
                        over(fr, cache[key], int(70 * (1 - pr)), 640 + 200 * ri, pr)
                if u < .05:
                    fr = fr * (1 - .5 * (1 - u / .05)) + 255 * .5 * (1 - u / .05)
            elif s['kind'] == 'cta':
                fr = zoom(arf, 1.06 + .06 * u / d, 540, 620)
                fr = fr * (1 - np.clip((yy - 1150) / 300, 0, 1) * .6)
                lt = s.get('land_t', s['t0'])
                if t > lt and CTA is not None and not s.get('bare'):
                    e = ease((t - lt) / .2); pulse = 1 + .06 * math.exp(-((t - lt - .1) / .12) ** 2)
                    place(fr, CTA, 540, 1380 + 50 * (1 - e), (.95 + .05 * e) * pulse, e)
            else:
                fr = arf.astype(np.float32)
            for g in GRAPHICS:                                    # overlays the creator can move, resize, retime, rewrite
                if g['t0'] <= t < g['t1']:
                    draw_graphic(fr, g, t, cache)
            # captions (slide-up, never across a cut, skipped where a graphic carries the words)
            if t < speech_end or plan.get('timeline_edit'):
                y0 = 960 if s['kind'] in ('split', 'offer') else (1060 if s['kind'] == 'cta' else plan.get('caption_y', 1220))
                for ci, c in enumerate(plan['captions']):
                    if c['t0'] <= t < c['t1']:
                        img = cap_imgs[ci]; pr = ease((t - c['t0']) / .12); y = c.get('y', y0)
                        over(fr, img, int(c.get('x', 0)), int(y - img.shape[0] / 2 + 22 * (1 - pr)), pr)
                        if not plan.get('timeline_edit'):
                            break
            p.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
            if f % 150 == 0:
                log('frame %d/%d' % (f, NF))
    finally:
        p.stdin.close(); p.wait(); ar.close()
        for r in readers.values():
            if r is not None:
                r.close()
    return NF


# ------------------------------------------------------------------ sound (hf_mix_v3, event times from the plan)

def mix(plan, aroll, wav_out):
    from scipy.signal import butter, sosfilt
    SR = 48000; total = plan['total']; N = int(round(total * SR)); rng = np.random.default_rng(11); tt_all = np.arange(N) / SR

    def hc(n): return .5 - .5 * np.cos(np.linspace(0, np.pi, n))

    def lp(x, f, o=2): return sosfilt(butter(o, f, 'lowpass', fs=SR, output='sos'), x)

    def hp(x, f, o=2): return sosfilt(butter(o, f, 'highpass', fs=SR, output='sos'), x)

    def bp(x, a, b): return sosfilt(butter(2, [a, b], 'bandpass', fs=SR, output='sos'), x)

    def hz(m): return 440 * 2 ** ((m - 69) / 12)
    src, _ = _pcm(aroll, SR)
    lines = plan['lines']

    def srms(x):
        f = x[:len(x) // 480 * 480].reshape(-1, 480); r = np.sqrt((f ** 2).mean(1)); r = r[r > np.percentile(r, 60)]; return np.sqrt((r ** 2).mean() + 1e-12)
    LV = [srms(src[int(l['src_in'] * SR):int(l['src_out'] * SR)]) for l in lines]; REF = float(np.median(LV))
    vo = np.zeros(N); fd = 384
    for l, lv in zip(lines, LV):
        seg = src[int(l['src_in'] * SR):int(l['src_out'] * SR)].copy() * min(2.0, max(.5, REF / lv))
        seg[:fd] *= hc(fd); seg[-fd:] *= hc(fd)[::-1]
        s0 = int(round(l['out'] * SR)); n = min(len(seg), N - s0); vo[s0:s0 + n] += seg[:n]
    vo = hp(vo, 80)
    segs = plan['segments']; speech_end = plan['speech_end']
    first_split = next((s['t0'] for s in segs if s['kind'] == 'split'), 1.0)
    card = next((s for s in segs if s['kind'] in ('card', 'screen')), None)
    card_t = card['t0'] if card else first_split
    offer = next((s for s in segs if s['kind'] == 'offer'), None)
    off_t = offer['t0'] if offer else None
    cta = next((s for s in segs if s['kind'] == 'cta'), None)
    BEAT, BAR, END = .5, 2.0, speech_end + .05
    DROP = (off_t - .62, off_t) if off_t else (-1, -1)
    ROOTS = [33, 29, 36, 31]; CH = [[57, 60, 64], [57, 60, 65], [55, 60, 64], [55, 59, 62]]

    def on(x): return (x < DROP[0] or x >= DROP[1]) and x < END
    kick, bass, hats, snare, arp, pad = (np.zeros(N) for _ in range(6))

    def put(buf, sig, at):
        a = int(round(at * SR))
        if a >= N or a < 0:
            return
        n = min(len(sig), N - a); buf[a:a + n] += sig[:n]
    kn = int(.22 * SR); kt = np.arange(kn) / SR; KICK = np.sin(2 * np.pi * np.cumsum(48 + 110 * np.exp(-kt * 38)) / SR) * np.exp(-kt * 16)
    for b in np.arange(0, END, BEAT):
        if on(b):
            put(kick, KICK * (.85 if b < first_split else 1.0), b)
    for b in np.arange(0, END, BEAT / 2):
        if not on(b):
            continue
        bi = int(b // BAR) % 4; f = hz(ROOTS[bi]) * (2 if (int(b / (BEAT / 2)) % 4) == 3 else 1); n = int(.24 * SR); tt = np.arange(n) / SR
        put(bass, sum(np.sin(2 * np.pi * f * h * tt) / h for h in (1, 2, 3, 4)) * np.exp(-tt * 7), b)
    bass = lp(bass, 420)
    pump = np.ones(N)
    for b in np.arange(0, END, BEAT):
        a = int(b * SR); n = min(int(.2 * SR), N - a)
        if n > 0:
            pump[a:a + n] = np.minimum(pump[a:a + n], .35 + .65 * (np.arange(n) / n) ** .7)
    for b in np.arange(first_split, END, BEAT / 4):
        if on(b):
            n = int(.04 * SR); tt = np.arange(n) / SR; acc = 1.0 if int(round(b / (BEAT / 4))) % 2 else .55
            put(hats, hp(rng.standard_normal(n), 7500) * np.exp(-tt * 110) * acc, b)
    for b in np.arange(card_t, END, BEAT):
        if on(b) and int(round((b - card_t) / BEAT)) % 2 == 1:
            n = int(.16 * SR); tt = np.arange(n) / SR
            put(snare, bp(rng.standard_normal(n), 900, 6000) * np.exp(-tt * 26) + np.sin(2 * np.pi * 190 * tt) * np.exp(-tt * 30) * .6, b)
    arp_end = cta['t0'] if cta else END
    for j, b in enumerate(np.arange(card_t, END, BEAT / 4)):
        if not on(b) or b >= arp_end:
            continue
        bi = int(b // BAR) % 4; m = CH[bi][j % 3] + 12 * ((j // 3) % 2); n = int(.14 * SR); tt = np.arange(n) / SR
        x = (np.sign(np.sin(2 * np.pi * hz(m) * tt)) * .5 + np.sin(2 * np.pi * hz(m) * tt)) * np.exp(-tt * 22)
        lvl = .45 + .55 * min(1, max(0, (b - card_t) / max(.1, (DROP[0] if off_t else END) - card_t)))
        put(arp, x * (lvl if (not off_t or b < off_t) else .8), b)
    arp = lp(arp, 3200)
    for i in range(int(END // BAR) + 1):
        a = i * BAR
        if a >= END:
            break
        n = int(min(BAR, END - a) * SR); tt = np.arange(n) / SR; env = np.minimum(1, tt / .08) * np.minimum(1, (n / SR - tt) / .08)
        put(pad, sum(np.sin(2 * np.pi * hz(m) * tt) for m in CH[i % 4]) * env, a)
    gate = np.array([0.0 if not on(x) else 1.0 for x in tt_all[::480]]).repeat(480)[:N]
    pad = lp(pad, 1500) * np.pad(gate, (0, max(0, N - len(gate))))[:N]
    music = kick * .30 + bass * pump * .22 + hats * .035 + snare * .10 + arp * pump * .028 + pad * pump * .010
    music *= np.interp(tt_all, [0, first_split, first_split + .1, card_t, off_t or END, END], [.82, .82, .92, .95, 1.0, .9])
    sfx = np.zeros(N)

    def noise(n): return rng.standard_normal(n)

    def hit(lvl=1.0):
        n = int(.5 * SR); tt = np.arange(n) / SR
        return (np.sin(2 * np.pi * np.cumsum(40 + 90 * np.exp(-tt * 30)) / SR) * np.exp(-tt * 7) * .45 + lp(noise(n), 2500) * np.exp(-tt * 40) * .12) * lvl

    def accent():
        n = int(.3 * SR); tt = np.arange(n) / SR
        return bp(noise(n), 1800, 8000) * np.exp(-tt * 45) * .35 + np.sin(2 * np.pi * np.cumsum(55 + 120 * np.exp(-tt * 45)) / SR) * np.exp(-tt * 12) * .4 + np.sin(2 * np.pi * 2600 * tt) * np.exp(-tt * 90) * .12

    def click(lvl=1.0):
        n = int(.03 * SR); tt = np.arange(n) / SR
        return (hp(noise(n), 2500) * np.exp(-tt * 400) * .3 + np.sin(2 * np.pi * 1700 * tt) * np.exp(-tt * 260) * .2) * lvl

    def riser(d):
        n = int(d * SR); tt = np.arange(n) / SR; u = tt / d
        return hp(noise(n), 1500) * .10 * u ** 2 + np.sin(2 * np.pi * np.cumsum(180 + 900 * u ** 2) / SR) * .05 * u ** 1.5

    def impact():
        n = int(.9 * SR); tt = np.arange(n) / SR
        y = np.sin(2 * np.pi * np.cumsum(32 + 70 * np.exp(-tt * 18)) / SR) * np.exp(-tt * 5) * .55 + lp(noise(n), 3000) * np.exp(-tt * 25) * .15
        for m in (57, 61, 64, 69, 73):
            y += (np.sin(2 * np.pi * hz(m) * tt) + .3 * np.sin(4 * np.pi * hz(m) * tt)) * np.exp(-tt * 4.5) * .045
        return y

    def stab():
        n = int(.6 * SR); tt = np.arange(n) / SR; y = np.sin(2 * np.pi * 45 * tt) * np.exp(-tt * 8) * .3
        for m in (57, 64, 69, 72):
            y += np.sin(2 * np.pi * hz(m) * tt) * np.exp(-tt * 6) * .04
        return y
    events = []
    put(sfx, hit(.8), 0.0); events.append(('hit', 0.0))
    for s in segs:
        if s['kind'] == 'split':
            put(sfx, hit(.45), s['t0']); events.append(('hit', s['t0']))
        if s['kind'] in ('card', 'screen'):
            put(sfx, accent() * .75, s['t0']); events.append(('accent', s['t0']))
            for r in s.get('rows', []):
                put(sfx, click(.8), r['t']); events.append(('click', r['t']))
    if off_t:
        put(sfx, riser(DROP[1] - DROP[0] + .25), DROP[0] - .25); put(sfx, impact() * .75, off_t); events += [('riser', DROP[0] - .25), ('impact', off_t)]
    if cta and cta.get('land_t'):
        put(sfx, click(.8), cta['land_t']); events.append(('click', cta['land_t']))
    put(sfx, stab(), END); events.append(('stab', END))
    env = np.sqrt(np.convolve(vo ** 2, np.ones(480) / 480, 'same')); act = np.clip((20 * np.log10(env + 1e-9) + 50) / 14, 0, 1)
    sm = np.zeros(N); a_at, a_rel = 1 - np.exp(-1 / (.015 * SR)), 1 - np.exp(-1 / (.18 * SR)); v = 0.0
    for i in range(0, N, 48):
        x = act[i]; v += (a_at if x > v else a_rel) * 48 * (x - v); v = min(1, max(0, v)); sm[i:i + 48] = v
    duck = 10 ** (-12 * sm / 20)
    music *= .30
    out = vo + music * duck + sfx * .6
    spk = sm > .5
    rest = music * duck + sfx * .75
    margin = float(10 * np.log10((vo[spk] ** 2).mean() / (((music * duck)[spk] ** 2).mean() + 1e-12))) if spk.any() else None   # voice over the music bed (v3 C4)
    pk = float(np.abs(out).max())
    if pk > .98:
        out *= .98 / pk
    pcm = (np.clip(out, -1, 1) * 32767).astype('<i2')
    import wave
    with wave.open(str(wav_out), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return {'voice_over_bed_db': round(margin, 1) if margin is not None else None, 'events': [(k, round(t, 3)) for k, t in events]}


def _lufs(path):
    err = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', err)
    return float(m[-1]) if m else None


def master(video, wav, out):
    """Mux and master to -14 LUFS with a -1.5 dBTP ceiling (v3 delivery spec): measured gain, then a true-peak limiter."""
    gain = -14.0 - (_lufs(wav) or -14.0)
    for _ in range(2):
        af = 'volume=%.2fdB,alimiter=limit=0.84:level=false:attack=3:release=60,aresample=48000' % gain
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-i', str(wav), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                        '-af', af, '-ac', '2', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart', str(out)], check=True)
        got = _lufs(out)
        if got is None or abs(got + 14) <= .5:
            break
        gain += -14.0 - got                      # the limiter shaved some level; correct once


def qc(path, plan):
    info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,duration,nb_frames:format=duration', '-of', 'json', str(path)],
                                     capture_output=True, text=True, check=True).stdout)
    v = next(s for s in info['streams'] if s['codec_type'] == 'video'); a = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    lufs = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', lufs)
    gaps = [round(b['out'] - (a_['out'] + a_['src_out'] - a_['src_in']), 3) for a_, b in zip(plan['lines'], plan['lines'][1:])]
    crossings = [c for c in plan['captions'] if any(c['t0'] < s['t0'] < c['t1'] - 1e-6 for s in plan['segments'])]
    return {'duration_video': float(v.get('duration', 0)), 'duration_audio': float(a.get('duration', 0)), 'frames': int(v.get('nb_frames', 0)),
            'integrated_lufs': float(m[-1]) if m else None, 'captions_crossing_cuts': len(crossings), 'max_gap_between_lines_s': max(gaps) if gaps else 0}


# ------------------------------------------------------------------ FRAME integration

JOBS = {}
LOCK = threading.Lock()


def kit_dir(name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name or ''):
        raise ValueError('Unknown kit.')
    d = (KITS / name).resolve()
    if d.parent != KITS.resolve() or not (d / 'visual-map.json').is_file():
        raise ValueError('That kit has no visual-map.json.')
    return d


def list_kits(project=None):
    out = []
    for p in sorted(KITS.glob('*/visual-map.json')) if KITS.is_dir() else []:
        if p.parent.name.startswith('auto-') and (not project or p.parent.name != 'auto-' + project[:12]):
            continue
        vm = json.loads(p.read_text())
        media = sorted(str(m.relative_to(p.parent)) for m in (p.parent / 'media-kit').glob('*.mp4')) if (p.parent / 'media-kit').is_dir() else []
        out.append({'kit': p.parent.name, 'title': vm.get('title', p.parent.name), 'visuals': vm['visuals'], 'media': media})
    return out


def apply_overrides(vmap, overrides):
    """Explicit user changes to the visual map: label, clip, clip start, chip. Anchors and kinds stay as documented."""
    vm = copy.deepcopy(vmap)
    for k, ch in (overrides or {}).items():
        if k == 'captions':
            y = (ch or {}).get('y')
            if isinstance(y, bool) or not isinstance(y, (int, float)) or not 700 <= y <= 1800:
                raise ValueError('Caption height must be 700–1800 px (of 1920).')
            vm['caption_y'] = int(y)
            continue
        i = int(k)
        if not 0 <= i < len(vm['visuals']) or not isinstance(ch, dict):
            raise ValueError('Unknown visual %s.' % k)
        v = vm['visuals'][i]
        for field in ('label', 'chip', 'keyword', 'sub', 'sub2', 'note', 'head'):
            if field in ch:
                if not isinstance(ch[field], str) or len(ch[field]) > 80:
                    raise ValueError('%s must be text up to 80 characters.' % field)
                v[field] = ch[field]
        if 'media' in ch:
            if v.get('kind') not in ('split', 'screen') or not re.fullmatch(r'media-kit/[\w .()-]+\.mp4', ch['media'] or ''):
                raise ValueError('Pick a media-kit clip for a split visual.')
            v['media'] = ch['media']
        if 'media_in' in ch:
            if isinstance(ch['media_in'], bool) or not isinstance(ch['media_in'], (int, float)) or not 0 <= ch['media_in'] <= 120:
                raise ValueError('Clip start must be 0–120 s.')
            v['media_in'] = float(ch['media_in'])
    return vm


def project_words(app, pid):
    import quick_style
    return quick_style.words(app, pid)['words']


def plan_for(app, pid, kit, overrides=None):
    d = kit_dir(kit)
    vmap = apply_overrides(json.loads((d / 'visual-map.json').read_text()), overrides)
    aroll = Path(app.WORK) / pid / 'input.mp4'
    words = project_words(app, pid)
    if not words:
        raise ValueError('This project has no transcript yet. Transcribe first.')
    for v in vmap['visuals']:
        if v.get('media') and not (d / v['media']).is_file():
            raise ValueError('Missing media-kit clip: %s' % v['media'])
    plan = build_plan(aroll, words, vmap)
    plan['kit'] = kit
    plan['font'] = font_name()
    return plan


SEG_KINDS = ('split', 'screen', 'card', 'offer', 'cta')
TEXT_FIELDS = ('label', 'chip', 'keyword', 'sub', 'sub2', 'note', 'head')


def _num(x, lo, hi, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not lo <= x <= hi:
        raise ValueError('%s must be a number from %s to %s.' % (what, lo, hi))
    return float(x)


def apply_timeline(app, pid, plan, tl, kit_root):
    """The editor's timeline is the edit: A-roll pieces, every section's place and length, every caption.

    The kit plan supplies the look; whatever the creator moved, trimmed, swapped, rewrote or deleted wins.
    """
    plan = copy.deepcopy(plan)
    if not isinstance(tl, dict):
        raise ValueError('Timeline must be an object.')
    lines = tl.get('lines') or []
    if not isinstance(lines, list) or not 1 <= len(lines) <= 400:
        raise ValueError('The A-roll track is empty.')
    out, pos = [], 0.0
    for l in sorted(lines, key=lambda x: x.get('out', 0)):
        a = _num(l.get('src_in'), 0, 7200, 'A-roll in point'); b = _num(l.get('src_out'), 0, 7200, 'A-roll out point')
        o = _num(l.get('out'), 0, 7200, 'A-roll position')
        if b - a < .04:
            continue
        if o > pos + .05:
            raise ValueError('There is a %.2f s gap on the A-roll track at %.2f s. Close it (drag the next clip left) and render again.' % (o - pos, pos))
        out.append({'src_in': round(a, 3), 'src_out': round(b, 3), 'out': round(pos, 3)}); pos += b - a
    plan['lines'] = out
    speech_end = round(pos, 3)
    total = round(speech_end + float(plan.get('total', speech_end) - plan.get('speech_end', speech_end)), 3)
    segs = []
    for sg in tl.get('segments') or []:
        if not isinstance(sg, dict) or sg.get('kind') not in SEG_KINDS:
            raise ValueError('Unknown section type.')
        t0 = _num(sg.get('t0'), 0, 7200, 'Section start'); t1 = _num(sg.get('t1'), 0, 7200, 'Section end')
        if t1 - t0 < .05 or t0 >= total:
            continue
        seg = {'kind': sg['kind'], 't0': round(t0, 3), 't1': round(min(t1, total), 3), 'anchor': sg.get('anchor')}
        for k in TEXT_FIELDS:
            if isinstance(sg.get(k), str) and not (k == 'note' and sg['kind'] != 'offer'):
                seg[k] = sg[k][:120]
        for k in ('white', 'lime'):
            if k in sg:
                if not isinstance(sg[k], list) or len(sg[k]) > 6 or not all(isinstance(x, str) and len(x) <= 60 for x in sg[k]):
                    raise ValueError('Offer lines must be up to 6 short lines.')
                seg[k] = list(sg[k])
        if sg['kind'] in ('split', 'screen'):
            m = sg.get('media') or ''
            if m.startswith('asset:'):
                doc = json.loads((Path(app.WORK) / pid / 'timeline.json').read_text())
                a = next((x for x in doc.get('assets', []) if x.get('id') == m[6:]), None)
                if not a:
                    raise ValueError('An imported clip is missing from the project.')
                f = (Path(app.WORK) / pid / a['path']).resolve()
                if Path(app.WORK).resolve() not in f.parents or not f.is_file():
                    raise ValueError('An imported clip is missing from the project.')
                seg['media'] = str(f)
            elif re.fullmatch(r'media-kit/[\w .()-]+\.mp4', m) and (Path(kit_root) / m).is_file():
                seg['media'] = m
            else:
                raise ValueError('Pick a clip for the section at %.1f s.' % t0)
            seg['media_in'] = _num(sg.get('media_in', 0), 0, 3600, 'Clip start')
            if sg.get('media_out') is not None:
                seg['media_out'] = _num(sg['media_out'], 0, 3600, 'Clip end')
        if sg.get('rows'):
            seg['rows'] = [{'num': str(r.get('num', ''))[:4], 'title': str(r.get('title', ''))[:60], 't': round(_num(r.get('t'), 0, 7200, 'Step time'), 3),
                            **({'media_t': _num(r['media_t'], 0, 3600, 'Step clip time')} if r.get('media_t') is not None else {})}
                           for r in sg['rows'][:12]]
        if sg.get('land_t') is not None:
            seg['land_t'] = round(_num(sg['land_t'], 0, 7200, 'CTA time'), 3)
        if sg.get('bare'):
            seg['bare'] = True
        if sg.get('label_y') is not None:
            seg['label_y'] = _num(sg['label_y'], 100, 1850, 'Label height')
        segs.append(seg)
    # Where sections overlap, the one that starts later is on screen (as in the editor's preview); the earlier one
    # resumes when it ends. Each visible piece keeps its place in the original section (u0, media time).
    for i, x in enumerate(segs):
        x['_i'] = i
    bounds = sorted({0.0, total} | {x['t0'] for x in segs} | {min(x['t1'], total) for x in segs})
    full = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 1e-4:
            continue
        cov = [x for x in segs if x['t0'] <= a + 1e-6 and x['t1'] >= b - 1e-6]
        top = max(cov, key=lambda x: (x['t0'], x['_i'])) if cov else None
        key = top['_i'] if top else -1
        if full and full[-1]['_key'] == key and abs(full[-1]['t1'] - a) < 1e-6:
            full[-1]['t1'] = round(b, 3); continue
        if top is None:
            full.append({'kind': 'face', 't0': round(a, 3), 't1': round(b, 3), 'anchor': None, '_key': -1}); continue
        pc = {k: v for k, v in top.items() if k != '_i'}
        pc.update(t0=round(a, 3), t1=round(b, 3), _key=key)
        if a > top['t0'] + 1e-6:
            pc['u0'] = round(a - top['t0'], 3); pc['d_full'] = round(top['t1'] - top['t0'], 3)
            if top['kind'] == 'split':
                pc['media_in'] = round(top.get('media_in', 0) + pc['u0'], 3)
            elif top['kind'] == 'screen':
                pc['media_in'] = round(screen_time(top, a), 3); pc.pop('media_out', None); pc['media_out'] = round(screen_time(top, b), 3)
        full.append(pc)
    for x in full:
        x.pop('_key', None)
    caps = []
    for c in (tl.get('captions') or [])[:800]:
        toks = c.get('tokens') if isinstance(c, dict) else None
        if not isinstance(toks, list) or not 1 <= len(toks) <= 16:
            continue
        toks = [{'text': str(t.get('text', ''))[:40], 'hot': bool(t.get('hot'))} for t in toks if isinstance(t, dict)]
        cap = {'t0': round(_num(c.get('t0'), 0, 7200, 'Caption start'), 3), 't1': round(_num(c.get('t1'), 0, 7200, 'Caption end'), 3), 'tokens': toks}
        for k, lo, hi in (('y', 200, 1880), ('x', -500, 500), ('k', .3, 3)):
            if c.get(k) is not None:
                cap[k] = _num(c[k], lo, hi, 'Caption ' + k)
        if cap['t1'] > cap['t0']:
            caps.append(cap)
    gfx = []
    for g in (tl.get('graphics') or [])[:400]:
        if not isinstance(g, dict) or g.get('type') not in GRAPHIC_TYPES:
            continue
        o = {'type': g['type'], 't0': round(_num(g.get('t0'), 0, 7200, 'Overlay start'), 3), 't1': round(_num(g.get('t1'), 0, 7200, 'Overlay end'), 3)}
        for k2 in ('text', 'note', 'keyword', 'sub', 'sub2', 'num', 'title'):
            if g.get(k2) is not None:
                o[k2] = str(g[k2])[:120]
        for k2 in ('white', 'lime'):
            if isinstance(g.get(k2), list):
                o[k2] = [str(x)[:60] for x in g[k2][:6]]
        for k2, lo, hi in (('x', -600, 1700), ('y', -400, 2300), ('k', .2, 4)):
            if g.get(k2) is not None:
                o[k2] = _num(g[k2], lo, hi, 'Overlay ' + k2)
        if o['t1'] > o['t0']:
            gfx.append(o)
    plan.update(segments=full, captions=sorted(caps, key=lambda c: c['t0']), speech_end=speech_end, total=total, timeline_edit=True,
                graphics=sorted(gfx, key=lambda g: g['t0']), graphics_mode=bool(tl.get('graphics_mode')))
    if tl.get('caption_y') is not None:
        plan['caption_y'] = int(_num(tl['caption_y'], 600, 1850, 'Caption height'))
    plan.pop('digest', None)
    plan['digest'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def ensure_deps(log=print):
    """The v3 renderer needs OpenCV and SciPy in FRAME's own Python; install them on first use."""
    try:
        import cv2, scipy  # noqa: F401
        return
    except ImportError:
        pass
    log('installing OpenCV + SciPy (first run only, about a minute)')
    run = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'opencv-python-headless', 'scipy'],
                         capture_output=True, text=True, timeout=1200)
    if run.returncode:
        raise RuntimeError('Could not install OpenCV/SciPy for the v3 renderer: ' + (run.stderr or run.stdout)[-600:])
    import importlib
    importlib.invalidate_caches()


def start_render(app, pid, kit, overrides=None, tl=None):
    import quick_timeline as timeline
    plan = plan_for(app, pid, kit, overrides)
    if tl:
        plan = apply_timeline(app, pid, plan, tl, kit_dir(kit))
    plan['overrides'] = overrides or {}
    key = plan['digest'][:16]
    with LOCK:
        j = JOBS.get((pid, key))
        if j and j['status'] in ('working', 'done'):
            return dict(j)
        JOBS[(pid, key)] = j = {'status': 'working', 'key': key, 'progress': 'starting', 'started_at': time.time()}

    def work():
        eid = uuid.uuid4().hex
        folder = Path(app.WORK) / pid / 'versions' / eid
        try:
            folder.mkdir(parents=True)
            (folder / 'v3-plan.json').write_text(json.dumps(plan, indent=1))
            aroll = Path(app.WORK) / pid / 'input.mp4'

            def log(m):
                with LOCK:
                    JOBS[(pid, key)]['progress'] = m
            ensure_deps(log)
            with app.WORKERS:
                render(plan, aroll, kit_dir(kit), folder / 'video.mp4', log)
                log('mixing sound')
                sound = mix(plan, aroll, folder / 'mix.wav')
                log('mastering to -14 LUFS')
                master(folder / 'video.mp4', folder / 'mix.wav', folder / 'edited.mp4')
            report = qc(folder / 'edited.mp4', plan)
            report.update(sound)
            (folder / 'qc.json').write_text(json.dumps(report, indent=1))
            for tmp in ('video.mp4', 'mix.wav'):
                (folder / tmp).unlink(missing_ok=True)
            with timeline.LOCK:
                doc = timeline.load(app, pid)
                doc.setdefault('exports', []).append({'id': eid, 'status': 'done', 'kind': 'v3', 'timeline_version': doc['version'],
                                                      'plan_digest': plan['digest'], 'duration': report['duration_video'], 'created': time.time(),
                                                      'url': '/media/%s/versions/%s/edited.mp4' % (pid, eid), 'qc': report})
                timeline.write(Path(app.WORK) / pid / 'timeline.json', doc)
            res = {'status': 'done', 'export_id': eid, 'url': '/media/%s/versions/%s/edited.mp4' % (pid, eid), 'qc': report}
        except Exception as exc:
            res = {'status': 'failed', 'error': str(exc)[-900:]}
        with LOCK:
            JOBS[(pid, key)].update(res, finished_at=time.time())
    threading.Thread(target=work, daemon=True).start()
    return dict(j)


LIVE_TYPES = ('say', 'build', 'patch', 'seek', 'render')


def push_live(project_dir, event):
    """Queue an edit for the open FRAME editor. The editor polls this file and performs it with agent cursors.

    Anything that can write to the project folder (the editor's server, a chat agent, a script) can drive the live build.
    """
    if not isinstance(event, dict) or event.get('type') not in LIVE_TYPES:
        raise ValueError('Live event type must be one of: ' + ', '.join(LIVE_TYPES))
    raw = json.dumps(dict(event, at=round(time.time(), 3)))
    if len(raw) > 20000:
        raise ValueError('Live event too large.')
    with LOCK:
        with open(Path(project_dir) / 'live.jsonl', 'a') as fh:
            fh.write(raw + '\n')


def read_live(project_dir, after):
    f = Path(project_dir) / 'live.jsonl'
    if not f.is_file():
        return {'events': [], 'next': 0}
    lines = f.read_text().splitlines()
    out = []
    for i in range(max(0, after), len(lines)):
        try:
            out.append(dict(json.loads(lines[i]), seq=i))
        except ValueError:
            continue
    return {'events': out[:50], 'next': min(len(lines), max(0, after) + 50) if out else len(lines)}


# ------------------------------------------------------------------ saved v3 styles: the format, reusable on new footage

STYLES = KITS / '_styles'
CUES = {
    'screen': ["here's how", 'here is how', 'how it works', 'how to', 'step one', 'first', 'open'],
    'offer': ['free', 'unlimited', 'discount', 'promo', 'deal', 'trial', 'off'],
    'cta': ['comment', 'follow', 'dm', 'link in bio', 'subscribe'],
}
STOP = {'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'it', 'is', 'you', 'your', 'i', 'we', 'that', 'this', 'with',
        'for', 'just', 'so', 'then', 'now', 'can', 'be', 'are', 'was', 'all', 'at', 'as', 'what', 'my', 'me'}


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')[:48]
    if not s:
        raise ValueError('Give the style a name.')
    return s


def list_styles():
    out = []
    for f in sorted(STYLES.glob('*.json')) if STYLES.is_dir() else []:
        try:
            st = json.loads(f.read_text())
            out.append({'slug': f.stem, 'name': st.get('name', f.stem), 'source': st.get('source', {}), 'created': st.get('created'),
                        'sections': [x['kind'] for x in st.get('sections', [])]})
        except ValueError:
            continue
    return out


def get_style(slug):
    f = STYLES / (_slug(slug) + '.json')
    if not f.is_file():
        raise ValueError('Unknown style.')
    return json.loads(f.read_text())


def save_style(app, pid, name, replace=False):
    """Freeze the edit a creator approved into a reusable format: section order and texts, caption rules,
    where they moved each kind of overlay, timing. Footage, clips and words are NOT part of a style."""
    doc = json.loads((Path(app.WORK) / pid / 'timeline.json').read_text())
    es = doc.get('editor_state') or {}
    p = es.get('p') or {}
    v3 = p.get('v3') or {}
    if not v3.get('kit'):
        raise ValueError('Build a v3 edit in this project first, then save it as a style.')
    vmap = json.loads((kit_dir(v3['kit']) / 'visual-map.json').read_text())
    vmap = apply_overrides(vmap, v3.get('overrides') or {})
    clips = p.get('clips') or []
    # where the creator put each kind of overlay (median of the ones they moved or resized)
    graphics = {}
    for ty in GRAPHIC_TYPES:
        moved = [c for c in clips if c.get('tr') == 'g1' and (c.get('g') or {}).get('type') == ty and (c.get('x') is not None or c.get('y') is not None or c.get('k'))]
        if moved:
            hx, hy = GRAPHIC_HOME[ty]
            med = lambda xs: sorted(xs)[len(xs) // 2]
            graphics[ty] = {'x': med([c.get('x', hx) for c in moved]), 'y': med([c.get('y', hy) for c in moved]), 'k': med([c.get('k') or 1 for c in moved])}
    # the texts as the creator last left them, per section kind
    gtext = {}
    for c in clips:
        g = c.get('g') or {}
        if c.get('tr') == 'g1' and g.get('type') in ('offer', 'cta') and g.get('type') not in gtext:
            gtext[g['type']] = {k: g[k] for k in ('white', 'lime', 'note', 'keyword', 'sub', 'sub2') if k in g}
    sections = []
    for v in vmap['visuals']:
        sec = {'kind': v['kind']}
        for k in ('chip', 'head', 'white', 'lime', 'note', 'keyword', 'sub', 'sub2', 'lead_s'):
            if k in v and not (k == 'note' and v['kind'] != 'offer'):
                sec[k] = v[k]
        sec.update(gtext.get(v['kind'], {}))
        if v['kind'] == 'split':
            sec['label'] = 'from the clip'     # a new video's clips name their own splits
        if v['kind'] == 'cta' and v.get('land_on'):
            sec['keyword_from_speech'] = True  # "comment X" -> keyword X
        sections.append(sec)
    caps_y = ((v3.get('overrides') or {}).get('captions') or {}).get('y') or vmap.get('caption_y', 1220)
    st = {'format': 'frame-v3-style/1', 'name': name.strip()[:80], 'template': vmap.get('template', 'higgsfield-v3'),
          'created': time.strftime('%Y-%m-%d %H:%M'), 'source': {'project': pid, 'kit': v3['kit']},
          'captions': {'max_words': vmap.get('caption_max_words', 3), 'y': int(caps_y), 'hot_words': vmap.get('hot_words', [])},
          'end_hold_s': vmap.get('end_hold_s', 1.15), 'graphics': graphics, 'sections': sections, 'cues': CUES}
    STYLES.mkdir(parents=True, exist_ok=True)
    slug = _slug(name)
    if (STYLES / (slug + '.json')).exists() and not replace:
        raise ValueError('A style named “%s” already exists. Pick another name (saved styles are never overwritten from the editor).' % name.strip())
    (STYLES / (slug + '.json')).write_text(json.dumps(st, indent=1, ensure_ascii=False))
    return dict(st, slug=slug)


def _phrase_at(words, cues, lo, hi, last=False):
    """Index of the first (or last) word in [lo, hi) seconds that starts one of the cue phrases."""
    hits = []
    toks = [_norm(w['w']) for w in words]
    for cue in cues:
        cw = [_norm(x) for x in cue.split()]
        for i in range(len(words) - len(cw) + 1):
            if lo <= words[i]['s'] < hi and toks[i:i + len(cw)] == cw:
                hits.append(i)
    if not hits:
        return None
    return max(hits) if last else min(hits)


def _clauses(words, i0, i1):
    """Clause starts between two word indexes: after punctuation or before 'then'/'and'."""
    out = []
    for i in range(i0, i1):
        prev = words[i - 1]['w'] if i > 0 else '.'
        if re.search(r'[.,!?;:]$', prev) or _norm(words[i]['w']) in ('then', 'and', 'next', 'finally'):
            out.append(i)
    return out


def _title(words, i, n=4):
    out = []
    for w in words[i:i + 8]:                      # the clause's first few words, stopping at its punctuation
        t = re.sub(r'[^\w&+.\'-]', '', w['w']).rstrip('.')
        if t and not (not out and _norm(t) in ('then', 'and', 'next', 'finally', 'just')):
            out.append(t)
        if len(out) >= n or re.search(r'[.,!?;:]$', w['w']):
            break
    return ' '.join(out).upper() or 'STEP'


def first_cut(app, pid, slug, assets):
    """A visual map for NEW footage from a saved style + the creator's clips.

    Deterministic: the style decides the sections, their order and look; the transcript decides where each
    lands (cue phrases for the setup / offer / CTA, the clip's own cue word or an even spread for splits).
    The creator then trims what does not sync."""
    st = get_style(slug)
    words = project_words(app, pid)
    if not words:
        raise ValueError('Transcribe the video first.')
    words = sorted(words, key=lambda w: w['s'])
    end = words[-1]['e']
    doc = json.loads((Path(app.WORK) / pid / 'timeline.json').read_text())
    by_id = {a['id']: a for a in doc.get('assets', [])}
    if not isinstance(assets, list) or not assets:
        raise ValueError('Import at least one B-roll clip first.')
    kit = 'auto-' + pid[:12]
    kd = KITS / kit
    (kd / 'media-kit').mkdir(parents=True, exist_ok=True)
    clips = []
    for a in assets[:24]:
        src = by_id.get(str(a.get('asset_id')))
        if not src:
            raise ValueError('A clip is missing from the project; import it again.')
        f = (Path(app.WORK) / pid / src['path']).resolve()
        src_name = src.get('name') or Path(src['path']).name
        name = re.sub(r'[^\w.()-]+', '-', Path(src_name).stem)[:60] + '.mp4'
        dst = kd / 'media-kit' / name
        if not dst.exists():
            try:
                os.link(f, dst)
            except OSError:
                shutil.copyfile(f, dst)
        dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(dst)],
                                   capture_output=True, text=True).stdout.strip() or 0)
        role = a.get('role') if a.get('role') in ('split', 'screen') else 'split'
        label = (a.get('label') or Path(src_name).stem.replace('_', ' ').replace('-', ' ')).strip().upper()[:40]
        clips.append({'media': 'media-kit/' + name, 'role': role, 'label': label, 'cue': (a.get('cue') or '').strip(), 'dur': dur})
    cues = st.get('cues') or CUES
    kinds = [x['kind'] for x in st['sections']]
    tpl = {k: next((x for x in st['sections'] if x['kind'] == k), {}) for k in ('split', 'screen', 'offer', 'cta')}
    visuals = []
    cta_i = _phrase_at(words, cues['cta'], end * .5, end + 1, last=True) if 'cta' in kinds else None
    lim = words[cta_i]['s'] if cta_i is not None else end + 1
    offer_i = _phrase_at(words, cues['offer'], end * .4, lim) if 'offer' in kinds else None
    lim2 = words[offer_i]['s'] if offer_i is not None else lim
    screen = next((c for c in clips if c['role'] == 'screen'), None)
    screen_i = _phrase_at(words, cues['screen'], 1.0, lim2) if screen else None
    # splits: a clip's own cue word wins; the rest spread over the open stretch before the first fixed section
    splits = [c for c in clips if c['role'] == 'split']
    taken = {x for x in (cta_i, offer_i, screen_i) if x is not None}
    first_fixed = min([words[x]['s'] for x in taken] + [end])
    free = []
    for c in splits:
        if c['cue']:
            j = _phrase_at(words, [c['cue']], .5, end + 1)
            if j is not None and j not in taken:
                c['i'] = j; taken.add(j); continue
        free.append(c)
    if free:
        cand = [i for i, w in enumerate(words) if 1.2 <= w['s'] < first_fixed - .8 and i not in taken and _norm(w['w']) not in STOP]
        if not cand:
            cand = [i for i, w in enumerate(words) if w['s'] >= 1.2 and i not in taken and _norm(w['w']) not in STOP]
        step = max(1, len(cand) // (len(free) + 1))
        for n, c in enumerate(free):
            if cand:
                c['i'] = cand[min(len(cand) - 1, (n + 1) * step - 1)]; taken.add(c['i'])
    sp = tpl['split']
    for c in splits:
        if 'i' in c:
            visuals.append({'at_s': words[c['i']]['s'], 'anchor': words[c['i']]['w'], 'kind': 'split', 'media': c['media'],
                            'media_in': 0, 'label': c['label'], 'chip': sp.get('chip', '')})
    if screen is not None and screen_i is not None:
        nxt = min([words[x]['s'] for x in taken if words[x]['s'] > words[screen_i]['s']] + [end])
        j1 = next((k for k, w in enumerate(words) if w['s'] >= nxt), len(words))
        starts = [k for k in _clauses(words, screen_i + 1, j1)][:5]
        rows = [{'at_s': words[k]['s'], 'anchor': words[k]['w'], 'num': '%02d' % (n + 1), 'title': _title(words, k)} for n, k in enumerate(starts)]
        visuals.append({'at_s': words[screen_i]['s'], 'anchor': words[screen_i]['w'], 'kind': 'screen', 'media': screen['media'], 'media_in': 0,
                        'media_out': round(max(.5, screen['dur'] - .05), 2), 'head': tpl['screen'].get('head', "HERE'S HOW IT WORKS"), 'rows': rows})
    if offer_i is not None:
        o = tpl['offer']
        visuals.append({'at_s': words[offer_i]['s'], 'anchor': words[offer_i]['w'], 'kind': 'offer', 'white': o.get('white', []),
                        'lime': o.get('lime', []), 'note': o.get('note', '')})
    if cta_i is not None:
        c = tpl['cta']
        kw = c.get('keyword', 'LINK')
        land = cta_i
        if _norm(words[cta_i]['w']) == 'comment' and cta_i + 1 < len(words):
            land = cta_i + 1
            if c.get('keyword_from_speech'):
                kw = re.sub(r'[^\w]', '', words[land]['w']).upper() or kw
        visuals.append({'at_s': words[max(0, cta_i - 2)]['s'], 'anchor': words[max(0, cta_i - 2)]['w'], 'kind': 'cta', 'land_at_s': words[land]['s'],
                        'keyword': kw, 'sub': c.get('sub', ''), 'sub2': c.get('sub2', '')})
    if not visuals:
        raise ValueError('Nothing to place: add clips, or say the style\'s cue words (e.g. "here\'s how", "free", "comment").')
    visuals.sort(key=lambda v: v['at_s'])
    hot = set(h.lower() for h in st['captions'].get('hot_words', []))
    for i, w in enumerate(words):                 # names and numbers in THIS video are lime too
        raw = re.sub(r'[^\w.]', '', w['w'])
        if raw and (re.match(r'^\d', raw) or (raw[0].isupper() and i > 0 and not re.search(r'[.!?]$', words[i - 1]['w']))):
            hot.add(_norm(raw))
    vm = {'format': 'frame-visual-map/1', 'title': st['name'] + ' — first cut', 'template': st.get('template', 'higgsfield-v3'),
          'style': slug, 'caption_max_words': st['captions'].get('max_words', 3), 'caption_y': st['captions'].get('y', 1220),
          'end_hold_s': st.get('end_hold_s', 1.15), 'hot_words': sorted(hot), 'graphics': st.get('graphics', {}), 'visuals': visuals}
    (kd / 'visual-map.json').write_text(json.dumps(vm, indent=1, ensure_ascii=False))
    return {'kit': kit, 'visuals': len(visuals), 'placed': [{'kind': v['kind'], 'at_s': v['at_s'], 'word': v['anchor'], 'label': v.get('label') or v.get('head') or v.get('keyword') or ''} for v in visuals]}


def route(handler, app, method):
    parsed = urlparse(handler.path)
    path = parsed.path
    if not path.startswith('/api/v3/'):
        return False
    try:
        if method == 'GET' and path == '/api/v3/kits':
            handler.json(200, {'kits': list_kits((parse_qs(parsed.query).get('project') or [None])[0])}); return True
        if path == '/api/v3/styles':
            if method == 'GET':
                handler.json(200, {'styles': list_styles()}); return True
            length = int(handler.headers.get('Content-Length', '0'))
            b = json.loads(handler.rfile.read(length)) if 0 < length <= 20000 else {}
            if not re.fullmatch(r'[a-f0-9]{32}', str(b.get('project', ''))):
                raise ValueError('Unknown project.')
            handler.json(200, save_style(app, b['project'], str(b.get('name') or ''), replace=b.get('replace') is True)); return True
        m = re.fullmatch(r'/api/v3/projects/([a-f0-9]{32})/first-cut', path)
        if m and method == 'POST':
            length = int(handler.headers.get('Content-Length', '0'))
            b = json.loads(handler.rfile.read(length)) if 0 < length <= 50000 else {}
            handler.json(200, first_cut(app, m[1], str(b.get('style') or ''), b.get('assets'))); return True
        m = re.fullmatch(r'/api/v3/kits/([a-z0-9-]+)/poster', path)
        if method == 'GET' and m:
            q = parse_qs(parsed.query); d = kit_dir(m[1]); rel = (q.get('media') or [''])[0]
            if not re.fullmatch(r'media-kit/[\w .()-]+\.mp4', rel) or not (d / rel).is_file():
                raise ValueError('Unknown clip.')
            t = max(0.0, min(120.0, float((q.get('t') or ['0'])[0])))
            cache = d / 'media-kit' / '.posters' / ('%s_%.2f.jpg' % (Path(rel).stem, t))
            if not cache.exists():
                cache.parent.mkdir(exist_ok=True)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '%.2f' % (t + .3), '-i', str(d / rel), '-frames:v', '1', '-vf', 'scale=720:-2', str(cache)], check=True)
            handler.media(cache, 'image/jpeg'); return True
        m = re.fullmatch(r'/api/v3/kits/([a-z0-9-]+)/media', path)
        if method == 'GET' and m:
            d = kit_dir(m[1]); rel = (parse_qs(parsed.query).get('media') or [''])[0]
            if not re.fullmatch(r'media-kit/[\w .()-]+\.mp4', rel) or not (d / rel).is_file():
                raise ValueError('Unknown clip.')
            handler.media(d / rel, 'video/mp4'); return True
        m = re.fullmatch(r'/api/v3/projects/([a-f0-9]{32})/live', path)
        if m:
            pdir = Path(app.WORK) / m[1]
            if not pdir.is_dir():
                raise ValueError('Unknown project.')
            if method == 'GET':
                handler.json(200, read_live(pdir, int((parse_qs(parsed.query).get('after') or ['0'])[0]))); return True
            length = int(handler.headers.get('Content-Length', '0'))
            push_live(pdir, json.loads(handler.rfile.read(length)) if 0 < length <= 20000 else {})
            handler.json(200, {'ok': True}); return True
        m = re.fullmatch(r'/api/v3/projects/([a-f0-9]{32})/(plan|render)(?:/([a-f0-9]{16}))?', path)
        if not m:
            raise ValueError('Unknown v3 request.')
        pid, action, key = m.groups()
        kit = (parse_qs(parsed.query).get('kit') or [''])[0]
        body = {}
        if method == 'POST':
            length = int(handler.headers.get('Content-Length', '0'))
            if length > 2000000:
                raise ValueError('Request too large.')
            body = json.loads(handler.rfile.read(length)) if length > 0 else {}
            kit = body.get('kit', kit)
        if action == 'plan' and method in ('GET', 'POST'):
            handler.json(200, plan_for(app, pid, kit, body.get('overrides')))
        elif action == 'render' and method == 'POST' and not key:
            handler.json(200, start_render(app, pid, kit, body.get('overrides'), body.get('timeline')))
        elif action == 'render' and method == 'GET' and key:
            with LOCK:
                j = JOBS.get((pid, key))
            if not j:
                raise ValueError('Render not found.')
            handler.json(200, dict(j))
        else:
            raise ValueError('Unsupported v3 request.')
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        handler.json(400, {'error': str(exc)})
    return True


if __name__ == '__main__' and sys.argv[1:2] == ['--live']:
    # python3 quick_v3.py --live <project folder> '{"type":"say","text":"..."}'
    push_live(sys.argv[2], json.loads(sys.argv[3])); print('queued'); sys.exit()

if __name__ == '__main__':
    # Offline: python3 quick_v3.py <aroll.mp4> <transcript.json> <kit dir> <out.mp4>
    aroll, tx, kitd, out = sys.argv[1:5]
    t = json.loads(Path(tx).read_text())
    words = [{'w': w['text'].strip(), 's': w['start'], 'e': w['end']} for seg in t['transcript'] for w in seg['words']]
    vmap = json.loads((Path(kitd) / 'visual-map.json').read_text())
    plan = build_plan(aroll, words, vmap)
    Path(out).with_suffix('.plan.json').write_text(json.dumps(plan, indent=1))
    if '--plan-only' in sys.argv:
        print(json.dumps({k: plan[k] for k in ('total', 'speech_end', 'measure', 'digest')}, indent=1))
        for s in plan['segments']:
            print(s['kind'], s['t0'], s.get('t1'), s.get('label') or s.get('head') or s.get('anchor'))
        sys.exit()
    tmpv, tmpa = Path(out).with_suffix('.video.mp4'), Path(out).with_suffix('.mix.wav')
    render(plan, aroll, kitd, tmpv)
    print(mix(plan, aroll, tmpa))
    master(tmpv, tmpa, out)
    print(json.dumps(qc(out, plan), indent=1))
