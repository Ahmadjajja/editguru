"""Upload any video on /demo and get a real edit, replayed by the agent swarm.

POST /api/autoedit                 raw video body (X-Filename header) -> {"id": job}
GET  /api/autoedit/<job>           -> {"status", "stage", "progress", "preview"?, "recipe"?, "error"?}
GET  /api/autoedit/<job>/preview   vertical proxy of the raw upload (once "preview" is true)

From the transcript it keeps the last clean take of every line (drops retakes, false
starts, fillers and dead air), then renders 1080x1920 with blur-fill reframing,
punch-in zooms on alternate cuts, 3-word captions, kinetic title words, white
flashes where material was removed, and -14 LUFS loudness. It writes
recipes/u-<job>/recipe.json in the same shape /demo replays for the built-in demo.
"""
import difflib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import editor
import quick_refstyle

RECIPES = Path(__file__).resolve().parents[2] / 'recipes'
MAX_BYTES = 700 * 1024 * 1024
JOBS = {}
REFS = {}
LOCK = threading.Lock()
WORKER = threading.Semaphore(1)
W, H, FPS = 1080, 1920, 30
ZOOM = 1.12
UMS = {'um', 'uh', 'uhm', 'umm', 'erm', 'er', 'ah', 'hmm', 'mm', 'uhh', 'ahh', 'mhm'}
FILLERS = {'um', 'uh', 'uhm', 'umm', 'erm', 'er', 'ah', 'hmm', 'mm', 'like', 'so', 'okay', 'ok', 'yeah', 'right', 'and', 'but', 'well', 'you', 'know'}
STOP = {'the', 'and', 'that', 'this', 'with', 'have', 'from', 'your', 'you', 'just', 'what', 'about', 'they', 'there',
        'their', 'would', 'could', 'should', 'because', 'really', 'going', 'gonna', 'into', 'them', 'then', 'than', 'when',
        'which', 'were', 'been', 'being', 'it\'s', 'that\'s', 'don\'t', 'i\'m', 'you\'re', 'actually', 'basically'}


def _sh(*args, timeout=1800):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors='replace')[-1200:])
    return r.stdout


