#!/usr/bin/env node
/* Capture FRAME's live preview at chosen times, plus what the editor says is on screen there.

   NODE_PATH=~/frame-test-runs/tools/node_modules node work/frame-product/tests/v3_preview_capture.cjs \
     --project <test project id> --out ~/frame-test-runs/compare-1 [--base http://127.0.0.1:8890] [--times 1,4.2,13]

   Without --times it samples every section's middle, every overlay's middle and every 5th caption.
   Writes preview_<t>.png (540x960, the canvas itself), state.json (timeline + what is visible at each t),
   timeline.json (exactly what Render sends). Read-only: it never edits or saves the project. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
const base = args.base || 'http://127.0.0.1:8890';
if (!args.project || !args.out) { console.error('usage: --project <id> --out <dir> [--times 1,2.5] [--base url]'); process.exit(2); }
if (args.project === '8ba3cd4acef0484dbb2a2d9a6927abe4' && !args['allow-approved']) { console.error('Refusing to open the approved Fable project; test on a copy.'); process.exit(2); }
fs.mkdirSync(args.out, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.goto(base + '/swarm?project=' + args.project + '#pro');
  await page.waitForFunction(() => window.frameEditor && window.frameEditor.frame.ok && window.frameEditor.v3On(), null, { timeout: 60000 });
  // read-only: block autosave so capturing can never write to the project
  await page.evaluate(() => { window.frameEditor.frameSaveNow = async () => {}; });
  const timeline = await page.evaluate(() => window.frameEditor.v3Timeline());
  fs.writeFileSync(path.join(args.out, 'timeline.json'), JSON.stringify(timeline, null, 1));
  let times;
  if (args.times) times = args.times.split(',').map(Number);
  else {
    const t = new Set();
    timeline.segments.forEach((s) => t.add(+((s.t0 + s.t1) / 2).toFixed(2)));
    timeline.graphics.forEach((g) => t.add(+((g.t0 + Math.min(g.t1, g.t0 + 2)) / 2 + 0.3).toFixed(2)));
    timeline.captions.forEach((c, i) => { if (i % 5 === 0) t.add(+((c.t0 + c.t1) / 2).toFixed(2)); });
    const end = timeline.lines.reduce((m, l) => Math.max(m, l.out + l.src_out - l.src_in), 0);
    times = [...t].filter((x) => x > 0.1 && x < end - 0.1).sort((a, b) => a - b);
  }
  const state = { project: args.project, base, times: [], errors };
  for (const t of times) {
    await page.evaluate((t) => window.frameEditor.seek(t), t);
    // wait until every video the preview draws from has settled on its frame
    await page.waitForFunction(() => {
      const a = window.frameEditor;
      const vids = Array.from(document.querySelectorAll('video[data-mid]')).filter((v) => !v.paused || v.currentTime > 0);
      const kit = Object.values(a.v3vids || {});
      return [...vids, ...kit].every((v) => !v.seeking && v.readyState >= 2);
    }, null, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(500);
    const shot = await page.evaluate(() => {
      const a = window.frameEditor, t = a.t, p = a.p;
      const sec = a.v3Sections().filter((c) => t >= c.start && t < c.start + c.dur).sort((x, y) => y.start - x.start)[0];
      const seg = sec ? a.v3SegOut(sec) : null;
      return {
        t: +t.toFixed(3),
        png: document.querySelector('canvas[data-v3]').toDataURL('image/png'),
        section: seg ? { kind: seg.kind, t0: seg.t0, t1: seg.t1, label: seg.label || seg.head || seg.keyword || '', media: seg.media || null, media_in: seg.media_in } : { kind: 'face' },
        captions: p.clips.filter((c) => c.tr === 't1' && t >= c.start && t < c.start + c.dur).map((c) => ({ text: c.tokens.map((k) => k.text).join(' '), y: c.y, x: c.x, k: c.k })),
        graphics: p.clips.filter((c) => c.tr === 'g1' && t >= c.start && t < c.start + c.dur).map((c) => ({ type: c.g.type, name: a.v3GfxName(c), x: c.x, y: c.y, k: c.k })),
        boxes: a._v3boxes
      };
    });
    const file = 'preview_' + shot.t.toFixed(2) + '.png';
    fs.writeFileSync(path.join(args.out, file), Buffer.from(shot.png.split(',')[1], 'base64'));
    delete shot.png; shot.file = file;
    state.times.push(shot);
    console.log('captured', shot.t, shot.section.kind, shot.section.label || '');
  }
  fs.writeFileSync(path.join(args.out, 'state.json'), JSON.stringify(state, null, 1));
  console.log('wrote', state.times.length, 'previews to', args.out, errors.length ? '(' + errors.length + ' browser errors in state.json)' : '');
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
