import { CATEGORIES } from './detectors.js';
import { processDocument, buildThumb } from './anonymizer.js';
import { buildPdf, buildCsv, buildJson, downloadBytes, downloadText } from './exporter.js';
import { createFaceDetector } from './faceService.js';
import * as pdfjs from '../vendor/pdf.min.mjs';

pdfjs.GlobalWorkerOptions.workerSrc = new URL('../vendor/pdf.worker.min.mjs', import.meta.url).href;

const LIMITS = Object.freeze({
  maxFileBytes: 100 * 1024 * 1024,
  maxPages: 200,
  maxPagePixels: 40_000_000,
  maxTotalPixels: 180_000_000,
});

const $ = (id) => document.getElementById(id);
const els = {
  dropzone: $('dropzone'), fileInput: $('fileInput'), dzFile: $('dzFile'), documentQueue: $('documentQueue'),
  catGrid: $('catGrid'), optOcr: $('optOcr'), optFaces: $('optFaces'), optFaceMode: $('optFaceMode'), optLogOriginals: $('optLogOriginals'),
  optDpi: $('optDpi'), optMode: $('optMode'), btnRun: $('btnRun'), errMsg: $('errMsg'),
  progressCard: $('progressCard'), progressFill: $('progressFill'), progressText: $('progressText'),
  emptyPreview: $('emptyPreview'), resultsCard: $('resultsCard'), currentFileName: $('currentFileName'),
  statsHost: $('statsHost'), originalGallery: $('originalGallery'), gallery: $('gallery'), rowsBody: $('rowsBody'), rowsCount: $('rowsCount'),
  btnPdf: $('btnPdf'), btnCsv: $('btnCsv'), btnJson: $('btnJson'), btnAllOn: $('btnAllOn'),
  btnAllOff: $('btnAllOff'), btnReset: $('btnReset'), btnPrevPage: $('btnPrevPage'),
  btnNextPage: $('btnNextPage'), pageIndicator: $('pageIndicator'),
  btnManual: $('btnManual'),
  detectionNotice: $('detectionNotice'),
};

const FACE_COLOR = '#a678ff';
let nextDocumentId = 1;
const state = {
  documents: [],
  activeId: null,
  activePageIndex: 0,
  faceDetector: null,
  busy: false,
  manualMode: false,
  previewRequest: 0,
};

function activeDocument() {
  return state.documents.find((document) => document.id === state.activeId) || null;
}

function catEntries() {
  return Object.entries(CATEGORIES).filter(([key]) => key !== 'face' && key !== 'manual');
}

function buildCategoryGrid() {
  els.catGrid.replaceChildren();
  for (const [key, category] of catEntries()) {
    const label = document.createElement('label');
    label.className = 'cat';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.dataset.cat = key;
    const text = document.createElement('span');
    text.textContent = category.label;
    label.append(checkbox, text);
    els.catGrid.append(label);
  }
}

function setError(message) {
  els.errMsg.textContent = message || '';
  els.errMsg.hidden = !message;
}

function setProgress(percent, text) {
  els.progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  els.progressText.textContent = text;
}

function showBusy(busy) {
  state.busy = busy;
  els.btnRun.disabled = busy || state.documents.length === 0;
  els.fileInput.disabled = busy;
  els.dropzone.classList.toggle('busy', busy);
  for (const control of [els.optOcr, els.optFaces, els.optFaceMode, els.optDpi, els.optMode, ...els.catGrid.querySelectorAll('input')]) {
    control.disabled = busy;
  }
  renderDocumentQueue();
}

function currentOptions() {
  const dpi = Number.parseInt(els.optDpi.value, 10);
  return {
    scale: dpi / 72,
    dpi,
    useOcr: els.optOcr.checked,
    redactFaces: els.optFaces.checked,
    faceMode: els.optFaceMode.value,
    mode: els.optMode.value,
    filter: 'auto',
    cats: new Set([...els.catGrid.querySelectorAll('input:checked')].map((input) => input.dataset.cat)),
    limits: LIMITS,
  };
}

function releaseDocument(documentRecord) {
  for (const page of documentRecord.data?.pageRecords || []) {
    page.baseCanvas.width = 0;
    page.baseCanvas.height = 0;
  }
  documentRecord.data = null;
  documentRecord.enabled = new Map();
  documentRecord.pdfCache = null;
}

