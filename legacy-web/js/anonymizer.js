import { detectAll, CATEGORIES } from './detectors.js';
import * as pdfjs from '../vendor/pdf.min.mjs';
import { recognizeCanvas } from './ocrService.js';

// Track transformation matrices (CTM) from the PDF operator list.

function mmul(a, b) {
  return [
    a[0] * b[0] + a[2] * b[1],
    a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3],
    a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4],
    a[1] * b[4] + a[3] * b[5] + a[5],
  ];
}

function makeCtmState() {
  let ctm = [1, 0, 0, 1, 0, 0];
  const stack = [];
  return {
    transform(m) { ctm = mmul(ctm, m); },
    save() { stack.push(ctm); },
    restore() { ctm = stack.pop() || ctm; },
    get() { return ctm; },
  };
}

const IMAGE_OPS = ['paintImageXObject', 'paintInlineImageXObject', 'paintImageMaskXObject', 'paintJpegXObject'];

async function extractImageBoxes(page, viewport) {
  const op = await page.getOperatorList();
  const OPS = pdfjs.OPS;
  const fn = op.fnArray;
  const args = op.argsArray;
  const st = makeCtmState();
  const raw = [];
  for (let i = 0; i < fn.length; i++) {
    const f = fn[i];
    if (f === OPS.transform) st.transform(args[i]);
    else if (f === OPS.save) st.save();
    else if (f === OPS.restore) st.restore();
    else if (f === OPS.rotate90) st.transform([0, 1, -1, 0, 0, 0]);
    else if (f === OPS.rotate180) st.transform([-1, 0, 0, -1, 0, 0]);
    else if (f === OPS.rotate270) st.transform([0, -1, 1, 0, 0, 0]);
    else if (IMAGE_OPS.some((k) => OPS[k] !== undefined && OPS[k] === f)) {
      const { 0: a, 1: b, 2: c, 3: d, 4: e, 5: f2 } = st.get();
      const pts = [[0, 0], [1, 0], [1, 1], [0, 1]].map(([u, v]) => [
        a * u + c * v + e,
        b * u + d * v + f2,
      ]);
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const [px, py] of pts) {
        const [vx, vy] = viewport.convertToViewportPoint(px, py);
        minX = Math.min(minX, vx); minY = Math.min(minY, vy);
        maxX = Math.max(maxX, vx); maxY = Math.max(maxY, vy);
      }
      raw.push({ x: minX, y: minY, w: maxX - minX, h: maxY - minY });
    }
  }
  const boxes = [];
  for (const b of raw) {
    if (b.w < 1 || b.h < 1) continue;
    const lb = {
      x: Math.floor(b.x), y: Math.floor(b.y),
      w: Math.ceil(b.w), h: Math.ceil(b.h),
    };
    if (boxes.some((p) => Math.abs(p.x - lb.x) < 3 && Math.abs(p.y - lb.y) < 3
      && Math.abs(p.w - lb.w) < 3 && Math.abs(p.h - lb.h) < 3)) continue;
    boxes.push(lb);
  }
  return boxes;
}

function buildEntries(items) {
  const entries = [];
  let pos = 0;
  for (const it of items) {
    const start = pos;
    const end = start + it.str.length;
    pos = end + 1;
    entries.push({ start, end });
  }
  return entries;
}

function buildText(items) {
  let text = '';
  for (let index = 0; index < items.length; index++) {
    text += items[index].str;
    if (index < items.length - 1) text += items[index].hasEOL ? '\n' : ' ';
  }
  return text;
}

