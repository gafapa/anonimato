import { FilesetResolver, FaceDetector } from '../vendor/mediapipe/vision_bundle.mjs';

const BASE = new URL('../vendor/mediapipe/', import.meta.url).href;

export async function createFaceDetector(onStatus) {
  onStatus?.({ phase: 'model-load' });
  const vision = await FilesetResolver.forVisionTasks(BASE);
  let delegate = 'GPU';
  let detector = null;
  for (const d of [delegate, 'CPU']) {
    try {
      detector = await FaceDetector.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: BASE + 'blaze_face_short_range.tflite',
          delegate: d,
        },
        runningMode: 'IMAGE',
        minDetectionConfidence: 0.6,
      });
      onStatus?.({ phase: 'model-ready', delegate: d });
      break;
    } catch (e) {
      if (d === delegate) delegate = 'CPU';
      else throw e;
    }
  }
  return {
    detect(canvas) {
      const res = detector.detect(canvas);
      const out = [];
      for (const det of res?.detections || []) {
        const b = det.boundingBox;
        if (!b || b.width <= 0 || b.height <= 0) continue;
        out.push({ nx: b.originX, ny: b.originY, nw: b.width, nh: b.height });
      }
      return out;
    },
  };
}