function addFiles(fileList) {
  const files = [...fileList];
  const errors = [];
  let added = 0;
  for (const file of files) {
    if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
      errors.push(`${file.name}: no es un PDF`);
      continue;
    }
    if (file.size > LIMITS.maxFileBytes) {
      errors.push(`${file.name}: supera ${LIMITS.maxFileBytes / 1024 / 1024} MB`);
      continue;
    }
    const id = nextDocumentId++;
    state.documents.push({
      id,
      file,
      baseName: file.name.replace(/\.pdf$/i, '') || `documento-${id}`,
      status: 'pending',
      data: null,
      enabled: new Map(),
      error: null,
    });
    if (state.activeId == null) state.activeId = id;
    added++;
  }
  els.fileInput.value = '';
  els.dzFile.hidden = added === 0;
  els.dzFile.textContent = added === 1 ? '1 documento añadido' : `${added} documentos añadidos`;
  setError(errors.join(' · '));
  renderDocumentQueue();
  renderActiveDocument();
  showBusy(false);
}

function statusLabel(documentRecord) {
  if (documentRecord.status === 'processing') return 'Procesando…';
  if (documentRecord.status === 'ready') return `${documentRecord.data.numPages} páginas · listo`;
  if (documentRecord.status === 'failed') return 'No se pudo procesar';
  return `${Math.round(documentRecord.file.size / 1024)} KB · pendiente`;
}

function renderDocumentQueue() {
  els.documentQueue.replaceChildren();
  for (const documentRecord of state.documents) {
    const item = document.createElement('div');
    item.className = 'document-item';
    item.classList.toggle('active', documentRecord.id === state.activeId);

    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'document-select';
    select.disabled = state.busy;
    select.setAttribute('aria-label', `Abrir ${documentRecord.file.name}`);
    const name = document.createElement('span');
    name.className = 'document-name';
    name.textContent = documentRecord.file.name;
    const status = document.createElement('span');
    status.className = `document-status ${documentRecord.status}`;
    status.textContent = statusLabel(documentRecord);
    select.append(name, status);
    select.addEventListener('click', () => {
      state.activeId = documentRecord.id;
      state.activePageIndex = 0;
      renderDocumentQueue();
      renderActiveDocument();
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'document-remove';
    remove.textContent = 'Quitar';
    remove.disabled = state.busy;
    remove.setAttribute('aria-label', `Quitar ${documentRecord.file.name}`);
    remove.addEventListener('click', () => removeDocument(documentRecord.id));
    item.append(select, remove);
    els.documentQueue.append(item);
  }
}

function removeDocument(id) {
  const index = state.documents.findIndex((document) => document.id === id);
  if (index < 0) return;
  releaseDocument(state.documents[index]);
  state.documents.splice(index, 1);
  if (state.activeId === id) {
    state.activeId = state.documents[Math.min(index, state.documents.length - 1)]?.id ?? null;
    state.activePageIndex = 0;
  }
  renderDocumentQueue();
  renderActiveDocument();
  showBusy(false);
}

els.dropzone.addEventListener('click', () => { if (!els.fileInput.disabled) els.fileInput.click(); });
els.dropzone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); els.fileInput.click(); }
});
els.fileInput.addEventListener('change', (event) => addFiles(event.target.files));
for (const eventName of ['dragenter', 'dragover']) {
  els.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); els.dropzone.classList.add('drag'); });
}
for (const eventName of ['dragleave', 'drop']) {
  els.dropzone.addEventListener(eventName, (event) => { event.preventDefault(); els.dropzone.classList.remove('drag'); });
}
els.dropzone.addEventListener('drop', (event) => { if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files); });

async function validatePdfFile(file) {
  const bytes = await file.arrayBuffer();
  const signature = new Uint8Array(bytes, 0, Math.min(5, bytes.byteLength));
  if (new TextDecoder('ascii').decode(signature) !== '%PDF-') {
    throw new Error('la cabecera del archivo no corresponde a un PDF');
  }
  return bytes;
}

