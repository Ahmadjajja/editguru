"""Measure the editing style of a reference video (low memory, FFmpeg only) so it can be
applied to different raw footage.

analyze(path) -> style dict:
  shot        average shot length in seconds (from scene cuts)
  cuts_pm     cuts per minute
  punch       True when the reference is fast-cut, so alternate pieces get punch-ins
  flash       True when the reference uses white-flash transitions
  lufs        integrated loudness of the reference
  look        {'y','sat','contrast'} measured colour/tonal profile
  wps         words per second is added by the caller when a transcript exists
"""
import re
import statistics
import subprocess

SAMPLE = 120  # only the first 2 minutes of a reference are studied


def _run(*args, timeout=900):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    return r.stderr.decode(errors='replace') + r.stdout.decode(errors='replace')


def _scene_cuts(path):
    out = _run('ffmpeg', '-hide_banner', '-nostats', '-t', str(SAMPLE), '-i', str(path), '-an', '-vf',
               _crop(path) + "scale=320:-2,select='gt(scene,0.28)',showinfo", '-f', 'null', '-')
    return sorted({round(float(t), 2) for t in re.findall(r'pts_time:([\d.]+)', out)})


def _frame_stats(path):
    """Per-frame luma/sat/contrast at 30 fps on a tiny copy of the video."""
    out = _run('ffmpeg', '-hide_banner', '-nostats', '-t', str(SAMPLE), '-i', str(path), '-an', '-vf',
               _crop(path) + 'scale=160:-2,fps=30,signalstats,metadata=mode=print:file=-', '-f', 'null', '-')
    rows, cur = [], {}
    for line in out.splitlines():
        m = re.search(r'lavfi\.signalstats\.(YAVG|SATAVG|YLOW|YHIGH)=([\d.]+)', line)
        if m:
            cur[m[1]] = float(m[2])
            if m[1] == 'YHIGH' and len(cur) == 4:
                rows.append(cur); cur = {}
    return rows


def look_of(path):
    rows = _frame_stats(path)
    if not rows:
        return None
    return {'y': statistics.fmean(r['YAVG'] for r in rows),
            'sat': statistics.fmean(r['SATAVG'] for r in rows),
            'contrast': statistics.fmean(r['YHIGH'] - r['YLOW'] for r in rows)}


def _flashes(rows):
    """A flash = luma jumps >35 above its surroundings for at most ~8 frames."""
    ys = [r['YAVG'] for r in rows]
    n, i, found = len(ys), 3, 0
    while i < n - 10:
        base = statistics.fmean(ys[i - 3:i])
        if ys[i] - base > 35:
            j = i
            while j < n and ys[j] > ys[i] - 30:
                j += 1
            if j - i <= 8:
                found += 1
            i = j + 3
        else:
            i += 1
    return found


def _crop(path):
    """Content rectangle without black letterbox bars, as an FFmpeg crop filter ('' if none)."""
    out = _run('ffmpeg', '-hide_banner', '-nostats', '-ss', '1', '-t', '20', '-i', str(path), '-an', '-vf', 'cropdetect=limit=24:round=2:reset=0', '-f', 'null', '-')
    m = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', out)
    return 'crop=%s:%s:%s:%s,' % m[-1] if m else ''