function matchToRects(match, entries, rects) {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (let i = 0; i < entries.length; i++) {
    const en = entries[i];
    if (en.end <= match.start || en.start >= match.end) continue;
    const r = rects[i];
    if (!r || r.w <= 0) continue;
    const itemLength = Math.max(1, en.end - en.start);
    const horizontal = Math.abs(Math.sin(r.angle || 0)) < 0.1;
    const startFraction = horizontal ? Math.max(0, match.start - en.start) / itemLength : 0;
    const endFraction = horizontal ? Math.min(itemLength, match.end - en.start) / itemLength : 1;
    const rx1 = r.x + r.w * startFraction;
    const ry1 = r.y;
    const rx2 = r.x + r.w * endFraction;
    const ry2 = r.y + r.h;
    x1 = Math.min(x1, rx1); y1 = Math.min(y1, ry1);
    x2 = Math.max(x2, rx2); y2 = Math.max(y2, ry2);
  }
  if (!isFinite(x1)) return null;
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

function trimValue(s) {
  return s.replace(/\s+/g, ' ').trim();
}

function textItemRect(item, viewport) {
  const transform = pdfjs.Util.transform(viewport.transform, item.transform);
  const baselineLength = Math.hypot(transform[0], transform[1]) || 1;
  const width = Math.max(0, item.width * viewport.scale);
  const widthVector = [transform[0] / baselineLength * width, transform[1] / baselineLength * width];
  const heightVector = [transform[2], transform[3]];
  const origin = [transform[4], transform[5]];
  const points = [
    origin,
    [origin[0] + widthVector[0], origin[1] + widthVector[1]],
    [origin[0] + heightVector[0], origin[1] + heightVector[1]],
    [origin[0] + widthVector[0] + heightVector[0], origin[1] + widthVector[1] + heightVector[1]],
  ];
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return {
    x: Math.min(...xs), y: Math.min(...ys),
    w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys),
    angle: Math.atan2(transform[1], transform[0]),
  };
}