els.btnRun.addEventListener('click', async () => {
  if (!state.documents.length) return;
  setError('');
  showBusy(true);
  els.progressCard.hidden = false;
  const options = currentOptions();
  const failures = [];

  try {
    if (options.redactFaces && !state.faceDetector) {
      setProgress(2, 'Preparando detección de rostros…');
      state.faceDetector = await createFaceDetector();
    }
    for (let index = 0; index < state.documents.length; index++) {
      const documentRecord = state.documents[index];
      releaseDocument(documentRecord);
      documentRecord.status = 'processing';
      documentRecord.error = null;
      renderDocumentQueue();
      try {
        const bytes = await validatePdfFile(documentRecord.file);
        const data = await processDocument({
          bytes,
          options: { ...options, cats: new Set(options.cats) },
          faceDetector: options.redactFaces ? state.faceDetector : null,
          onStatus: (progress) => {
            if (progress.phase === 'ocr') {
              const overall = ((index + ((progress.page - 0.5) / progress.numPages)) / state.documents.length) * 100;
              setProgress(overall, `${documentRecord.file.name} · OCR de página ${progress.page} de ${progress.numPages}`);
              return;
            }
            if (progress.phase !== 'page') return;
            const documentProgress = progress.page / progress.numPages;
            const overall = ((index + documentProgress) / state.documents.length) * 100;
            setProgress(overall, `${documentRecord.file.name} · página ${progress.page} de ${progress.numPages}`);
          },
        });
        documentRecord.data = data;
        documentRecord.enabled = new Map(data.rows.map((row) => [row.id, true]));
        documentRecord.status = 'ready';
      } catch (error) {
        console.error(error);
        documentRecord.status = 'failed';
        documentRecord.error = error.message;
        failures.push(`${documentRecord.file.name}: ${error.message}`);
      }
      renderDocumentQueue();
      if (documentRecord.id === state.activeId) renderActiveDocument();
    }
    const firstReady = state.documents.find((document) => document.status === 'ready');
    if (firstReady && activeDocument()?.status !== 'ready') state.activeId = firstReady.id;
    state.activePageIndex = 0;
    renderDocumentQueue();
    renderActiveDocument();
    if (failures.length) setError(failures.join(' · '));
  } finally {
    showBusy(false);
    els.progressCard.hidden = true;
  }
});

function enabledSet(documentRecord = activeDocument()) {
  return new Set([...(documentRecord?.enabled || [])].filter(([, enabled]) => enabled).map(([id]) => id));
}

function pdfStateKey(documentRecord) {
  return `${documentRecord.data.options.mode}|${[...enabledSet(documentRecord)].sort().join('|')}`;
}

async function getActualPdfBytes(documentRecord) {
  const key = pdfStateKey(documentRecord);
  if (documentRecord.pdfCache?.key === key && documentRecord.pdfCache.bytes) return documentRecord.pdfCache.bytes;
  if (documentRecord.pdfCache?.key === key && documentRecord.pdfCache.promise) return documentRecord.pdfCache.promise;
  const promise = buildPdf(documentRecord.data, enabledSet(documentRecord), documentRecord.data.options, () => {})
    .then((bytes) => {
      if (documentRecord.pdfCache?.key === key) documentRecord.pdfCache = { key, bytes };
      return bytes;
    })
    .catch((error) => {
      if (documentRecord.pdfCache?.key === key) documentRecord.pdfCache = null;
      throw error;
    });
  documentRecord.pdfCache = { key, promise };
  return promise;
}

async function renderActualPdfPreview(image, imageWrap, documentRecord, pageRecord, requestId) {
  try {
    const bytes = await getActualPdfBytes(documentRecord);
    if (requestId !== state.previewRequest || activeDocument()?.id !== documentRecord.id) return;
    const loadingTask = pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false });
    try {
      const pdf = await loadingTask.promise;
      const page = await pdf.getPage(pageRecord.pageNumber);
      const baseViewport = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: Math.min(2, 1000 / baseViewport.width) });
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await page.render({ canvasContext: canvas.getContext('2d', { alpha: false }), viewport, background: '#ffffff' }).promise;
      if (requestId !== state.previewRequest || activeDocument()?.id !== documentRecord.id) return;
      image.src = canvas.toDataURL('image/png');
      imageWrap.classList.remove('loading-preview');
      imageWrap.setAttribute('aria-busy', 'false');
    } finally {
      await loadingTask.destroy();
    }
  } catch (error) {
    if (requestId !== state.previewRequest) return;
    imageWrap.classList.remove('loading-preview');
    imageWrap.setAttribute('aria-busy', 'false');
    setError(`No se pudo generar la vista previa real: ${error.message}`);
  }
}

