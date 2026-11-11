"""Footage analysis and deterministic rendering. All times refer to the original."""
import json
import math
from fractions import Fraction
import re
import subprocess
import threading
from pathlib import Path

TRANSCRIBE_LOCK = threading.Lock()
MODEL = None


def run(args, timeout=1200):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1600:])
    return result.stdout


def probe(path, enforce_limit=True):
    try:
        data = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                               '-of', 'json', str(path)], timeout=30))
    except subprocess.TimeoutExpired:
        raise ValueError('Frame could not inspect this video within 30 seconds. Try exporting a fresh MP4 and importing it again.') from None
    except (RuntimeError, json.JSONDecodeError):
        raise ValueError('Frame could not read this video. Try exporting it as an H.264/AAC MP4 and importing it again.') from None
    if not isinstance(data, dict) or not isinstance(data.get('streams'), list):
        raise ValueError('Frame could not read this video’s metadata. Try exporting a fresh MP4 and importing it again.')
    video = next((s for s in data['streams'] if isinstance(s, dict) and s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('Please upload a video file.')
    metadata = data.get('format') or {}
    try:
        total = float(metadata.get('duration', video.get('duration', 0)))
        width, height = int(video['width']), int(video['height'])
        if width <= 0 or height <= 0:
            raise ValueError
        sar = video.get('sample_aspect_ratio')
        if sar not in (None, '', 'N/A', '0:1'):
            ratio = float(Fraction(str(sar).replace(':', '/')))
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError
            width = max(1, round(width * ratio))
        # Phone footage can store landscape pixels with a portrait display matrix.
        # FFmpeg/browser playback applies it, so report the displayed frame shape.
        rotation = next((item.get('rotation') for item in video.get('side_data_list', [])
                         if isinstance(item, dict) and item.get('rotation') is not None),
                        (video.get('tags') or {}).get('rotate', 0))
        rotation = float(rotation)
        if not math.isfinite(rotation):
            raise ValueError
        rotation %= 360
        if math.isclose(rotation, 90, abs_tol=.01) or math.isclose(rotation, 270, abs_tol=.01):
            width, height = height, width
    except (AttributeError, TypeError, ValueError, KeyError, ZeroDivisionError, OverflowError):
        raise ValueError('Frame could not read this video’s duration or dimensions. Try exporting a fresh MP4 and importing it again.') from None
    if not math.isfinite(total) or total <= 0 or (enforce_limit and total > 300.1):
        raise ValueError('Use a video between 0 and 300 seconds long.')
    return {'duration': total, 'audio': any(isinstance(s, dict) and s.get('codec_type') == 'audio' for s in data['streams']),
            'width': width, 'height': height}


def detect_silence(path):
    """Find sustained low-energy spans from a decoded waveform.

    A short-time RMS envelope adapts its threshold to each recording's noise
    floor and level. Hysteresis and gap merging keep consonant gaps/breaths
    from fragmenting the result. Returned regions are candidates; callers
    retain handles around each boundary before making cuts.
    """
    result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(path),
                             '-vn', '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                            capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError((result.stderr or b'Audio decode failed')[-1200:].decode(errors='replace'))
    import array
    samples = array.array('h')
    samples.frombytes(result.stdout[:len(result.stdout) - len(result.stdout) % 2])
    if not samples:
        return []

    # 20 ms RMS frames preserve useful boundary detail without a DSP dependency.
    rate, hop = 8000, 160
    levels = []
    for offset in range(0, len(samples), hop):
        frame = samples[offset:offset + hop]
        if not frame:
            break
        rms = math.sqrt(sum(value * value for value in frame) / len(frame))
        levels.append(20 * math.log10(max(rms, 1) / 32768))
    ordered = sorted(levels)
    noise = ordered[int((len(ordered) - 1) * .10)]
    typical = ordered[int((len(ordered) - 1) * .85)]
    # A flat or near-flat recording has no valley to cut. This also prevents
    # the adaptive threshold from classifying a steady tone as silence.
    if typical - noise < 12:
        return []
    # Put the gate above the lower-tail floor but at least 16 dB below active
    # audio. Never push it above the measured waveform by enforcing a floor.
    gate = min(noise + 8, typical - 16)
    release = gate + 4

    regions, start = [], None
    for i, level in enumerate(levels + [release + 1]):
        t = i * hop / rate
        if start is None and level <= gate:
            start = t
        elif start is not None and level > release:
            if t - start >= .32:
                regions.append([max(0, start), t])
            start = None

    # Bridge tiny waveform dips inside a phrase; keep clear valleys separate.
    merged = []
    for a, b in regions:
        if merged and a - merged[-1][1] <= .12:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def transcribe(path):
    global MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Speech understanding needs faster-whisper. Run: python3 -m pip install -r requirements.txt') from exc
    with TRANSCRIBE_LOCK:
        if MODEL is None:
            # The existing cached English model avoids an unexpected model download.
            MODEL = WhisperModel('small.en', device='cpu', compute_type='int8',
                                 cpu_threads=4, local_files_only=True)
        segments, info = MODEL.transcribe(str(path), word_timestamps=True,
                                           vad_filter=True, beam_size=3)
        return [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip(),
                 'words': [{'start': round(w.start, 3), 'end': round(w.end, 3), 'text': w.word}
                           for w in (s.words or [])]} for s in segments]


def storyboard(path, folder, total):
    from PIL import Image, ImageDraw
    count = min(12, max(1, math.ceil(total / 2)))
    times = [min(total - .04, (i + .5) * total / count) for i in range(count)]
    sheet = Image.new('RGB', (4 * 320, math.ceil(count / 4) * 208), '#11151c')
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(times):
        frame = folder / ('frame-%02d.jpg' % i)
        run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(max(0, t)), '-i', str(path),
             '-frames:v', '1', '-vf', 'scale=320:180:force_original_aspect_ratio=decrease', str(frame)])
        with Image.open(frame) as im:
            x, y = (i % 4) * 320, (i // 4) * 208
            sheet.paste(im, (x + (320 - im.width) // 2, y + (180 - im.height) // 2))
            draw.text((x + 10, y + 185), 'SOURCE %.2fs' % t, fill='white')
    dest = folder / 'storyboard.jpg'
    sheet.save(dest, quality=85)
    return [round(t, 2) for t in times]


def analyze(folder, stage):
    cache = folder / 'analysis.json'
    if cache.exists():
        return json.loads(cache.read_text())
    inp = folder / 'input.mp4'
    stage('Checking your video')
    info = probe(inp)
    stage('Sampling the footage')
    info['frame_times'] = storyboard(inp, folder, info['duration'])
    info['transcript'], info['silences'], info['warnings'] = [], [], []
    if info['audio']:
        stage('Listening and transcribing — first pass may take a minute')
        try:
            info['transcript'] = transcribe(inp)
        except Exception as exc:
            info['warnings'].append('Transcription unavailable: ' + str(exc)[-350:])
        stage('Measuring the pauses')
        info['silences'] = detect_silence(inp)
    else:
        info['warnings'].append('This clip has no audio track. Decisions use sampled frames and timestamps.')
    cache.write_text(json.dumps(info))
    return info


def validate_segments(segments, total):
    if not isinstance(segments, list) or not 1 <= len(segments) <= 48:
        raise ValueError('The edit must keep between 1 and 48 sections.')
    clean = []
    for segment in segments:
        a, b = segment['start'], segment['end']
        if isinstance(a, bool) or isinstance(b, bool):
            raise ValueError('Invalid cut times.')
        a, b = float(a), float(b)
        if not all(math.isfinite(v) for v in (a, b)) or a < 0 or b > total + .08 or b - a < .12:
            raise ValueError('A planned cut falls outside the footage or is too short.')
        clean.append([round(a, 4), round(min(b, total), 4)])
    # Reordering is allowed, accidental repeated footage is not.
    ordered = sorted(clean)
    if any(b > c + .01 for (_, b), (c, _) in zip(ordered, ordered[1:])):
        raise ValueError('The planned sections overlap. Ask for a clearer cut.')
    return clean


def trim_pauses(keep, regions):
    result = []
    for start, end in keep:
        cursor = start
        for a, b in regions:
            if b - a < .55:
                continue
            # Keep a short room tone/breath handle on both sides of the valley.
            a, b = max(start, a + .12), min(end, b - .14)
            if b - a < .28 or b <= cursor:
                continue
            if a - cursor >= .12:
                result.append([cursor, a])
            cursor = max(cursor, b)
        if end - cursor >= .12:
            result.append([cursor, end])
    if not result:
        raise ValueError('Removing every pause would leave no usable footage. Try a different request.')
    if len(result) > 48:
        raise ValueError('That creates more than 48 cuts. Please choose a shorter section first.')
    return result


def protect_spoken_audio(regions, transcript, lead=.18, tail=.20):
    """Drop pause candidates whose proposed cut core overlaps timed speech."""
    speech = []
    for segment in transcript or []:
        words = segment.get('words') or []
        if words:
            speech.extend((float(word['start']), float(word['end'])) for word in words)
        elif segment.get('start') is not None and segment.get('end') is not None:
            speech.append((float(segment['start']), float(segment['end'])))
    if not speech:
        return list(regions)
    return [region for region in regions
            if not any(start < region[1] - tail and end > region[0] + lead
                       for start, end in speech)]


def render(source, folder, keep, audio, stage):
    parts = []
    for i, (a, b) in enumerate(keep):
        stage('Rendering section %s of %s' % (i + 1, len(keep)))
        dest = folder / ('part%03d.mp4' % i)
        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-ss', str(a), '-i', str(source),
               '-t', str(b - a), '-map', '0:v:0', '-map', '0:a:0?', '-vf',
               'scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1', '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '21', '-pix_fmt', 'yuv420p', '-r', '30', '-threads', '4']
        if audio:
            cmd += ['-af', 'asetpts=PTS-STARTPTS', '-c:a', 'aac', '-ar', '48000', '-ac', '2']
        run(cmd + ['-movflags', '+faststart', str(dest)])
        parts.append(dest)
    listing = folder / 'clips.txt'
    listing.write_text(''.join("file '%s'\n" % p.name for p in parts))
    output = folder / 'edited.mp4'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
         '-c', 'copy', '-movflags', '+faststart', str(output)])
    # Concat can shift video by AAC encoder priming (typically 1,024 samples).
    # Normalize the common stream origin so preview time zero and export time zero agree.
    streams = json.loads(run(['ffprobe','-v','error','-show_entries','stream=codec_type,start_time',
                              '-of','json',str(output)]))['streams']
    video_start = float(next(s for s in streams if s['codec_type']=='video').get('start_time',0))
    if abs(video_start)>1e-6:
        normalized=folder/'normalized.mp4'
        run(['ffmpeg','-y','-loglevel','error','-itsoffset',str(-video_start),'-i',str(output),
             '-map','0','-c','copy','-avoid_negative_ts','disabled','-movflags','+faststart',str(normalized)])
        normalized.replace(output)
    stage('Checking the exported video')
    measured = probe(output, enforce_limit=False)['duration']
    if abs(measured - sum(b - a for a, b in keep)) > max(.35, .06 * len(keep)):
        raise RuntimeError('Export length did not match the planned cut. Original footage is safe.')
    # Intermediate renders can be recreated from the saved plan.
    for p in parts:
        p.unlink()
    return measured


def render_timeline(source, folder, keep, audio, stage, positions=None):
    """Frame-aligned timeline, one encode: no accumulated AAC priming per cut."""
    fps = 30
    count = len(keep)
    expected_frames = sum(round(b*fps)-round(a*fps) for a,b in keep)
    duration = expected_frames/fps
    if positions is None or all(not x and not y for x,y in positions):
        return _render_selected(source, folder, keep, audio, stage, fps, duration)
    video_outputs = ''.join('[vs%d]' % i for i in range(count))
    filters = ['[0:v:0]fps=30,scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1,split=%d%s' % (count,video_outputs)]
    if audio:
        # Align audio to source time and fill any missing head/tail before slicing.
        filters.append('[0:a:0]aresample=async=1:first_pts=0,apad=whole_dur=%.9f,asplit=%d%s' %
                       (max(b for a,b in keep),count,''.join('[as%d]' % i for i in range(count))))
    if positions is None:positions=[(0,0)]*count
    if len(positions)!=count:raise ValueError('One position is required for each clip.')
    for i,(a,b) in enumerate(keep):
        x,y=positions[i]
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and abs(v)<=.5 for v in (x,y)):
            raise ValueError('Invalid clip position.')
        shift=(',pad=iw*3:ih*3:iw:ih:color=black,crop=iw/3:ih/3:iw/3*(1-%.9f):ih/3*(1-%.9f)'%(x,y)) if x or y else ''
        filters.append('[vs%d]trim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS%s[v%d]' % (i,round(a*fps),round(b*fps),shift,i))
        if audio:
            filters.append('[as%d]atrim=start=%.9f:end=%.9f,asetpts=PTS-STARTPTS,apad=whole_dur=%.9f,atrim=duration=%.9f[a%d]' % (i,a,b,b-a,b-a,i))
    inputs = ''.join('[v%d][a%d]' % (i,i) if audio else '[v%d]' % i for i in range(count))
    filters.append('%sconcat=n=%d:v=1:a=%d[vout]%s' % (inputs,count,int(audio),'[aout]' if audio else ''))
    script = folder/'timeline-filter.txt'
    script.write_text(';\n'.join(filters))
    stage('Rendering timeline in one synchronized encode')
    cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(source),'-filter_complex_threads','2',
         '-filter_complex',script.read_text(),'-map','[vout]']
    if audio:cmd+=['-map','[aout]','-c:a','aac','-ar','48000','-ac','2']
    cmd+=['-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-r','30','-threads','4',
          '-t','%.9f'%duration,'-movflags','+faststart',str(folder/'edited.mp4')]
    run(cmd)
    measured=probe(folder/'edited.mp4',enforce_limit=False)['duration']
    if abs(measured-duration) > .05:
        raise RuntimeError('Export does not match timeline within 50 ms.')
    return measured