function normalizeRect(rect) {
  const x1 = Math.min(rect[0], rect[2]);
  const y1 = Math.min(rect[1], rect[3]);
  const x2 = Math.max(rect[0], rect[2]);
  const y2 = Math.max(rect[1], rect[3]);
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

function overlapsExisting(rect, redacts) {
  return redacts.some((item) => {
    const other = item.rect;
    if (!other) return false;
    const overlapWidth = Math.max(0, Math.min(rect.x + rect.w, other.x + other.w) - Math.max(rect.x, other.x));
    const overlapHeight = Math.max(0, Math.min(rect.y + rect.h, other.y + other.h) - Math.max(rect.y, other.y));
    const overlap = overlapWidth * overlapHeight;
    return overlap > Math.min(rect.w * rect.h, other.w * other.h) * 0.7;
  });
}

function appendDetected(redacts, matches, entries, rects, pageNumber, source) {
  const detectionsFromEarlierSources = [...redacts];
  for (const match of matches) {
    const rect = matchToRects(match, entries, rects);
    if (!rect || overlapsExisting(rect, detectionsFromEarlierSources)) continue;
    redacts.push({
      id: `p${pageNumber}-t${redacts.length}`,
      page: pageNumber,
      type: match.type,
      original: trimValue(match.value),
      confidence: match.confidence ?? 0.7,
      validationWarning: match.validationWarning ?? null,
      source,
      start: match.start,
      end: match.end,
      rect,
    });
  }
}

function collectOcrLines(blocks) {
  const lines = [];
  for (const block of blocks || []) {
    for (const paragraph of block.paragraphs || []) {
      for (const line of paragraph.lines || []) lines.push(line);
    }
  }
  return lines;
}

function addOcrDetections(redacts, ocrData, pageNumber, categories) {
  for (const line of collectOcrLines(ocrData.blocks)) {
    const words = (line.words || []).filter((word) => word.text?.trim() && word.confidence >= 35);
    if (!words.length) continue;
    const items = words.map((word) => ({ str: word.text.trim(), hasEOL: false }));
    const text = buildText(items);
    const entries = buildEntries(items);
    const rects = words.map((word) => ({
      x: word.bbox.x0,
      y: word.bbox.y0,
      w: word.bbox.x1 - word.bbox.x0,
      h: word.bbox.y1 - word.bbox.y0,
    }));
    const matches = detectAll(text).filter((match) => !categories || categories.has(match.type));
    appendDetected(redacts, matches, entries, rects, pageNumber, 'ocr');
  }
}

async function addFormDetections(page, viewport, redacts, pageNumber, categories) {
  const annotations = await page.getAnnotations({ intent: 'display' });
  for (const annotation of annotations) {
    if (annotation.subtype !== 'Widget' || annotation.fieldValue == null || !annotation.rect) continue;
    const value = Array.isArray(annotation.fieldValue) ? annotation.fieldValue.join(' ') : String(annotation.fieldValue);
    if (!value.trim() || value === 'Off') continue;
    const label = String(annotation.fieldName || 'campo');
    const prefix = `${label}: `;
    const matches = detectAll(prefix + value)
      .filter((match) => match.end > prefix.length && (!categories || categories.has(match.type)))
      .map((match) => ({ ...match, value: value.trim() }));
    if (!matches.length) continue;
    const firstCorner = viewport.convertToViewportPoint(annotation.rect[0], annotation.rect[1]);
    const secondCorner = viewport.convertToViewportPoint(annotation.rect[2], annotation.rect[3]);
    const rect = normalizeRect([...firstCorner, ...secondCorner]);
    if (rect.w <= 0 || rect.h <= 0 || overlapsExisting(rect, redacts)) continue;
    const match = matches[0];
    redacts.push({
      id: `p${pageNumber}-t${redacts.length}`,
      page: pageNumber,
      type: match.type,
      original: value.trim(),
      confidence: Math.max(0.9, match.confidence ?? 0),
      validationWarning: match.validationWarning ?? null,
      source: 'form',
      rect,
    });
  }
}

async function processPage(page, pageNumber, options, faceDetector, onStatus, numPages) {
  const scale = options.scale;
  const viewport = page.getViewport({ scale });
  const viewport1 = page.getViewport({ scale: 1 });

  const canvas = document.createElement('canvas');
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  const ctx = canvas.getContext('2d', { alpha: false });
  await page.render({ canvasContext: ctx, viewport, background: '#ffffff' }).promise;

  const tc = await page.getTextContent({ normalizeWhitespace: false });
  const items = tc.items.filter((it) => typeof it.str === 'string');
  const entries = buildEntries(items);
  const fullText = buildText(items);

  const rects = items.map((item) => textItemRect(item, viewport));

  const detected = detectAll(fullText).filter((m) => !options.cats || options.cats.has(m.type));
  const redacts = [];
  appendDetected(redacts, detected, entries, rects, pageNumber, 'text');
  await addFormDetections(page, viewport, redacts, pageNumber, options.cats);

  if (options.useOcr) {
    onStatus({ phase: 'ocr', page: pageNumber, numPages });
    const ocrData = await recognizeCanvas(canvas);
    addOcrDetections(redacts, ocrData, pageNumber, options.cats);
  }

  let faces = [];
  if (options.redactFaces && faceDetector) {
    const boxes = await extractImageBoxes(page, viewport);
    const srcW = canvas.width;
    const srcH = canvas.height;
    const seen = [];
    for (const b of boxes) {
      const crop = document.createElement('canvas');
      crop.width = b.w;
      crop.height = b.h;
      crop.getContext('2d').drawImage(canvas, b.x, b.y, b.w, b.h, 0, 0, b.w, b.h);
      let dets = [];
      try { dets = faceDetector.detect(crop) || []; } catch { continue; }
      for (const d of dets) {
        const fx = b.x + d.nx;
        const fy = b.y + d.ny;
        const fw = Math.min(d.nw, b.w - d.nx);
        const fh = Math.min(d.nh, b.h - d.ny);
        if (fw <= 2 || fh <= 2) continue;
        if (seen.some((p) => Math.abs(p.x - fx) < 2 && Math.abs(p.y - fy) < 2
          && Math.abs(p.w - fw) < 2 && Math.abs(p.h - fh) < 2)) continue;
        seen.push({ x: fx, y: fy, w: fw, h: fh });
        faces.push({
          id: `p${pageNumber}-f${faces.length}`,
          page: pageNumber,
          type: 'face',
          original: null,
          confidence: 0.85,
          nx: fx / srcW,
          ny: fy / srcH,
          nw: fw / srcW,
          nh: fh / srcH,
        });
      }
    }
  }

  return {
    pageNumber,
    widthPx: canvas.width,
    heightPx: canvas.height,
    pdfWidth: viewport1.width,
    pdfHeight: viewport1.height,
    scale,
    baseCanvas: canvas,
    textCharacters: fullText.replace(/\s/g, '').length,
    redacts,
    faces,
  };
}

function sampleBackground(ctx, cW, cH, x, y, w, h) {
  const pts = [];
  const push = (px, py) => {
    if (px < 1 || py < 1 || px >= cW - 1 || py >= cH - 1) return;
    const d = ctx.getImageData(px, py, 1, 1).data;
    pts.push([d[0], d[1], d[2]]);
  };
  const xm = x + w / 2, ym = y + h / 2;
  push(x - 1, ym); push(x + w + 1, ym); push(xm, y - 1); push(xm, y + h + 1);
  push(x - 1, y - 1); push(x + w + 1, y - 1); push(x - 1, y + h + 1); push(x + w + 1, y + h + 1);
  if (!pts.length) return '#ffffff';
  const med = (i) => {
    const v = pts.map((p) => p[i]).sort((a, b) => a - b);
    return v[Math.floor(v.length / 2)];
  };
  return `rgb(${med(0)},${med(1)},${med(2)})`;
}

function luminance(color) {
  const m = color.match(/rgb\((\d+),(\d+),(\d+)\)/);
  if (!m) return 1;
  return (m[1] * 299 + m[2] * 587 + m[3] * 114) / 255000;
}

function drawLabel(ctx, text, x, y, w, h, bgDark) {
  let size = Math.max(6, Math.min(h * 0.62, 16));
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  const maxWidth = Math.max(1, w - 4);
  const measured = ctx.measureText(text).width;
  if (measured > maxWidth) {
    size = Math.max(5, size * (maxWidth / measured));
    ctx.font = `600 ${size}px system-ui, sans-serif`;
  }
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = bgDark ? '#ffffff' : '#000000';
  ctx.fillText(text, x + w / 2, y + h / 2, maxWidth);
}

function applyTextRedactions(ctx, rec, enabledSet, options) {
  ctx.save();
  ctx.font = '12px system-ui';
  for (const r of rec.redacts) {
    if (!enabledSet.has(r.id) || !r.rect) continue;
    const pad = Math.max(2, r.rect.h * 0.45);
    const x = Math.max(0, r.rect.x - pad);
    const y = Math.max(0, r.rect.y - pad);
    const w = r.rect.w + pad * 2;
    const h = r.rect.h + pad * 2;
    if (w <= 0 || h <= 0) continue;
    const bg = options.filter === 'white'
      ? '#ffffff'
      : sampleBackground(ctx, rec.widthPx, rec.heightPx, x, y, w, h);
    ctx.fillStyle = bg;
    ctx.fillRect(x, y, w, h);
    if (options.mode === 'label') {
      drawLabel(ctx, r.token, x, y, w, h, luminance(bg) < 0.5);
    }
  }
  ctx.restore();
}

function pixelate(ctx, src, x, y, w, h) {
  const step = Math.max(6, Math.round(Math.min(w, h) / 20));
  const sw = Math.max(1, Math.round(w / step));
  const sh = Math.max(1, Math.round(h / step));
  const tmp = document.createElement('canvas');
  tmp.width = sw;
  tmp.height = sh;
  const tctx = tmp.getContext('2d');
  tctx.imageSmoothingEnabled = false;
  tctx.drawImage(src, x, y, w, h, 0, 0, sw, sh);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tmp, 0, 0, sw, sh, x, y, w, h);
}

