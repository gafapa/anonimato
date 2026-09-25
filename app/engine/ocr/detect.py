"""Text-line detection (PP-OCRv5 server det, DB post-processing) and page orientation."""
from __future__ import annotations

import cv2
import numpy as np

from .. import models
from ..onnx_runtime import session

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class LineDetector:
    def __init__(self, use_gpu: bool = True, max_side: int = 2048):
        from ..onnx_runtime import gpu_active
        self.session = session(str(models.model("ocr-det").path), use_gpu)
        if not gpu_active():
            # Without a GPU the server model takes ~40 s per page: use the light model.
            self.session = session(str(models.model("ocr-det-mobile").path), False)
            max_side = min(max_side, 1600)
        self.input = self.session.get_inputs()[0].name
        self.max_side = max_side

    def _prepare(self, rgb: np.ndarray) -> tuple[np.ndarray, float, float]:
        """Resize (keeping aspect) and pad to a small set of fixed sizes.

        GPU back-ends compile one graph per input shape; padding to 256-pixel buckets keeps
        the number of shapes (and compilations) small.
        """
        h, w = rgb.shape[:2]
        ratio = min(1.0, self.max_side / max(h, w))
        if max(h, w) * ratio < 960:  # small images are enlarged so thin handwriting is detected
            ratio = 960 / max(h, w)
        nh, nw = max(32, int(round(h * ratio))), max(32, int(round(w * ratio)))
        resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_CUBIC)
        bh, bw = -(-nh // 256) * 256, -(-nw // 256) * 256
        canvas = np.full((bh, bw, 3), 255, dtype=np.uint8)
        canvas[:nh, :nw] = resized
        bgr = canvas[:, :, ::-1].astype(np.float32) / 255.0
        tensor = ((bgr - MEAN) / STD).transpose(2, 0, 1)[None]
        return np.ascontiguousarray(tensor, dtype=np.float32), w / nw, h / nh

    def detect(self, rgb: np.ndarray) -> list[np.ndarray]:
        """Return quadrilaterals (4x2 float arrays, pixel coords), reading order."""
        tensor, sx, sy = self._prepare(rgb)
        try:
            prob = self.session.run(None, {self.input: tensor})[0][0, 0]
        except Exception:  # noqa: BLE001 - GPU lost or out of memory: continue on CPU
            self.session = session(str(models.model("ocr-det-mobile").path), False)
            self.input = self.session.get_inputs()[0].name
            self.max_side = min(self.max_side, 1600)
            tensor, sx, sy = self._prepare(rgb)
            prob = self.session.run(None, {self.input: tensor})[0][0, 0]
        bitmap = (prob > 0.3).astype(np.uint8)
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if len(c) >= 4 and cv2.contourArea(c) >= 12]
        contours.sort(key=cv2.contourArea, reverse=True)
        limit = max(bitmap.shape) * 0.08
        boxes = []
        for contour in contours[:4000]:
            (cx, cy), (bw, bh), angle = cv2.minAreaRect(contour)
            if min(bw, bh) < 3:
                continue
            if min(bw, bh) > limit and max(bw, bh) / max(1.0, min(bw, bh)) < 3:
                continue  # blob (texture, photo, stain, noise), not a text line
            x, y, cw, ch = cv2.boundingRect(contour)
            mask = np.zeros((ch, cw), dtype=np.uint8)
            cv2.drawContours(mask, [contour - [x, y]], -1, 1, -1)
            score = float(cv2.mean(prob[y:y + ch, x:x + cw], mask)[0])
            if score < 0.5:
                continue
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            distance = area * 1.5 / max(perimeter, 1e-6)
            rect = ((cx, cy), (bw + 2 * distance, bh + 2 * distance), angle)
            if min(rect[1]) < 5:
                continue
            pts = cv2.boxPoints(rect)
            pts[:, 0] = np.clip(pts[:, 0] * sx, 0, rgb.shape[1] - 1)
            pts[:, 1] = np.clip(pts[:, 1] * sy, 0, rgb.shape[0] - 1)
            boxes.append(_order(pts))
        boxes.sort(key=lambda q: (round(q[:, 1].mean() / 10), q[:, 0].min()))
        return boxes


def _order(pts: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    pts = pts[np.argsort(pts[:, 0])]
    left, right = pts[:2], pts[2:]
    tl, bl = left[np.argsort(left[:, 1])]
    tr, br = right[np.argsort(right[:, 1])]
    return np.array([tl, tr, br, bl], dtype=np.float32)


class OrientationClassifier:
    """Predicts how a page image is rotated: 0, 90, 180 or 270 degrees."""

    def __init__(self, use_gpu: bool = True):
        self.session = session(str(models.model("ocr-doc-ori").path), False)
        self.input = self.session.get_inputs()[0].name

    def predict(self, rgb: np.ndarray) -> tuple[int, float]:
        h, w = rgb.shape[:2]
        scale = 256 / min(h, w)
        resized = cv2.resize(rgb, (max(224, int(w * scale)), max(224, int(h * scale))), interpolation=cv2.INTER_AREA)
        rh, rw = resized.shape[:2]
        top, left = (rh - 224) // 2, (rw - 224) // 2
        crop = resized[top:top + 224, left:left + 224].astype(np.float32) / 255.0
        tensor = ((crop - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
        scores = self.session.run(None, {self.input: tensor})[0][0]
        index = int(np.argmax(scores))
        return (0, 90, 180, 270)[index], float(scores[index])