function renderActiveDocument() {
  const documentRecord = activeDocument();
  const ready = documentRecord?.status === 'ready' && documentRecord.data;
  els.emptyPreview.hidden = Boolean(ready);
  els.resultsCard.hidden = !ready;
  if (!ready) {
    const heading = els.emptyPreview.querySelector('h2');
    const text = els.emptyPreview.querySelector('p');
    if (documentRecord?.status === 'failed') {
      heading.textContent = 'No se pudo procesar';
      text.textContent = documentRecord.error || 'Revisa el archivo e inténtalo de nuevo.';
    } else if (state.documents.length) {
      heading.textContent = 'Documentos preparados';
      text.textContent = 'Ajusta las opciones y pulsa “Anonimizar documentos”.';
    } else {
      heading.textContent = 'Añade tus documentos';
      text.textContent = 'La previsualización aparecerá aquí, página a página.';
    }
    return;
  }
  renderResults(documentRecord);
}

function renderResults(documentRecord) {
  const data = documentRecord.data;
  const unique = new Set(data.rows.filter((row) => row.original).map((row) => `${row.type}|${row.original}`)).size;
  const faces = data.rows.filter((row) => row.type === 'face').length;
  els.currentFileName.textContent = documentRecord.file.name;
  const averageText = data.textCharacters / Math.max(1, data.numPages);
  els.detectionNotice.hidden = averageText >= 30;
  els.detectionNotice.textContent = averageText < 30
    ? (data.options.useOcr
      ? 'Poco texto nativo: se ha aplicado OCR local a las imágenes. Revisa igualmente cada hallazgo y usa “Ocultar zona” si falta alguno.'
      : 'Poco texto extraíble: este PDF parece escaneado. Activa el OCR o usa “Ocultar zona” para cubrir los datos.')
    : '';
  els.statsHost.innerHTML = [
    ['Páginas', data.numPages], ['Sustituciones', data.rows.length], ['Rostros', faces], ['Valores únicos', unique],
  ].map(([label, value]) => `<div class="stat"><b>${value}</b>${label}</div>`).join('');
  els.btnPdf.disabled = false;
  els.btnCsv.disabled = false;
  els.btnJson.disabled = false;
  renderCurrentPage();
  renderTable();
}

function pageRedactionCount(documentRecord, pageRecord) {
  return pageRecord.redacts.filter((row) => documentRecord.enabled.get(row.id)).length
    + pageRecord.faces.filter((row) => documentRecord.enabled.get(row.id)).length;
}

function renderCurrentPage() {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  const pages = documentRecord.data.pageRecords;
  state.activePageIndex = Math.max(0, Math.min(state.activePageIndex, pages.length - 1));
  const pageRecord = pages[state.activePageIndex];
  const originalFigure = document.createElement('figure');
  originalFigure.className = 'page';
  originalFigure.dataset.page = pageRecord.pageNumber;
  const originalImage = document.createElement('img');
  originalImage.alt = `Original, página ${pageRecord.pageNumber} de ${pages.length}`;
  originalImage.src = buildThumb(pageRecord, new Set(), documentRecord.data.options, 1000);
  const originalCaption = document.createElement('figcaption');
  const originalTitle = document.createElement('b');
  originalTitle.textContent = `Página ${pageRecord.pageNumber}`;
  const originalStatus = document.createElement('span');
  originalStatus.textContent = 'Sin cambios';
  originalCaption.append(originalTitle, originalStatus);
  originalFigure.append(originalImage, originalCaption);
  els.originalGallery.replaceChildren(originalFigure);

  const figure = document.createElement('figure');
  figure.className = 'page';
  figure.dataset.page = pageRecord.pageNumber;
  const image = document.createElement('img');
  image.alt = `Anonimizado, página ${pageRecord.pageNumber} de ${pages.length}`;
  image.src = buildThumb(pageRecord, new Set(), documentRecord.data.options, 1000);
  const imageWrap = document.createElement('div');
  imageWrap.className = 'page-image-wrap loading-preview';
  imageWrap.setAttribute('aria-busy', 'true');
  imageWrap.classList.toggle('manual-mode', state.manualMode);
  imageWrap.append(image);
  installManualRedaction(imageWrap, image, documentRecord, pageRecord);
  const caption = document.createElement('figcaption');
  const title = document.createElement('b');
  title.textContent = `Página ${pageRecord.pageNumber}`;
  const count = document.createElement('span');
  const total = pageRedactionCount(documentRecord, pageRecord);
  count.textContent = `${total} ${total === 1 ? 'sustitución' : 'sustituciones'}`;
  caption.append(title, count);
  figure.append(imageWrap, caption);
  els.gallery.replaceChildren(figure);
  els.pageIndicator.textContent = `Página ${pageRecord.pageNumber} de ${pages.length}`;
  els.btnPrevPage.disabled = state.activePageIndex === 0;
  els.btnNextPage.disabled = state.activePageIndex === pages.length - 1;
  els.btnManual.setAttribute('aria-pressed', String(state.manualMode));
  els.btnManual.textContent = state.manualMode ? 'Arrastra sobre la página' : 'Ocultar zona';
  const requestId = ++state.previewRequest;
  renderActualPdfPreview(image, imageWrap, documentRecord, pageRecord, requestId);
}

