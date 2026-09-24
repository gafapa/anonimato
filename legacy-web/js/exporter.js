import { CATEGORIES } from './detectors.js';
import * as mupdf from '../vendor/mupdf/mupdf.js';

function rowRect(row, pageRecord) {
  if (row.rect) {
    const pad = row.type === 'manual' ? 0 : Math.max(0.8, row.rect.h / pageRecord.scale * 0.18);
    return [
      Math.max(0, row.rect.x / pageRecord.scale - pad),
      Math.max(0, row.rect.y / pageRecord.scale - pad),
      Math.min(pageRecord.pdfWidth, (row.rect.x + row.rect.w) / pageRecord.scale + pad),
      Math.min(pageRecord.pdfHeight, (row.rect.y + row.rect.h) / pageRecord.scale + pad),
    ];
  }
  if (row.type === 'face') {
    const expandX = row.nw * pageRecord.pdfWidth * 0.15;
    const expandY = row.nh * pageRecord.pdfHeight * 0.15;
    return [
      Math.max(0, row.nx * pageRecord.pdfWidth - expandX),
      Math.max(0, row.ny * pageRecord.pdfHeight - expandY),
      Math.min(pageRecord.pdfWidth, (row.nx + row.nw) * pageRecord.pdfWidth + expandX),
      Math.min(pageRecord.pdfHeight, (row.ny + row.nh) * pageRecord.pdfHeight + expandY),
    ];
  }
  return null;
}

function addReplacement(page, rect, token) {
  const width = Math.max(1, rect[2] - rect[0]);
  const height = Math.max(1, rect[3] - rect[1]);
  const fontSize = Math.max(2.25, Math.min(height * 0.62, (width - 3) / Math.max(1, token.length * 0.72), 11));
  const annotation = page.createAnnotation('FreeText');
  annotation.setRect(rect);
  annotation.setContents(token);
  annotation.setDefaultAppearance('Helv', fontSize, [0, 0, 0]);
  annotation.setBorderWidth(0);
  annotation.setFlags(4);
  annotation.update();
}

function addFaceReplacement(page, rect) {
  const annotation = page.createAnnotation('Square');
  annotation.setRect(rect);
  annotation.setColor([0, 0, 0]);
  annotation.setInteriorColor([0, 0, 0]);
  annotation.setBorderWidth(0);
  annotation.setOpacity(1);
  annotation.setFlags(4);
  annotation.update();
}

export async function buildPdf(state, enabledSet, options, onStatus) {
  if (!state.sourceBytes) throw new Error('No se conserva una copia local del PDF de origen');
  const document = mupdf.Document.openDocument(state.sourceBytes, 'application/pdf');
  const pdfDocument = document.asPDF();
  if (!pdfDocument) {
    document.destroy();
    throw new Error('El documento no puede editarse como PDF');
  }

  try {
    pdfDocument.disableJS();
    // Flatten source widgets and annotations first so their visible values become redactable page content.
    pdfDocument.bake(true, true);

    const embeddedFiles = pdfDocument.getEmbeddedFiles();
    for (const filename of Object.keys(embeddedFiles)) pdfDocument.deleteEmbeddedFile(filename);
    for (const key of ['info:Title', 'info:Author', 'info:Subject', 'info:Keywords', 'info:Creator', 'info:Producer']) {
      pdfDocument.setMetaData(key, '');
    }

    for (let index = 0; index < state.pageRecords.length; index++) {
      onStatus({ phase: 'export', page: index + 1, numPages: state.pageRecords.length });
      const pageRecord = state.pageRecords[index];
      const page = pdfDocument.loadPage(index);
      const rows = state.rows.filter((row) => row.page === index + 1 && enabledSet.has(row.id));
      const replacements = [];
      try {
        for (const row of rows) {
          const rect = rowRect(row, pageRecord);
          if (!rect) continue;
          const redaction = page.createAnnotation('Redact');
          redaction.setRect(rect);
          redaction.update();
          replacements.push({ row, rect });
        }
        if (replacements.length) {
          page.applyRedactions(
            false,
            mupdf.PDFPage.REDACT_IMAGE_PIXELS,
            mupdf.PDFPage.REDACT_LINE_ART_REMOVE_IF_COVERED,
            mupdf.PDFPage.REDACT_TEXT_REMOVE,
          );
          for (const { row, rect } of replacements) {
            if (row.type === 'face') addFaceReplacement(page, rect);
            else if (options.mode === 'label') addReplacement(page, rect, row.token);
          }
          page.update();
        }
      } finally {
        page.destroy();
      }
    }

    // Convert replacement annotations into ordinary page content and discard annotation objects.
    pdfDocument.bake(true, true);
    pdfDocument.subsetFonts();
    const output = pdfDocument.saveToBuffer(
      'garbage=deduplicate,compress,compress-fonts,compress-images,clean,sanitize,encrypt=none,regenerate-id=yes'
    );
    return new Uint8Array(output.asUint8Array());
  } finally {
    document.destroy();
  }
}

