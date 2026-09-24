import Tesseract from '../vendor/tesseract/tesseract.esm.min.js';

const { createWorker } = Tesseract;

let workerPromise = null;

function assetUrl(path) {
  return new URL(path, document.baseURI).href;
}

export async function getOcrWorker(onProgress = () => {}) {
  if (!workerPromise) {
    workerPromise = createWorker(['spa', 'eng'], 1, {
      workerPath: assetUrl('vendor/tesseract/worker.min.js'),
      corePath: assetUrl('vendor/tesseract/core'),
      langPath: assetUrl('vendor/tesseract/lang'),
      logger: (message) => onProgress(message),
    }).catch((error) => {
      workerPromise = null;
      throw error;
    });
  }
  return workerPromise;
}

export async function recognizeCanvas(canvas, onProgress) {
  const worker = await getOcrWorker(onProgress);
  const result = await worker.recognize(canvas, {}, { text: true, blocks: true });
  return result.data;
}