function installManualRedaction(container, image, documentRecord, pageRecord) {
  let start = null;
  let selection = null;
  container.addEventListener('pointerdown', (event) => {
    if (!state.manualMode || event.button !== 0) return;
    event.preventDefault();
    const bounds = container.getBoundingClientRect();
    start = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    selection = document.createElement('div');
    selection.className = 'manual-selection';
    container.append(selection);
    container.setPointerCapture(event.pointerId);
  });
  container.addEventListener('pointermove', (event) => {
    if (!start || !selection) return;
    const bounds = container.getBoundingClientRect();
    const current = {
      x: Math.max(0, Math.min(bounds.width, event.clientX - bounds.left)),
      y: Math.max(0, Math.min(bounds.height, event.clientY - bounds.top)),
    };
    const x = Math.min(start.x, current.x);
    const y = Math.min(start.y, current.y);
    Object.assign(selection.style, {
      left: `${x}px`, top: `${y}px`, width: `${Math.abs(current.x - start.x)}px`, height: `${Math.abs(current.y - start.y)}px`,
    });
  });
  container.addEventListener('pointerup', (event) => {
    if (!start || !selection) return;
    const displayWidth = image.clientWidth;
    const displayHeight = image.clientHeight;
    const x = Number.parseFloat(selection.style.left) || 0;
    const y = Number.parseFloat(selection.style.top) || 0;
    const width = Number.parseFloat(selection.style.width) || 0;
    const height = Number.parseFloat(selection.style.height) || 0;
    selection.remove();
    start = null;
    selection = null;
    if (width < 8 || height < 8 || displayWidth <= 0 || displayHeight <= 0) return;
    const manualNumber = documentRecord.data.rows.filter((row) => row.type === 'manual').length + 1;
    const redaction = {
      id: `p${pageRecord.pageNumber}-m${Date.now()}-${manualNumber}`,
      page: pageRecord.pageNumber,
      type: 'manual',
      original: null,
      confidence: 1,
      token: `[${CATEGORIES.manual.token} ${manualNumber}]`,
      rect: {
        x: x * pageRecord.widthPx / displayWidth,
        y: y * pageRecord.heightPx / displayHeight,
        w: width * pageRecord.widthPx / displayWidth,
        h: height * pageRecord.heightPx / displayHeight,
      },
    };
    pageRecord.redacts.push(redaction);
    documentRecord.data.rows.push(redaction);
    documentRecord.enabled.set(redaction.id, true);
    state.manualMode = false;
    renderTable();
    renderCurrentPage();
    const substitutionStat = els.statsHost.querySelectorAll('.stat b')[1];
    if (substitutionStat) substitutionStat.textContent = documentRecord.data.rows.length;
    els.progressText.textContent = `Zona manual añadida en la página ${pageRecord.pageNumber}.`;
  });
}