function applyFaceRedactions(ctx, rec, enabledSet, options) {
  for (const f of rec.faces) {
    if (!enabledSet.has(f.id)) continue;
    let x = f.nx * rec.widthPx;
    let y = f.ny * rec.heightPx;
    let w = f.nw * rec.widthPx;
    let h = f.nh * rec.heightPx;
    const ex = w * 0.15, ey = h * 0.15;
    x -= ex; y -= ey; w += ex * 2; h += ey * 2;
    x = Math.max(0, x); y = Math.max(0, y);
    w = Math.min(rec.widthPx - x, w); h = Math.min(rec.heightPx - y, h);
    if (w <= 4 || h <= 4) continue;
    if (options.faceMode === 'pixelate') {
      pixelate(ctx, rec.baseCanvas, x, y, w, h);
    } else {
      ctx.fillStyle = '#000000';
      ctx.fillRect(x, y, w, h);
    }
  }
}

export function buildFinalCanvas(rec, enabledSet, options) {
  const c = document.createElement('canvas');
  c.width = rec.widthPx;
  c.height = rec.heightPx;
  const ctx = c.getContext('2d', { alpha: false });
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(rec.baseCanvas, 0, 0);
  applyTextRedactions(ctx, rec, enabledSet, options);
  applyFaceRedactions(ctx, rec, enabledSet, options);
  return c;
}

