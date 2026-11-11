#!/usr/bin/env python3
"""Preview vs render: does the MP4 FRAME renders show what the editor's preview showed, at the same moment?

    python3 work/frame-product/tests/v3_compare.py --capture ~/frame-test-runs/compare-1 --render <edited.mp4>

Reads the previews written by v3_preview_capture.cjs. For each captured time t it pulls the render's frames
from t-0.3 s to t+0.3 s, scales them to the preview's 540x960, and measures the mean absolute pixel difference
(0 = identical, 255 = opposite) for the whole frame and for three bands (top / middle / bottom thirds, where
split media, labels and captions sit). The offset with the smallest difference is the timing error.

Writes compare.md + compare.json + side_<t>.png (preview | render at t | difference x4) into the capture folder.
Thresholds are deliberately simple; read the side-by-side images before calling anything a bug:
  visual mismatch  = best-offset difference > --visual (default 18)
  timing mismatch  = best offset is more than one frame away from 0 and clearly better than offset 0
Needs numpy + Pillow (FRAME's venv has both) and ffmpeg.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FPS = 30


def frames_around(render, t, span=0.3, size=(540, 960)):
    t0 = max(0.0, t - span)
    n = int(round((t + span - t0) * FPS)) + 1
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '%.3f' % t0, '-i', str(render), '-frames:v', str(n),
                          '-vf', 'scale=%d:%d:flags=area' % size, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True, check=True).stdout
    w, h = size
    k = len(raw) // (w * h * 3)
    arr = np.frombuffer(raw[:k * w * h * 3], np.uint8).reshape(k, h, w, 3).astype(np.float32)
    return [(round(t0 + i / FPS - t, 3), arr[i]) for i in range(k)]


def diff(a, b):
    d = np.abs(a - b).mean(axis=2)
    h = d.shape[0]
    return float(d.mean()), [float(d[i * h // 3:(i + 1) * h // 3].mean()) for i in range(3)], d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', required=True)
    ap.add_argument('--render', required=True)
    ap.add_argument('--visual', type=float, default=18.0)
    a = ap.parse_args()
    cap = Path(a.capture).expanduser()
    state = json.loads((cap / 'state.json').read_text())
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', a.render],
                               capture_output=True, text=True).stdout.strip() or 0)
    rows = []
    for s in state['times']:
        prev = np.asarray(Image.open(cap / s['file']).convert('RGB').resize((540, 960)), np.float32)
        cands = frames_around(a.render, s['t'])
        if not cands:
            rows.append(dict(t=s['t'], error='render has no frame here (render is %.2f s)' % dur)); continue
        scored = [(off, *diff(prev, fr)[:2], fr) for off, fr in cands]
        at0 = min(scored, key=lambda x: abs(x[0]))
        best = min(scored, key=lambda x: x[1])
        _, _, dmap = diff(prev, at0[3])
        side = np.concatenate([prev, at0[3], np.clip(np.repeat(dmap[..., None], 3, 2) * 4, 0, 255)], axis=1).astype(np.uint8)
        Image.fromarray(side).save(cap / ('side_%.2f.png' % s['t']))
        timing = abs(best[0]) > 1.5 / FPS and best[1] < at0[1] * 0.8
        rows.append({'t': s['t'], 'section': s['section']['kind'], 'label': s['section'].get('label', ''),
                     'captions': [c['text'] for c in s['captions']], 'graphics': [g['name'] for g in s['graphics']],
                     'diff_at_t': round(at0[1], 1), 'bands_at_t': [round(x, 1) for x in at0[2]],
                     'best_offset_s': best[0], 'diff_best': round(best[1], 1),
                     'visual_mismatch': best[1] > a.visual, 'timing_mismatch': bool(timing), 'side': 'side_%.2f.png' % s['t']})
    (cap / 'compare.json').write_text(json.dumps({'render': a.render, 'render_duration': dur, 'rows': rows}, indent=1))
    lines = ['# Preview vs render', '', 'Render: `%s` (%.2f s). Difference = mean absolute pixel difference at 540x960 (0 identical).' % (a.render, dur), '',
             '| t (s) | Section | On screen | Diff at t | Top / mid / bottom | Best offset (s) | Diff at best | Visual | Timing |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        if 'error' in r:
            lines.append('| %.2f | — | — | — | — | — | — | %s | — |' % (r['t'], r['error'])); continue
        what = '; '.join([r['label']] + r['graphics'] + r['captions'])[:80]
        lines.append('| %.2f | %s | %s | %.1f | %s | %+.3f | %.1f | %s | %s |' % (
            r['t'], r['section'], what.replace('|', '/'), r['diff_at_t'], ' / '.join('%.1f' % x for x in r['bands_at_t']),
            r['best_offset_s'], r['diff_best'], 'MISMATCH' if r['visual_mismatch'] else 'ok', 'OFF' if r['timing_mismatch'] else 'ok'))
    bad_v = sum(1 for r in rows if r.get('visual_mismatch') or 'error' in r)
    bad_t = sum(1 for r in rows if r.get('timing_mismatch'))
    lines += ['', 'Summary: %d times compared, %d visual mismatches, %d timing mismatches. Open the side_*.png files (preview | render | difference x4) for each flagged row.' % (len(rows), bad_v, bad_t)]
    (cap / 'compare.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 1 if bad_v or bad_t else 0


if __name__ == '__main__':
    sys.exit(main())