function renderTable() {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  els.rowsBody.replaceChildren();
  for (const row of documentRecord.data.rows) {
    const tableRow = document.createElement('tr');
    const enabled = documentRecord.enabled.get(row.id) !== false;
    tableRow.classList.toggle('off', !enabled);
    const selectCell = document.createElement('td');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = enabled;
    checkbox.setAttribute('aria-label', `Incluir sustitución de la página ${row.page}`);
    checkbox.addEventListener('change', () => {
      documentRecord.enabled.set(row.id, checkbox.checked);
      tableRow.classList.toggle('off', !checkbox.checked);
      if (documentRecord.data.pageRecords[state.activePageIndex]?.pageNumber === row.page) renderCurrentPage();
      updateCounts();
    });
    selectCell.append(checkbox);
    const pageCell = document.createElement('td'); pageCell.textContent = row.page;
    const typeCell = document.createElement('td');
    const badge = document.createElement('span'); badge.className = 'type-badge';
    badge.textContent = CATEGORIES[row.type]?.label || row.type;
    badge.style.boxShadow = `inset 1px 0 ${row.type === 'face' ? FACE_COLOR : 'var(--accent)'}`;
    typeCell.append(badge);
    const confidenceCell = document.createElement('td');
    confidenceCell.className = 'confidence';
    const confidence = Math.round((row.confidence ?? 0.7) * 100);
    confidenceCell.textContent = `${confidence} %`;
    confidenceCell.title = row.validationWarning === 'checksum'
      ? 'Formato reconocido; letra de control no válida'
      : confidence >= 95 ? 'Confianza alta' : confidence >= 80 ? 'Revisar contexto' : 'Revisión recomendada';
    confidenceCell.classList.toggle('low', confidence < 80);
    const originalCell = document.createElement('td'); originalCell.className = 'orig'; originalCell.textContent = row.original ?? '(rostro detectado en imagen)';
    const replacementCell = document.createElement('td'); replacementCell.className = 'tok'; replacementCell.textContent = row.token;
    tableRow.append(selectCell, pageCell, typeCell, confidenceCell, originalCell, replacementCell);
    els.rowsBody.append(tableRow);
  }
  updateCounts();
}

function updateCounts() {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  const enabled = documentRecord.data.rows.filter((row) => documentRecord.enabled.get(row.id)).length;
  els.rowsCount.textContent = `(${enabled}/${documentRecord.data.rows.length} incluidos)`;
}

function changePage(offset) {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  state.activePageIndex = Math.max(0, Math.min(state.activePageIndex + offset, documentRecord.data.numPages - 1));
  renderCurrentPage();
  els.gallery.scrollIntoView({ behavior: 'auto', block: 'start' });
}

els.btnPrevPage.addEventListener('click', () => changePage(-1));
els.btnNextPage.addEventListener('click', () => changePage(1));
els.btnManual.addEventListener('click', () => {
  state.manualMode = !state.manualMode;
  renderCurrentPage();
});
document.addEventListener('keydown', (event) => {
  if (event.target.matches('input, select, button, textarea')) return;
  if (event.key === 'ArrowLeft') changePage(-1);
  if (event.key === 'ArrowRight') changePage(1);
});

els.btnAllOn.addEventListener('click', () => {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  for (const row of documentRecord.data.rows) documentRecord.enabled.set(row.id, true);
  renderTable(); renderCurrentPage();
});
els.btnAllOff.addEventListener('click', () => {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  for (const row of documentRecord.data.rows) documentRecord.enabled.set(row.id, false);
  renderTable(); renderCurrentPage();
});

els.btnPdf.addEventListener('click', async () => {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  els.btnPdf.disabled = true;
  setError('');
  try {
    const bytes = await getActualPdfBytes(documentRecord);
    downloadBytes(bytes, `${documentRecord.baseName}_anonimizado.pdf`, 'application/pdf');
  } catch (error) {
    console.error(error);
    setError(`Error al generar el PDF: ${error.message}`);
  } finally {
    els.btnPdf.disabled = false;
  }
});
els.btnCsv.addEventListener('click', () => {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  downloadText(buildCsv(documentRecord.data, enabledSet(documentRecord), { includeOriginals: els.optLogOriginals.checked }), `${documentRecord.baseName}_registro.csv`, 'text/csv;charset=utf-8');
});
els.btnJson.addEventListener('click', () => {
  const documentRecord = activeDocument();
  if (!documentRecord?.data) return;
  downloadText(buildJson(documentRecord.data, enabledSet(documentRecord), { includeOriginals: els.optLogOriginals.checked }), `${documentRecord.baseName}_registro.json`, 'application/json;charset=utf-8', { bom: false });
});
els.btnReset.addEventListener('click', () => {
  for (const documentRecord of state.documents) releaseDocument(documentRecord);
  state.documents = [];
  state.activeId = null;
  state.activePageIndex = 0;
  els.dzFile.hidden = true;
  els.dzFile.textContent = '';
  setError('');
  renderDocumentQueue();
  renderActiveDocument();
  showBusy(false);
});

buildCategoryGrid();
renderDocumentQueue();
renderActiveDocument();
showBusy(false);