export function buildThumb(rec, enabledSet, options, maxWidth = 520) {
  const scale = Math.min(1, maxWidth / rec.widthPx);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(rec.widthPx * scale));
  canvas.height = Math.max(1, Math.round(rec.heightPx * scale));
  const ctx = canvas.getContext('2d');
  const finalC = buildFinalCanvas(rec, enabledSet, options);
  ctx.drawImage(finalC, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.8);
}

export function assignTokens(state) {
  const byKey = new Map();
  const counters = new Map();
  const rows = [];
  for (const rec of state.pageRecords) {
    for (const r of rec.redacts) {
      const key = `${r.type}|${String(r.original).toLowerCase()}`;
      let token = byKey.get(key);
      if (!token) {
        const n = (counters.get(r.type) || 0) + 1;
        counters.set(r.type, n);
        token = `[${CATEGORIES[r.type].token} ${n}]`;
        byKey.set(key, token);
      }
      r.token = token;
      rows.push(r);
    }
    for (const f of rec.faces) {
      const n = (counters.get('face') || 0) + 1;
      counters.set('face', n);
      f.token = `[${CATEGORIES.face.token} ${n}]`;
      rows.push(f);
    }
  }
  state.rows = rows;
}

export async function processDocument({ bytes, options, faceDetector, onStatus }) {
  const sourceBytes = new Uint8Array(bytes.slice(0));
  const loadingTask = pdfjs.getDocument({ data: bytes, isEvalSupported: false });
  const pdf = await loadingTask.promise;
  const numPages = pdf.numPages;
  if (numPages > options.limits.maxPages) {
    await loadingTask.destroy();
    throw new Error(`El documento supera el límite de ${options.limits.maxPages} páginas`);
  }

  const state = { numPages, pageRecords: [], rows: [], options, sourceBytes };
  let totalPixels = 0;
  try {
    for (let i = 1; i <= numPages; i++) {
      onStatus({ phase: 'page', page: i, numPages });
      const page = await pdf.getPage(i);
      try {
        const viewport = page.getViewport({ scale: options.scale });
        const pagePixels = Math.ceil(viewport.width) * Math.ceil(viewport.height);
        totalPixels += pagePixels;
        if (pagePixels > options.limits.maxPagePixels || totalPixels > options.limits.maxTotalPixels) {
          throw new Error('El documento requiere demasiada memoria para procesarse de forma segura');
        }
        const rec = await processPage(page, i, options, faceDetector, onStatus, numPages);
        state.pageRecords.push(rec);
      } finally {
        try { page.cleanup(); } catch { /* No cleanup action is available. */ }
      }
    }
  } finally {
    await loadingTask.destroy();
  }
  assignTokens(state);
  state.textCharacters = state.pageRecords.reduce((total, page) => total + page.textCharacters, 0);
  onStatus({ phase: 'done', numPages });
  return state;
}
