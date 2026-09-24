import { existsSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
import puppeteer from 'puppeteer-core';
import { PDFDocument, rgb } from 'pdf-lib';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);
const CHROME = browserCandidates.find(existsSync);
if (!CHROME) throw new Error('No supported browser found. Set PUPPETEER_EXECUTABLE_PATH.');

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.css': 'text/css', '.wasm': 'application/wasm', '.tflite': 'application/octet-stream',
};
function extOf(p) { const i = p.lastIndexOf('.'); return i < 0 ? '' : p.slice(i).toLowerCase(); }

const server = createServer((req, res) => {
  let p = decodeURIComponent((req.url || '/').split('?')[0]);
  if (p === '/') p = '/index.html';
  try {
    const candidate = join(ROOT, p);
    const relative = candidate.slice(ROOT.length);
    if (relative.includes('..') || !candidate.startsWith(ROOT)) {
      res.writeHead(403); res.end('forbidden'); return;
    }
    const data = readFileSync(candidate);
    res.writeHead(200, {
      'Content-Type': MIME[extOf(p)] || 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'no-store',
    });
    res.end(data);
  } catch (e) {
    console.log('SERVER 404: ' + p);
    res.writeHead(404); res.end('nf');
  }
});
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;

// Build a deterministic test PDF.
async function buildTestPdf(scannedImageBytes) {
  const doc = await PDFDocument.create();
  doc.setTitle('Documento de prueba');

  const p1 = doc.addPage([595.3, 841.9]);
  const lines = [
    'CONTRATO DE PRESTACION DE SERVICIOS',
    '',
    'El Sr. Juan Garcia Perez, mayor de edad, con DNI 12345678Z,',
    'con domicilio en Calle Mayor 12, 28013 Madrid.',
    '',
    'Fecha de nacimiento: 14/03/1985.',
    'Telefono de contacto: 600 123 456',
    'Correo electronico: juan.garcia@correo.es',
    '',
    'Cliente: Maria del Carmen Rodriguez Gomez.',
    'Matricula del vehiculo: 1234 BCD.',
  ];
  let y = 790;
  for (const ln of lines) {
    p1.drawText(ln, { x: 60, y, size: 12 });
    y -= 22;
  }

  const p2 = doc.addPage([595.3, 841.9]);
  // Use MediaPipe's sample portrait when the network is available.
  let faceBytes = null;
  try {
    const r = await fetch('https://storage.googleapis.com/mediapipe-assets/portrait.jpg');
    if (r.ok) faceBytes = new Uint8Array(await r.arrayBuffer());
  } catch { /* no internet */ }
  if (faceBytes) {
    const img = await doc.embedJpg(faceBytes);
    p2.drawImage(img, { x: 160, y: 300, width: 275, height: 380 });
  }
  p2.drawText('Fdo: Manuel Lopez Torres.', { x: 60, y: 240, size: 12 });
  p2.drawText('DNI 87654321X. Telefono 654321987.', { x: 60, y: 220, size: 12 });

  const form = doc.getForm();
  const nameField = form.createTextField('Nombre completo');
  nameField.setText('Ana Lopez Torres');
  nameField.addToPage(p2, { x: 60, y: 170, width: 220, height: 24 });
  const dniField = form.createTextField('DNI');
  dniField.setText('11223344B');
  dniField.addToPage(p2, { x: 300, y: 170, width: 130, height: 24 });

  const p3 = doc.addPage([595.3, 841.9]);
  const scannedImage = await doc.embedPng(scannedImageBytes);
  p3.drawImage(scannedImage, { x: 48, y: 610, width: 500, height: 125 });

  return await doc.save();
}

const tmp = join(os.tmpdir(), 'anon-e2e-' + Date.now());
mkdirSync(tmp, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-webgl'],
});
const scanPage = await browser.newPage();
await scanPage.setViewport({ width: 1200, height: 300, deviceScaleFactor: 1 });
await scanPage.setContent('<main style="font: 700 48px Arial; padding: 35px; background: white; color: black">Nombre: Laura Sanchez Martin<br>DNI: 33445566R</main>');
const scannedImageBytes = await scanPage.screenshot({ type: 'png' });
await scanPage.close();
const pdfPath = join(tmp, 'prueba.pdf');
writeFileSync(pdfPath, Buffer.from(await buildTestPdf(scannedImageBytes)));

const page = await browser.newPage();
if (process.env.TEST_VIEWPORT_WIDTH) {
  await page.setViewport({
    width: Number(process.env.TEST_VIEWPORT_WIDTH),
    height: Number(process.env.TEST_VIEWPORT_HEIGHT || 900),
  });
}
const client = await page.createCDPSession();
await client.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: tmp });