function csvCell(v) {
  if (v == null) return '';
  let value = String(v);
  if (/^[=+\-@]/.test(value)) value = `'${value}`;
  return `"${value.replace(/"/g, '""')}"`;
}

export function buildCsv(state, enabledSet, { includeOriginals = false } = {}) {
  const scaleOf = pageScaleMap(state);
  const head = ['página', 'tipo', 'confianza', 'valor original', 'reemplazo', 'x', 'y', 'ancho', 'alto'];
  const lines = [head.map(csvCell).join(',')];
  for (const r of state.rows) {
    if (!enabledSet.has(r.id)) continue;
    const label = CATEGORIES[r.type]?.label || r.type;
    const pts = r.rect ? {
      x: r.rect.x / scaleOf.get(r.page),
      y: r.rect.y / scaleOf.get(r.page),
      w: r.rect.w / scaleOf.get(r.page),
      h: r.rect.h / scaleOf.get(r.page),
    } : null;
    lines.push([
      r.page,
      label,
      r.confidence == null ? '' : `${Math.round(r.confidence * 100)} %`,
      includeOriginals ? (r.original ?? '—') : '',
      r.token,
      pts ? pts.x.toFixed(1) : '',
      pts ? pts.y.toFixed(1) : '',
      pts ? pts.w.toFixed(1) : '',
      pts ? pts.h.toFixed(1) : '',
    ].map(csvCell).join(','));
  }
  return lines.join('\r\n');
}

function pageScaleMap(state) {
  const m = new Map();
  for (const p of state.pageRecords) m.set(p.pageNumber, p.scale);
  return m;
}

export function buildJson(state, enabledSet, { includeOriginals = false } = {}) {
  const scaleOf = pageScaleMap(state);
  const unique = new Map();
  for (const r of state.rows) {
    if (!enabledSet.has(r.id) || !r.original) continue;
    const key = `${r.type}|${r.original}`;
    if (!unique.has(key)) unique.set(key, { tipo: CATEGORIES[r.type]?.label || r.type, original: r.original, reemplazo: r.token, ocurrencias: 0 });
    unique.get(key).ocurrencias++;
  }
  return JSON.stringify({
    generado: new Date().toISOString(),
    fuente: state.fileName || null,
    numPaginas: state.numPages,
    resumen: {
      totalSustituciones: state.rows.filter((r) => enabledSet.has(r.id)).length,
      rostros: state.rows.filter((r) => enabledSet.has(r.id) && r.type === 'face').length,
      valoresUnicos: unique.size,
    },
    sustituciones: state.rows.filter((r) => enabledSet.has(r.id)).map((r) => {
      const p = r.rect ? r.rect.x / scaleOf.get(r.page) : null;
      return {
        pagina: r.page,
        tipo: CATEGORIES[r.type]?.label || r.type,
        confianza: r.confidence == null ? null : +r.confidence.toFixed(2),
        original: includeOriginals ? r.original : null,
        reemplazo: r.token,
        x: p == null ? null : +p.toFixed(1),
        y: p == null ? null : +(r.rect.y / scaleOf.get(r.page)).toFixed(1),
      };
    }),
    mapeo: includeOriginals ? [...unique.values()] : [],
  }, null, 2);
}

export function downloadBytes(bytes, filename, mime) {
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function downloadText(text, filename, mime, { bom = true } = {}) {
  const prefix = bom ? '\uFEFF' : '';
  downloadBytes(new TextEncoder().encode(prefix + text), filename, mime);
}
