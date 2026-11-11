#!/usr/bin/env python3
"""Turn a raw take + its finished cut into a FRAME demo recipe (served at /demo?recipe=<name>).

    python3 make_demo.py RAW.mov FINAL.mp4 --name my-video [--labels labels.json]

What it measures (no manual timing needed):
  cuts      final audio matched back to the raw take -> A-roll pieces + voice
  captions  final's words, 3 at a time, never across a cut
  graphics  frames where the top half (split screen) or whole frame (full screen) is a graphic
  flashes   white-flash frames
  music     sound in the final where nobody is speaking
labels.json (optional) adds copy and names; see LABELS_HELP below. Writes repo/recipes/<name>/.
Needs ffmpeg/ffprobe, numpy and faster-whisper (pip install faster-whisper).
"""
import argparse, json, re, shutil, subprocess, sys, difflib
from pathlib import Path
import numpy as np

SR = 16000
REPO = Path(__file__).resolve().parents[2]
LABELS_HELP = """{
  "title": "FRAME demo — My video",
  "intro": {"eyebrow": "...", "headline": "...", "body": "...", "steps": ["...", "...", "..."]},
  "graphics": {"2.6": "Auto-edit timeline", "30.2": "End card"},      // segment start (s) -> name
  "titles":   [["Fable 5.2", 1.0, 2.4]]                                 // big on-screen words, optional
}"""


def sh(*a, capture=False):
    r = subprocess.run(a, check=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE)
    return r.stdout