const failures = [];
let checks = 0;
function ok(cond, label) {
  checks++;
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`);
  if (!cond) failures.push(label);
}

try {
  page.on('pageerror', (e) => { failures.push('pageerror: ' + e.message); console.log('PAGEERROR:', e.message); });
  page.on('console', (m) => { if (m.type() === 'error') { failures.push('console.error: ' + m.text()); console.log('CONSOLE_ERROR:', m.text()); } });

  await page.goto(base, { waitUntil: 'networkidle0' });
  ok(true, 'carga de index.html');
  await page.waitForSelector('#catGrid .cat', { timeout: 10000 });
  const nCats = await page.$$eval('#catGrid .cat', (a) => a.length);
  ok(nCats === 13, `13 categorías en la UI (hay ${nCats})`);
  const defaultReplacementMode = await page.$eval('#optMode', (element) => element.value);
  ok(defaultReplacementMode === 'label', 'sustitución por token activada por defecto');

  const input = await page.$('#fileInput');
  await input.uploadFile(pdfPath);
  await page.waitForFunction(() => !document.getElementById('dzFile').hidden);
  const dzTxt = await page.$eval('#dzFile', (el) => el.textContent);
  ok(/1 documento añadido/.test(dzTxt), 'archivo añadido a la cola: ' + dzTxt);

  await page.click('#btnRun');
  await page.waitForSelector('#resultsCard:not([hidden])', { timeout: 90000 });
  await page.waitForSelector('.page-image-wrap:not(.loading-preview)', { timeout: 90000 });

  const rows = await page.$$eval('#rowsBody tr', (trs) => trs.map((tr) => {
    const tds = [...tr.querySelectorAll('td')];
    const badge = tr.querySelector('.type-badge');
    return { tipo: badge?.textContent, orig: tds[4]?.textContent, token: tds[5]?.textContent, pag: tds[1]?.textContent };
  }));

  const byOrig = {};
  for (const r of rows) byOrig[r.orig] = r;

  const expect = {
    '12345678Z': 'DNI / NIF',
    '87654321X': 'DNI / NIF',
    '11223344B': 'DNI / NIF',
    '33445566R': 'DNI / NIF',
    'juan.garcia@correo.es': 'Email',
    '600 123 456': 'Teléfono',
    '654321987': 'Teléfono',
    '14/03/1985': 'Fecha nacimiento',
    '1234 BCD': 'Matrícula',
  };
  let hits = 0;
  for (const [orig, tipo] of Object.entries(expect)) {
    const found = rows.find((r) => r.orig === orig);
    if (found?.tipo === tipo) hits++;
    else ok(false, `detectado "${orig}" como ${tipo} (estado: ${found ? found.tipo : 'no detectado'})`);
  }
  ok(hits === Object.keys(expect).length, `${hits}/${Object.keys(expect).length} PII esperadas detectadas`);

  const names = rows.filter((r) => r.tipo === 'Nombres').map((r) => r.orig);
  console.log('DUMP ROWS:\n' + JSON.stringify(rows, null, 2));
  ok(names.some((n) => n.includes('Juan Garcia')), 'nombre con título: ' + names.join(' | '));
  ok(names.some((n) => n.includes('Ana Lopez Torres')), 'valor de formulario AcroForm: ' + names.join(' | '));
  ok(names.some((n) => n.includes('Laura Sanchez Martin')), 'nombre leído dentro de una imagen por OCR: ' + names.join(' | '));
  ok(names.some((n) => /Maria Carmen Rodriguez/.test(n)), 'nombre con partículas removidas: ' + names.join(' | '));
  ok(names.every((n) => !/\bMatricula\b/.test(n)), 'sin colarse palabras del texto vecino: ' + names.join(' | '));

  const faces = rows.filter((r) => r.tipo === 'Rostros (imagen)');
  console.log('INFO: rostros detectados = ' + faces.length);
  ok(faces.length >= 1, 'rostros detectados y contabilizados');

  const visiblePages = await page.$$eval('#gallery figure', (items) => items.length);
  ok(visiblePages === 1, `previsualización muestra una sola página (${visiblePages})`);
  const originalPages = await page.$$eval('#originalGallery figure', (items) => items.length);
  ok(originalPages === 1, `original visible junto al anonimizado (${originalPages})`);
  const comparisonColumns = await page.$$eval('.comparison-grid .document-column', (items) => items.length);
  ok(comparisonColumns === 2, `comparación en dos columnas (${comparisonColumns})`);
  if (process.env.VISUAL_SCREENSHOT) {
    await page.screenshot({ path: process.env.VISUAL_SCREENSHOT, fullPage: true });
  }
  const firstIndicator = await page.$eval('#pageIndicator', (element) => element.textContent);
  ok(firstIndicator === 'Página 1 de 3', `indicador inicial: ${firstIndicator}`);
  await page.click('#btnNextPage');
  await page.waitForSelector('.page-image-wrap:not(.loading-preview)', { timeout: 90000 });
  const secondIndicator = await page.$eval('#pageIndicator', (element) => element.textContent);
  ok(secondIndicator === 'Página 2 de 3', `navegación página a página: ${secondIndicator}`);

  // Verify that manual-redaction mode is available on the anonymized page.
  await page.click('#btnManual');
  await page.waitForFunction(() => document.getElementById('btnManual').getAttribute('aria-pressed') === 'true');
  ok(true, 'modo de ocultación manual disponible en el anonimizado');
  await page.click('#btnManual');

  // Disable one row and verify that exports honor the selection.
  await page.$$eval('#rowsBody input', (cbs) => { if (cbs[0]) cbs[0].click(); });
  await new Promise((r) => setTimeout(r, 900));
  const countTxt = await page.$eval('#rowsCount', (el) => el.textContent);
  ok(/\((\d+)\/\d+ incluidos\)/.test(countTxt), 'contador actualizado: ' + countTxt);

  // CSV must be privacy-preserving by default.
  await page.click('#btnCsv');
  await waitForFile(tmp, '_registro.csv');
  const csv = readFileSync(join(tmp, 'prueba_registro.csv'), 'utf8');
  ok(!csv.includes('12345678Z') && csv.includes('NOMBRE') && csv.includes('TELÉFONO'), 'CSV oculta valores originales');

  // JSON must exclude disabled entries and original values by default.
  await page.click('#btnJson');
  await waitForFile(tmp, '_registro.json');
  const json = JSON.parse(readFileSync(join(tmp, 'prueba_registro.json'), 'utf8'));
  ok(json.numPaginas === 3 && json.sustituciones.length === rows.length - 1
    && json.sustituciones.every((item) => item.original == null), 'JSON privado respeta la selección');

  // Generate and validate the anonymized PDF.
  await page.$$eval('#rowsBody input', (checkboxes) => { if (checkboxes[0] && !checkboxes[0].checked) checkboxes[0].click(); });
  await page.click('#btnPdf');
  await waitForFile(tmp, '_anonimizado.pdf');
  const pdfBytes = readFileSync(join(tmp, 'prueba_anonimizado.pdf'));
  if (process.env.TEST_OUTPUT_PDF) {
    mkdirSync(dirname(process.env.TEST_OUTPUT_PDF), { recursive: true });
    writeFileSync(process.env.TEST_OUTPUT_PDF, pdfBytes);
  }
  ok(pdfBytes.subarray(0, 4).toString() === '%PDF' && pdfBytes.length > 2000, `PDF anonimizado válido (${pdfBytes.length} bytes)`);
  const sanitizedDocument = await PDFDocument.load(pdfBytes);
  ok(sanitizedDocument.getForm().getFields().length === 0
    && sanitizedDocument.getPages().every((pdfPage) => {
      const annotations = pdfPage.node.Annots();
      return !annotations || annotations.size() === 0;
    }),
  'PDF final sin campos AcroForm ni anotaciones reutilizables');
  const textLoadingTask = pdfjs.getDocument({ data: new Uint8Array(pdfBytes), isEvalSupported: false });
  const textPdf = await textLoadingTask.promise;
  let extractedText = '';
  for (let pageNumber = 1; pageNumber <= textPdf.numPages; pageNumber++) {
    const textPage = await textPdf.getPage(pageNumber);
    const textContent = await textPage.getTextContent();
    extractedText += textContent.items.map((item) => item.str || '').join(' ');
  }
  await textLoadingTask.destroy();
  ok(!/Juan|12345678Z|juan\.garcia@correo\.es|Ana Lopez Torres|11223344B|Laura Sanchez Martin|33445566R/.test(extractedText),
    'PDF final sin texto personal extraíble ni datos ocultos bajo capas');
  ok(/\[NOMBRE 1\]/.test(extractedText) && /\[DNI 1\]/.test(extractedText),
    'tokens de reemplazo insertados como texto PDF extraíble');

  // Add another PDF without clearing the completed document.
  await input.uploadFile(pdfPath);
  await page.waitForFunction(() => document.querySelectorAll('#documentQueue .document-item').length === 2);
  const queuedDocuments = await page.$$eval('#documentQueue .document-item', (items) => items.length);
  ok(queuedDocuments === 2, `cola conserva y añade documentos (${queuedDocuments})`);
  await page.click('#btnRun');
  await page.waitForFunction(() => [...document.querySelectorAll('.document-status')]
    .filter((element) => element.textContent.includes('listo')).length === 2, { timeout: 120000 });
  ok(true, 'procesamiento consecutivo de varios PDF');
} catch (e) {
  failures.push('excepción global: ' + e.stack);
  console.error(e);
} finally {
  await browser.close();
  server.close();
  rmSync(tmp, { recursive: true, force: true });
}

console.log(`\n${checks - failures.length}/${checks} comprobaciones OK`);
if (failures.length) { console.log('\nFALLOS:\n' + failures.join('\n')); process.exit(1); }

function waitForFile(dir, suffix, ms = 20000) {
  const end = Date.now() + ms;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const f = readdirSync(dir).find((n) => n.endsWith(suffix));
      if (f) return resolve();
      if (Date.now() > end) return reject(new Error('timeout esperando ' + suffix));
      setTimeout(tick, 200);
    };
    tick();
  });
}