def _render_selected(source, folder, keep, audio, stage, fps, duration):
    """Many cuts without buffering: one select pass for video, sample-exact atrim for audio.

    split=N buffers decoded frames for every later branch, which grows with cut count and
    resolution. select keeps only wanted frame numbers in a single streaming pass.
    """
    frames = [(round(a*fps), round(b*fps)) for a,b in keep]
    picks = '+'.join('between(n,%d,%d)' % (fa, fb-1) for fa,fb in frames if fb > fa)
    filters = ["[0:v:0]fps=30,scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1,select='%s',setpts=N/(30*TB)[vout]" % picks]
    if audio:
        count = len(keep)
        filters.append('[0:a:0]aresample=async=1:first_pts=0,apad=whole_dur=%.9f,asplit=%d%s' %
                       (max(b for a,b in keep),count,''.join('[as%d]' % i for i in range(count))))
        for i,(fa,fb) in enumerate(frames):
            a,b = fa/fps, fb/fps
            filters.append('[as%d]atrim=start=%.9f:end=%.9f,asetpts=PTS-STARTPTS,apad=whole_dur=%.9f,atrim=duration=%.9f[a%d]' % (i,a,b,b-a,b-a,i))
        filters.append('%sconcat=n=%d:v=0:a=1[aout]' % (''.join('[a%d]' % i for i in range(count)), count))
    script = folder/'timeline-filter.txt'
    script.write_text(';\n'.join(filters))
    stage('Rendering timeline in one synchronized encode')
    cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(source),'-filter_complex_threads','2',
         '-filter_complex',script.read_text(),'-map','[vout]']
    if audio:cmd+=['-map','[aout]','-c:a','aac','-ar','48000','-ac','2']
    cmd+=['-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-r','30','-threads','4',
          '-t','%.9f'%duration,'-movflags','+faststart',str(folder/'edited.mp4')]
    run(cmd)
    measured=probe(folder/'edited.mp4',enforce_limit=False)['duration']
    if abs(measured-duration) > .05:
        raise RuntimeError('Export does not match timeline within 50 ms.')
    return measured
