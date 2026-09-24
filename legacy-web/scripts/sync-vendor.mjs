import { copyFile, cp, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const copies = [
  ['node_modules/pdfjs-dist/build/pdf.min.mjs', 'vendor/pdf.min.mjs'],
  ['node_modules/pdfjs-dist/build/pdf.worker.min.mjs', 'vendor/pdf.worker.min.mjs'],
  ['node_modules/pdf-lib/dist/pdf-lib.min.js', 'vendor/pdf-lib.min.js'],
  ['node_modules/@mediapipe/tasks-vision/vision_bundle.mjs', 'vendor/mediapipe/vision_bundle.mjs'],
  ['node_modules/tesseract.js/dist/tesseract.esm.min.js', 'vendor/tesseract/tesseract.esm.min.js'],
  ['node_modules/tesseract.js/dist/worker.min.js', 'vendor/tesseract/worker.min.js'],
  ['node_modules/@tesseract.js-data/spa/4.0.0_best_int/spa.traineddata.gz', 'vendor/tesseract/lang/spa.traineddata.gz'],
  ['node_modules/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz', 'vendor/tesseract/lang/eng.traineddata.gz'],
  ['node_modules/mupdf/LICENSE', 'vendor/mupdf/LICENSE'],
  ['node_modules/mupdf/LICENSE', 'LICENSE'],
];

for (const [source, destination] of copies) {
  await mkdir(dirname(join(root, destination)), { recursive: true });
  await copyFile(join(root, source), join(root, destination));
}

await cp(
  join(root, 'node_modules/@mediapipe/tasks-vision/wasm'),
  join(root, 'vendor/mediapipe'),
  { recursive: true }
);

await cp(
  join(root, 'node_modules/tesseract.js-core'),
  join(root, 'vendor/tesseract/core'),
  { recursive: true }
);

await cp(
  join(root, 'node_modules/mupdf/dist'),
  join(root, 'vendor/mupdf'),
  { recursive: true }
);

console.log('Vendored runtime dependencies synchronized.');