def _mmss(s):
    s = int(round(s))
    return '%d:%02d' % (s // 60, s % 60)


def _norm(w):
    return re.sub(r"[^a-z0-9']", '', w.lower())


def _transcribe(path):
    """Word timings, or [] with a note. Runs Whisper in a child process so its ~0.5 GB is
    fully returned to the OS afterwards (small hosts can't hold it next to a render)."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return [], 'No captions or retake detection: faster-whisper is not installed on this server.'
    wav = Path(path).with_name('audio16k.wav')   # decode audio once, small: keeps Whisper's memory low on big 4K files
    try:
        _sh('ffmpeg', '-v', 'error', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav))
        with editor.TRANSCRIBE_LOCK:
            r = subprocess.run([sys.executable, __file__, '--transcribe', str(wav)], capture_output=True, timeout=3600)
    finally:
        pass
    wav.unlink(missing_ok=True)
    if r.returncode:
        why = r.stderr.decode(errors='replace').strip()[-200:] or ('killed by the OS, probably out of memory' if r.returncode in (-9, 137) else 'exit code %d' % r.returncode)
        return [], 'No captions or retake detection: transcription failed (%s).' % why
    return json.loads(r.stdout), None


def _transcribe_here(path):
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True)
    except Exception:
        model = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=2)
    # The disfluent prompt makes Whisper write out "um"/"uh" instead of silently dropping them.
    segs, _ = model.transcribe(str(path), word_timestamps=True, vad_filter=True, beam_size=3,
                               initial_prompt="Umm, let me think like, hmm... Okay, uh, here's what I'm, like, thinking.")
    return [{'w': w.word.strip(), 's': round(w.start, 3), 'e': round(w.end, 3)}
            for s in segs for w in (s.words or []) if w.word.strip()]


# ---------------------------------------------------------------- choosing what to keep

def _phrases(words):
    """Split the transcript into lines at sentence punctuation or pauses over 0.7 s."""
    out, cur = [], []
    for w in words:
        if cur and w['s'] - cur[-1]['e'] > .7:
            out.append(cur); cur = []
        cur.append(w)
        if re.search(r'[.?!]$', w['w']):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return [{'words': p, 's': p[0]['s'], 'e': p[-1]['e'], 'n': [_norm(x['w']) for x in p]} for p in out]


def _is_retake(a, b):
    """True if line a is an earlier attempt at line b (speaker restarted)."""
    a, b = [x for x in a if x], [x for x in b if x]
    if not a or not b:
        return False
    if len(a) >= 2 and a[:2] == b[:2]:
        return True
    if len(a) <= 3 and a[0] == b[0] and len(b) > len(a):
        return True                                   # false start
    k = min(len(a), len(b))
    return k >= 3 and difflib.SequenceMatcher(None, a, b[:max(k, len(a))]).ratio() >= .7


def _choose(words, silences, dur):
    phrases = _phrases(words)
    dropped = {'retake': 0, 'filler': 0}
    for i, p in enumerate(phrases):
        if all(x in FILLERS or not x for x in p['n']):
            p['drop'] = 'filler'; continue
        for q in phrases[i + 1:i + 4]:
            if q['s'] - p['e'] > 25:
                break
            if _is_retake([x for x in p['n'] if x not in UMS], [x for x in q['n'] if x not in UMS]):
                p['drop'] = 'retake'; break
    kept = [p for p in phrases if not p.get('drop')]
    for p in phrases:
        if p.get('drop'):
            dropped[p['drop']] += 1
    if not kept:                                     # never return an empty edit
        kept, dropped = phrases, {'retake': 0, 'filler': 0}
    spans = []
    for p in kept:
        a, b = max(0, p['s'] - .12), min(dur, p['e'] + .22)
        if spans and a - spans[-1][1] < .25:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    # Remove long pauses that remain inside a kept span (never through a word).
    regions = editor.protect_spoken_audio([r for r in silences if r[1] - r[0] >= .55],
                                          [{'words': [{'start': w['s'], 'end': w['e']} for w in words]}])
    keep = []
    for a, b in spans:
        try:
            keep += editor.trim_pauses([[a, b]], regions)
        except ValueError:
            keep.append([a, b])
    # Cut each "um"/"uh" inside the kept lines, butted up against its neighbours.
    ums = []
    for p in kept:
        ws = p['words']
        for i, w in enumerate(ws):
            if _norm(w['w']) in UMS:
                a = ws[i - 1]['e'] + .02 if i else w['s'] - .04
                b = ws[i + 1]['s'] - .02 if i + 1 < len(ws) else w['e'] + .06
                if b - a >= .12:
                    ums.append((a, b))
    for a, b in ums:
        nxt = []
        for x, y in keep:
            if b <= x or a >= y:
                nxt.append([x, y]); continue
            if a - x >= .08: nxt.append([x, a])
            if y - b >= .08: nxt.append([b, y])
        keep = nxt
    dropped['um'] = len(ums)
    return _tidy(keep, dur), kept, dropped


def _silence_only(silences, dur):
    regions = [r for r in silences if r[1] - r[0] >= .55]
    try:
        keep = editor.trim_pauses([[0, dur]], regions)
    except ValueError:
        keep = [[0, dur]]
    return _tidy(keep, dur)


def _tidy(keep, dur):
    keep = [[round(a, 3), round(min(b, dur), 3)] for a, b in sorted(keep) if b - a >= .08] or [[0, round(dur, 3)]]
    while len(keep) > 60:                            # merge the closest neighbours
        i = min(range(len(keep) - 1), key=lambda k: keep[k + 1][0] - keep[k][1])
        keep[i:i + 2] = [[keep[i][0], keep[i + 1][1]]]
    return keep


def _join(ws):
    """Join Whisper tokens ("5", ".2," -> "5.2") and drop trailing commas for captions."""
    text = ''
    for w in ws:
        t = w['w'].strip()
        text += t if (text and re.match(r"^[.,!?;:%']", t)) else (' ' + t if text else t)
    return text.rstrip(',;:')


def _map_time(t, keep):
    """Source time -> edited time (None if t falls in a removed span)."""
    out = 0
    for a, b in keep:
        if a - .05 <= t <= b + .05:
            return out + min(max(t - a, 0), b - a)
        out += b - a
    return None


def _titles(edited_words, final_len, gap=None, ctx=False):
    """One punchy word per few seconds: numbers, names, then long content words."""
    def score(w):
        raw, n = w['w'].strip('.,!?;:"'), _norm(w['w'])
        if not n or n in STOP or len(n) < 3:
            return 0
        s = len(n) / 4
        if re.search(r'\d', n): s += 3
        if raw[:1].isupper() and not w.get('first') and n != 'i': s += 2
        return s if s >= 1.6 else 0
    picks, last = [], -99
    gap = gap or max(3.5, final_len / 8)
    for w in sorted(edited_words, key=score, reverse=True):
        if score(w) and all(abs(w['s'] - p['s']) >= gap for p in picks):
            picks.append(w)
    picks.sort(key=lambda w: w['s'])
    out = []
    for i, w in enumerate(picks):
        end = max(w['e'] + .35, w['s'] + .8)
        if i + 1 < len(picks):
            end = min(end, picks[i + 1]['s'] - .05)
        t = {'track': 'ttl', 'label': w['w'].strip('.,!?;:"').upper(), 'start': round(w['s'], 2), 'end': round(min(end, final_len), 2)}
        if ctx:
            k = next((j for j, x in enumerate(edited_words) if x is w), 0)
            before = [_join([x]).strip('.,!?;:') for x in edited_words[max(0, k - 3):k] if w['s'] - x['e'] < 1.5]
            t['ctx'] = ' '.join(before)
        out.append(t)
    return out


# ---------------------------------------------------------------- rendering

def _ass_time(t):
    cs = int(round(max(t, 0) * 100))
    return '%d:%02d:%02d.%02d' % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


FONTS = Path(__file__).resolve().parent / 'fonts'


def _bgr(c):
    return '&H00%02X%02X%02X&' % (c[2], c[1], c[0])


def _write_ass(path, caps, titles, flashes, canvas=(W, H), look=None, final_len=0):
    if look:
        return _write_ass_editorial(path, caps, titles, flashes, canvas, look, final_len)
    W, H = canvas
    esc = lambda s: s.replace('\\', '').replace('{', '(').replace('}', ')').replace('\n', ' ')
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n'
            '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
            'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Cap,DejaVu Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,520,1\n'
            'Style: Ttl,DejaVu Sans,150,&H003DFFC6,&H003DFFC6,&H00000000,&H78000000,-1,0,0,0,100,100,2,0,1,9,4,5,60,60,0,1\n'
            'Style: Fx,DejaVu Sans,10,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n'
            '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n') % (W, H)
    ev = ['Dialogue: 0,%s,%s,Cap,,0,0,0,,%s' % (_ass_time(c['start']), _ass_time(c['end']), esc(c['label']).upper()) for c in caps]
    ev += ['Dialogue: 1,%s,%s,Ttl,,0,0,0,,{\\pos(540,560)\\fad(40,90)\\fscx60\\fscy60\\t(0,140,\\fscx108\\fscy108)\\t(140,220,\\fscx100\\fscy100)}%s'
           % (_ass_time(t['start']), _ass_time(t['end']), esc(t['label'])) for t in titles]
    ev += ['Dialogue: 2,%s,%s,Fx,,0,0,0,,{\\pos(0,0)\\fad(0,140)\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}'
           % (_ass_time(f['start']), _ass_time(f['end']), W, W, H, H) for f in flashes]
    path.write_text(head + '\n'.join(ev) + '\n')


def _write_ass_editorial(path, caps, titles, flashes, canvas, look, final_len):
    """The reference's look: cream full-screen cards with huge condensed type, white pop-up words,
    small monospace HUD captions and an accent colour, all measured from the reference video."""
    cw, ch = canvas
    k = min(cw, ch) / 1080
    esc = lambda t: t.replace('\\', '').replace('{', '(').replace('}', ')').replace('\n', ' ')
    card = look['cards']['color']
    accent = look['cards'].get('accent') or (230, 57, 70)
    ink = '&H00141414&'
    sty = lambda name, font, size, col, bold, align, mv=0, ml=0, outline=0: (
        'Style: %s,%s,%d,%s,%s,&H00000000,&H64000000,%d,0,0,0,100,100,%s,0,1,%s,0,%d,%d,%d,%d,1\n'
        % (name, font, int(size * k), col, col, bold, 1 if name == 'Hud' else 0, outline, align, ml, ml, mv))
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n'
            '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
            'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n') % (cw, ch)
    head += sty('Cap', 'Space Mono', 34, '&H00FFFFFF&', -1, 1, mv=int(ch * (.1 if cw > ch else .2)), ml=int(56 * k), outline=2)
    head += sty('Pop', 'Anton', 250, '&H00FFFFFF&', 0, 5, outline=0).replace(',0,0,0,100,100,0,0,1,0,0', ',0,0,0,100,100,0,0,1,0,0')
    head += sty('Big', 'Anton', 330, ink, 0, 4, ml=int(72 * k))
    head += sty('Tag', 'Space Mono', 30, ink, -1, 1, ml=int(72 * k))
    head += sty('Hud', 'Space Mono', 22, '&H00FFFFFF&', -1, 7, mv=int(34 * k), ml=int(40 * k), outline=1)
    head += 'Style: Fx,DejaVu Sans,10,&H00FFFFFF&,&H00FFFFFF&,&H00FFFFFF&,&H00FFFFFF&,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n'
    head += '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    T = _ass_time
    rect = lambda x, y, w, h: 'm %d %d l %d %d %d %d %d %d' % (x, y, x + w, y, x + w, y + h, x, y + h)
    ev = []
    ev.append('Dialogue: 3,%s,%s,Hud,,0,0,0,,{\\1c&H00E6E6E6&\\alpha&H30&}FROM RAW FOOTAGE  ·  FINISHED VIDEO' % (T(0), T(max(final_len, 1))))
    ev.append('Dialogue: 3,%s,%s,Hud,,0,0,0,,{\\an9\\1c&H00E6E6E6&\\alpha&H30&}FRAME  ·  AGENT EDIT' % (T(0), T(max(final_len, 1))))
    ev += ['Dialogue: 1,%s,%s,Cap,,0,0,0,,%s' % (T(c['start']), T(c['end']), esc(c['label']).upper()) for c in caps]
    for t in titles:
        if t.get('card'):
            a, b = T(t['start']), T(t['end'])
            ev.append('Dialogue: 4,%s,%s,Fx,,0,0,0,,{\\pos(0,0)\\1c%s\\fad(0,90)\\p1}%s{\\p0}' % (a, b, _bgr(card), rect(0, 0, cw, ch)))
            y = int(ch * .47)
            ev.append('Dialogue: 5,%s,%s,Big,,0,0,0,,{\\move(%d,%d,%d,%d,0,160)\\fad(60,70)}%s' % (a, b, int(30 * k), y, int(72 * k), y, esc(t['label'])))
            ev.append('Dialogue: 5,%s,%s,Fx,,0,0,0,,{\\pos(0,0)\\1c%s\\fad(120,70)\\p1}%s{\\p0}' % (a, b, _bgr(accent), rect(int(72 * k), y + int(215 * k), int(260 * k), int(10 * k))))
            if t.get('ctx'):
                ev.append('Dialogue: 5,%s,%s,Tag,,0,0,0,,{\\pos(%d,%d)\\fad(120,70)}%s' % (a, b, int(72 * k), y - int(235 * k), esc(t['ctx']).upper()))
            ev.append('Dialogue: 5,%s,%s,Hud,,0,0,0,,{\\1c&H00141414&\\alpha&H30&}FROM RAW FOOTAGE  ·  FINISHED VIDEO' % (a, b))
        else:
            ev.append('Dialogue: 2,%s,%s,Pop,,0,0,0,,{\\pos(%d,%d)\\fad(30,70)\\fscx60\\fscy60\\t(0,130,\\fscx108\\fscy108)\\t(130,210,\\fscx100\\fscy100)}%s'
                      % (T(t['start']), T(t['end']), cw // 2, int(ch * .42), esc(t['label'])))
    ev += ['Dialogue: 6,%s,%s,Fx,,0,0,0,,{\\pos(0,0)\\1c%s\\fad(0,140)\\p1}%s{\\p0}' % (T(f['start']), T(f['end']), _bgr(accent), rect(0, 0, int(14 * k), ch)) for f in flashes]
    path.write_text(head + '\n'.join(ev) + '\n')


def _render(src, out, keep, zoomed, has_audio, ass, progress=lambda f: None, grade='', target=-14.0, canvas=(W, H)):
    """Low-memory render: encode each kept segment on its own, join them, then burn overlays.
    (One giant filter graph held every segment's 1080x1920 frames at once and got OOM-killed.)"""
    work = out.parent
    W, H = canvas
    zw, zh = int(round(W * ZOOM / 2) * 2), int(round(H * ZOOM / 2) * 2)
    total = max(sum(b - a for a, b in keep), .1)
    done = 0.0
    base = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    venc = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-threads', '2']
    aenc = ['-c:a', 'aac', '-b:a', '160k', '-ar', '48000']
    segs = []
    for i, (a, b) in enumerate(keep):
        seg = work / ('seg%03d.mp4' % i)
        f = ('[0:v:0]fps=%d,setsar=1,split=2[bgsrc][fgsrc];'
             '[bgsrc]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=12:2,eq=brightness=-0.12,scale=%d:%d[bg];'
             '[fgsrc]scale=%d:%d:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2[fg];'
             '[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1%s%s[vout]') % (
            FPS, W, H, W, H, (',scale=%d:%d,crop=%d:%d' % (zw, zh, W, H)) if i in zoomed else '', (',' + grade) if grade else '')
        cmd = base + ['-ss', '%.4f' % a, '-t', '%.4f' % (b - a), '-i', str(src), '-filter_complex', f,
                      '-filter_complex_threads', '1', '-map', '[vout]'] + venc
        if has_audio:
            cmd += ['-map', '0:a:0', '-af', 'aresample=async=1:first_pts=0,afade=t=in:d=0.015,afade=t=out:st=%.4f:d=0.015' % max(0, b - a - .015)] + aenc
        r = subprocess.run(cmd + [str(seg)], capture_output=True, timeout=3600)
        if r.returncode:
            raise RuntimeError(r.stderr.decode(errors='replace')[-1200:] or 'ffmpeg exited %d (likely out of memory)' % r.returncode)
        segs.append(seg)
        done += b - a
        progress(min(1, done / total) * (.7 if ass else 1))
    lst = work / 'segs.txt'
    lst.write_text(''.join("file '%s'\n" % s_.name for s_ in segs))
    tmp = out.with_name('cut.mp4')
    joined = tmp if not ass else work / 'joined.mp4'
    _sh(*base, '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', '-movflags', '+faststart', str(joined))
    for s_ in segs:
        s_.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    if ass:
        esc_ = lambda x: str(x).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        vf = "ass='%s':fontsdir='%s'" % (esc_(ass), esc_(FONTS))
        cmd = base + ['-i', str(joined), '-vf', vf] + venc + ['-c:a', 'copy', '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(tmp)]
        err = work / 'ffmpeg.log'
        try:
            with err.open('wb') as log:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
                for line in proc.stdout:
                    if line.startswith('out_time_us=') and line[12:].strip().isdigit():
                        progress(.7 + .3 * min(1, int(line[12:]) / 1e6 / total))
                if proc.wait(timeout=3600):
                    raise RuntimeError(err.read_text(errors='replace')[-1200:] or 'ffmpeg exited (likely out of memory)')
        finally:
            err.unlink(missing_ok=True)
            joined.unlink(missing_ok=True)
    if has_audio:
        _normalise(tmp, out, target)
        tmp.unlink()
    else:
        tmp.replace(out)


def _normalise(src, out, target=-14.0):
    """Measure integrated loudness, then apply one gain with a peak limiter (video copied)."""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(src), '-map', '0:a:0', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, timeout=900)
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', r.stderr.decode(errors='replace'))
    level = float(m[-1]) if m else None
    gain = 0.0 if level is None or level < -60 else max(-12.0, min(18.0, target - level))
    _sh('ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(src), '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
        '-af', 'volume=%.2fdB,alimiter=limit=0.84:level=false' % gain, '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
        '-movflags', '+faststart', str(out))


# ---------------------------------------------------------------- the job

def _repace(keep, words, shot):
    """Re-time the cut to the reference: split long pieces into ~`shot`-second shots at word boundaries."""
    target = max(.9, min(6.0, shot))
    starts = sorted(w['s'] for w in words)
    out = []
    for a, b in keep:
        n = int(round((b - a) / target))
        if n < 2:
            out.append((a, b)); continue
        pts = [a]
        for k in range(1, n):
            ideal = a + (b - a) * k / n
            near = [t for t in starts if abs(t - ideal) <= min(.5, target / 3) and t - pts[-1] >= .6 and b - t >= .6]
            pts.append(min(near, key=lambda t: abs(t - ideal)) if near else ideal)
        pts.append(b)
        out += [(x, y) for x, y in zip(pts, pts[1:]) if y - x > .05]
    return out


def _ref_job(rid, src, filename):
    ref = REFS[rid]
    try:
        with WORKER:
            ref['stage'] = 'Checking the reference'
            info = editor.probe(src, enforce_limit=False)
            ref['stage'] = 'Studying cuts, flashes, colour and loudness'
            proxy = src.with_name('ref-proxy.mp4')
            _sh('ffmpeg', '-v', 'error', '-y', '-t', '120', '-i', str(src), '-map', '0:v:0', '-map', '0:a:0?',
                '-vf', 'scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2,fps=24',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', str(proxy))
            style = quick_refstyle.analyze(src, info['duration'], info['audio'])
            style['canvas'] = [info['width'], info['height']]
            if info['audio']:
                ref['stage'] = 'Listening to the reference'
                words, _ = _transcribe(src)
                if len(words) > 5:
                    span = max(words[-1]['e'] - words[0]['s'], 1)
                    style['wps'] = round(len(words) / span, 2)
            ref.update(status='done', stage='Reference studied', style=style, summary=quick_refstyle.describe(style), proxy=str(proxy), file=filename)
    except Exception as exc:
        ref.update(status='failed', stage='Failed', error=str(exc)[-400:] or 'Could not analyse the reference.')
    finally:
        for f in src.parent.glob('source*'):
            f.unlink(missing_ok=True)


def _plural(n, word):
    return '%d %s%s' % (n, word, '' if n == 1 else 's')


def _job(jid, src, filename, ref_id=None):
    """Edit one upload, publishing every agent step to JOBS[jid]['steps'] the moment it is decided."""
    job = JOBS[jid]
    name = 'u-' + jid[:12]
    out = RECIPES / name
    med = out / 'media'
    r2 = lambda x: round(x, 2)
    recipe = {}
    canvas = (W, H)

    def stage(msg, p, **extra):
        with LOCK:
            job.update(stage=msg, progress=p, **extra)

    def publish(phase, lane, title, did, show, place):
        step = {'id': 'step-%02d' % (len(recipe['steps']) + 1), 'phase': phase, 'lane': lane, 'title': title, 'did': did, 'place': place}
        if show:
            step['show'] = show
        recipe['steps'].append(step)
        save()
        with LOCK:
            job['steps'] = list(recipe['steps'])

    def save():
        tmp = out / 'recipe.tmp'
        tmp.write_text(json.dumps(recipe, indent=1))
        tmp.replace(out / 'recipe.json')

    style, ref = None, None
    try:
        if ref_id:
            ref = REFS.get(ref_id)
            while ref and ref['status'] == 'working':
                stage(ref.get('stage') or 'Studying the reference', .01)
                time.sleep(1)
            if ref and ref['status'] == 'done':
                style = ref['style']
                if style.get('canvas') and style['canvas'][0] > style['canvas'][1]:
                    canvas = (1920, 1080)
            elif ref:
                raise ValueError('The reference video could not be studied: ' + (ref.get('error') or 'unknown error'))
        with WORKER:
            (med / 'stills').mkdir(parents=True, exist_ok=True)
            stage('Checking the video', .03)
            info = editor.probe(src, enforce_limit=False)
            dur = info['duration']
            if dur > 600:
                raise ValueError('Use a video up to 10 minutes long.')
            stage('Making a vertical preview of the raw take', .06)
            _sh('ffmpeg', '-v', 'error', '-y', '-i', str(src), '-map', '0:v:0', '-map', '0:a:0?',
                '-vf', 'scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,fps=30',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart', str(med / 'raw-proxy.mp4'))
            stem = Path(filename).stem[:60] or 'your video'
            recipe.update({
                'format': 'frame-recipe/1', 'name': name, 'title': 'FRAME cut — ' + stem, 'duration': r2(dur), 'canvas': list(canvas),
                'upload': True, 'live': True, 'notes': [],
                'provenance': 'Edited on upload by quick_autoedit.py: lines, retakes and ums from the transcript, pauses from the waveform, rendered with FFmpeg.',
                'intro': {'eyebrow': 'Your upload', 'headline': 'Your raw take, edited by the swarm.'},
                'rawClip': {'path': 'media/raw-proxy.mp4', 'file': filename, 'meta': '%s raw take' % _mmss(dur), 'label': 'Raw footage · ' + filename, 'duration': r2(dur), 'at': 0},
                'lanes': [['gfx', 'MOTION', 'var(--v2)'], ['ttl', 'TITLES', 'var(--t1)'], ['v1', 'A-ROLL', 'var(--v1)'], ['t1', 'CAPTIONS', '#f2f2f5'],
                          ['fx', 'FX', 'var(--fx)'], ['a1', 'VOICE', 'var(--a1)'], ['a2', 'MIX', 'var(--a2)']],
                'steps': [],
            })
            save()
            stage('Listening to the raw take', .1, preview=True, recipe=name)
            if style:
                shutil.copy(ref['proxy'], med / 'ref-proxy.mp4')
                publish('Reference', 'bcoll', 'Study the reference video', 'Style learned from %s: %s' % (ref.get('file', 'the reference'), ref['summary']),
                        {'kind': 'video', 'path': 'media/ref-proxy.mp4', 'at': 0}, [])

            words, note, silences = [], None, []
            if info['audio']:
                stage('Transcribing every word', .12)
                words, note = _transcribe(src)
                stage('Measuring pauses and dead air', .45)
                silences = editor.detect_silence(src)
            else:
                note = 'No audio track: kept the whole take, no captions.'
            if note:
                recipe['notes'] = [note]
            (out / 'transcript.txt').write_text('%s — raw take, %s\n\n%s\n' % (filename, _mmss(dur), ' '.join(w['w'] for w in words) or '(no transcript)'))
            if words:
                publish('Transcribe', 'caps', 'Transcribe the raw take', '%d words with timings from %s (%s).' % (len(words), filename, _mmss(dur)), {'kind': 'text', 'path': 'transcript.txt'}, [])
            else:
                publish('Analyse', 'caps', 'Read the raw take', '%s, %s. %s' % (filename, _mmss(dur), note or ''), {'kind': 'video', 'path': 'media/raw-proxy.mp4', 'at': 0}, [])

            stage('Choosing the strongest takes', .5)
            if words:
                keep, kept_lines, dropped = _choose(words, silences, dur)
            else:
                keep, kept_lines, dropped = _silence_only(silences, dur), [], {'retake': 0, 'filler': 0, 'um': 0}
            if style:
                keep = _repace(keep, words, style['shot'])
            final_len = sum(b - a for a, b in keep)
            recipe['duration'] = r2(final_len)
            first_words = {id(p['words'][0]) for p in kept_lines}
            edited_words = []
            for w in words:
                if _norm(w['w']) in UMS:
                    continue
                s, e = _map_time(w['s'], keep), _map_time(w['e'], keep)
                if s is not None and e is not None and e > s:
                    edited_words.append({'w': w['w'], 's': s, 'e': e, 'src': w['s'], 'first': id(w) in first_words})
            cut_at, t = [], 0
            for a, b in keep[:-1]:
                t += b - a; cut_at.append(t)
            def src_at(t):                       # edited time -> source time, for previews
                for a, b in keep:
                    if t <= b - a:
                        return a + max(t, 0)
                    t -= b - a
                return keep[-1][1]
            raw_show = lambda t: {'kind': 'video', 'path': 'media/raw-proxy.mp4', 'at': round(src_at(t), 2)}

            pos, aroll = 0, []
            for a, b in keep:
                said = [w['w'] for w in words if a - .05 <= w['s'] < b - .05 and _norm(w['w']) not in UMS][:5]
                aroll.append({'track': 'v1', 'label': 'Take %.1f–%.1fs%s' % (a, b, (' · ' + ' '.join(said)) if said else ''), 'start': r2(pos), 'end': r2(pos + b - a)})
                pos += b - a
            why = []
            if dropped['retake']: why.append(_plural(dropped['retake'], 'retake'))
            if dropped['filler']: why.append(_plural(dropped['filler'], 'filler line'))
            if dropped.get('um'): why.append(_plural(dropped['um'], 'um/uh'))
            why.append('dead air')
            publish('Cut', 'razor', 'Cut to the strongest lines' if words else 'Cut the dead air',
                    'Kept %s, %.1f s of %.0f s. Dropped %s (%.1f s).' % (_plural(len(keep), 'piece'), final_len, dur,
                                                                        ', '.join(why[:-1]) + (' and ' if len(why) > 1 else '') + why[-1], dur - final_len),
                    raw_show(final_len / 2), aroll)
            if info['audio']:
                publish('Voice', 'mix', 'Lay the voice under the cut', 'Voice follows every A-roll piece, 15 ms fades on each cut.', raw_show(aroll[-1]['start'] + .2), [dict(x, track='a1', label='Voice') for x in aroll])

            chunk = 3
            if style and style.get('wps'):
                chunk = 2 if style['wps'] > 3.3 else 4 if style['wps'] < 2.0 else 3
            if style and style.get('editorial'):
                chunk = 4
            caps, cur = [], []
            def flush():
                if cur:
                    caps.append({'track': 't1', 'label': _join(cur), 'start': r2(cur[0]['s']), 'end': r2(max(cur[-1]['e'], cur[0]['s'] + .2))})
            for w in edited_words:
                if cur and (len(cur) == chunk or any(cur[-1]['s'] < c <= w['s'] for c in cut_at) or w['s'] - cur[-1]['e'] > .6):
                    flush(); cur = []
                cur.append(w)
            flush()
            for a_, b_ in zip(caps, caps[1:]):
                a_['end'] = min(a_['end'], b_['start'])
            if caps:
                publish('Captions', 'caps', 'Captions, %d words at a time' % chunk, '%d caption clips, never across a cut.' % len(caps), raw_show(caps[len(caps) // 2]['start']), caps)
            ed = bool(style and style.get('editorial'))
            titles = _titles(edited_words, final_len, gap=max(2.2, min(6.0, 30 / max(style['cards']['pm'], 1))) if ed else None, ctx=ed)
            if ed:
                for i, t_ in enumerate(titles):
                    if i % 2 == 0:
                        t_['card'] = True
                        nxt = titles[i + 1]['start'] - .05 if i + 1 < len(titles) else final_len
                        t_['end'] = round(min(max(t_['end'], t_['start'] + 1.0), nxt, final_len), 2)
                        t_['label'] = t_['label'].rstrip('.') + '.'
            if titles:
                publish('Titles', 'gfx', 'Title cards + kinetic words' if ed else 'Kinetic title hits', ('%d full-screen cards and %d pop-up words in the reference style: ' % (sum(1 for t_ in titles if t_.get('card')), sum(1 for t_ in titles if not t_.get('card')))) if ed else 'Big type on the key words: ' + ', '.join(t_['label'].title() for t_ in titles[:4]) + '.', raw_show(titles[0]['start']), titles)
            zoomed = {i for i in range(1, len(keep), 2)} if (not style or style['punch']) else set()
            punches = [{'track': 'gfx', 'label': 'Punch-in %d%%' % round(ZOOM * 100), 'start': x['start'], 'end': x['end']} for i, x in enumerate(aroll) if i in zoomed]
            if punches:
                publish('Motion', 'gfx', 'Punch-ins on the jump cuts', '%d alternate pieces pushed in to %d%% so cuts feel deliberate.' % (len(punches), round(ZOOM * 100)), raw_show(punches[0]['start'] + .2), punches)
            portrait = info['height'] >= info['width'] * 1.7
            ratio = '16:9' if canvas[0] > canvas[1] else '9:16'
            publish('Look', 'grade', 'Reframe to ' + ratio, ('%d×%d source fitted to %d×%d like the reference.' if canvas[0] > canvas[1] else ('%d×%d portrait source fitted to %d×%d.' if portrait else '%d×%d source over a blurred 9:16 fill (%d×%d).')) % (info['width'], info['height'], canvas[0], canvas[1]), raw_show(final_len * .5), [])
            flashes, last = [], -9
            for i, c in enumerate(cut_at):
                if style and style['flash']:
                    ok = c - last >= 1.0
                else:
                    ok = not style and keep[i + 1][0] - keep[i][1] >= 1.2 and c - last >= 2.5
                if ok:
                    flashes.append({'track': 'fx', 'label': 'Flash', 'start': r2(c), 'end': r2(c + .14)}); last = c
            if flashes:
                publish('Look', 'grade', 'White-flash transitions', '%d flashes where material was cut out.' % len(flashes), raw_show(flashes[0]['start']), flashes)
            target = max(-20.0, min(-9.0, style['lufs'])) if style and style.get('lufs') is not None else -14.0
            grade = ''
            if style and style.get('look'):
                grade = quick_refstyle.grade_filter(style['look'], quick_refstyle.look_of(src))
                if grade:
                    publish('Look', 'grade', 'Match the reference colour', 'Tone and saturation nudged toward the reference (%s).' % grade.replace('eq=', ''), raw_show(final_len * .3), [{'track': 'fx', 'label': 'Colour match', 'start': 0, 'end': r2(final_len)}])
            if info['audio']:
                publish('Mix', 'mix', 'Loudness to %d LUFS' % round(target), 'Normalised to the reference level with a peak limiter.' if style else 'Normalised for social playback with a peak limiter.', None, [{'track': 'a2', 'label': 'Loudness %d LUFS' % round(target), 'start': 0, 'end': r2(final_len)}])

            stage('Rendering the final cut', .6, render=0)
            ass = None
            if caps or titles or flashes or ed:
                ass = out / 'overlays.ass'
                _write_ass(ass, caps, titles, flashes, canvas=canvas, look=style if ed else None, final_len=final_len)
            _render(src, med / 'final.mp4', keep, zoomed, info['audio'], ass,
                    progress=lambda f: stage('Rendering the final cut · %d%%' % round(f * 100), .6 + .33 * f, render=round(f, 3)), grade=grade, target=target, canvas=canvas)
            stage('Checking the export', .95, render=1)
            final_len = editor.probe(med / 'final.mp4', enforce_limit=False)['duration']

            # For later replays, show frames of the finished cut instead of the raw take.
            def still(t, fname):
                _sh('ffmpeg', '-v', 'error', '-y', '-ss', '%.2f' % min(max(0, t), max(0, final_len - .1)), '-i', str(med / 'final.mp4'),
                    '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '3', str(med / 'stills' / fname))
                return 'media/stills/' + fname
            for st in recipe['steps']:
                if st['phase'] in ('Captions', 'Titles', 'Motion', 'Look') and st['place']:
                    p0 = st['place'][len(st['place']) // 2 if st['phase'] == 'Captions' else 0]
                    t0 = p0['start'] + (.03 if st['phase'] == 'Look' else min(.25, (p0['end'] - p0['start']) / 2))
                    st['show'] = {'kind': 'image', 'path': still(t0, st['id'] + '.jpg')}
            recipe['lanes'] = [l for l in recipe['lanes'] if any(p['track'] == l[0] for s_ in recipe['steps'] for p in s_['place'])] or recipe['lanes']
            recipe.update(final='media/final.mp4', duration=r2(final_len), live=False)
            recipe['intro']['body'] = 'FRAME went through %s of footage and cut it to %s. Launch the swarm to watch every edit land again.' % (_mmss(dur), _mmss(final_len))
            save()
            with LOCK:
                job.update(status='done', stage='Done', progress=1, render=1, recipe=name, notes=recipe['notes'], steps=list(recipe['steps']))
    except Exception as exc:
        shutil.rmtree(out, ignore_errors=True)
        with LOCK:
            job.update(status='failed', stage='Failed', preview=False, error=str(exc)[-600:])
    finally:
        shutil.rmtree(src.parent, ignore_errors=True)


def route(handler, app, method):
    path = urlparse(handler.path).path
    if not path.startswith('/api/autoedit'):
        return False
    m = re.fullmatch(r'/api/autoedit/([a-f0-9]{32})(/preview)?', path)
    if method == 'GET' and m:
        with LOCK:
            job = dict(JOBS.get(m[1]) or {})
        if m[2]:
            proxy = RECIPES / ('u-' + m[1][:12]) / 'media' / 'raw-proxy.mp4'
            if job.get('preview') and proxy.is_file():
                handler.media(proxy, 'video/mp4')
            else:
                handler.json(404, {'error': 'Preview not ready yet.'})
            return True
        handler.json(200 if job else 404, job or {'error': 'Job not found. The server may have restarted; upload again.'})
        return True
    mr = re.fullmatch(r'/api/autoedit/reference(?:/([a-f0-9]{32}))?', path)
    if method == 'GET' and mr and mr[1]:
        r = REFS.get(mr[1])
        handler.json(200 if r else 404, {k: v for k, v in (r or {'error': 'Reference not found.'}).items() if k != 'proxy'})
        return True
    is_ref = method == 'POST' and path == '/api/autoedit/reference'
    if method != 'POST' or (path != '/api/autoedit' and not is_ref):
        handler.json(404, {'error': 'Not found'}); return True
    try:
        length = int(handler.headers.get('Content-Length', '0'))
    except ValueError:
        length = 0
    if not 0 < length <= MAX_BYTES:
        handler.close_connection = True
        handler.json(413, {'error': 'Video must be between 1 byte and 700 MB.'}); return True
    jid = uuid.uuid4().hex
    folder = app.WORK / (('autoref-' if is_ref else 'autoedit-') + jid)
    folder.mkdir(parents=True)
    filename = Path(unquote(handler.headers.get('X-Filename', 'upload.mp4'))).name[:120] or 'upload.mp4'
    suffix = Path(filename).suffix.lower()
    src = folder / ('source' + (suffix if re.fullmatch(r'\.[a-z0-9]{1,5}', suffix) else '.mp4'))
    handler.connection.settimeout(300)
    try:
        with src.open('wb') as f:
            left = length
            while left:
                chunk = handler.rfile.read(min(1 << 20, left))
                if not chunk:
                    raise ValueError('Upload was interrupted. Please pick the video again.')
                f.write(chunk); left -= len(chunk)
        editor.probe(src, enforce_limit=False)
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        handler.close_connection = True
        handler.json(400, {'error': str(exc)[-400:]}); return True
    if is_ref:
        REFS[jid] = {'id': jid, 'status': 'working', 'stage': 'Queued', 'file': filename}
        threading.Thread(target=_ref_job, args=(jid, src, filename), daemon=True).start()
        handler.json(202, {'id': jid}); return True
    ref_id = handler.headers.get('X-Reference', '')
    ref_id = ref_id if re.fullmatch(r'[a-f0-9]{32}', ref_id) and ref_id in REFS else None
    with LOCK:
        JOBS[jid] = {'id': jid, 'status': 'working', 'stage': 'Queued', 'progress': 0, 'created': time.time(), 'file': filename, 'steps': [], 'reference': bool(ref_id)}
    threading.Thread(target=_job, args=(jid, src, filename, ref_id), daemon=True).start()
    handler.json(202, {'id': jid})
    return True


if __name__ == '__main__' and sys.argv[1:2] == ['--transcribe']:
    print(json.dumps(_transcribe_here(sys.argv[2])))
