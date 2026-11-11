/* FRAME bridge: runs the Swarmcut editor against the FRAME service.
 *
 * - Loads the project named by ?project=<id> (source video, word timings, saved editor state).
 * - Saves every edit back to FRAME as a versioned timeline revision (sync_editor_state).
 * - Replaces Swarmcut's built-in "one click" taste with the creator's saved style:
 *   the server compiles the style into a deterministic plan, and the agent cursors
 *   perform those exact ops live. Pause stops them; manual edits keep working.
 * - Exports through FRAME's FFmpeg renderer.
 */
(function () {
  'use strict';
  const PID = new URLSearchParams(location.search).get('project');
  const ID_RE = /^[a-f0-9]{32}$/;

  async function api(method, path, body, raw) {
    const opts = { method: method, headers: {} };
    if (raw) { opts.body = raw.body; opts.headers = raw.headers; }
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    let j = {};
    try { j = await r.json(); } catch (e) {}
    if (!r.ok) { const err = new Error(j.error || ('HTTP ' + r.status)); err.status = r.status; throw err; }
    return j;
  }

  // Each plan lane is performed by Swarmcut's existing agent cursors.
  const LANE_AGENTS = { razor: ['razor-01', 'razor-02'], caps: ['caps-01', 'caps-02'], grade: ['grade-01', 'grade-02'], frame: ['grade-02'], mix: ['mix-01'], gfx: ['gfx-01'] };
  const LANE_AREA = { razor: 'timeline', caps: 'captions', grade: 'color', frame: 'program', mix: 'mix', gfx: 'sfx' };
  const MAX_SECTIONS = 240;

  Object.assign(ROLE_COPY, {
    razor: 'Cuts: pauses and retakes, as your style sets them',
    caps: 'Captions in your style',
    bcoll: 'Your images on the words you tag',
    grade: 'Color from your style',
    gfx: 'Brand overlays from your style',
    mix: 'Voice and music levels from your style'
  });

  function srcClipsFromDoc(doc) {
    let t = 0;
    const clips = doc.clips.map(function (c, i) {
      const clip = { id: 'c' + (i + 1), tr: 'v1', m: 'src', in: c.start, out: c.end, start: t };
      t += c.end - c.start;
      return clip;
    });
    const n = clips.length;
    clips.push({ id: 'c' + (n + 1), tr: 'fx', start: 0, dur: Math.max(1, t) });
    clips.push({ id: 'c' + (n + 2), tr: 'a2', m: null, in: 0, start: 0, dur: Math.max(1, t) });
    return { clips: clips, nid: n + 3 };
  }

  function gradeToStudio(g, muted) {
    if (muted) return { brightness: 0, contrast: 1, saturation: 1 };
    const L = g.look ? g.lookAmt / 100 : 0;
    return {
      brightness: +clamp((Math.pow(2, g.expo / 100) - 1) * 0.3, -0.3, 0.3).toFixed(4),
      contrast: +clamp(1 + g.con / 200 + L * 0.06, 0.5, 2).toFixed(4),
      saturation: +clamp(1 + g.sat / 100 + L * 0.1, 0, 2).toFixed(4)
    };
  }
  function studioToGrade(look) {
    const o = {};
    if (look.brightness != null) o.expo = Math.round(100 * Math.log2(1 + look.brightness / 0.3));
    if (look.contrast != null) o.con = Math.round((look.contrast - 1) * 200);
    if (look.saturation != null) o.sat = Math.round((look.saturation - 1) * 100);
    o.look = false;
    return o;
  }


  // ---- v3 template drawing for the live preview (canvas port of quick_v3's PIL drawing, 1080×1920 space) ----
  const V3_LIME = '#E2FD56';
  const V3_FONT = '-apple-system, "SF Pro Display", BlinkMacSystemFont, Inter, system-ui, sans-serif';
  function v3Ease(x) { x = Math.min(1, Math.max(0, x)); return 1 - Math.pow(1 - x, 3); }
  // Draw rows [sy0, sy0+dh) of a zoomed, cover-fitted video frame (spaceW×spaceH) into canvas rows [dy0, dy0+dh).
  function v3Frame(ctx, vid, z, cx, cy, dy0, dh, sy0, spaceW, spaceH) {
    spaceW = spaceW || 1080; spaceH = spaceH || 1920;
    const vw = vid.videoWidth, vh = vid.videoHeight, s = Math.max(spaceW / vw, spaceH / vh);
    const ox = (vw * s - spaceW) / 2, oy = (vh * s - spaceH) / 2;
    z = Math.max(1, z);
    const cw = spaceW / z, ch = spaceH / z;
    const x0 = Math.min(Math.max(0, cx - cw / 2), spaceW - cw), y0 = Math.min(Math.max(0, cy - ch / 2), spaceH - ch);
    const Y0 = y0 + sy0 / z, Y1 = y0 + (sy0 + dh) / z;
    ctx.drawImage(vid, (x0 + ox) / s, (Y0 + oy) / s, cw / s, (Y1 - Y0) / s, 0, dy0, 1080, dh);
  }
  function v3ScreenTime(seg, t) {   // same as quick_v3.screen_time
    const pts = [[seg.t0, seg.media_in || 0]].concat((seg.rows || []).filter(function (r) { return r.media_t != null && r.t > seg.t0 && r.t < (seg.t1 != null ? seg.t1 : 1e9); }).map(function (r) { return [r.t, r.media_t]; }));
    if (seg.media_out != null) pts.push([seg.t1, seg.media_out]);
    if (t <= pts[0][0]) return pts[0][1];
    for (let i = 1; i < pts.length; i++) if (t <= pts[i][0]) return pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (t - pts[i - 1][0]) / Math.max(1e-6, pts[i][0] - pts[i - 1][0]);
    return pts[pts.length - 1][1];
  }
  function v3Round(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function v3CardBg(ctx, h) {
    ctx.fillStyle = '#090a08'; ctx.fillRect(0, 0, 1080, h);
    const g = ctx.createRadialGradient(180, 420, 0, 180, 420, 1100);
    g.addColorStop(0, 'rgba(226,253,86,0.16)'); g.addColorStop(0.6, 'rgba(226,253,86,0.03)'); g.addColorStop(1, 'rgba(226,253,86,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, 1080, h);
  }
  function v3Label(ctx, text, cx, cy, k, op) {
    ctx.save(); ctx.globalAlpha = op; ctx.translate(cx, cy); ctx.scale(k, k);
    ctx.font = '900 58px ' + V3_FONT; const w = ctx.measureText(text).width + 96, h = 118;
    ctx.shadowColor = 'rgba(0,0,0,0.65)'; ctx.shadowBlur = 36; ctx.shadowOffsetY = 12;
    v3Round(ctx, -w / 2, -h / 2, w, h, 26); ctx.fillStyle = 'rgba(12,13,11,0.9)'; ctx.fill();
    ctx.shadowColor = 'transparent'; ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.stroke();
    v3Round(ctx, -w / 2, -h / 2, 12, h, 6); ctx.fillStyle = V3_LIME; ctx.fill();
    ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.fillText(text, -w / 2 + 56, 2);
    ctx.restore();
  }
  function v3Pill(ctx, text, x, y, size, op, lime) {
    if (op <= 0) return;
    ctx.save(); ctx.globalAlpha = op; ctx.font = '700 ' + size + 'px ' + V3_FONT;
    const h = size * 1.85, w = ctx.measureText(text).width + size * 1.4;
    v3Round(ctx, x, y, w, h, h / 2);
    if (lime) { ctx.fillStyle = V3_LIME; ctx.fill(); ctx.fillStyle = '#0a0b09'; }
    else { ctx.fillStyle = 'rgba(10,11,12,0.84)'; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,255,255,0.22)'; ctx.stroke(); ctx.fillStyle = '#e8eae4'; }
    ctx.textBaseline = 'middle'; ctx.fillText(text, x + size * 0.7, y + h / 2);
    ctx.restore();
    return w;
  }
  function v3Fit(ctx, text, weight, size, maxW) {
    ctx.font = weight + ' ' + size + 'px ' + V3_FONT;
    while (ctx.measureText(text).width > maxW && size > 20) { size -= 2; ctx.font = weight + ' ' + size + 'px ' + V3_FONT; }
  }
  function v3Offer(ctx, seg, cx, cy, k, op) {
    // panel is 900 tall in the render, centred on cy; its own y runs from 0
    ctx.save(); ctx.globalAlpha = op; ctx.translate(cx, cy); ctx.scale(k, k); ctx.translate(-540, -450);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    let y = 200;
    (seg.white || []).forEach(function (t) { v3Fit(ctx, t, '900', 76, 940); ctx.fillStyle = '#fff'; ctx.fillText(t, 540, y); y += 96; });
    y += 24;
    (seg.lime || []).forEach(function (t) { v3Fit(ctx, t, '900', 96, 960); ctx.fillStyle = V3_LIME; ctx.fillText(t, 540, y); y += 112; });
    if (seg.note) { ctx.textAlign = 'left'; ctx.font = '700 30px ' + V3_FONT; const w = ctx.measureText(seg.note).width + 42; v3Pill(ctx, seg.note, 540 - w / 2, y + 10, 30, 1); }
    ctx.restore();
  }
  function v3Cta(ctx, seg, cx, cy, k, op) {
    ctx.save(); ctx.globalAlpha = op; ctx.translate(cx, cy); ctx.scale(k, k);
    const w = 900, h = 300;
    v3Round(ctx, -w / 2, -h / 2, w, h, 44); ctx.fillStyle = 'rgba(9,10,9,0.91)'; ctx.fill();
    ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(226,253,86,0.92)'; ctx.stroke();
    ctx.textBaseline = 'middle'; ctx.font = '900 104px ' + V3_FONT;
    const t1 = 'COMMENT ', t2 = String(seg.keyword || '').toUpperCase();
    const x = -ctx.measureText(t1 + t2).width / 2;
    ctx.fillStyle = '#fff'; ctx.fillText(t1, x, -60); ctx.fillStyle = V3_LIME; ctx.fillText(t2, x + ctx.measureText(t1).width, -60);
    ctx.textAlign = 'center';
    ctx.font = '700 37px ' + V3_FONT; ctx.fillStyle = '#f0f2ec'; ctx.fillText(seg.sub || '', 0, 42);
    if (seg.sub2) { ctx.font = '600 31px ' + V3_FONT; ctx.fillStyle = '#becd96'; ctx.fillText(seg.sub2, 0, 96); }
    ctx.restore();
  }
  function v3Caption(ctx, tokens, cy, op, ox, k) {   // same layout as quick_v3.caption_img(tokens, k), shifted by ox
    ox = ox || 0; k = k || 1;
    const toks = tokens.filter(function (t) { return t.text; });
    const fnt = function (t) { return t.hot ? '900 ' + Math.max(12, Math.floor(74 * k)) + 'px ' + V3_FONT : '800 ' + Math.max(12, Math.floor(66 * k)) + 'px ' + V3_FONT; };
    const wid = function (t) { ctx.font = fnt(t); return ctx.measureText(t.text + ' ').width; };
    const lines = []; let cur = [], ws = 0;
    toks.forEach(function (t) { const l = wid(t); if (cur.length && ws + l > 900) { lines.push(cur); cur = []; ws = 0; } cur.push(t); ws += l; });
    lines.push(cur);
    const LH = Math.floor(92 * k);
    let bx0 = 1e9, bx1 = -1e9;
    ctx.save(); ctx.globalAlpha = op; ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.lineJoin = 'round';
    lines.forEach(function (line, li) {
      if (!line.length) return;
      const y = cy + (li - (lines.length - 1) / 2) * LH;
      ctx.font = fnt(line[line.length - 1]); const sp = ctx.measureText(' ').width;
      const lw = line.reduce(function (s, t) { return s + wid(t); }, 0);
      let x = 540 + ox - lw / 2 + sp / 2;
      bx0 = Math.min(bx0, x); bx1 = Math.max(bx1, x + lw - sp);
      line.forEach(function (t) {
        ctx.font = fnt(t);
        ctx.shadowColor = 'rgba(0,0,0,0.85)'; ctx.shadowBlur = 22;
        ctx.lineWidth = 4; ctx.strokeStyle = '#000'; ctx.strokeText(t.text, x, y);
        ctx.shadowColor = 'transparent'; ctx.fillStyle = t.hot ? V3_LIME : '#fff'; ctx.fillText(t.text, x, y);
        x += ctx.measureText(t.text + ' ').width;
      });
    });
    ctx.restore();
    const hh = lines.length * LH / 2 + 10 * k;
    return { x0: bx0, x1: bx1, y0: cy - hh, y1: cy + hh };
  }

  class FrameApp extends App {
    constructor(props) {
      super(props);
      this.frame = { pace: 3, pid: PID, ok: false, version: null, status: PID ? 'Loading…' : 'No project', error: '', name: '',
        styles: [], styleId: '', plan: null, paused: false, refs: [], exportState: null, words: 0, studio: {}, panel: null, draft: null, note: '' };
      this.frameIds = {};
      ['frameSaveNow', 'frameRunStyle', 'framePause', 'frameStop', 'frameExport', 'frameTranscribe'].forEach((n) => { this[n] = this[n].bind(this); });
      if (!PID || !ID_RE.test(PID)) { this.frame.status = 'Upload footage to start'; this.frame.recent = []; this.logs = []; this.log('system', 'Upload a talking-head video to start a FRAME project, or open a recent one.'); }
    }

    componentDidMount() {
      super.componentDidMount();
      window.frameEditor = this;   // handle for tests and the console
      if (PID && ID_RE.test(PID)) this.frameLoad().catch((e) => this.frameFail('Could not load the project: ' + e.message));
      else api('GET', '/api/projects').then((rows) => this.frameSet({ recent: rows.slice(0, 12) })).catch(function () {});
    }

    frameFail(msg) { this.frame.error = msg; this.frame.status = 'Error'; this.log('system', msg); this.bump(); }
    frameSet(patch) { Object.assign(this.frame, patch); this.bump(); }

    async frameLoad() {
      const doc = await api('GET', '/api/quick/projects/' + PID);
      const w = await api('GET', '/api/style/projects/' + PID + '/words');
      const saved = doc.editor_state || null;
      const src = { id: 'src', kind: 'video', name: doc.name || 'Project video', url: '/media/' + PID + '/input.mp4', src0: '/media/' + PID + '/input.mp4',
        local: true, dur: doc.source_duration, hasAudio: !!doc.audio, status: '', w: 0, h: 0,
        words: w.words && w.words.length ? w.words : null, wordsExact: true, wordsSrc: w.source || 'none' };
      const extra = (saved && Array.isArray(saved.media) ? saved.media : []).map(function (m) {
        const url = m.asset_id ? '/api/quick/projects/' + PID + '/assets/' + m.asset_id + '/download' : null;
        return Object.assign({}, m, { url: url, thumb: m.kind === 'image' ? url : null, local: true, status: url ? '' : 'not saved to FRAME' });
      });
      this.media = [src].concat(extra);
      this.mid = 100;
      if (saved && saved.p && Array.isArray(saved.p.clips)) {
        this.p = saved.p;
        this.frameIds = saved.ids || {};
      } else {
        const base = srcClipsFromDoc(doc);
        this.p = Object.assign(initialProject(), { clips: base.clips, nid: base.nid });
        const look = doc.studio || {};
        this.p = setGrade(this.p, studioToGrade({ brightness: look.brightness || 0, contrast: look.contrast || 1, saturation: look.saturation || 1 }));
        const v1 = this.p.clips.filter(function (c) { return c.tr === 'v1'; });
        v1.forEach((c, i) => { if (doc.clips[i]) this.frameIds[c.id] = doc.clips[i].id; });
      }
      this.undoStack = []; this.redoStack = [];
      this._savedP = this.p; this._savedMediaSig = this.mediaSig(); this._savedWords = src.words;
      this.frameSet({ ok: true, version: doc.version, name: doc.name, studio: doc.studio || {}, words: src.words ? src.words.length : 0,
        refs: (doc.video_references || []).map(function (r) { return { id: r.project_id, name: r.name || r.project_id.slice(0, 8) }; }),
        status: 'Saved · v' + doc.version, brand: doc.brand || '' });
      this.setState({ mainVideo: 'src', selMedia: 'src' });
      this.measureVideo();
      this.log('system', (doc.name || 'Project') + ' loaded from FRAME' + (src.words ? ' with ' + src.words.length + ' timed words.' : '. No transcript yet: press Transcribe, paste your script, or import an .srt.'));
      await this.frameLoadStyles();
      try { const k = await api('GET', '/api/v3/kits?project=' + PID); const own = k.kits.find(function (x) { return x.kit.indexOf('auto-') === 0; }); this.frameSet({ kits: k.kits, kit: own ? own.kit : (k.kits[0] ? k.kits[0].kit : ''), v3over: {} }); } catch (e) {}
      await this.v3Restore();
      this.liveStart();
      if (!src.words) this.frameTranscribe();
    }

    measureVideo() {
      const v = document.createElement('video');
      v.muted = true; v.preload = 'metadata'; v.src = '/media/' + PID + '/input.mp4';
      v.addEventListener('loadedmetadata', () => { this.updateMedia('src', { w: v.videoWidth, h: v.videoHeight, dur: v.duration || this.mm().src.dur }); });
    }

    async frameLoadStyles() {
      const r = await api('GET', '/api/style/styles?project=' + PID);
      const keep = r.styles.some((s) => s.style_id === this.frame.styleId);
      this.frameSet({ styles: r.styles, styleId: keep ? this.frame.styleId : (r.styles[0] ? r.styles[0].style_id : '') });
    }

    mediaSig() { return JSON.stringify(this.media.filter(function (m) { return m.id !== 'src'; }).map(function (m) { return [m.id, m.asset_id || '', m.cues || '', m.iw || 0]; })); }

    // ---- persistence: every change becomes a FRAME revision ----
    bump(extra) {
      super.bump(extra);
      if (!this.frame || !this.frame.ok) return;
      const src = this.mm().src;
      if (src && src.words !== this._savedWords && src.words) { this._savedWords = src.words; this.frameSaveWords(src.words); }
      if (this.p !== this._savedP || this.mediaSig() !== this._savedMediaSig) {
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(this.frameSaveNow, this.swarm ? 900 : 600);
      }
    }

    async frameSaveWords(words) {
      try {
        await api('POST', '/api/style/projects/' + PID + '/words', { words: words.map(function (w) { return { w: w.w, s: w.s, e: w.e }; }) });
        this.frameSet({ words: words.length });
        this.log('system', 'Saved ' + words.length + ' timed words to FRAME.');
      } catch (e) { this.log('system', 'Could not save the transcript: ' + e.message); }
    }

    buildStudio() {
      const p = this.p, d = this.derived();
      const keep = this.frame.studio || {};
      const studio = Object.assign({ aspect: keep.aspect || '9:16', fit: keep.fit || 'cover' }, gradeToStudio(p.grade, !!p.mute.fx || !p.clips.some(function (c) { return c.tr === 'fx'; })));
      studio.volume = p.mute.a1 ? 0 : +clamp(dbToGain(p.mix.voice), 0, 2).toFixed(4);
      const st = CAP_STYLES[p.caps.style] || CAP_STYLES.minimal;
      const kase = p.caps.case || (st.transform === 'upper' ? 'upper' : st.transform === 'lower' ? 'lower' : 'as_spoken');
      const color = p.caps.exportColor || (p.caps.style === 'minimal' ? '#ffffff' : (p.caps.color || '#ffffff'));
      const y = p.caps.exportY != null ? p.caps.exportY : (({ upper: 0.24, center: 0.5, lower: 0.72 })[p.caps.pos] || 0.72);
      const size = p.caps.exportSize || +clamp(st.size / 300 * (9 / 16), 0.015, 0.12).toFixed(4);
      let captions = [];
      if (!p.mute.t1) {
        captions = d.chunks.slice(0, 150).map(function (ch, i) {
          let text = ch.text;
          text = kase === 'upper' ? text.toUpperCase() : kase === 'lower' ? text.toLowerCase() : kase === 'sentence' ? text.charAt(0).toUpperCase() + text.slice(1) : text;
          return { id: 'sw_cap_' + i, origin: 'speech', text: text.slice(0, 500), start: +ch.s.toFixed(3), end: +Math.max(Math.min(ch.end, ch.e + 0.6), ch.s + 0.04).toFixed(3), x: 0.5, y: y, size: size, color: /^#[0-9a-fA-F]{6}$/.test(color) ? color : '#ffffff' };
        });
        if (d.chunks.length > 150) this.frame.note = 'Only the first 150 captions export; trim the edit to fit the rest.';
      }
      const mm = this.mm(), layers = [];
      p.clips.forEach(function (c) {
        const m = c.m ? mm[c.m] : null;
        if (!m || !m.project_asset_id) return;
        if (c.tr === 'v2' && !p.mute.v2 && m.kind === 'image') {
          const bx = brollBox(m.iw, m.ih);
          layers.push({ id: 'sw_' + c.id, asset_id: m.project_asset_id, kind: 'image', start: +c.start.toFixed(3), end: +(c.start + c.dur).toFixed(3), x: 0.5, y: 0.5, width: +bx.w.toFixed(3) });
        } else if (c.tr === 'a2' && !p.mute.a2 && m.kind === 'audio') {
          layers.push({ id: 'sw_' + c.id, asset_id: m.project_asset_id, kind: 'audio', start: +c.start.toFixed(3), end: +Math.min(c.start + c.dur, (m.dur || c.dur) + c.start).toFixed(3), inpoint: c.in || 0, volume: +clamp(dbToGain(p.mix.music), 0, 2).toFixed(4) });
        }
      });
      (keep.layers || []).forEach(function (l) { if (String(l.id).indexOf('library_') === 0) layers.push(l); });
      studio.captions = captions;
      studio.layers = layers.slice(0, 16);
      return studio;
    }

    async frameSaveNow() {
      if (!this.frame.ok) return;
      if (this._saving) { this._saveAgain = true; return; }
      const p = this.p, sig = this.mediaSig();
      const v1 = p.clips.filter(function (c) { return c.tr === 'v1' && c.m === 'src'; }).sort(function (a, b) { return a.start - b.start; });
      if (!v1.length) { this.frameSet({ status: 'Not saved: the edit needs at least one A-roll clip' }); return; }
      if (v1.length > MAX_SECTIONS) { this.frameSet({ status: 'Not saved: more than ' + MAX_SECTIONS + ' A-roll pieces' }); return; }
      const clips = v1.map((c) => { const out = { start: +c.in.toFixed(4), end: +c.out.toFixed(4) }; if (this.frameIds[c.id]) out.id = this.frameIds[c.id]; return out; });
      const media = this.media.filter(function (m) { return m.id !== 'src'; }).map(function (m) {
        return { id: m.id, kind: m.kind, name: m.name, asset_id: m.asset_id || null, project_asset_id: m.project_asset_id || null, cues: m.cues || '', iw: m.iw || 0, ih: m.ih || 0, dur: m.dur || 0 };
      });
      this._saving = true; this.frameSet({ status: 'Saving…' });
      try {
        let studio = this.buildStudio();
        const body = () => ({ operation: 'sync_editor_state', expected_version: this.frame.version, clips: clips, studio: studio,
          editor_state: { format: 'swarmcut-editor/1', p: p, media: media, ids: this.frameIds }, provider: this.swarm ? 'style-agents' : 'editor' });
        let doc;
        try { doc = await api('POST', '/api/quick/projects/' + PID + '/commands', body()); }
        catch (e) {
          if (e.status !== 409) throw e;
          const fresh = await api('GET', '/api/quick/projects/' + PID);
          this.frame.version = fresh.version; this.frame.studio = fresh.studio || {};
          studio = this.buildStudio();
          doc = await api('POST', '/api/quick/projects/' + PID + '/commands', body());
        }
        doc.clips.forEach((c, i) => { if (v1[i]) this.frameIds[v1[i].id] = c.id; });
        this._savedP = p; this._savedMediaSig = sig;
        this.frameSet({ version: doc.version, studio: doc.studio || {}, status: 'Saved · v' + doc.version, error: '' });
      } catch (e) {
        this.frameSet({ status: 'Not saved', error: 'Save failed: ' + e.message });
      } finally {
        this._saving = false;
        if (this._saveAgain || this.p !== this._savedP) { this._saveAgain = false; clearTimeout(this._saveTimer); this._saveTimer = setTimeout(this.frameSaveNow, 400); }
      }
    }

    async flushSave() {
      clearTimeout(this._saveTimer);
      for (let i = 0; i < 20 && (this._saving || this.p !== this._savedP); i++) {
        if (!this._saving) await this.frameSaveNow(); else await new Promise(function (r) { setTimeout(r, 150); });
      }
    }

    // ---- imported files are stored in the project, so they survive reloads and reach the export ----
    async uploadAsset(id, f) {
      try {
        const r = await api('POST', '/api/quick/projects/' + PID + '/assets', undefined, { body: f, headers: { 'X-Filename': encodeURIComponent(f.name || 'file') } });
        this.frame.version = r.version;
        this.updateMedia(id, { project_asset_id: r.uploaded_asset_id, asset_id: r.uploaded_asset_id });
        this.log('system', (f.name || 'File') + ' saved to the FRAME project.');
      } catch (e) { this.updateMedia(id, { status: 'not saved: ' + e.message }); }
    }
    importImage(f) {
      super.importImage(f);
      if (this.frame.ok) this.uploadAsset('m' + this.mid, f);
    }
    async importAudio(f) {
      const id = 'm' + (this.mid + 1);
      await super.importAudio(f);
      if (this.frame.ok) this.uploadAsset(id, f);
    }
    async importVideo(f) {
      if (!(PID && ID_RE.test(PID))) return this.frameUpload({ target: { files: [f] } });
      if (this.frame.ok) { this.log('system', 'This FRAME project already has its video. Start a new project in FRAME to edit ' + f.name + '.'); return; }
      return super.importVideo(f);
    }
    onVideoMeta(id) { if (!this.frame.ok) super.onVideoMeta(id); }

    // ---- style-driven agents: the plan comes from the server; cursors perform it ----
    runOneClick() { this.frameRunStyle(); }
    commit(np, label, key) {
      const S = this.swarm, before = this.p;
      if (S && np && before) {
        ['caps', 'grade', 'mix'].forEach(function (group) {
          Object.keys(np[group] || {}).forEach(function (k) {
            if (JSON.stringify(np[group][k]) !== JSON.stringify((before[group] || {})[k])) S.touched.add(group + '.' + k);
            if (group === 'caps' && k === 'color') S.touched.add('caps.exportColor');
          });
        });
      }
      super.commit(np, label, key);
    }
    keepUser(S, group, patch) {
      const kept = [];
      Object.keys(patch).forEach(function (k) { if (S.touched.has(group + '.' + k)) { kept.push(k); delete patch[k]; } });
      return kept;
    }
    runCommand(text) {
      const s = String(text || '').toLowerCase();
      if (/(one click|everything|edit (it|this|the video|my video)|full edit|auto[- ]?edit|do it all|all of it|whole thing|assemble)/.test(s)) { this.log('you', '› ' + text); return this.frameRunStyle(); }
      return super.runCommand(text);
    }

    opToAgentOp(op) {
      const self = this;
      const msg = op.label;
      if (op.kind === 'cut') {
        const a = op.source[0], b = op.source[1];
        return { lane: 'v1', area: 'timeline', time: function (pp) { return srcToTimeline(pp, 'src', a); },
          run: function (pp, S) {
            if (S.paused) return { wait: true };
            const at = srcToTimeline(pp, 'src', a);
            const np = cutSource(pp, 'src', a, b);
            return np ? { p: np, msg: msg, at: at } : { msg: null };
          } };
      }
      const area = LANE_AREA[op.lane] || 'swarm';
      return { area: area, run: function (pp, S) {
        if (S.paused) return { wait: true };
        if (op.kind === 'captions') {
          if (S.live.has('razor-01') || S.live.has('razor-02')) return { wait: true };
          const y = op.y == null ? 0.72 : op.y;
          // Emphasis colour drives the preview's word highlight (Lime Pop); the export keeps the style's own colour, size and height.
          const style = op.style || (op.emphasis_color ? 'lime' : pp.caps.style);
          const patch = { style: style, font: op.font || pp.caps.font, per: clamp(op.max_words || pp.caps.per, 1, 4),
            color: op.emphasis_color || op.color || pp.caps.color, pos: y < 0.4 ? 'upper' : y < 0.6 ? 'center' : 'lower', case: op.case || null,
            exportColor: op.color || null, exportSize: op.size || null, exportY: op.y == null ? null : op.y };
          const kept = self.keepUser(S, 'caps', patch);
          let np = setCaps(pp, patch);
          if (np.mute.t1) { const mu = Object.assign({}, np.mute); delete mu.t1; np = Object.assign({}, np, { mute: mu }); }
          return { p: np, msg: msg + (kept.length ? ' (kept your ' + kept.join(', ') + ')' : '') };
        }
        if (op.kind === 'look') {
          let np = pp.clips.some(function (c) { return c.tr === 'fx'; }) ? pp : addClip(pp, { tr: 'fx', start: 0, dur: Math.max(1, seqEnd(pp)) });
          const patch = studioToGrade(op);
          const kept = self.keepUser(S, 'grade', patch);
          np = setGrade(np, patch);
          return { p: np, msg: msg + (kept.length ? ' (kept your ' + kept.join(', ') + ')' : '') };
        }
        if (op.kind === 'voice') {
          const patch = { voice: Math.round(clamp(20 * Math.log10(Math.max(op.volume, 0.01)), -40, 6)) };
          if (self.keepUser(S, 'mix', patch).length) return { msg: msg + ' (kept your voice level)' };
          return { p: setMix(pp, patch), msg: msg };
        }
        if (op.kind === 'frame') { self.frame.studio = Object.assign({}, self.frame.studio, { aspect: op.aspect || self.frame.studio.aspect, fit: op.fit || self.frame.studio.fit }); self._savedP = null; return { msg: msg }; }
        if (op.kind === 'music' || op.kind === 'overlay') return { msg: msg + ' (in the FRAME export)' };
        return { msg: msg };
      } };
    }

    async frameRunStyle() {
      if (!this.frame.ok) { this.log('system', this.frame.error || 'The project is still loading.'); return; }
      if (this.swarm) { this.log('system', 'Agents are already working. Pause or stop them first.'); return; }
      if (!this.frame.styleId) { this.log('system', 'Pick a style first. FRAME only applies a style you saved or measured from a reference; it never invents one.'); this.frameSet({ panel: 'styles' }); return; }
      try {
        await this.flushSave();
        const full = await api('GET', '/api/style/styles/' + this.frame.styleId + '?project=' + PID);
        this.log('system', 'Recipe “' + full.style.name + '”: ' + this.recipeLines(full.style).map(function (l, i) { return (i + 1) + ') ' + l; }).join('  '));
        const plan = await api('POST', '/api/style/projects/' + PID + '/plan', { style_id: this.frame.styleId });
        this.frameSet({ plan: plan });
        plan.warnings.forEach((w) => this.log('system', w));
        // Library assets (music, logo) are copied into the project by the server before the cursors run.
        const serverOps = plan.ops.filter(function (o) { return o.kind === 'music' || o.kind === 'overlay'; });
        if (serverOps.length) {
          const res = await api('POST', '/api/style/projects/' + PID + '/apply', { style_id: this.frame.styleId, expected_version: this.frame.version, op_ids: serverOps.map(function (o) { return o.id; }) });
          this.frame.version = res.project.version; this.frame.studio = res.project.studio || {};
        }
        if (!plan.ops.length) { this.log('system', 'This style sets nothing that applies to this video yet.'); return; }
        this.startPlan(plan);
        const chosen = this.frame.styles.find((x) => x.style_id === this.frame.styleId);
        if (chosen && chosen.source_kind === 'frame_starter') this.frameSet({ note: 'This is FRAME’s starter. Change anything you want (caption style, pause tightness, color), then Styles… → Save this edit as a style. Next time, assemble with yours.' });
      } catch (e) { this.log('system', 'Could not run the style: ' + e.message); }
    }

    startPlan(plan) {
      const Q = {};
      AGENTS.forEach(function (a) { Q[a.id] = []; });
      const turn = {};
      plan.ops.forEach((op) => {
        const crew = LANE_AGENTS[op.lane] || ['mix-01'];
        const i = turn[op.lane] = (turn[op.lane] || 0) + 1;
        Q[crew[(i - 1) % crew.length]].push(this.opToAgentOp(op));
      });
      const tagged = this.media.filter(function (m) { return m.kind === 'image' && m.project_asset_id && String(m.cues || '').trim(); });
      if (tagged.length) {
        const saved = this.media;
        this.media = this.media.filter(function (m) { return m.kind !== 'image' || tagged.indexOf(m) >= 0; });
        const B = Engine.prototype.buildPlan.call(this, ['bcoll'], {});
        this.media = saved;
        ['bcoll-01', 'bcoll-02'].forEach(function (id) {
          Q[id] = Q[id].concat((B[id] || []).map(function (op) { const run = op.run; return Object.assign({}, op, { run: function (pp, S) { return S.paused ? { wait: true } : run(pp, S); } }); }));
        });
      }
      const ids = Object.keys(Q).filter(function (k) { return Q[k].length; });
      this.undoStack.push(this.p); this.redoStack = []; this.lastKey = null;
      const S = { timers: [], live: new Set(ids), started: performance.now(), ops: 0, paused: false, plan: plan, touched: new Set() };
      this.swarm = S; this.roleCounts = {};
      this.log('system', ids.length + ' agents are applying “' + plan.style_name + '” (rev ' + plan.style_revision + ', plan ' + plan.digest.slice(0, 8) + '): ' + plan.ops.length + ' steps.');
      ids.forEach((id, i) => { S.timers.push(setTimeout(() => { this.agentStep(id, Q[id]); }, 120 + i * 90)); });
      this.frameSet({ paused: false });
      this.bump({ swarmOn: true });
    }

    // Same as Swarmcut's agentStep, with a pace you can slow down to watch every move.
    agentStep(id, q) {
      const S = this.swarm;
      if (!S || !this.alive) return;
      const k = this.frame.pace || 1;
      const op = q[0];
      if (!op) { this.agentDone(id); return; }
      const tgt = this.cursorTarget(op);
      const a = this.agentPos[id];
      if (tgt) { a.x = tgt.x; a.y = tgt.y; }
      a.op = 1;
      this.bump();
      S.timers.push(setTimeout(() => {
        if (this.swarm !== S) return;
        let res = {};
        try { res = op.run(this.p, S) || {}; } catch (e) { res = { msg: 'error: ' + (e && e.message ? e.message : e) }; }
        if (res.wait) { S.timers.push(setTimeout(() => { this.agentStep(id, q); }, 350)); return; }
        if (!res.stay) q.shift();
        if (res.p) {
          this.p = res.p; this.edits++; S.ops++;
          const role = (AGENTS.find(function (x) { return x.id === id; }) || {}).role;
          this.roleCounts[role] = (this.roleCounts[role] || 0) + 1;
          this.bump({ selA: null, selB: null });
        }
        if (res.msg) this.log(id, res.msg, res.at);
        S.timers.push(setTimeout(() => { this.agentStep(id, q); }, (120 + Math.random() * 160) * k));
      }, 360 * k));
    }

    framePause() {
      if (!this.swarm) return;
      this.swarm.paused = !this.swarm.paused;
      this.log('you', this.swarm.paused ? 'paused the agents. Edit anything, then resume.' : 'resumed the agents');
      this.frameSet({ paused: this.swarm.paused });
    }
    frameStop() {
      const S = this.swarm;
      if (!S) return;
      S.timers.forEach(clearTimeout);
      this.swarm = null;
      AGENTS.forEach((a) => { this.agentPos[a.id].op = 0; });
      this.log('you', 'stopped the agents after ' + S.ops + ' edits. Everything they did is kept; one undo reverts it.');
      this.frameSet({ paused: false });
      this.bump({ swarmOn: false });
    }
    doUndo() {
      if (this.swarm && this.swarm.paused) { this.frameStop(); }
      super.doUndo();
    }

    async frameTranscribe() {
      try {
        let job = await api('POST', '/api/style/projects/' + PID + '/transcribe', {});
        this.frameSet({ note: 'Transcribing on your Mac… (the first time can take a minute while the speech model loads)' });
        while (job && job.status === 'working') {
          await new Promise(function (r) { setTimeout(r, 2000); });
          job = (await api('GET', '/api/style/projects/' + PID + '/words')).job;
        }
        if (job && job.status === 'failed') throw new Error(job.error);
        const w = await api('GET', '/api/style/projects/' + PID + '/words');
        this._savedWords = w.words;
        this.updateMedia('src', { words: w.words, wordsExact: true, wordsSrc: w.source });
        this.frameSet({ words: w.words.length, note: 'Transcript ready: ' + w.words.length + ' words. Pick a style and press Assemble with style.' });
      } catch (e) { this.frameSet({ note: 'Transcription failed: ' + e.message + ' You can paste your script or import an .srt instead.' }); }
    }

    async frameExport() {
      try {
        await this.flushSave();
        this.frameSet({ exportState: { status: 'working' } });
        let doc = await api('POST', '/api/quick/projects/' + PID + '/commands', { operation: 'export_video', expected_version: this.frame.version });
        const mine = doc.exports[doc.exports.length - 1];
        while (true) {
          await new Promise(function (r) { setTimeout(r, 1500); });
          doc = await api('GET', '/api/quick/projects/' + PID);
          const e = doc.exports.find(function (x) { return x.id === mine.id; });
          if (!e || e.status !== 'working') { this.frameSet({ exportState: e || { status: 'failed', error: 'Export disappeared.' } }); break; }
        }
      } catch (e) { this.frameSet({ exportState: { status: 'failed', error: e.message } }); }
    }

    // ---- v3 template: word-anchored plan from the kit's visual map; agents build it live, then FRAME renders it ----
    v3Kit() { return (this.frame.kits || []).find((k) => k.kit === this.frame.kit); }
    async frameRunV3() {
      if (this.swarm) { this.log('system', 'Agents are already working. Pause or stop them first.'); return; }
      const kit = this.v3Kit();
      if (!kit) return;
      try {
        await this.flushSave();
        const plan = await api('POST', '/api/v3/projects/' + PID + '/plan', { kit: kit.kit, overrides: this.frame.v3over || {} });
        this.frameSet({ v3plan: plan, v3render: null });
        this.log('system', 'v3 plan ' + plan.digest.slice(0, 8) + ': ' + plan.lines.length + ' measured lines, ' + plan.segments.length + ' visuals, ' + plan.captions.length + ' captions, ' + plan.total.toFixed(1) + ' s. Font: ' + plan.font + '.');
        this.startV3(plan, kit);
      } catch (e) { this.log('system', 'Could not plan the v3 edit: ' + e.message); }
    }
    startV3(plan, kit) {
      const self = this, Q = {};
      AGENTS.forEach(function (a) { Q[a.id] = []; });
      const dur = this.mm().src.dur || 0;
      // Every v3 build starts from the raw take, so the timeline and the plan share one clock. One undo restores the old timeline.
      this.undoStack.push(this.p); this.redoStack = [];
      const old = this.p.clips;
      const grade = old.find(function (c) { return c.tr === 'fx' && c.v3 == null && !c.label; });
      const music = old.find(function (c) { return c.tr === 'a2'; });
      let nid = this.p.nid;
      const fresh = [{ id: 'c' + (nid++), tr: 'v1', m: 'src', in: 0, out: dur, start: 0 }];
      this.setState({ sel: null });
      if (grade) fresh.push(Object.assign({}, grade, { start: 0, dur: Math.max(1, dur) }));
      if (music) fresh.push(Object.assign({}, music, { start: 0, dur: Math.max(1, dur) }));
      this.p = Object.assign({}, this.p, { clips: fresh, nid: nid, v3: { kit: kit.kit, overrides: this.frame.v3over || {}, digest: plan.digest, gfx: true },
        caps: Object.assign({}, this.p.caps, { v3: false }) });
      this.t = 0;
      const keep = plan.lines.map(function (l) { return [l.src_in, l.src_out]; });
      const cuts = []; let prev = 0;
      keep.forEach(function (k) { if (k[0] - prev > 0.02) cuts.push([prev, k[0]]); prev = k[1]; });
      if (dur - prev > 0.02) cuts.push([prev, dur]);
      cuts.reverse().forEach(function (c, i) {
        Q[i % 2 ? 'razor-02' : 'razor-01'].push({ lane: 'v1', area: 'timeline', time: function (pp) { return srcToTimeline(pp, 'src', c[0]); },
          run: function (pp, S) { if (S.paused) return { wait: true }; const at = srcToTimeline(pp, 'src', c[0]); const np = cutSource(pp, 'src', c[0], c[1]); return np ? { p: np, msg: 'cut ' + (c[1] - c[0]).toFixed(2) + ' s on measured speech', at: at } : {}; } });
      });
      const afterCuts = function (S) { return S.paused || S.live.has('razor-01') || S.live.has('razor-02'); };
      Q['caps-01'].push({ area: 'captions', run: function (pp, S) { if (afterCuts(S)) return { wait: true };
        const patch = { style: 'lime', per: 3, color: '#E2FD56', case: 'upper', pos: 'lower', exportColor: '#FFFFFF', exportSize: 0.034, exportY: 0.635 };
        self.keepUser(S, 'caps', patch);
        let np = setCaps(pp, Object.assign(patch, { v3: true }));
        np = Object.assign({}, np, { clips: np.clips.filter(function (c) { return c.tr !== 't1'; }) });
        plan.captions.forEach(function (cap) { np = addClip(np, { tr: 't1', start: cap.t0, dur: Math.max(0.1, cap.t1 - cap.t0), tokens: cap.tokens }); });
        return { p: np, msg: plan.captions.length + ' captions placed as text clips: click any to edit, drag to move, Delete to remove' }; } });
      plan.segments.forEach(function (sg, i) {
        if (!sg.kind || sg.kind === 'face') return;
        const isClip = sg.kind === 'split' || sg.kind === 'screen';
        const lane = isClip ? 'v2' : 'fx';
        const agent = isClip ? (i % 2 ? 'bcoll-02' : 'bcoll-01') : (sg.kind === 'card' ? 'grade-01' : 'gfx-01');
        Q[agent].push({ lane: lane, area: isClip ? 'media' : 'program', time: function () { return sg.t0; }, run: function (pp, S) {
          if (afterCuts(S)) return { wait: true };
          const dur = Math.max(0.2, sg.t1 - sg.t0);
          if (isClip) {
            const id = 'v3m' + i, url = '/api/v3/kits/' + kit.kit + '/poster?media=' + encodeURIComponent(sg.media) + '&t=' + (sg.kind === 'screen' ? 2 : (sg.media_in || 0));
            const name = (sg.label || sg.head || 'clip') + ' · ' + sg.media.replace('media-kit/', '');
            if (!self.mm()[id]) { self.media = self.media.concat([{ id: id, kind: 'image', name: name, url: url, thumb: url, local: true, cues: '' }]); self.measureImage(id, url); }
            return { p: self.v3WithGfx(addClip(pp, { tr: 'v2', m: id, start: sg.t0, dur: dur, v3: i })), msg: sg.kind === 'screen' ? 'screen recording on “' + sg.anchor + '”: each step lands on its word' : 'split screen on “' + sg.anchor + '”: ' + sg.label, at: sg.t0 };
          }
          const label = sg.kind === 'card' ? 'Card · ' + (sg.head || '') : sg.kind === 'offer' ? 'Offer card · required text' : 'CTA · COMMENT ' + (sg.keyword || '');
          return { p: self.v3WithGfx(addClip(pp, { tr: 'fx', start: sg.t0, dur: dur, label: label, v3: i })), msg: label + ' on “' + sg.anchor + '”', at: sg.t0 };
        } });
        const hits = sg.kind === 'card' || sg.kind === 'screen' ? [sg.t0].concat((sg.rows || []).map(function (r) { return r.t; })) : sg.kind === 'cta' && sg.land_t ? [sg.land_t] : [sg.t0];
        hits.forEach(function (h) { Q['gfx-01'].push({ lane: 's1', area: 'sfx', time: function () { return h; }, run: function (pp, S) { if (afterCuts(S)) return { wait: true }; return { p: addClip(pp, { tr: 's1', sfx: sg.kind === 'card' || sg.kind === 'screen' ? 'pop' : 'impact', start: h, dur: 0.3, label: sg.kind === 'card' || sg.kind === 'screen' ? 'click' : 'hit', v3s: true }), at: h }; } }); });
      });
      Q['mix-01'].push({ area: 'mix', run: function (pp, S) { if (afterCuts(S)) return { wait: true }; return { msg: '120 BPM bed with voice ducking and event SFX (in the render)' }; } });
      const ids = Object.keys(Q).filter(function (k) { return Q[k].length; });
      const S = { timers: [], live: new Set(ids), started: performance.now(), ops: 0, paused: false, touched: new Set(), onDone: function () { self.log('system', 'Build finished. The preview is the v3 cut: press play. “Render v3” writes the file with music and mastering.'); } };
      this.swarm = S; this.roleCounts = {};
      this.log('system', ids.length + ' agents are building “' + kit.title + '” on the raw take. Watch the preview: every cut, split, card and caption appears as it is placed.');
      ids.forEach((id, i) => { S.timers.push(setTimeout(() => { this.agentStep(id, Q[id]); }, 120 + i * 90)); });
      this.frameSet({ paused: false });
      this.bump({ swarmOn: true });
    }
    agentDone(id) {
      const S = this.swarm;
      super.agentDone(id);
      if (S && !this.swarm && S.onDone) S.onDone();
    }
    async frameRenderV3() {
      const kit = this.v3Kit();
      if (!kit) return;
      try {
        await this.flushSave();
        this.frameSet({ v3render: { status: 'working', progress: 'starting' } });
        let job = await api('POST', '/api/v3/projects/' + PID + '/render', { kit: kit.kit, overrides: this.frame.v3over || {}, timeline: this.v3On() ? this.v3Timeline() : null });
        this.log('system', 'Rendering the v3 cut with FRAME’s compositor…');
        while (job.status === 'working') { await new Promise(function (r) { setTimeout(r, 2000); }); job = await api('GET', '/api/v3/projects/' + PID + '/render/' + job.key); this.frameSet({ v3render: job }); }
        this.frameSet({ v3render: job });
        if (job.status === 'done') this.log('system', 'v3 cut ready: ' + job.qc.duration_video.toFixed(1) + ' s, ' + (job.qc.integrated_lufs) + ' LUFS, voice ' + job.qc.voice_over_bed_db + ' dB over the music, ' + job.qc.captions_crossing_cuts + ' captions crossing cuts.');
        else this.log('system', 'v3 render failed: ' + job.error);
      } catch (e) { this.frameSet({ v3render: { status: 'failed', error: e.message } }); }
    }
    v3Panel() {
      const kit = this.v3Kit(), f = this.frame;
      if (!kit || f.panel !== 'v3') return null;
      const ov = f.v3over || {};
      const set = (i, k, v) => { const o = Object.assign({}, ov); o[i] = Object.assign({}, o[i] || {}, { [k]: v }); this.frameSet({ v3over: o }); };
      const r = f.v3render;
      return html`<div class="modal-back" onClick=${(e) => { if (e.target === e.currentTarget) this.frameSet({ panel: null }); }}>
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="v3-title" style="max-width:820px">
          <div class="head-row"><h2 id="v3-title">${kit.title}</h2><button type="button" class="btn sm" onClick=${() => this.frameSet({ panel: null })}>Close</button></div>
          <p class="small muted" style="margin:0">Each visual lands on the word you say. Change a label or swap a clip, then build again; anchors stay as documented.</p>
          ${r && r.status === 'done' ? html`<div class="result"><video class="result-video" src=${r.url} controls=${true} playsinline></video><div>
            <a class="btn-primary" href=${r.url + '?download=1'}>Download v3 cut</a>
            <span class="small muted mono">${r.qc.duration_video.toFixed(1)} s · ${r.qc.integrated_lufs} LUFS · voice +${r.qc.voice_over_bed_db} dB · ${r.qc.captions_crossing_cuts} caption crossings</span></div></div>` : null}
          ${r && r.status === 'working' ? html`<p class="small mono">Rendering… ${r.progress || ''}</p>` : null}
          ${r && r.status === 'failed' ? html`<p class="err">Render failed: ${r.error}</p>` : null}
          <ol class="small" style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px">
            ${kit.visuals.map((v, i) => html`<li>
              <strong>${v.kind}</strong> on “${v.anchor}”
              ${'label' in v ? html` · <input class="input sm" style="width:220px" value=${(ov[i] || {}).label != null ? ov[i].label : v.label} onInput=${(e) => set(i, 'label', e.target.value)} />` : null}
              ${v.kind === 'split' ? html` · <select class="input sm" style="width:auto" value=${(ov[i] || {}).media || v.media} onChange=${(e) => set(i, 'media', e.target.value)}>${kit.media.map((m) => html`<option value=${m}>${m.replace('media-kit/', '')}</option>`)}</select>
                · start <input class="input sm" type="number" min="0" step="0.5" style="width:70px" value=${(ov[i] || {}).media_in != null ? ov[i].media_in : (v.media_in || 0)} onInput=${(e) => set(i, 'media_in', parseFloat(e.target.value) || 0)} /> s` : null}
              ${v.kind === 'cta' ? html` · keyword <input class="input sm" style="width:120px" value=${(ov[i] || {}).keyword != null ? ov[i].keyword : v.keyword} onInput=${(e) => set(i, 'keyword', e.target.value)} />` : null}
            </li>`)}
          </ol>
          <div class="row wrap"><button type="button" class="btn-primary" disabled=${!!this.swarm} onClick=${() => { this.frameSet({ panel: null }); this.frameRunV3(); }}>Build v3 live</button>
          <button type="button" class="btn" disabled=${r && r.status === 'working'} onClick=${() => this.frameRenderV3()}>Render only</button></div>
        </div></div>`;
    }

    // ---- v3 live preview: the program monitor draws the v3 templates from the clips the agents place ----
    // Same layouts as quick_v3.render (1080×1920 coordinates). Overlays follow their timeline clips, so moving
    // or trimming a split/card on the timeline moves it in the preview too.
    async v3Restore() {
      const v3 = this.p && this.p.v3;
      if (!v3 || !(this.frame.kits || []).some(function (k) { return k.kit === v3.kit; })) return;
      try {
        const plan = await api('POST', '/api/v3/projects/' + PID + '/plan', { kit: v3.kit, overrides: v3.overrides || {} });
        this.frameSet({ kit: v3.kit, v3over: v3.overrides || {}, v3plan: plan });
        if (!this.p.v3.gfx) { this.p = this.v3Detach(this.p); this.bump(); this.log('system', 'Every label, step, offer and CTA panel is now its own overlay on the GRAPHICS lane: click one in the preview to move, resize, rewrite or delete it.'); }
        // edits made before captions were text clips: turn the plan's captions into clips once
        if (this.p.caps && this.p.caps.v3 && !this.p.clips.some(function (c) { return c.tr === 't1'; })) {
          let np = this.p;
          plan.captions.forEach(function (cap) { np = addClip(np, { tr: 't1', start: cap.t0, dur: Math.max(0.1, cap.t1 - cap.t0), tokens: cap.tokens }); });
          this.p = np; this.bump();
          this.log('system', plan.captions.length + ' captions are now text clips: click any to edit, drag to move, Delete to remove.');
        }
      } catch (e) { this.log('system', 'Could not reload the v3 plan: ' + e.message); }
    }
    v3On() { return !!(this.p && this.p.v3 && this.frame.v3plan); }
    monitor(v) {
      if (!this.v3On()) return super.monitor(v);
      const vv = Object.assign({}, v, { broll: { on: false }, cap: { on: false } });
      return html`<div class="v3wrap" style="position:relative;width:300px;max-width:100%">${super.monitor(vv)}
        <canvas data-v3="1" width="540" height="960" aria-label="v3 preview. Click a caption to select it; drag it to move it." style=${'position:absolute;inset:0;width:100%;height:100%;border-radius:12px;z-index:2;touch-action:none;cursor:' + (this._v3drag ? 'grabbing' : this._v3hover ? 'grab' : 'default')}
          onPointerDown=${(e) => this.v3Pointer(e, 'down')} onPointerMove=${(e) => this.v3Pointer(e, 'move')} onPointerUp=${(e) => this.v3Pointer(e, 'up')} onPointerCancel=${(e) => this.v3Pointer(e, 'up')}></canvas>
        ${this.v3Inspector()}</div>`;
    }
    tick(now) {
      super.tick(now);
      if (this.v3On()) { try { this.drawV3(); } catch (e) { if (!this._v3err) { this._v3err = true; this.log('system', 'Preview error: ' + e.message); } } }
    }
    v3CapY() { const o = (this.frame.v3over || {}).captions; return o && o.y ? o.y : ((this.frame.v3plan && this.frame.v3plan.caption_y) || 1220); }
    // Default height for captions on the speaker. Captions you drag keep their own spot.
    v3SetCapY(y, done) {
      y = Math.round(Math.max(700, Math.min(1800, y)) / 10) * 10;
      const ov = Object.assign({}, this.frame.v3over || {}, { captions: { y: y } });
      this.frame.v3over = ov;
      if (done) {
        this.commit(Object.assign({}, this.p, { v3: Object.assign({}, this.p.v3, { overrides: ov }) }), 'caption height');
        this.log('you', 'set caption height to ' + Math.round(y / 19.2) + '% down the frame (captions you placed by hand keep their spot).');
      }
      this.bump();
    }
    // ---- captions are text clips: click one in the preview or the TEXT lane to select it, drag it anywhere ----
    v3Pointer(e, kind) {
      const cv = e.currentTarget, r = cv.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width * 1080, y = (e.clientY - r.top) / r.height * 1920;
      const hit = (this._v3boxes || []).slice().reverse().find(function (b) { return x >= b.x0 - 30 && x <= b.x1 + 30 && y >= b.y0 - 20 && y <= b.y1 + 20; });
      if (kind === 'down') {
        if (!hit) { const sc = this.p.clips.find((c) => c.id === this.state.sel); if (sc && (sc.tr === 't1' || sc.tr === 'g1')) this.setState({ sel: null }); return; }
        const c = this.p.clips.find(function (q) { return q.id === hit.id; });
        const HOME = { label: [540, 820], chip: [44, 60], step: [540, 1010], text: [540, 960], offer: [540, 470], cta: [540, 1380], cardhead: [540, 520], cardrow: [0, 640] };
        const hm = c.tr === 'g1' ? (HOME[(c.g || {}).type] || [540, 960]) : null;
        const y0 = c.y != null ? c.y : (hm ? hm[1] : (hit.y0 + hit.y1) / 2);
        this._v3drag = { id: c.id, gfx: c.tr === 'g1', hx: hm ? hm[0] : 0, sx: e.clientX, sy: e.clientY, k: 1920 / r.height, cx: c.x != null ? c.x : (hm ? hm[0] : 0), cy: y0, snap: this.p, moved: false };
        this.setState({ sel: c.id });
        try { cv.setPointerCapture(e.pointerId); } catch (q) {}
        e.preventDefault();
        return;
      }
      if (kind === 'move') {
        const D = this._v3drag;
        if (D) {
          const dx = (e.clientX - D.sx) * D.k, dy = (e.clientY - D.sy) * D.k;   // screen deltas: robust if the page reflows
          if (!D.moved && Math.abs(dx) + Math.abs(dy) < 8) return;
          D.moved = true;
          const nx = D.gfx ? (Math.abs(D.cx + dx - D.hx) < 20 ? D.hx : Math.max(-600, Math.min(1700, D.cx + dx))) : (Math.abs(D.cx + dx) < 24 ? 0 : Math.max(-500, Math.min(500, D.cx + dx)));   // snaps to centre
          const ny = D.gfx ? Math.max(-400, Math.min(2300, D.cy + dy)) : Math.max(200, Math.min(1880, D.cy + dy));
          this.p = Object.assign({}, D.snap, { clips: D.snap.clips.map(function (c) { return c.id === D.id ? Object.assign({}, c, { x: Math.round(nx), y: Math.round(ny) }) : c; }) });
          this.bump();
          return;
        }
        if (!!hit !== !!this._v3hover) { this._v3hover = !!hit; this.bump(); }
        return;
      }
      const D = this._v3drag;
      if (D) {
        this._v3drag = null;
        if (D.moved) { const np = this.p; this.p = D.snap; this.commit(np, 'moved caption'); }
        this.bump();
      }
    }
    v3SelClip() { const id = this.state.sel; return id ? this.p.clips.find(function (c) { return c.id === id; }) : null; }
    v3Edit(id, patch, label) {
      const np = Object.assign({}, this.p, { clips: this.p.clips.map(function (c) { return c.id === id ? Object.assign({}, c, typeof patch === 'function' ? patch(c) : patch) : c; }) });
      this.commit(np, label || 'edited clip', 'v3edit-' + id + '-' + (label || ''));
    }
    v3Delete(id) {
      const c = this.p.clips.find(function (x) { return x.id === id; });
      if (!c) return;
      this.setState({ sel: null });
      this.commit(Object.assign({}, this.p, { clips: this.p.clips.filter(function (x) { return x.id !== id; }) }), 'deleted ' + (c.tr === 't1' ? 'caption “' + c.tokens.map(function (t) { return t.text; }).join(' ') + '”' : 'section'));
    }
    v3AddCaption() {
      const t = this.t;
      const np = addClip(this.p, { tr: 't1', start: t, dur: 1.5, tokens: [{ text: 'NEW', hot: false }, { text: 'TEXT', hot: true }] });
      this.commit(np, 'added a caption at ' + tc(t));
      this.setState({ sel: 'c' + (np.nid - 1) });
    }
    v3AllHeight(y) {
      const ov = Object.assign({}, this.frame.v3over || {}, { captions: { y: Math.round(y) } });
      this.frame.v3over = ov;
      this.commit(Object.assign({}, this.p, { v3: Object.assign({}, this.p.v3, { overrides: ov }), clips: this.p.clips.map(function (c) { return c.tr === 't1' ? Object.assign({}, c, { y: undefined, x: undefined }) : c; }) }), 'all captions to one height');
    }
    // ---- imported clips for B-roll sections ----
    async v3ImportBroll(e) {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      for (const f of files) {
        const id = 'b' + (++this.mid);
        const url = URL.createObjectURL(f);
        this.media = this.media.concat([{ id: id, kind: 'video', broll: true, name: f.name, url: url, local: true, status: 'saving to FRAME…' }]);
        this.bump();
        const v = document.createElement('video'); v.muted = true; v.preload = 'metadata'; v.src = url;
        v.addEventListener('loadedmetadata', () => { this.updateMedia(id, { dur: v.duration, w: v.videoWidth, h: v.videoHeight }); });
        await this.uploadAsset(id, f);
        const m = this.mm()[id];
        if (m && m.asset_id) { this.updateMedia(id, { status: '', url: '/api/quick/projects/' + PID + '/assets/' + m.asset_id + '/download' }); this.log('system', f.name + ' is ready. Select a B-roll section and swap it in, or press “Add as split at playhead”.'); }
      }
      this.setState({ selMedia: null });
    }
    v3Brolls() {
      const kit = this.v3Kit();
      const out = ((kit && kit.media) || []).map(function (m) { return { value: m, name: m.replace('media-kit/', '') + ' (kit)' }; });
      this.media.forEach(function (m) { if (m.broll && m.asset_id) out.push({ value: 'asset:' + m.asset_id, name: m.name + ' (imported)' }); });
      return out;
    }
    v3AddSplit(media, name) {
      const t = this.t;
      const np = addClip(this.p, { tr: 'v2', m: null, start: t, dur: 2.5, seg: { kind: 'split', media: media, media_in: 0, label: '', chip: '' }, name: name });
      this.commit(np, 'added a B-roll split at ' + tc(t));
      this.setState({ sel: 'c' + (np.nid - 1) });
    }
    // ---- trimming: drag either edge of any clip ----
    clipDown(id, e) {
      const c = this.p.clips.find(function (x) { return x.id === id; });
      if (!c || this.state.tool === 'razor' || c.tr === 'a2') return super.clipDown(id, e);
      const b = e.currentTarget.getBoundingClientRect(), px = e.clientX - b.left;
      const edge = b.width >= 14 ? (px <= 7 ? 'L' : px >= b.width - 7 ? 'R' : null) : null;
      if (!edge) return super.clipDown(id, e);
      e.preventDefault(); e.stopPropagation();
      this.setState({ sel: id });
      const pps = this.state.zoom, x0 = e.clientX, snap0 = this.p, ripple = this.state.ripple || c.tr === 'v1';
      const srcDur = (this.mm()[c.m] || {}).dur || 1e9;
      let moved = false;
      const trim = (d) => {
        let nc = Object.assign({}, c), shiftFrom = null, delta = 0;
        if (c.tr === 'v1') {
          if (edge === 'L') { const ni = Math.max(0, Math.min(c.out - 0.1, c.in + d)); delta = -(ni - c.in); nc.in = ni; shiftFrom = cend(c); }
          else { const no = Math.min(srcDur, Math.max(c.in + 0.1, c.out + d)); delta = no - c.out; nc.out = no; shiftFrom = cend(c); }
        } else if (edge === 'L') {
          const ns = Math.max(0, Math.min(c.start + c.dur - 0.1, c.start + d)), dd = ns - c.start;
          nc.start = ns; nc.dur = c.dur - dd; nc.min = (c.min || 0) + dd;
        } else nc.dur = Math.max(0.1, c.dur + d);
        const clips = snap0.clips.map(function (x) {
          if (x.id === id) return nc;
          if (shiftFrom != null && ripple && x.start >= shiftFrom - 1e-3 && x.tr !== 'fx' && x.tr !== 'a2' || (shiftFrom != null && ripple && x.start >= shiftFrom - 1e-3 && x.v3 != null)) return Object.assign({}, x, { start: Math.max(0, x.start + delta) });
          if (shiftFrom != null && ripple && (x.tr === 'a2' || (x.tr === 'fx' && x.v3 == null && !x.seg)) && cend(x) >= shiftFrom - 1e-3) return Object.assign({}, x, { dur: Math.max(0.1, x.dur + delta) });
          return x;
        });
        return Object.assign({}, snap0, { clips: clips });
      };
      const move = (ev) => {
        const dx = ev.clientX - x0;
        if (!moved && Math.abs(dx) < 2) return;
        moved = true; this.p = trim(dx / pps); this.bump();
      };
      const up = () => {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
        if (moved) { const np = this.p; this.p = snap0; this.commit(np, 'trimmed ' + (edge === 'L' ? 'start' : 'end') + ' of ' + (c.tr === 't1' ? 'a caption' : c.tr === 'v1' ? 'the A-roll' : 'a section')); }
      };
      window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    }
    // TEXT lane shows the caption clips (movable, trimmable, deletable) once captions are text clips
    renderVals() {
      const v = super.renderVals();
      if (!this.v3On()) return v;
      const p = this.p, s = this.state, pps = s.zoom, self = this, tool = s.tool;
      const mk = function (c, label) {
        return {
          left: (c.start * pps).toFixed(1) + 'px', width: Math.max(4, c.dur * pps - 1).toFixed(1) + 'px', label: label,
          border: c.id === s.sel ? '#c8f53a' : 'rgba(255,255,255,0.10)', cursor: tool === 'razor' ? 'crosshair' : 'grab', op: p.mute[c.tr] ? 0.35 : 1,
          aria: label + ' at ' + tc(c.start) + '. Drag to move, drag an edge to trim, Delete to remove.',
          down: function (e) { self.clipDown(c.id, e); }, pick: function () { if (self.state.tool !== 'razor') self.setState({ sel: c.id }); }
        };
      };
      const caps = p.clips.filter(function (c) { return c.tr === 't1' && c.tokens; }).sort(function (a, b) { return a.start - b.start; });
      if (caps.length) v.lt1 = caps.map(function (c) { return mk(c, c.tokens.map(function (t) { return t.text; }).join(' ')); });
      v.lg1 = p.clips.filter(function (c) { return c.tr === 'g1' && c.g; }).sort(function (a, b) { return a.start - b.start; }).map(function (c) { return mk(c, self.v3GfxName(c)); });
      const plan = this.frame.v3plan;
      v.lfx = p.clips.filter(function (c) { return c.tr === 'fx'; }).sort(function (a, b) { return a.start - b.start; }).map(function (c) {
        const sg = (c.v3 != null || c.seg) ? self.v3SegOut(c) : null;
        return mk(Object.assign({}, c, { dur: cdur(c) }), sg ? (sg.kind === 'offer' ? 'Offer card' : sg.kind === 'cta' ? 'CTA · COMMENT ' + (sg.keyword || '') : sg.kind === 'card' ? 'Card · ' + (sg.head || '') : sg.kind) : 'Grade · wheels + look');
      });
      v.lv2 = p.clips.filter(function (c) { return c.tr === 'v2'; }).sort(function (a, b) { return a.start - b.start; }).map(function (c) {
        const sg = (c.v3 != null || c.seg) ? self.v3SegOut(c) : null;
        const nm = sg ? (sg.label || sg.head || (sg.kind === 'screen' ? 'Screen recording' : 'B-roll')) + ' · ' + String(sg.media || '').replace('media-kit/', '').replace(/^asset:.*/, c.name || 'imported clip') : ((self.mm()[c.m] || {}).name || 'clip');
        return mk(c, nm);
      });
      return v;
    }
    // ---- inspector: everything about the selected caption or section, editable ----
    v3Inspector() {
      if (!this.v3On()) return null;
      const c = this.v3SelClip(), self = this;
      const tools = html`<div class="row wrap" style="gap:8px;align-items:center">
        <span class="label">Edit</span>
        <button type="button" class="btn sm" onClick=${() => this.v3AddCaption()}>Add caption at playhead</button>
        <button type="button" class="btn sm" onClick=${() => this.v3AddText()}>Add text overlay</button>
        <input id="v3-broll" class="vh" type="file" multiple accept="video/*,.mov,.mp4,.m4v" onChange=${(e) => this.v3ImportBroll(e)} />
        <label for="v3-broll" class="btn sm">Import B-roll clips</label>
        ${this.v3Brolls().filter((b) => b.value.indexOf('asset:') === 0).map((b) => html`<button type="button" class="btn sm" onClick=${() => this.v3AddSplit(b.value, b.name)}>Add “${b.name.replace(' (imported)', '')}” at playhead</button>`)}
      </div>`;
      if (c && c.tr === 'g1') return this.v3GfxInspector(c, tools);
      if (!c || !(c.tr === 't1' || c.v3 != null || c.seg)) return html`<div class="v3insp" role="region" aria-label="Edit">${tools}<p class="small muted" style="margin:6px 0 0">Click a caption in the preview, or any clip on the timeline, to edit it here. Drag captions to move them. Drag a clip’s edge on the timeline to trim or extend it. Delete removes the selected clip.</p></div>`;
      if (c.tr === 't1') {
        const text = c.tokens.map(function (t) { return t.text; }).join(' ');
        return html`<div class="v3insp" role="region" aria-label="Selected caption">${tools}
          <div class="v3card">
            <strong class="small">Caption ${tc(c.start)}</strong>
            <label class="small" style="display:flex;gap:6px;align-items:center">Text
              <input class="input sm" style="width:260px" key=${c.id + 'text' + text} defaultValue=${text} onChange=${(e) => {
                const words = e.target.value.trim().split(/\s+/).filter(Boolean).slice(0, 16);
                const hot = {}; c.tokens.forEach(function (t) { if (t.hot) hot[t.text.toUpperCase()] = true; });
                if (!words.length) return this.v3Delete(c.id);
                this.v3Edit(c.id, { tokens: words.map(function (w) { return { text: w, hot: !!hot[w.toUpperCase()] }; }) }, 'edited caption text');
              }} /></label>
            <div class="row"><span class="small muted">Lime words:</span>
            ${c.tokens.map((t, i) => html`<button type="button" class=${'chip' + (t.hot ? ' on' : '')} aria-pressed=${t.hot ? 'true' : 'false'} onClick=${() => this.v3Edit(c.id, function (cc) { return { tokens: cc.tokens.map(function (q, j) { return j === i ? { text: q.text, hot: !q.hot } : q; }) }; }, 'lime word')}>${t.text}</button>`)}</div>
            <label class="small" style="display:flex;gap:6px;align-items:center">Size
              <input type="range" min="0.5" max="2" step="0.05" value=${c.k || 1} onInput=${(e) => { this.p = Object.assign({}, this.p, { clips: this.p.clips.map(function (q) { return q.id === c.id ? Object.assign({}, q, { k: +e.target.value }) : q; }) }); this.bump(); }} onChange=${(e) => this.v3Edit(c.id, { k: +e.target.value }, 'caption size')} style="width:100px" /></label>
            <button type="button" class="btn sm" onClick=${() => this.v3Edit(c.id, { x: undefined, y: undefined, k: undefined }, 'reset caption')}>Reset position</button>
            <button type="button" class="btn sm" onClick=${() => this.v3AllHeight(c.y != null ? c.y : this.v3CapY())}>Use this height for all</button>
            <button type="button" class="btn sm" onClick=${() => this.v3Delete(c.id)}>Delete caption</button>
          </div></div>`;
      }
      const sg = this.v3SegOut(c) || {};
      const set = (k, val, label) => this.v3Edit(c.id, function (cc) { return { seg: Object.assign({}, cc.seg || {}, { [k]: val }) }; }, label || ('section ' + k));
      const field = (k, label, w) => html`<label class="small" style="display:flex;gap:6px;align-items:center">${label}<input class="input sm" style=${'width:' + (w || 200) + 'px'} key=${c.id + k + (sg[k] || '')} defaultValue=${sg[k] || ''} onChange=${(e) => set(k, e.target.value)} /></label>`;
      return html`<div class="v3insp" role="region" aria-label="Selected section">${tools}
        <div class="v3card">
          <strong class="small">${sg.kind === 'split' ? 'B-roll split' : sg.kind === 'screen' ? 'Screen recording' : sg.kind === 'offer' ? 'Offer card' : sg.kind === 'cta' ? 'Call to action' : 'Card'} · ${tc(c.start)}–${tc(c.start + c.dur)}</strong>
          ${sg.kind === 'split' || sg.kind === 'screen' ? html`<label class="small" style="display:flex;gap:6px;align-items:center">Clip
            <select class="input sm" style="width:auto;max-width:240px" value=${sg.media} onChange=${(e) => set('media', e.target.value, 'swapped clip')}>
              ${this.v3Brolls().map((b) => html`<option value=${b.value}>${b.name}</option>`)}
              ${this.v3Brolls().some((b) => b.value === sg.media) ? null : html`<option value=${sg.media}>${String(sg.media).replace('media-kit/', '')}</option>`}
            </select></label>
            <label class="small" style="display:flex;gap:6px;align-items:center">Clip starts at
              <input class="input sm" type="number" min="0" step="0.1" style="width:70px" key=${c.id + 'mi' + (+(sg.media_in || 0)).toFixed(1)} defaultValue=${(+(sg.media_in || 0)).toFixed(1)} onChange=${(e) => { const want = Math.max(0, +e.target.value || 0); this.v3Edit(c.id, function (cc) { return { min: (cc.min || 0) + (want - (sg.media_in || 0)) }; }, 'clip start'); }} /> s</label>` : null}
          ${sg.bare ? html`<span class="small muted">Its labels and panels are on the GRAPHICS lane: click them in the preview to edit.</span>` : null}
          ${sg.kind === 'split' && !sg.bare ? [field('label', 'Label', 180), field('chip', 'Corner note', 220)] : null}
          ${(sg.kind === 'screen' || sg.kind === 'card') && !sg.bare ? field('head', 'Heading', 220) : null}
          ${sg.kind === 'cta' && !sg.bare ? [field('keyword', 'Keyword', 110), field('sub', 'Line 2', 200), field('sub2', 'Line 3', 240)] : null}
          ${sg.kind === 'offer' && !sg.bare ? html`<label class="small" style="display:flex;gap:6px;align-items:center">White lines<input class="input sm" style="width:260px" key=${c.id + 'w' + (sg.white || []).join('/')} defaultValue=${(sg.white || []).join(' / ')} onChange=${(e) => set('white', e.target.value.split('/').map((x) => x.trim()).filter(Boolean))} /></label>
            <label class="small" style="display:flex;gap:6px;align-items:center">Lime lines<input class="input sm" style="width:220px" key=${c.id + 'l' + (sg.lime || []).join('/')} defaultValue=${(sg.lime || []).join(' / ')} onChange=${(e) => set('lime', e.target.value.split('/').map((x) => x.trim()).filter(Boolean))} /></label>${field('note', 'Note', 220)}` : null}
          <button type="button" class="btn sm" onClick=${() => this.v3Delete(c.id)}>Delete section</button>
          <span class="small muted" style="flex-basis:100%">Drag the section on the B-roll lane to move it; drag its edges to trim or extend. Trimming the start skips into the clip.</span>
        </div></div>`;
    }
    v3Video(url) {
      this.v3vids = this.v3vids || {};
      if (!this.v3vids[url]) {
        const v = document.createElement('video');
        v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
        this.v3vids[url] = v;
      }
      return this.v3vids[url];
    }
    // ---- overlays as graphics: every label, step, chip, offer and CTA panel is its own clip on the GRAPHICS lane ----
    v3GraphicsFromSeg(seg) {
      const out = [], end = seg.t1;
      const add = function (o, t0, t1) { if (t1 - t0 >= 0.05) out.push(Object.assign({ tr: 'g1', start: +t0.toFixed(3), dur: +(t1 - t0).toFixed(3) }, o)); };
      if (seg.kind === 'split') {
        if (seg.label) add({ g: { type: 'label', text: seg.label } }, seg.t0, end);
        if (seg.chip) add({ g: { type: 'chip', text: seg.chip } }, seg.t0, end);
      } else if (seg.kind === 'screen') {
        const rows = (seg.rows || []).filter(function (r) { return r.t < end; });
        const first = rows.length ? Math.max(seg.t0, rows[0].t) : end;
        if (seg.head) add({ g: { type: 'step', text: seg.head } }, seg.t0, first);
        rows.forEach(function (r, i) { add({ g: { type: 'step', text: r.num + '  ' + r.title } }, Math.max(seg.t0, r.t), i + 1 < rows.length ? rows[i + 1].t : end); });
      } else if (seg.kind === 'offer') {
        add({ g: { type: 'offer', white: seg.white || [], lime: seg.lime || [], note: seg.note || '' } }, seg.t0, end);
      } else if (seg.kind === 'cta') {
        add({ g: { type: 'cta', keyword: seg.keyword || '', sub: seg.sub || '', sub2: seg.sub2 || '' } }, Math.max(seg.t0, seg.land_t != null ? seg.land_t : seg.t0), end);
      } else if (seg.kind === 'card') {
        if (seg.head) add({ g: { type: 'cardhead', text: seg.head } }, seg.t0, end);
        (seg.rows || []).forEach(function (r, i) { add({ g: { type: 'cardrow', num: r.num, title: r.title }, y: 640 + 200 * i }, Math.max(seg.t0, r.t), end); });
      }
      const gd = (this.frame.v3plan || {}).graphic_defaults || {};   // a saved style remembers where the creator puts each kind
      out.forEach(function (o) { const d = gd[o.g.type]; if (!d || o.g.type === 'cardrow') return; if (o.x == null) o.x = d.x; if (o.y == null) o.y = d.y; if (d.k && d.k !== 1) o.k = d.k; });
      return out;
    }
    // ---- styles: save this edit's format; make a first cut of new footage from a saved one ----
    async v3SaveStyle() {
      const name = window.prompt('Name this style (it keeps the format, not the footage):', 'Higgsfield v3 Discovery');
      if (!name) return;
      try {
        await this.flushSave();
        const r = await api('POST', '/api/v3/styles', { project: PID, name: name });
        this.log('system', 'Saved style “' + r.name + '”: ' + r.sections.length + ' sections, captions at ' + Math.round(r.captions.y / 19.2) + '% down, your overlay positions. Use it on new footage with “First cut from a style…”.');
        this.frameSet({ v3styles: null });
      } catch (e) { this.log('system', 'Could not save the style: ' + e.message); }
    }
    async v3OpenStyles() {
      try { const r = await api('GET', '/api/v3/styles'); this.frameSet({ v3styles: r.styles, v3style: (r.styles[0] || {}).slug || '', panel: 'style', v3assets: this.v3assets || {} }); }
      catch (e) { this.log('system', 'Could not load styles: ' + e.message); }
    }
    async v3FirstCut() {
      const f = this.frame, roles = this.v3assets || {};
      const assets = this.media.filter(function (m) { return m.broll && m.asset_id; }).map(function (m) {
        const r = roles[m.asset_id] || {}; return { asset_id: m.asset_id, role: r.role || 'split', label: r.label || '', cue: r.cue || '' };
      }).filter(function (a) { return a.role !== 'skip'; });
      try {
        this.frameSet({ note: 'Placing the style on your footage…' });
        const r = await api('POST', '/api/v3/projects/' + PID + '/first-cut', { style: f.v3style, assets: assets });
        const k = await api('GET', '/api/v3/kits?project=' + PID);
        this.frameSet({ kits: k.kits, kit: r.kit, v3over: {}, panel: null, note: '' });
        this.log('system', 'First cut plan: ' + r.placed.map(function (x) { return x.kind + ' on “' + x.word + '” (' + x.at_s.toFixed(1) + ' s)'; }).join(', ') + '. The agents build it now; trim anything that does not sync.');
        this.frameRunV3();
      } catch (e) { this.frameSet({ note: 'Could not make the first cut: ' + e.message }); }
    }
    v3StylePanel() {
      const f = this.frame;
      if (f.panel !== 'style') return null;
      const clips = this.media.filter(function (m) { return m.broll && m.asset_id; });
      const roles = this.v3assets = this.v3assets || {};
      const set = (id, k, v) => { roles[id] = Object.assign({}, roles[id] || {}, { [k]: v }); this.bump(); };
      return html`<div class="modal-back" onClick=${(e) => { if (e.target === e.currentTarget) this.frameSet({ panel: null }); }}>
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="st-title" style="max-width:760px">
          <div class="head-row"><h2 id="st-title">First cut from a style</h2><button type="button" class="btn sm" onClick=${() => this.frameSet({ panel: null })}>Close</button></div>
          <p class="small muted" style="margin:0">The style decides the sections, their look and where overlays sit. Your transcript decides where each lands: setup on “here's how…”, offer on “free / unlimited…”, CTA on “comment…”. Clips without a cue word are spread over the opening.</p>
          ${(f.v3styles || []).length ? html`<label class="small" style="display:flex;gap:8px;align-items:center">Style
            <select class="input sm" style="width:auto" value=${f.v3style} onChange=${(e) => this.frameSet({ v3style: e.target.value })}>${f.v3styles.map((s) => html`<option value=${s.slug}>${s.name} · ${s.sections.join(', ')}</option>`)}</select></label>`
            : html`<p class="small warn">No saved styles yet. Open a finished v3 edit and press “Save as style”.</p>`}
          ${f.words ? null : html`<p class="small warn">This video has no transcript yet. Press Transcribe first.</p>`}
          <div class="small" style="font-weight:600">Your clips (${clips.length}) ${clips.length ? null : html`<span class="muted" style="font-weight:400">· use “Import B-roll clips” under the preview first</span>`}</div>
          ${clips.map((m) => { const r = roles[m.asset_id] || {}; return html`<div class="row wrap" style="gap:8px;align-items:center">
            <span class="small mono" style="min-width:160px">${m.name}</span>
            <select class="input sm" style="width:auto" value=${r.role || 'split'} onChange=${(e) => set(m.asset_id, 'role', e.target.value)}><option value="split">B-roll split</option><option value="screen">Setup screen recording</option><option value="skip">Leave out</option></select>
            <input class="input sm" style="width:150px" placeholder="Label (optional)" key=${m.asset_id + 'l'} defaultValue=${r.label || ''} onChange=${(e) => set(m.asset_id, 'label', e.target.value)} />
            <input class="input sm" style="width:150px" placeholder="Cue word (optional)" key=${m.asset_id + 'c'} defaultValue=${r.cue || ''} onChange=${(e) => set(m.asset_id, 'cue', e.target.value)} />
          </div>`; })}
          ${f.note ? html`<p class="small">${f.note}</p>` : null}
          <div class="row wrap"><button type="button" class="btn-primary" disabled=${!f.v3style || !clips.length || !f.words || !!this.swarm} onClick=${() => this.v3FirstCut()}>Make first cut live</button></div>
        </div></div>`;
    }
    v3Detach(p) {   // one-time: turn every section's baked overlays into graphic clips
      let np = Object.assign({}, p, { v3: Object.assign({}, p.v3, { gfx: true }), clips: p.clips.filter(function (c) { return c.tr !== 'g1'; }) });
      const self = this;
      p.clips.forEach(function (c) {
        if (!((c.tr === 'v2' || c.tr === 'fx') && (c.v3 != null || c.seg))) return;
        const seg = self.v3SegOut(c);
        if (seg) self.v3GraphicsFromSeg(seg).forEach(function (g) { np = addClip(np, g); });
      });
      return np;
    }
    // In a v3 edit the Render button makes the real file (FRAME's renderer: overlays, music, mastering).
    openRender() {
      if (!this.v3On()) return super.openRender();
      this.frameRenderV3();
      this.frameSet({ panel: 'v3' });
    }
    v3WithGfx(np) {   // the clip just added is a section: put its overlays on the GRAPHICS lane
      const c = np.clips[np.clips.length - 1], seg = this.v3SegOut(c);
      if (seg) this.v3GraphicsFromSeg(seg).forEach(function (g) { np = addClip(np, g); });
      return np;
    }
    v3AddText() {
      const np = addClip(this.p, { tr: 'g1', start: this.t, dur: 2, g: { type: 'text', text: 'NEW TEXT' } });
      this.commit(np, 'added a text overlay at ' + tc(this.t));
      this.setState({ sel: 'c' + (np.nid - 1) });
    }
    v3GfxName(c) {
      const g = c.g || {};
      return g.type === 'offer' ? 'Offer · ' + (g.lime || []).join(' ') : g.type === 'cta' ? 'CTA · COMMENT ' + (g.keyword || '') : g.type === 'cardrow' ? g.num + ' ' + g.title : (g.text || g.type);
    }
    drawGraphic(ctx, c, t) {
      const g = c.g || {}, u = t - c.start, k = c.k || 1;
      const H = { label: [540, 820], chip: [44, 60], step: [540, 1010], text: [540, 960], offer: [540, 470], cta: [540, 1380], cardhead: [540, 520], cardrow: [0, 640] }[g.type] || [540, 960];
      const x = c.x != null ? c.x : H[0], y = c.y != null ? c.y : H[1];
      const labelBox = function (text, cx, cy, kk) { ctx.font = '900 58px ' + V3_FONT; const w = (ctx.measureText(text).width + 96) * kk, h = 118 * kk; return { x0: cx - w / 2, x1: cx + w / 2, y0: cy - h / 2, y1: cy + h / 2 }; };
      if (g.type === 'label') {
        const e = v3Ease((u - 0.08) / 0.22);
        if (e > 0) v3Label(ctx, g.text || '', x - 60 * (1 - e), y, (0.96 + 0.04 * e) * k, e);
        return labelBox(g.text || '', x, y, k);
      }
      if (g.type === 'step' || g.type === 'text') {
        const e = v3Ease(u / 0.2);
        v3Label(ctx, g.text || '', x - 50 * (1 - e), y, (0.96 + 0.04 * e) * k, Math.max(0.001, e));
        return labelBox(g.text || '', x, y, k);
      }
      if (g.type === 'chip') {
        const w = v3Pill(ctx, g.text || '', x, y, 24 * k, v3Ease((u - 0.15) / 0.2)) || 0;
        ctx.font = '700 ' + (24 * k) + 'px ' + V3_FONT;
        return { x0: x, x1: x + ctx.measureText(g.text || '').width + 24 * k * 1.4, y0: y, y1: y + 24 * k * 1.85 };
      }
      if (g.type === 'offer') {
        const e = v3Ease(u / 0.22);
        v3Offer(ctx, g, x, y + 40 * (1 - e), (1.04 - 0.04 * e) * k, e);
        const lines = (g.white || []).length * 96 + 24 + (g.lime || []).length * 112 + (g.note ? 70 : 0);
        return { x0: x - 470 * k, x1: x + 470 * k, y0: y + (200 - 450 - 50) * k, y1: y + (200 - 450 + lines) * k };
      }
      if (g.type === 'cta') {
        const e = v3Ease(u / 0.2), pulse = 1 + 0.06 * Math.exp(-Math.pow((u - 0.1) / 0.12, 2));
        v3Cta(ctx, g, x, y + 50 * (1 - e), (0.95 + 0.05 * e) * pulse * k, e);
        return { x0: x - 450 * k, x1: x + 450 * k, y0: y - 150 * k, y1: y + 150 * k };
      }
      if (g.type === 'cardhead') {
        const sc = (u < 0.1 ? 1.06 - 0.06 * v3Ease(u / 0.1) : 1 + 0.02 * u) * k;
        ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); ctx.translate(-540, -520);
        ctx.font = '900 50px ' + V3_FONT; ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
        let xx = 84; for (const ch of (g.text || '')) { ctx.fillText(ch, xx, 520); xx += ctx.measureText(ch).width + 6; }
        ctx.restore();
        ctx.fillStyle = V3_LIME; ctx.fillRect(x - 540 + 84, y + 52, 380 * v3Ease(u / 0.18) * k, 8);
        return { x0: x - 456 * k, x1: x - 456 * k + (xx - 84) * k, y0: y - 40 * k, y1: y + 60 * k };
      }
      if (g.type === 'cardrow') {
        const pr = v3Ease(u / 0.14);
        if (pr > 0) {
          ctx.save(); ctx.globalAlpha = pr; ctx.translate(x + 70 * (1 - pr), y); ctx.scale(k, k);
          ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(84, 4); ctx.lineTo(996, 4); ctx.stroke();
          ctx.textBaseline = 'middle'; ctx.font = '900 110px ' + V3_FONT; ctx.fillStyle = V3_LIME; ctx.fillText(g.num || '', 84, 104);
          const nx = 84 + ctx.measureText(g.num || '').width + 40;
          let size = 64; ctx.font = '800 ' + size + 'px ' + V3_FONT;
          while (ctx.measureText(g.title || '').width > 1000 - nx && size > 40) { size -= 2; ctx.font = '800 ' + size + 'px ' + V3_FONT; }
          ctx.fillStyle = '#fff'; ctx.fillText(g.title || '', nx, 108);
          ctx.restore();
        }
        return { x0: x + 84 * k, x1: x + 996 * k, y0: y, y1: y + 200 * k };
      }
      return null;
    }
    v3GfxInspector(c, tools) {
      const g = c.g || {};
      const set = (k, val) => this.v3Edit(c.id, function (cc) { return { g: Object.assign({}, cc.g, { [k]: val }) }; }, 'edited overlay ' + k);
      const field = (k, label, w) => html`<label class="small">${label}<input class="input sm" style=${'width:' + (w || 200) + 'px'} key=${c.id + k + (g[k] || '')} defaultValue=${g[k] || ''} onChange=${(e) => set(k, e.target.value)} /></label>`;
      const lines = (k, label) => html`<label class="small">${label}<input class="input sm" style="width:240px" key=${c.id + k + (g[k] || []).join('/')} defaultValue=${(g[k] || []).join(' / ')} onChange=${(e) => set(k, e.target.value.split('/').map((x) => x.trim()).filter(Boolean))} /></label>`;
      const names = { label: 'Label', chip: 'Corner note', step: 'Step label', text: 'Text overlay', offer: 'Offer panel', cta: 'Call-to-action panel', cardhead: 'Card heading', cardrow: 'Card row' };
      return html`<div class="v3insp" role="region" aria-label="Selected overlay">${tools}
        <div class="v3card">
          <strong class="small">${names[g.type] || 'Overlay'} · ${tc(c.start)}–${tc(c.start + c.dur)}</strong>
          ${['label', 'chip', 'step', 'text', 'cardhead'].indexOf(g.type) >= 0 ? field('text', 'Text', 240) : null}
          ${g.type === 'cardrow' ? [field('num', 'Number', 60), field('title', 'Title', 220)] : null}
          ${g.type === 'offer' ? [lines('white', 'White lines'), lines('lime', 'Lime lines'), field('note', 'Note', 220)] : null}
          ${g.type === 'cta' ? [field('keyword', 'Keyword', 110), field('sub', 'Line 2', 200), field('sub2', 'Line 3', 240)] : null}
          <label class="small">Size
            <input type="range" min="0.3" max="2.5" step="0.05" value=${c.k || 1} onInput=${(e) => { this.p = Object.assign({}, this.p, { clips: this.p.clips.map(function (q) { return q.id === c.id ? Object.assign({}, q, { k: +e.target.value }) : q; }) }); this.bump(); }} onChange=${(e) => this.v3Edit(c.id, { k: +e.target.value }, 'overlay size')} style="width:110px" /></label>
          <div class="row"><button type="button" class="btn sm" onClick=${() => this.v3Edit(c.id, { x: undefined, y: undefined, k: undefined }, 'reset overlay')}>Reset position</button>
          <button type="button" class="btn sm" onClick=${() => this.v3Delete(c.id)}>Delete overlay</button></div>
          <span class="small muted">Drag it in the preview to move it. On the GRAPHICS lane: drag to retime, drag an edge to change when it appears or leaves.</span>
        </div></div>`;
    }
    // A timeline clip -> the section the render draws: kit plan values, then this clip's own edits, placed where the clip sits.
    v3SegOut(c) {
      const plan = this.frame.v3plan;
      const base = c.v3 != null && plan ? plan.segments[c.v3] : null;
      const sp = Object.assign({}, base || {}, c.seg || {});
      if (!sp.kind || sp.kind === 'face') return null;
      const b0 = base ? base.t0 : c.start;
      const origin = c.start - (c.min || 0), sh = origin - b0;
      const seg = Object.assign({}, sp, { t0: c.start, t1: c.start + c.dur });
      if (this.p.v3 && this.p.v3.gfx) seg.bare = true;   // its overlays live on the GRAPHICS lane
      if (sp.rows) seg.rows = sp.rows.map(function (r) { return Object.assign({}, r, { t: +(r.t + sh).toFixed(3) }); });
      if (sp.land_t != null) seg.land_t = +(sp.land_t + sh).toFixed(3);
      if (seg.kind === 'split') seg.media_in = Math.max(0, (sp.media_in || 0) + (c.min || 0));
      if (seg.kind === 'screen') {
        const full = Object.assign({}, seg, { t0: origin, media_in: sp.media_in || 0 });
        seg.media_in = Math.max(0, v3ScreenTime(full, c.start));
        seg.rows = (seg.rows || []).map(function (r) { if (r.t >= c.start) return r; const x = Object.assign({}, r); delete x.media_t; return x; });
      }
      return seg;
    }
    v3MediaUrl(media) {
      if (String(media).indexOf('asset:') === 0) return '/api/quick/projects/' + PID + '/assets/' + media.slice(6) + '/download';
      return '/api/v3/kits/' + this.p.v3.kit + '/media?media=' + encodeURIComponent(media);
    }
    v3Sections() { return this.p.clips.filter(function (x) { return (x.tr === 'v2' || x.tr === 'fx') && (x.v3 != null || x.seg); }); }
    v3Timeline() {
      const p = this.p;
      return {
        lines: p.clips.filter(function (c) { return c.tr === 'v1'; }).sort(function (a, b) { return a.start - b.start; }).map(function (c) { return { src_in: +c.in.toFixed(3), src_out: +c.out.toFixed(3), out: +c.start.toFixed(3) }; }),
        segments: this.v3Sections().map((c) => this.v3SegOut(c)).filter(Boolean).map(function (sg) {
          // send only what the renderer draws; kit-map comments (like a long "note" on a screen section) stay out
          const o = Object.assign({}, sg);
          if (o.kind !== 'offer') delete o.note;
          ['label', 'chip', 'keyword', 'sub', 'sub2', 'note', 'head'].forEach(function (k) { if (typeof o[k] === 'string') o[k] = o[k].slice(0, 120); });
          return o;
        }),
        captions: p.mute.t1 ? [] : p.clips.filter(function (c) { return c.tr === 't1' && c.tokens; }).map(function (c) {
          const o = { t0: +c.start.toFixed(3), t1: +(c.start + c.dur).toFixed(3), tokens: c.tokens };
          if (c.y != null) o.y = Math.round(c.y); if (c.x) o.x = Math.round(c.x); if (c.k && c.k !== 1) o.k = +c.k.toFixed(2);
          return o;
        }),
        caption_y: this.v3CapY(),
        graphics_mode: !!(p.v3 && p.v3.gfx),
        graphics: p.mute.g1 ? [] : p.clips.filter(function (c) { return c.tr === 'g1' && c.g; }).map(function (c) {
          const o = Object.assign({}, c.g, { t0: +c.start.toFixed(3), t1: +(c.start + c.dur).toFixed(3) });
          if (c.x != null) o.x = Math.round(c.x); if (c.y != null) o.y = Math.round(c.y); if (c.k && c.k !== 1) o.k = +c.k.toFixed(2);
          return o;
        })
      };
    }
    drawV3() {
      const cv = document.querySelector('canvas[data-v3]');
      if (!cv) return;
      const ctx = cv.getContext('2d'), p = this.p, t = this.t;
      ctx.setTransform(cv.width / 1080, 0, 0, cv.height / 1920, 0, 0);
      ctx.globalAlpha = 1; ctx.filter = 'none';
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 1080, 1920);
      const v1 = p.mute.v1 ? null : clipAt(p.clips, 'v1', t);
      const ar = v1 ? document.querySelector('video[data-mid="' + v1.m + '"]') : null;
      const arOk = ar && ar.readyState >= 2 && ar.videoWidth;
      let c = null;
      this.v3Sections().forEach(function (x) { if (!(p.mute[x.tr]) && t >= x.start && t < cend(x) && (!c || x.start >= c.start)) c = x; });
      const seg = c ? this.v3SegOut(c) : null;
      const kind = seg ? seg.kind : 'face';
      const u = c ? t - c.start : 0, d = c ? Math.max(0.1, c.dur) : 1;
      const wantUrl = seg && (kind === 'split' || kind === 'screen') && seg.media ? this.v3MediaUrl(seg.media) : null;
      Object.keys(this.v3vids || {}).forEach((k) => { const x = this.v3vids[k]; if (!x.paused && k !== wantUrl) x.pause(); });
      const face = (z, cx, cy, y0, h, sy0) => { if (arOk) v3Frame(ctx, ar, z, cx, cy, y0, h, sy0); };
      const sync = (kv, target, rate) => {
        if (kv.duration && isFinite(kv.duration) && target >= kv.duration - 0.05) target = target % kv.duration;   // the render loops a short clip too
        if (this.playing) { try { kv.playbackRate = rate; } catch (e) {} if (Math.abs(kv.currentTime - target) > 0.25) { try { kv.currentTime = target; } catch (e) {} } if (kv.paused) { const pr = kv.play(); if (pr && pr.catch) pr.catch(function () {}); } }
        else { if (!kv.paused) kv.pause(); if (Math.abs(kv.currentTime - target) > 0.04) { try { kv.currentTime = target; } catch (e) {} } }
        return kv.readyState >= 2 && kv.videoWidth;
      };
      if (kind === 'split' || kind === 'offer') {
        if (kind === 'split') {
          const kv = this.v3Video(wantUrl);
          if (sync(kv, (seg.media_in || 0) + u, 1)) v3Frame(ctx, kv, 1 + 0.05 * u / d, 540, 480, 0, 960, 0, 1080, 960);
          else { ctx.fillStyle = '#111'; ctx.fillRect(0, 0, 1080, 960); ctx.fillStyle = 'rgba(255,255,255,.6)'; ctx.font = '600 34px ' + V3_FONT; ctx.textAlign = 'center'; ctx.fillText(kv.error ? 'This clip can’t play in the browser' : 'Loading clip…', 540, 480); ctx.textAlign = 'left'; }
          if (u < 0.12) { ctx.fillStyle = 'rgba(255,255,255,' + (0.4 * (1 - u / 0.12)) + ')'; ctx.fillRect(0, 0, 1080, 960); }
          if (seg.label && !seg.bare) { const e = v3Ease((u - 0.08) / 0.22); if (e > 0) v3Label(ctx, seg.label, 540 - 60 * (1 - e), 820, 0.96 + 0.04 * e, e); }
          if (seg.chip && !seg.bare) v3Pill(ctx, seg.chip, 24, 40, 24, v3Ease((u - 0.15) / 0.2));
        } else {
          v3CardBg(ctx, 960);
          const e = v3Ease(u / 0.22);
          if (!seg.bare) v3Offer(ctx, seg, 540, 470 + 40 * (1 - e), 1.04 - 0.04 * e, e);
          if (u < 0.08) { ctx.fillStyle = 'rgba(255,255,255,' + (0.5 * (1 - u / 0.08)) + ')'; ctx.fillRect(0, 0, 1080, 960); }
        }
        face(1 + 0.03 * u / d, 540, 1000, 960, 960, 520);
        const g = ctx.createLinearGradient(0, 760, 0, 1160);
        g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.5, 'rgba(0,0,0,0.55)'); g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g; ctx.fillRect(0, 760, 1080, 400);
      } else if (kind === 'screen') {
        const kv = this.v3Video(wantUrl);
        const target = v3ScreenTime(seg, t), rate = Math.max(0.25, Math.min(8, (v3ScreenTime(seg, t + 0.1) - target) / 0.1));
        if (sync(kv, target, rate)) v3Frame(ctx, kv, 1 + 0.03 * u / d, 540, 960, 0, 1920, 0);
        if (u < 0.06) { ctx.fillStyle = 'rgba(255,255,255,' + (0.5 * (1 - u / 0.06)) + ')'; ctx.fillRect(0, 0, 1080, 1920); }
        let cur = null; (seg.rows || []).forEach(function (r) { if (r.t <= t) cur = r; });
        const text = cur ? cur.num + '  ' + cur.title : (seg.head || ''), since = cur ? Math.max(cur.t, c.start) : c.start;
        if (text && !seg.bare) { const e = v3Ease((t - since) / 0.2); v3Label(ctx, text, 540 - 50 * (1 - e), seg.label_y || 1010, 0.96 + 0.04 * e, Math.max(0.001, e)); }
      } else if (kind === 'card') {
        v3CardBg(ctx, 1920);
        if (!seg.bare) {
        const sc = u < 0.1 ? 1.06 - 0.06 * v3Ease(u / 0.1) : 1 + 0.02 * u;
        ctx.save(); ctx.translate(540, 520); ctx.scale(sc, sc); ctx.translate(-540, -520);
        ctx.font = '900 50px ' + V3_FONT; ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
        let x = 84; for (const ch of (seg.head || '')) { ctx.fillText(ch, x, 520); x += ctx.measureText(ch).width + 6; }
        ctx.restore();
        ctx.fillStyle = V3_LIME; ctx.fillRect(84, 572, 380 * v3Ease(u / 0.18), 8);
        (seg.rows || []).forEach(function (r, ri) {
          const pr = v3Ease((t - r.t) / 0.14);
          if (pr <= 0) return;
          ctx.save(); ctx.globalAlpha = pr; ctx.translate(70 * (1 - pr), 640 + 200 * ri);
          ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(84, 4); ctx.lineTo(996, 4); ctx.stroke();
          ctx.textBaseline = 'middle'; ctx.font = '900 110px ' + V3_FONT; ctx.fillStyle = V3_LIME; ctx.fillText(r.num, 84, 104);
          const nx = 84 + ctx.measureText(r.num).width + 40;
          let size = 64; ctx.font = '800 ' + size + 'px ' + V3_FONT;
          while (ctx.measureText(r.title).width > 1000 - nx && size > 40) { size -= 2; ctx.font = '800 ' + size + 'px ' + V3_FONT; }
          ctx.fillStyle = '#fff'; ctx.fillText(r.title, nx, 108);
          ctx.restore();
        });
        }
        if (u < 0.05) { ctx.fillStyle = 'rgba(255,255,255,' + (0.5 * (1 - u / 0.05)) + ')'; ctx.fillRect(0, 0, 1080, 1920); }
      } else if (kind === 'cta') {
        face(1.06 + 0.06 * u / d, 540, 620, 0, 1920, 0);
        const g = ctx.createLinearGradient(0, 1150, 0, 1450); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.6)');
        ctx.fillStyle = g; ctx.fillRect(0, 1150, 1080, 770);
        const lt = seg.land_t != null ? seg.land_t : seg.t0;
        if (t > lt && !seg.bare) { const e = v3Ease((t - lt) / 0.2), pulse = 1 + 0.06 * Math.exp(-Math.pow((t - lt - 0.1) / 0.12, 2)); v3Cta(ctx, seg, 540, 1380 + 50 * (1 - e), (0.95 + 0.05 * e) * pulse, e); }
      } else {
        // face: the render pushes in slowly between sections; here the push restarts after each section
        let prevEnd = 0; this.v3Sections().forEach(function (x) { const e = cend(x); if (e <= t + 1e-6 && e > prevEnd) prevEnd = e; });
        face(1 + 0.06 * Math.min(1, (t - prevEnd) / 4), 540, 620, 0, 1920, 0);
        const g = ctx.createLinearGradient(0, 1050, 0, 1430); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.27)');
        ctx.fillStyle = g; ctx.fillRect(0, 1050, 1080, 870);
      }
      if (!arOk && kind !== 'card' && kind !== 'screen') { ctx.fillStyle = 'rgba(255,255,255,0.6)'; ctx.font = '600 34px ' + V3_FONT; ctx.textAlign = 'center'; ctx.fillText(v1 ? 'Loading footage…' : 'Nothing on the A-roll here', 540, 1500); ctx.textAlign = 'left'; }
      const boxes = [];
      if (!p.mute.g1) p.clips.filter(function (x) { return x.tr === 'g1' && x.g && t >= x.start && t < x.start + x.dur; }).sort(function (a, b) { return a.start - b.start; }).forEach((gc) => {
        const bb = this.drawGraphic(ctx, gc, t);
        if (!bb) return;
        boxes.push({ id: gc.id, gfx: true, x0: bb.x0, x1: bb.x1, y0: bb.y0, y1: bb.y1 });
        if (this.state.sel === gc.id) { ctx.save(); ctx.setLineDash([14, 10]); ctx.strokeStyle = V3_LIME; ctx.lineWidth = 3; ctx.strokeRect(bb.x0 - 12, bb.y0 - 8, bb.x1 - bb.x0 + 24, bb.y1 - bb.y0 + 16); ctx.restore(); }
      });
      // captions: every TEXT clip under the playhead is drawn where it was placed
      if (!p.mute.t1) {
        const y0 = kind === 'split' || kind === 'offer' ? 960 : kind === 'cta' ? 1060 : this.v3CapY();
        p.clips.forEach((cc) => {
          if (cc.tr !== 't1' || !cc.tokens || t < cc.start || t >= cc.start + cc.dur) return;
          const y = cc.y != null ? cc.y : y0, x = cc.x || 0, k = cc.k || 1;
          const pr = this._v3drag && this._v3drag.id === cc.id ? 1 : v3Ease((t - cc.start) / 0.12);
          const bb = v3Caption(ctx, cc.tokens, y + 22 * (1 - pr), pr, x, k);
          boxes.push({ id: cc.id, x0: bb.x0, x1: bb.x1, y0: bb.y0, y1: bb.y1 });
          if (this.state.sel === cc.id || (this._v3drag && this._v3drag.id === cc.id)) { ctx.save(); ctx.setLineDash([14, 10]); ctx.strokeStyle = V3_LIME; ctx.lineWidth = 3; ctx.strokeRect(bb.x0 - 16, bb.y0 - 10, bb.x1 - bb.x0 + 32, bb.y1 - bb.y0 + 20); ctx.restore(); }
        });
      }
      this._v3boxes = boxes;
    }

    // ---- live channel: edits pushed to the project (by Claude in chat, a script, or the MCP) play here with agent cursors ----
    liveStart() {
      if (this._live) return;
      this._live = { after: null };
      const poll = async () => {
        if (!this.alive) return;
        try {
          const L = this._live;
          const r = await api('GET', '/api/v3/projects/' + PID + '/live?after=' + (L.after == null ? 1e9 : L.after));
          if (L.after == null) L.after = r.next;              // first poll: skip history, act only on new events
          else { for (const ev of r.events) { L.after = ev.seq + 1; await this.liveEvent(ev); } if (!r.events.length) L.after = Math.max(L.after, r.next); }
        } catch (e) {}
        setTimeout(poll, 2000);
      };
      // learn the current length first
      api('GET', '/api/v3/projects/' + PID + '/live?after=0').then((r) => { this._live.after = r.next; setTimeout(poll, 2000); }).catch(() => { this._live.after = 0; setTimeout(poll, 2000); });
    }
    async liveEvent(ev) {
      const who = 'Claude';
      if (ev.type === 'say') { this.log('system', who + ': ' + String(ev.text || '').slice(0, 600)); return; }
      if (ev.type === 'seek') { this.seek(+ev.t || 0); if (ev.play && !this.playing) this.togglePlay(); this.log('system', who + ' moved the playhead to ' + tc(+ev.t || 0) + (ev.note ? ': ' + ev.note : '')); return; }
      if (ev.type === 'render') { this.log('system', who + ' started the v3 render.'); this.frameRenderV3(); return; }
      if (ev.type === 'build' || ev.type === 'patch') {
        if (ev.kit) this.frameSet({ kit: ev.kit });
        if (ev.overrides) this.frameSet({ v3over: ev.overrides });
        if (ev.note) this.log('system', who + ': ' + ev.note);
        if (ev.type === 'patch' && this.v3On() && !this.swarm) return this.v3Patch();
        if (this.swarm) this.frameStop();
        return this.frameRunV3();
      }
    }
    // A changed label/clip/text: re-plan, then move only what changed (no rebuild of cuts).
    async v3Patch() {
      const kit = this.v3Kit();
      try {
        const plan = await api('POST', '/api/v3/projects/' + PID + '/plan', { kit: kit.kit, overrides: this.frame.v3over || {} });
        const old = this.frame.v3plan;
        if (!old || plan.segments.length !== old.segments.length || plan.lines.length !== old.lines.length) { this.log('system', 'That change moves the cuts, so the agents rebuild.'); return this.frameRunV3(); }
        const np = Object.assign({}, this.p, { v3: Object.assign({}, this.p.v3, { overrides: this.frame.v3over || {}, digest: plan.digest }) });
        this.frameSet({ v3plan: plan });
        let first = null;
        plan.segments.forEach(function (sg, i) { if (JSON.stringify(sg) !== JSON.stringify(old.segments[i]) && first == null) first = i; });
        this.commit(np, 'changed v3 visual');
        if (first != null) {
          const sg = plan.segments[first], c = this.p.clips.find(function (x) { return x.v3 === first; });
          const t = c ? c.start + 0.4 : sg.t0 + 0.4;
          this.seek(t);
          this.log('gfx-01', 'updated ' + sg.kind + ' “' + (sg.label || sg.head || sg.keyword || sg.anchor) + '”', t);
        }
      } catch (e) { this.log('system', 'Could not apply the change: ' + e.message); }
    }

    // ---- styles: save the current edit as a style, or measure a reference ----
    styleFromEdit(name, kind, brand) {
      const p = this.p, st = this.buildStudio();
      const caps = p.caps;
      const style = {
        format: 'frame-style/1', name: name,
        provenance: { source_kind: kind, reference_project_ids: kind === 'own_video' ? [] : [], use_scope: brand ? { type: 'brand', brand: brand } : { type: 'creator' } },
        frame: { aspect: st.aspect, fit: st.fit },
        look: { brightness: st.brightness, contrast: st.contrast, saturation: st.saturation },
        pacing: { remove_pauses: true, min_pause_s: this.state.minPause, pad_s: 0.12, remove_retakes: true },
        captions: { max_words: caps.per, max_s: 1.6, y: ({ upper: 0.24, center: 0.5, lower: 0.72 })[caps.pos] || 0.72, size: st.captions[0] ? st.captions[0].size : 0.041,
          color: (st.captions[0] && st.captions[0].color) || '#ffffff', case: caps.case || ((CAP_STYLES[caps.style] || {}).transform === 'upper' ? 'upper' : 'as_spoken'),
          style: caps.style, font: caps.font },
        audio: { voice_volume: st.volume },
        evidence: { 'captions.style': { method: 'user_set' }, 'look.contrast': { method: 'user_set' }, 'pacing.min_pause_s': { method: 'user_set' } }
      };
      return style;
    }

    async frameSaveStyle(style) {
      try {
        const r = await api('POST', '/api/style/styles', { style: style, project_id: null });
        await this.frameLoadStyles();
        this.frameSet({ styleId: r.style_id, panel: null, draft: null, note: 'Saved style “' + r.style.name + '”.' });
        this.log('system', 'Saved style “' + r.style.name + '” (rev ' + r.style.revision + ').');
      } catch (e) { this.frameSet({ note: 'Could not save the style: ' + e.message }); }
    }

    async frameUploadReference(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const brand = (document.getElementById('st-ref-brand') || {}).value || '';
      try {
        this.frameSet({ note: 'Uploading reference ' + file.name + '…' });
        const ref = await api('POST', '/upload-reference', undefined, { body: file, headers: { 'X-Filename': encodeURIComponent(file.name) } });
        let linked;
        try { linked = await api('POST', '/api/quick/projects/' + PID + '/revision', { action: 'add_video_reference', expected_version: this.frame.version, reference_project_id: ref.id }); }
        catch (err) {
          if (err.status !== 409) throw err;
          const fresh = await api('GET', '/api/quick/projects/' + PID);
          linked = await api('POST', '/api/quick/projects/' + PID + '/revision', { action: 'add_video_reference', expected_version: fresh.version, reference_project_id: ref.id });
        }
        this.frameSet({ version: linked.version, refs: (linked.video_references || []).map(function (r) { return { id: r.project_id, name: r.name || r.project_id.slice(0, 8) }; }) });
        await this.frameMeasure(ref.id, brand.trim(), (brand.trim() || file.name.replace(/\.[^.]+$/, '')) + ' style');
      } catch (err) { this.frameSet({ note: 'Could not add the reference: ' + err.message }); }
    }

    recipeLines(st) {
      const out = [];
      if (st.frame) out.push('Frame: ' + (st.frame.aspect || 'source') + ', ' + (st.frame.fit || 'cover'));
      const pc = st.pacing || {};
      if (pc.cut_first_s) out.push('Cut the first ' + pc.cut_first_s + ' s');
      if (pc.remove_retakes) out.push('Remove earlier takes when you repeat a line');
      if (pc.remove_pauses) out.push('Cut pauses longer than ' + pc.min_pause_s + ' s, keeping ' + pc.pad_s + ' s around speech');
      if (st.look) out.push('Color: brightness ' + st.look.brightness + ', contrast ' + st.look.contrast + ', saturation ' + st.look.saturation);
      if (st.captions) out.push('Captions: ' + (st.captions.max_words || 3) + ' words per line, ' + (st.captions.style || 'minimal') + ', ' + (st.captions.case || 'as spoken') + ', ' + (st.captions.color || '#ffffff'));
      if (st.audio && st.audio.voice_volume != null) out.push('Voice level ×' + st.audio.voice_volume);
      (st.slots || []).forEach(function (sl) { out.push('Asset slot “' + sl.id + '” (' + sl.kind + ')' + (sl.asset_id ? '' : ' — empty')); });
      return out;
    }

    async frameMeasure(refId, brand, name) {
      try {
        this.frameSet({ note: 'Measuring the reference…' });
        const r = await api('POST', '/api/style/projects/' + PID + '/extract', { reference_project_id: refId, brand: brand || null, name: name || null, source_kind: brand ? 'brand_reference' : 'own_video' });
        this.frameSet({ draft: r, note: 'Review what was measured, then save it as a style.' });
      } catch (e) { this.frameSet({ note: 'Could not measure the reference: ' + e.message }); }
    }

    header(v, s, pro) {
      return [super.header(v, s, pro), this.frameBar(), this.framePanel(), this.v3Panel(), this.v3StylePanel()];
    }

    async frameUpload(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      this.frameSet({ status: 'Uploading ' + file.name + '…', error: '' });
      try {
        const r = await api('POST', '/upload', undefined, { body: file, headers: { 'X-Filename': encodeURIComponent(file.name) } });
        location.href = '/swarm?project=' + r.id;
      } catch (err) { this.frameSet({ status: 'Upload failed', error: err.message }); }
    }

    frameBar() {
      const f = this.frame;
      if (!f.ok && !(PID && ID_RE.test(PID))) {
        return html`<div class="frame-bar" role="region" aria-label="FRAME project">
          <span class="label">FRAME</span><span class="small muted">${f.status}</span>
          <input id="frame-upload" class="vh" type="file" accept="video/*,.mov,.mp4,.m4v" onChange=${(e) => this.frameUpload(e)} />
          <label for="frame-upload" class="btn-primary">Upload footage</label>
          ${(f.recent || []).length ? html`<label class="sr-only" for="frame-recent">Recent projects</label>
            <select id="frame-recent" class="input sm" style="width:auto" onChange=${(e) => { if (e.target.value) location.href = '/swarm?project=' + e.target.value; }}>
              <option value="">Open a recent project…</option>
              ${f.recent.map((r) => html`<option value=${r.id}>${r.name}</option>`)}
            </select>` : null}
          ${f.error ? html`<span class="small warn" style="flex-basis:100%">${f.error}</span>` : null}
        </div>`;
      }
      const S = this.swarm;
      const ex = f.exportState;
      return html`<div class="frame-bar" role="region" aria-label="FRAME project">
        <span class="label">Project</span><strong class="small">${f.name || '—'}</strong>
        <span class=${'small mono ' + (f.error ? 'warn' : 'muted')}>${f.status}</span>
        <span class="grow"></span>
        <label class="sr-only" for="frame-style">Style</label>
        <select id="frame-style" class="input sm" style="width:auto;max-width:220px" disabled=${!f.ok || !!S} value=${f.styleId} onChange=${(e) => this.frameSet({ styleId: e.target.value })}>
          ${f.styles.length ? null : html`<option value="">No styles yet</option>`}
          ${f.styles.map((st) => html`<option value=${st.style_id}>${st.name} · rev ${st.revision}${st.use_scope.type === 'brand' ? ' · ' + st.use_scope.brand : ''}${st.owned ? '' : ' · starter'}</option>`)}
        </select>
        <button type="button" class="btn sm" disabled=${!f.ok} onClick=${() => this.frameSet({ panel: f.panel === 'styles' ? null : 'styles', note: '' })}>Styles…</button>
        ${S ? html`<button type="button" class="btn sm" onClick=${this.framePause}>${S.paused ? 'Resume' : 'Pause'}</button>
                   <button type="button" class="btn sm" onClick=${this.frameStop}>Stop</button>`
            : html`<button type="button" class="btn-primary" disabled=${!f.ok || !f.styleId} onClick=${this.frameRunStyle}>Assemble with style</button>`}
        <label class="sr-only" for="frame-pace">Agent speed</label>
        <select id="frame-pace" class="input sm" style="width:auto" value=${String(f.pace || 1)} onChange=${(e) => this.frameSet({ pace: parseFloat(e.target.value) })}>
          <option value="1">Speed: fast</option><option value="3">Speed: watch</option><option value="6">Speed: slow-mo</option>
        </select>
        ${f.words ? null : html`<button type="button" class="btn sm" disabled=${!f.ok} onClick=${this.frameTranscribe}>Transcribe</button>`}
        ${(f.kits || []).length ? html`<button type="button" class="btn-primary" disabled=${!f.ok || !!S} onClick=${() => this.frameRunV3()}>Build v3</button>
          <button type="button" class="btn sm" disabled=${!f.ok} onClick=${() => this.frameSet({ panel: 'v3' })}>v3 visuals…</button>
          ${this.v3On() ? html`<label class="small" style="display:inline-flex;align-items:center;gap:6px">Caption height
            <input type="range" min="700" max="1800" step="10" value=${this.v3CapY()} aria-valuetext=${Math.round(this.v3CapY() / 19.2) + '% down'} onInput=${(e) => this.v3SetCapY(+e.target.value, false)} onChange=${(e) => this.v3SetCapY(+e.target.value, true)} style="width:110px" /></label>` : null}
          ${this.v3On() && !S && !(f.v3render && f.v3render.status === 'working') ? html`<button type="button" class="btn sm" onClick=${() => this.frameRenderV3()}>Render v3</button>` : null}
          ${this.v3On() && !S ? html`<button type="button" class="btn sm" onClick=${() => this.v3SaveStyle()}>Save as style</button>` : null}
          <button type="button" class="btn sm" disabled=${!f.ok || !!S} onClick=${() => this.v3OpenStyles()}>First cut from a style…</button>
          ${f.v3render && f.v3render.status === 'working' ? html`<span class="small mono muted">v3 rendering ${f.v3render.progress || ''}</span>` : null}
          ${f.v3render && f.v3render.status === 'failed' ? html`<span class="small warn" style="flex-basis:100%">v3 render failed: ${f.v3render.error}</span>` : null}
          ${f.v3render && f.v3render.status === 'done' ? html`<a class="btn sm" href=${f.v3render.url + '?download=1'}>Download v3 cut</a><button type="button" class="btn sm" onClick=${() => this.frameSet({ panel: 'v3' })}>Watch v3 cut</button>` : null}` : null}
        <button type="button" class="btn sm" disabled=${!f.ok || (ex && ex.status === 'working')} onClick=${this.frameExport}>${ex && ex.status === 'working' ? 'Exporting…' : 'Export MP4'}</button>
        ${ex && ex.status === 'done' ? html`<a class="btn sm" href=${ex.url + '?download=1'}>Download v${ex.timeline_version}</a>` : null}
        ${ex && ex.status === 'failed' ? html`<span class="small warn">Export failed: ${ex.error}</span>` : null}
        ${f.note ? html`<span class="small muted" style="flex-basis:100%">${f.note}</span>` : null}
        ${f.error ? html`<span class="small warn" style="flex-basis:100%">${f.error}</span>` : null}
      </div>`;
    }

    framePanel() {
      const f = this.frame;
      if (f.panel !== 'styles') return null;
      const d = f.draft;
      const close = () => this.frameSet({ panel: null, draft: null, note: '' });
      return html`<div class="modal-back" onClick=${(e) => { if (e.target === e.currentTarget) close(); }}>
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="styles-title">
          <div class="head-row"><h2 id="styles-title">Styles</h2><button type="button" class="btn sm" onClick=${close}>Close</button></div>
          <p class="small muted" style="margin:0">FRAME edits only from a source you choose: this edit, a reference video, or a starter. Styles apply the same way every time.</p>
          <div class="card">
            <h3 class="label">Save this edit as a style</h3>
            <div class="row wrap">
              <input id="st-name" class="input sm" style="flex:1 1 180px" placeholder="Style name, e.g. AGI Guide series" />
              <input id="st-brand" class="input sm" style="flex:1 1 140px" placeholder="Brand (optional)" />
              <button type="button" class="btn-primary" onClick=${() => {
                const name = (document.getElementById('st-name').value || '').trim();
                const brand = (document.getElementById('st-brand').value || '').trim();
                if (!name) { this.frameSet({ note: 'Name the style first.' }); return; }
                this.frameSaveStyle(this.styleFromEdit(name, 'own_video', brand));
              }}>Save style</button>
            </div>
            <p class="small muted" style="margin:0">Captures your caption style, color, levels and how tight you cut pauses.</p>
          </div>
          <div class="card">
            <h3 class="label">Measure a reference video</h3>
            <div class="row wrap">
              <input id="st-ref-file" class="vh" type="file" accept="video/*,.mov,.mp4,.m4v" onChange=${(e) => this.frameUploadReference(e)} />
              <input id="st-ref-brand" class="input sm" style="flex:1 1 140px" placeholder="Brand that sent it (optional)" />
              <label for="st-ref-file" class="btn-primary">Upload a reference video</label>
              <span class="small muted">A finished video whose editing you want to copy, e.g. the one a brand sent you.</span>
            </div>
            ${f.refs.length ? html`<div class="row wrap">
              <select id="st-ref" class="input sm" style="width:auto">${f.refs.map((r) => html`<option value=${r.id}>${r.name}</option>`)}</select>
              <button type="button" class="btn" onClick=${() => this.frameMeasure(document.getElementById('st-ref').value, (document.getElementById('st-ref-brand').value || '').trim())}>Measure</button>
            </div>` : null}
            ${d ? html`<div class="detail">
              <ol class="small" style="margin:0;padding-left:18px">${this.recipeLines(d.style).map((l) => html`<li>${l}</li>`)}</ol>
              <div class="small muted">Measured from the reference: ${Object.keys(d.style.evidence || {}).join(', ') || 'nothing'}. Captions come from your current caption settings (pick them in step 4 before saving). Not measured yet: music/logo assets, b-roll.</div>
              <div class="row wrap">
                <input id="st-draft-name" class="input sm" style="flex:1 1 180px" value=${d.style.name} />
                <button type="button" class="btn-primary" onClick=${() => { const st = Object.assign({}, d.style, { name: (document.getElementById('st-draft-name').value || d.style.name).trim() }); delete st.owned;
                  if (!st.captions) { st.captions = this.styleFromEdit('x', 'own_video').captions; st.evidence = Object.assign({}, st.evidence, { 'captions.style': { method: 'user_set', note: 'taken from this edit' } }); }
                  this.frameSaveStyle(st); }}>Save measured style</button>
              </div>
            </div>` : null}
          </div>
          ${f.note ? html`<p class="small muted" style="margin:0">${f.note}</p>` : null}
        </div>
      </div>`;
    }
  }

  // ------------------------------------------------------------------ documented recipe replay
  const RECIPE = new URLSearchParams(location.search).get('recipe');
  const LANE_AGENT = { caps: ['caps-01', 'caps-02'], bcoll: ['bcoll-01', 'bcoll-02'], mix: ['mix-01'], razor: ['razor-01', 'razor-02'], gfx: ['gfx-01'], grade: ['grade-01', 'grade-02'] };
  const TRACK_AGENT = { v1: 'razor-01', v2: 'bcoll-01', t1: 'caps-01', s1: 'gfx-01', a1: 'mix-01', a2: 'mix-01', fx: 'grade-01' };
  const sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  class RecipeApp extends App {
    constructor(props) {
      super(props);
      this.media = []; this.logs = [];
      this.p = Object.assign(initialProject(), { clips: [], nid: 1 });
      this.r = { name: RECIPE, recipe: null, step: -1, show: null, text: '', running: false, paused: false, pace: 2, done: false,
        params: {}, render: null, error: '', panel: false };
      this.state.mode = 'pro';
      this.log('system', 'Loading the documented recipe…');
    }
    componentDidMount() {
      super.componentDidMount();
      this.setState({ mode: 'pro', title: RECIPE });
      api('GET', '/api/recipes/' + encodeURIComponent(RECIPE)).then((recipe) => {
        const params = {};
        Object.keys((recipe.rebuild || {}).params || {}).forEach(function (k) { params[k] = recipe.rebuild.params[k].default; });
        this.rset({ recipe: recipe, params: params });
        this.log('system', '“' + recipe.title + '”: ' + recipe.steps.length + ' documented steps, ' + recipe.duration + ' s final. Press Replay production.');
      }).catch((e) => this.rset({ error: 'Could not load the recipe: ' + e.message }));
    }
    rset(patch) { Object.assign(this.r, patch); this.bump(); }
    url(path) { return '/recipe-media/' + encodeURIComponent(RECIPE) + '/' + path.split('/').map(encodeURIComponent).join('/'); }
    setMode(mode) { super.setMode(mode); }
    audioEvents() {}
    clipName(c) { return c.label || super.clipName(c); }
    importVideo(f) { this.log('system', 'This is a documented recipe; its media comes from the production record.'); }
    runOneClick() { this.replay(); }
    runCommand(text) {
      if (/^(pause|resume|stop)\b/i.test(String(text || '').trim())) { this.log('you', '› ' + text); return /stop/i.test(text) ? this.stop() : this.pause(); }
      this.log('you', '› ' + text);
      this.log('system', 'In a recipe, the agents only perform documented steps. Use Change & re-render to change the intro prompt or background brightness.');
    }

    async showArtifact(show) {
      this.rset({ show: show, text: '' });
      if (show && show.kind === 'text') {
        try { const r = await fetch(this.url(show.path)); this.rset({ text: (await r.text()).slice(0, 4000) }); } catch (e) {}
      }
    }

    mediaFor(pl) {
      const id = 'r' + (++this.mid);
      const kind = /\.(mp4|mov)$/i.test(pl.media || '') ? 'video' : 'image';
      const url = pl.media ? this.url(pl.media) : null;
      this.media = this.media.concat([{ id: id, kind: kind, name: pl.label, url: url, thumb: kind === 'image' ? url : null, local: true, dur: pl.end - pl.start, hasAudio: false, status: '' }]);
      if (kind === 'image' && url) this.measureImage(id, url);
      return id;
    }

    placeClip(pl, step) {
      const dur = Math.max(0.05, (pl.end != null ? pl.end : pl.start + (pl.dur || 0.5)) - pl.start);
      let p = this.p;
      if (pl.track === 't1') {
        // Caption cues ride on the film's word track so the TEXT lane shows each cue at its time.
        const film = this.media.find(function (m) { return m.role === 'film'; });
        if (film) {
          const words = (film.words || []).concat([{ w: pl.label, s: +(pl.start - 2.2).toFixed(3), e: +(pl.end - 2.2).toFixed(3) }]);
          this.updateMedia(film.id, { words: words, wordsExact: true });
          p = setCaps(p, { per: 1, style: 'minimal' });
          return p;
        }
      }
      if (pl.track === 'v1') {
        const id = this.mediaFor(pl);
        this.updateMedia(id, { role: 'film', hasAudio: true });
        return addClip(p, { tr: 'v1', m: id, in: 0, out: dur, start: pl.start });
      }
      if (pl.track === 'a2') {
        const id = this.mediaFor(pl); this.updateMedia(id, { kind: 'audio' });
        const others = p.clips.filter(function (c) { return c.tr !== 'a2'; });
        return addClip(Object.assign({}, p, { clips: others }), { tr: 'a2', m: id, in: 0, start: pl.start, dur: dur });
      }
      if (pl.track === 'a1') return Object.assign({}, p, { mute: Object.assign({}, p.mute) });
      if (pl.track === 'v2') return addClip(p, { tr: 'v2', m: this.mediaFor(pl), start: pl.start, dur: dur });
      if (pl.track === 'fx') return addClip(p, { tr: 'fx', start: pl.start, dur: dur, label: pl.label });
      return addClip(p, { tr: pl.track, start: pl.start, dur: dur, label: pl.label });
    }

    async waitIfPaused() { while (this.r.paused && this.r.running) await sleep(200); }

    async replay() {
      const recipe = this.r.recipe;
      if (!recipe || this.r.running) return;
      this.media = []; this.p = Object.assign(initialProject(), { clips: [], nid: 1 }); this.undoStack = []; this.redoStack = [];
      this.logs = []; this.mid = 0;
      const live = new Set(AGENTS.map(function (a) { return a.id; }));
      this.swarm = { timers: [], live: live, paused: false, ops: 0 };
      this.rset({ running: true, paused: false, done: false, step: -1 });
      this.bump({ swarmOn: true });
      this.log('system', 'Replaying the documented production of “' + recipe.title + '”. Every step below happened; every file shown is the real output.');
      for (let i = 0; i < recipe.steps.length && this.r.running; i++) {
        const st = recipe.steps[i];
        await this.waitIfPaused();
        if (!this.r.running) break;
        this.rset({ step: i });
        if (st.request) this.log('you', '“' + st.request + '”');
        const crew = LANE_AGENT[st.lane] || ['mix-01'];
        const lead = crew[0];
        const tgt = this.cursorTarget({ area: 'program' });
        if (tgt) Object.assign(this.agentPos[lead], { x: tgt.x, y: tgt.y, op: 1 });
        await this.showArtifact(st.show);
        await sleep(500 * this.r.pace);
        for (let k = 0; k < st.place.length && this.r.running; k++) {
          await this.waitIfPaused();
          const pl = st.place[k];
          const who = TRACK_AGENT[pl.track] || lead;
          const at = this.cursorTarget({ lane: pl.track === 'a1' ? 'a1' : pl.track, area: 'timeline', time: function () { return pl.start; } });
          if (at) Object.assign(this.agentPos[who], { x: at.x, y: at.y, op: 1 });
          this.bump();
          await sleep((st.place.length > 10 ? 90 : 260) * this.r.pace);
          this.p = this.placeClip(pl, st); this.swarm.ops++;
          this.bump({ selA: null, selB: null });
        }
        this.log(lead, st.phase + ' · ' + st.title + ': ' + st.did);
        await sleep(700 * this.r.pace);
      }
      const finished = this.r.running;
      this.swarm = null;
      AGENTS.forEach((a) => { this.agentPos[a.id].op = 0; });
      this.rset({ running: false, paused: false, done: finished });
      this.bump({ swarmOn: false });
      if (finished) this.log('system', 'Replay complete. This is the approved final, rebuilt from its recipe. Change the intro below and re-render to see the same recipe produce a new cut.');
    }
    pause() { this.rset({ paused: !this.r.paused }); this.log('you', this.r.paused ? 'paused the replay' : 'resumed'); }
    stop() { this.rset({ running: false, paused: false }); }

    async rerender() {
      this.rset({ render: { status: 'working' } });
      try {
        let job = await api('POST', '/api/recipes/' + encodeURIComponent(RECIPE) + '/rebuild', { params: this.r.params });
        this.log('gfx-01', 'Re-rendering with ' + JSON.stringify(job.params) + ' using the production’s own compositor (V8/V9 scripts).');
        while (job.status === 'working') { await sleep(1500); job = await api('GET', '/api/recipes/' + encodeURIComponent(RECIPE) + '/rebuild/' + job.key); }
        if (job.status !== 'done') throw new Error(job.error || 'render failed');
        this.rset({ render: job });
        await this.showArtifact({ kind: 'video', path: job.path, label: 'Re-rendered: ' + JSON.stringify(job.params) });
        this.log('system', 'New cut ready' + (job.cached ? ' (same settings as before, so the identical file was reused)' : '') + '.');
      } catch (e) { this.rset({ render: { status: 'failed', error: e.message } }); }
    }

    monitor(v) {
      const sh = this.r.show;
      const st = this.r.recipe && this.r.step >= 0 ? this.r.recipe.steps[this.r.step] : null;
      let body = html`<div class="gap">Press Replay production</div>`;
      if (sh && sh.kind === 'video') body = html`<video key=${sh.path} src=${this.url(sh.path)} autoplay=${true} muted=${!(st && st.final) && !sh.label} controls=${true} loop=${!(st && st.final)} playsinline style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000"></video>`;
      else if (sh && sh.kind === 'image') body = html`<img key=${sh.path} src=${this.url(sh.path)} alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000" />`;
      else if (sh && sh.kind === 'audio') body = html`<div class="gap" style="flex-direction:column;gap:12px;color:#eaece6"><strong>Narration</strong><audio key=${sh.path} src=${this.url(sh.path)} controls=${true}></audio></div>`;
      else if (sh && sh.kind === 'text') body = html`<pre style="position:absolute;inset:0;margin:0;padding:18px;overflow:auto;white-space:pre-wrap;background:#fbfcf7;color:#14160f;font:13px/1.5 var(--ui)">${this.r.text || '…'}</pre>`;
      return html`<div class="monitor" data-area="program">${body}
        ${st ? html`<div style="position:absolute;left:8px;top:8px;right:8px;padding:4px 8px;border-radius:6px;background:rgba(0,0,0,.65);color:#fff;font:600 11px/1.3 var(--mono)">${st.phase} · ${(sh && sh.path) || ''}</div>` : null}
      </div>`;
    }

    header(v, s, pro) {
      const r = this.r, rec = r.recipe, spec = rec && rec.rebuild ? rec.rebuild.params : {};
      const st = rec && r.step >= 0 ? rec.steps[r.step] : null;
      const bar = html`<div class="frame-bar" role="region" aria-label="Recipe">
        <span class="label">Recipe</span><strong class="small">${rec ? rec.title : RECIPE}</strong>
        <span class="small mono muted">${st ? 'Step ' + (r.step + 1) + '/' + rec.steps.length + ' · ' + st.title : (rec ? rec.steps.length + ' steps' : '')}</span>
        <span class="grow"></span>
        <label class="sr-only" for="r-pace">Speed</label>
        <select id="r-pace" class="input sm" style="width:auto" value=${String(r.pace)} onChange=${(e) => this.rset({ pace: parseFloat(e.target.value) })}>
          <option value="1">Speed: fast</option><option value="2">Speed: watch</option><option value="4">Speed: slow-mo</option>
        </select>
        ${r.running ? html`<button type="button" class="btn sm" onClick=${() => this.pause()}>${r.paused ? 'Resume' : 'Pause'}</button><button type="button" class="btn sm" onClick=${() => this.stop()}>Stop</button>`
          : html`<button type="button" class="btn-primary" disabled=${!rec} onClick=${() => this.replay()}>${r.done ? 'Replay again' : 'Replay production'}</button>`}
        <button type="button" class="btn sm" disabled=${!rec} onClick=${() => this.rset({ panel: !r.panel })}>Change & re-render</button>
        ${rec ? html`<a class="btn sm" href=${this.url(rec.final) + '?download=1'}>Approved final</a>` : null}
        ${r.render && r.render.status === 'done' ? html`<a class="btn sm" href=${this.url(r.render.path) + '?download=1'}>Download new cut</a>` : null}
        ${r.error ? html`<span class="small warn" style="flex-basis:100%">${r.error}</span>` : null}
        ${r.panel && rec ? html`<div class="card" style="flex-basis:100%;flex-direction:row;flex-wrap:wrap;align-items:flex-end;gap:12px">
          ${Object.keys(spec).map((k) => spec[k].type === 'text'
            ? html`<label class="small" style="display:flex;flex-direction:column;gap:4px;flex:1 1 220px">${spec[k].label}<input class="input sm" maxlength=${spec[k].max} value=${r.params[k]} onInput=${(e) => { r.params[k] = e.target.value; }} /></label>`
            : html`<label class="small" style="display:flex;flex-direction:column;gap:4px;flex:1 1 220px">${spec[k].label}: <span class="mono">${Math.round(r.params[k] * 100)}%</span><input type="range" min=${spec[k].min} max=${spec[k].max} step=${spec[k].step} value=${r.params[k]} onInput=${(e) => { r.params[k] = parseFloat(e.target.value); this.bump(); }} /></label>`)}
          <button type="button" class="btn-primary" disabled=${r.render && r.render.status === 'working'} onClick=${() => this.rerender()}>${r.render && r.render.status === 'working' ? 'Rendering… (~30 s)' : 'Re-render final'}</button>
          ${r.render && r.render.status === 'failed' ? html`<span class="small warn">Render failed: ${r.render.error}</span>` : null}
          <span class="small muted" style="flex-basis:100%">Runs the production’s own V8/V9 compositor with only these values changed. Same values always give the same file.</span>
        </div>` : null}
      </div>`;
      return [super.header(v, s, pro), bar];
    }
  }

  const css = document.createElement('style');
  css.textContent = '.c-g1{background:#1f2a12;color:#d9f59a;border-color:#3d5220}.v3insp{position:absolute;left:0;right:0;top:calc(100% + 10px);height:250px;overflow:auto;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--panel);display:flex;flex-direction:column;gap:8px;text-align:left;z-index:3}.v3insp label{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center}.v3insp .row{display:flex;flex-wrap:wrap;gap:6px}.v3card{display:flex;flex-direction:column;gap:8px;padding-top:8px;border-top:1px solid var(--line)}.v3card .input{max-width:100%}.v3wrap{margin-bottom:270px}.lane .clip::before,.lane .clip::after{content:"";position:absolute;top:0;bottom:0;width:7px;cursor:ew-resize;background:rgba(255,255,255,.18)}.lane .clip::before{left:0;border-radius:4px 0 0 4px}.lane .clip::after{right:0;border-radius:0 4px 4px 0}.frame-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;padding:10px 0;border-bottom:1px solid var(--line)}.frame-bar .warn{color:var(--warn)}';
  document.head.appendChild(css);
  render(RECIPE ? html`<${RecipeApp} />` : html`<${FrameApp} />`, document.getElementById('app'));
})();