def _palette(path):
    """Full-screen title cards (flat light/dark backgrounds) and the accent colour, from 2 fps thumbnails."""
    try:
        import numpy as np
    except ImportError:
        return None
    w, h = 64, 112
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-t', str(SAMPLE), '-i', str(path), '-an', '-vf', _crop(path) + 'fps=2,scale=%d:%d' % (w, h),
                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, timeout=600).stdout
    n = len(raw) // (w * h * 3)
    if not n:
        return None
    fr = np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, w * h, 3).astype(int)
    cards, sat_px = [], []
    for f in fr:
        med = np.median(f, axis=0)
        flat = (np.abs(f - med).max(axis=1) < 14).mean()
        luma = med @ [.299, .587, .114]
        if flat > .62 and luma > 175:
            cards.append(med)
        mx, mn = f.max(axis=1), f.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1)
        sel = f[(sat > .6) & (mx > 120)]
        if len(sel) > w * h * .004:
            sat_px.append(sel.mean(axis=0))
    card = None
    runs = 0
    if cards:
        card = tuple(int(x) for x in np.median(np.array(cards), axis=0))
    flags = []
    for f in fr:
        med = np.median(f, axis=0)
        flags.append((np.abs(f - med).max(axis=1) < 14).mean() > .62 and med @ [.299, .587, .114] > 175)
    prev = False
    for fl in flags:
        runs += bool(fl and not prev); prev = fl
    accent = tuple(int(x) for x in np.median(np.array(sat_px), axis=0)) if len(sat_px) >= max(2, n * .08) else None
    return {'frac': round(len(cards) / n, 3), 'pm': round(runs / (n / 2) * 60, 1), 'color': card, 'accent': accent}


def loudness(path):
    out = _run('ffmpeg', '-hide_banner', '-nostats', '-t', str(SAMPLE), '-i', str(path), '-map', '0:a:0', '-af', 'ebur128=peak=true', '-f', 'null', '-')
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', out)
    return float(m[-1]) if m else None


def analyze(path, dur, has_audio):
    d = min(dur, SAMPLE)
    cuts = _scene_cuts(path)
    rows = _frame_stats(path)
    shot = d / (len(cuts) + 1)
    flashes = _flashes(rows) if rows else 0
    lufs = loudness(path) if has_audio else None
    look = None
    if rows:
        look = {'y': statistics.fmean(r['YAVG'] for r in rows), 'sat': statistics.fmean(r['SATAVG'] for r in rows),
                'contrast': statistics.fmean(r['YHIGH'] - r['YLOW'] for r in rows)}
    pal = _palette(path)
    editorial = bool(pal and pal['color'] and pal['frac'] >= .08 and pal['pm'] >= 2)
    return {'cards': pal, 'editorial': editorial, 'shot': round(shot, 2), 'cuts': len(cuts), 'cuts_pm': round(len(cuts) / d * 60, 1), 'punch': shot < 4.0,
            'flash': flashes >= 1 and flashes >= len(cuts) * .15, 'flashes': flashes,
            'lufs': round(lufs, 1) if lufs is not None and lufs > -40 else None, 'look': look, 'seconds': round(d, 1)}


def grade_filter(ref_look, raw_look):
    """eq filter that nudges the raw footage toward the reference's tone (clamped, so it never wrecks it)."""
    if not ref_look or not raw_look:
        return ''
    clamp = lambda x, a, b: max(a, min(b, x))
    contrast = clamp(ref_look['contrast'] / max(raw_look['contrast'], 1), .85, 1.3)
    sat = clamp(ref_look['sat'] / max(raw_look['sat'], 1), .7, 1.5)
    bright = clamp((ref_look['y'] - raw_look['y']) / 255, -.08, .08)
    if abs(contrast - 1) < .03 and abs(sat - 1) < .03 and abs(bright) < .01:
        return ''
    return 'eq=contrast=%.3f:saturation=%.3f:brightness=%.3f' % (contrast, sat, bright)


def describe(s):
    bits = ['%.1f s average shot (%s cuts/min)' % (s['shot'], s['cuts_pm'])]
    bits.append('punch-ins on the cuts' if s['punch'] else 'slow, mostly uncut pacing')
    if s.get('editorial'):
        bits.append('full-screen title cards (%s/min)' % s['cards']['pm'])
        if s['cards'].get('accent'):
            bits.append('accent #%02x%02x%02x' % s['cards']['accent'])
    bits.append('white-flash transitions' if s['flash'] else 'no flash transitions')
    if s.get('lufs') is not None:
        bits.append('%.0f LUFS loudness' % s['lufs'])
    if s.get('wps'):
        bits.append('%.1f words/s speech' % s['wps'])
    return ', '.join(bits) + '.'