def probe_duration(f):
    return float(sh('ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(f), capture=True))


def audio(f):
    raw = sh('ffmpeg', '-v', 'error', '-i', str(f), '-vn', '-ac', '1', '-ar', str(SR), '-f', 's16le', '-', capture=True)
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def transcribe(a, model):
    segs, _ = model.transcribe(a, word_timestamps=True, beam_size=1, vad_filter=False)
    return [{'w': w.word.strip(), 's': round(w.start, 3), 'e': round(w.end, 3)} for s in segs for w in s.words]


# ---------------------------------------------------------------- cuts
def find_offsets(d, r):
    """For each 0.25 s hop of the final, the raw-time offset where that audio came from."""
    win, hop = int(.5 * SR), int(.25 * SR)
    N = 1 << int(np.ceil(np.log2(len(r) + win)))
    R = np.fft.rfft(r, N)
    r2 = np.concatenate([[0], np.cumsum(r * r)])
    out = []
    for s in range(0, len(d) - win, hop):
        x = d[s:s + win]
        ex = np.sqrt((x * x).sum())
        if ex < .05:
            out.append((s / SR, None)); continue
        c = np.fft.irfft(R * np.conj(np.fft.rfft(x, N)), N)[:len(r) - win]
        er = np.sqrt(np.maximum(r2[win:win + len(c)] - r2[:len(c)], 0))
        ok = er > ex * .25                       # ignore near-silent raw windows (false peaks)
        sc = np.where(ok, c / (er * ex + 1e-9), 0)
        k = int(np.argmax(sc))
        out.append((s / SR, k / SR - s / SR) if .6 <= sc[k] <= 1.05 else (s / SR, None))
    return out


def group_offsets(hops):
    """Runs of agreeing offsets -> ordered list of distinct pieces (offset, first_t, last_t)."""
    runs = []
    for t, o in hops:
        if o is None:
            continue
        if runs and abs(runs[-1]['o'] - o) < .04 and t - runs[-1]['t1'] <= 1.0:
            runs[-1]['t1'] = t; runs[-1]['n'] += 1
        else:
            runs.append({'o': o, 't0': t, 't1': t, 'n': 1})
    runs = [x for x in runs if x['n'] >= 2]
    merged = []
    for x in runs:                                # same offset split by a stray hop -> one piece
        if merged and abs(merged[-1]['o'] - x['o']) < .04:
            merged[-1]['t1'] = x['t1']; merged[-1]['n'] += x['n']
        else:
            merged.append(x)
    return merged


def refine(d, r, o, t):
    s = int(t * SR); x = d[s:s + SR]; best = (-2, 0)
    for k in range(-400, 401, 2):
        j = int((t + o) * SR) + k; y = r[j:j + SR]
        if len(y) < SR: continue
        c = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
        best = max(best, (c, k))
    return o + best[1] / SR


def cut_points(d, r, pieces):
    F = 160
    def res(o, a, b):
        out = []
        for i in range(a, b):
            s = i * F; x = d[s:s + F]; j = int(s + o * SR); y = r[max(j, 0):j + F]
            if j < 0 or len(y) < F: out.append(1e9); continue
            g = (x * y).sum() / ((y * y).sum() + 1e-9); out.append(float(((x - g * y) ** 2).sum()))
        return np.array(out)
    cuts = []
    for a, b in zip(pieces, pieces[1:]):
        lo, hi = int(a['t1'] * 100), int((b['t0'] + .5) * 100)
        if hi <= lo: hi = lo + 50
        A, B = res(a['o'], lo, hi), res(b['o'], lo, hi)
        cost = [A[:m].sum() + B[m:].sum() for m in range(len(A) + 1)]
        cuts.append(round((lo + int(np.argmin(cost))) / 100, 2))
    return cuts


# ---------------------------------------------------------------- layout
def layout(final, dur):
    w, h = 54, 96
    raw = sh('ffmpeg', '-v', 'error', '-i', str(final), '-vf', f'fps=10,scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-', capture=True)
    fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
    top, bot = fr[:, :h // 2].mean((1, 2)), fr[:, h // 2:].mean((1, 2))
    whole = fr.mean((1, 2)); base = np.convolve(whole, np.ones(15) / 15, 'same')
    spike = (whole - base > 25) & (np.arange(len(whole)) >= 3) & (np.arange(len(whole)) < len(whole) - 3)
    kinds = ['flash' if f else 'full' if a < 60 and b < 60 else 'split' if a < 60 else 'face' for f, a, b in zip(spike, top, bot)]
    dif = np.concatenate([[0], np.abs(np.diff(fr[:, :h // 2], axis=0)).mean((1, 2))])
    segs = []
    for i, k in enumerate(kinds):
        t = round(i / 10, 2)
        if segs and segs[-1]['k'] == k: segs[-1]['e'] = round(t + .1, 2)
        else: segs.append({'k': k, 's': t, 'e': round(t + .1, 2)})
    # a new card inside one split run = a jump in the top half; keep parts of at least 1 s
    out = []
    for s in segs:
        if s['k'] != 'split':
            out.append(s); continue
        a, b = int(round(s['s'] * 10)), int(round(s['e'] * 10))
        start = a
        for i in range(a + 10, b - 9):
            if dif[i] > 22 and i - start >= 10:
                out.append({'k': 'split', 's': round(start / 10, 2), 'e': round(i / 10, 2)}); start = i
        out.append({'k': 'split', 's': round(start / 10, 2), 'e': s['e']})
    segs = out
    # split/full runs separated only by a flash or a 0.1 s blip stay separate graphics; drop tiny noise
    return [s for s in segs if s['e'] - s['s'] >= (.09 if s['k'] == 'flash' else .5)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('raw'); ap.add_argument('final')
    ap.add_argument('--name', required=True, help='recipe id, e.g. launch-reel-2')
    ap.add_argument('--labels', help='optional labels.json:\n' + LABELS_HELP)
    ap.add_argument('--model', default='small.en')
    a = ap.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', a.name):
        sys.exit('--name must be lowercase letters, digits and dashes.')
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit('Needs faster-whisper:  python3 -m pip install faster-whisper')
    raw, final = Path(a.raw).expanduser(), Path(a.final).expanduser()
    L = json.loads(Path(a.labels).read_text()) if a.labels else {}
    out = REPO / 'recipes' / a.name; (out / 'media' / 'stills').mkdir(parents=True, exist_ok=True)

    print('1/6 audio'); d, r = audio(final), audio(raw)
    FIN, RAWLEN = round(probe_duration(final), 2), round(probe_duration(raw), 2)

    print('2/6 transcribing (a minute or two)'); m = WhisperModel(a.model, device='cpu', compute_type='int8')
    DW, RW = transcribe(d, m), transcribe(r, m)
    (out / 'transcript.txt').write_text(f'{raw.name} — raw take, {int(round(RAWLEN) // 60)}:{int(round(RAWLEN) % 60):02d}\n\n' + ' '.join(w['w'] for w in RW) + '\n')

    print('3/6 matching the cut to the raw take')
    groups = group_offsets(find_offsets(d, r))
    if not groups: sys.exit('Could not match the final audio to the raw take. Is this the right pair?')
    for g in groups: g['o'] = refine(d, r, g['o'], (g['t0'] + g['t1']) / 2 + .25)
    cuts = cut_points(d, r, groups)
    speech_end = max(w['e'] for w in DW)
    bounds = [0] + cuts + [min(FIN, round(groups[-1]['t1'] + .5 + .3, 2), round(RAWLEN - groups[-1]['o'], 2))]
    bounds[-1] = max(bounds[-1], min(speech_end + .15, RAWLEN - groups[-1]['o']))
    pieces = [{'din': bounds[i], 'dout': bounds[i + 1], 'rin': round(bounds[i] + g['o'], 3), 'rout': round(bounds[i + 1] + g['o'], 3)} for i, g in enumerate(groups)]
    kept = sum(p['dout'] - p['din'] for p in pieces)
    print(f'    {len(pieces)} pieces, {kept:.1f} s kept of {RAWLEN:.1f} s')

    print('4/6 graphics, flashes, music'); segs = layout(final, FIN)
    gnames = {float(k): v for k, v in (L.get('graphics') or {}).items()}
    def gname(s):
        near = [v for k, v in gnames.items() if abs(k - s['s']) <= .4]
        return near[0] if near else ('Full-screen graphic' if s['k'] == 'full' else 'Split-screen graphic')
    gfx = [{'track': 'gfx', 'label': gname(s), 'start': s['s'], 'end': s['e'], 'full': s['k'] == 'full'} for s in segs if s['k'] in ('split', 'full')]
    flashes = [s['s'] for s in segs if s['k'] == 'flash']
    quiet = [(a_, b_) for a_, b_ in zip([0] + [w['e'] for w in DW], [w['s'] for w in DW] + [FIN]) if b_ - a_ > .4]
    music = any(20 * np.log10(np.sqrt((d[int(x * SR):int(y * SR)] ** 2).mean()) + 1e-9) > -45 for x, y in quiet[-2:])

    print('5/6 media'); med = out / 'media'
    sh('ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30',
       '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(med / 'raw-proxy.mp4'))
    shutil.copy2(final, med / 'final.mp4')
    def still(t, name):
        sh('ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(med / 'final.mp4'), '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '3', str(med / 'stills' / name))
        return f'media/stills/{name}'

    print('6/6 recipe')
    r2 = lambda x: round(x, 2)
    words_in = lambda s, e: [w['w'] for w in DW if s - .05 <= w['s'] < e - .05]
    aroll = [{'track': 'v1', 'label': f"Take {p['rin']:.1f}–{p['rout']:.1f}s · " + ' '.join(words_in(p['din'], p['dout'])[:5]), 'start': r2(p['din']), 'end': r2(p['dout'])} for p in pieces]
    caps, cur = [], []
    def flush():
        if cur: caps.append({'track': 't1', 'label': ' '.join(w['w'] for w in cur).replace(' .', '.'), 'start': r2(cur[0]['s']), 'end': r2(cur[-1]['e'])})
    for w in DW:
        if cur and (len(cur) == 3 or any(cur[-1]['s'] < c <= w['s'] for c in cuts)): flush(); cur = []
        cur.append(w)
    flush()
    face_t = next((p['din'] + p['dout']) / 2 for p in pieces)
    steps = [
        ('Transcribe', 'caps', 'Transcribe the raw take', f'{len(RW)} words with timings from {raw.name} ({int(round(RAWLEN) // 60)}:{int(round(RAWLEN) % 60):02d}).', {'kind': 'text', 'path': 'transcript.txt'}, []),
        ('Cut', 'razor', 'Cut to the strongest lines', f'Kept {len(pieces)} pieces, {kept:.1f} s of {RAWLEN:.0f} s. Dropped retakes, asides and dead air.', {'kind': 'video', 'path': 'media/raw-proxy.mp4', 'at': pieces[len(pieces) // 2]['rin']}, aroll),
        ('Voice', 'mix', 'Lay the voice under the cut', 'Voice follows every A-roll piece.', {'kind': 'video', 'path': 'media/raw-proxy.mp4', 'at': pieces[-1]['rin']}, [dict(x, track='a1', label='Voice') for x in aroll]),
        ('Captions', 'caps', f'Captions, 3 words at a time', f'{len(caps)} caption clips, never across a cut.', {'kind': 'image', 'path': still(face_t, 'captions.jpg')}, caps),
    ]
    titles = L.get('titles') or []
    if titles:
        steps.append(('Titles', 'gfx', 'Kinetic title hits', 'Big type on the key words: ' + ', '.join(t[0] for t in titles[:4]) + '.',
                      {'kind': 'image', 'path': still((titles[0][1] + titles[0][2]) / 2, 'titles.jpg')}, [{'track': 'ttl', 'label': t[0], 'start': t[1], 'end': t[2]} for t in titles]))
    split, full = [g for g in gfx if not g['full']], [g for g in gfx if g['full']]
    end_card = full[-1] if full and full[-1]['end'] >= FIN - .3 else None
    full = [g for g in full if g is not end_card]
    clean = lambda g: {k: g[k] for k in ('track', 'label', 'start', 'end')}
    if split:
        mid = split[len(split) // 2]
        steps.append(('B-roll', 'bcoll', 'Split-screen graphics', f'{len(split)} top-half graphics on the matching lines.', {'kind': 'image', 'path': still((mid['start'] + mid['end']) / 2, 'split.jpg')}, [clean(g) for g in split]))
    if full:
        steps.append(('Motion', 'gfx', 'Full-screen graphics', f'{len(full)} full-frame takeover(s).', {'kind': 'image', 'path': still((full[0]['start'] + full[0]['end']) / 2, 'full.jpg')}, [clean(g) for g in full]))
    if flashes:
        steps.append(('Look', 'grade', 'White-flash transitions', f'{len(flashes)} flashes on the beat changes.', {'kind': 'image', 'path': still(min(FIN - .2, flashes[-1] + .4), 'flash.jpg')}, [{'track': 'fx', 'label': 'Flash', 'start': t, 'end': r2(t + .2)} for t in flashes]))
    if music:
        steps.append(('Music', 'mix', 'Music bed', 'Bed runs the full reel.', None, [{'track': 'a2', 'label': 'Music bed', 'start': 0, 'end': FIN}]))
    if end_card:
        steps.append(('Finish', 'gfx', 'End card', end_card['label'] if end_card['label'] != 'Full-screen graphic' else 'Closing card.', {'kind': 'image', 'path': still(FIN - .3, 'end.jpg')}, [clean(end_card)]))
    lanes = [['gfx', 'GRAPHICS', 'var(--v2)']] + ([['ttl', 'TITLES', 'var(--t1)']] if titles else []) + [['v1', 'A-ROLL', 'var(--v1)'], ['t1', 'CAPTIONS', '#f2f2f5'], ['fx', 'FX', 'var(--fx)'], ['a1', 'VOICE', 'var(--a1)'], ['a2', 'MUSIC', 'var(--a2)']]
    recipe = {
        'format': 'frame-recipe/1', 'name': a.name, 'title': L.get('title') or f'FRAME demo — {final.stem}', 'duration': FIN, 'canvas': [1080, 1920],
        'final': 'media/final.mp4',
        'provenance': 'Rebuilt from the media by make_demo.py: cuts by matching the final audio to the raw take; captions from the final word timings; graphics, flashes and music from analysis of the final.',
        'intro': L.get('intro') or {},
        'rawClip': {'path': 'media/raw-proxy.mp4', 'file': raw.name, 'meta': f'{int(round(RAWLEN) // 60)}:{int(round(RAWLEN) % 60):02d} raw take', 'label': f'Raw footage · {raw.name}', 'duration': RAWLEN, 'at': 0},
        'lanes': lanes,
        'steps': [dict(id=f'step-{i + 1:02d}', phase=p, lane=l, title=t, did=dd, **({'show': sw} if sw else {}), place=pl) for i, (p, l, t, dd, sw, pl) in enumerate(steps)],
    }
    (out / 'recipe.json').write_text(json.dumps(recipe, indent=1))
    n = sum(len(s['place']) for s in recipe['steps'])
    print(f'\nDone: {out}\n  {len(recipe["steps"])} agent steps, {n} edits. Open http://127.0.0.1:<port>/demo?recipe={a.name}')


if __name__ == '__main__':
    main()
