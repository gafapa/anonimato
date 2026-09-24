"""Face detection with OpenCV YuNet over the whole page and overlapping tiles at two scales."""
from __future__ import annotations

import cv2
import numpy as np

from . import models

TILE = 640
OVERLAP = 0.25


def _nms(boxes: list[tuple[float, float, float, float, float]], threshold: float = 0.3):
    if not boxes:
        return []
    arr = np.array(boxes, dtype=np.float32)
    x0, y0, x1, y1, score = arr.T
    order = score.argsort()[::-1]
    area = (x1 - x0) * (y1 - y0)
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx0 = np.maximum(x0[i], x0[order[1:]])
        yy0 = np.maximum(y0[i], y0[order[1:]])
        xx1 = np.minimum(x1[i], x1[order[1:]])
        yy1 = np.minimum(y1[i], y1[order[1:]])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        overlap = inter / np.minimum(area[i], area[order[1:]])
        order = order[1:][overlap < threshold]
    return [tuple(float(v) for v in arr[i]) for i in keep]


class FaceDetector:
    def __init__(self, score: float = 0.6):
        self.path = str(models.model("faces-yunet").path)
        self.score = score
        self._detector = cv2.FaceDetectorYN.create(self.path, "", (320, 320), score, 0.3, 5000)

    def _run(self, bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        h, w = bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(bgr)
        out = []
        if faces is not None:
            for face in faces:
                x, y, fw, fh, score = float(face[0]), float(face[1]), float(face[2]), float(face[3]), float(face[-1])
                if fw > 4 and fh > 4:
                    out.append((x, y, x + fw, y + fh, score))
        return out

    def detect(self, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Face boxes in pixel coordinates of ``rgb``."""
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        h, w = bgr.shape[:2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        midtones = ((gray > 40) & (gray < 215)).astype(np.float32)
        found: list[tuple[float, float, float, float, float]] = []
        # Whole page, downscaled so large faces fit the model's receptive field.
        scale = min(1.0, 1280 / max(h, w))
        small = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
        found += [(x0 / scale, y0 / scale, x1 / scale, y1 / scale, s) for x0, y0, x1, y1, s in self._run(small)]
        # Tiles at native resolution and upscaled x2 for small faces (ID photos in an A4 page).
        for zoom in (1.0, 2.0):
            tile = int(TILE / zoom)
            step = max(1, int(tile * (1 - OVERLAP)))
            for top in range(0, max(1, h - tile // 4), step):
                for left in range(0, max(1, w - tile // 4), step):
                    crop = bgr[top:top + tile, left:left + tile]
                    if crop.shape[0] < 32 or crop.shape[1] < 32:
                        continue
                    # Photographs have many mid-tones; text and blank paper do not.
                    if midtones[top:top + tile, left:left + tile].mean() < 0.08:
                        continue
                    if zoom != 1.0:
                        crop = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
                    for x0, y0, x1, y1, s in self._run(crop):
                        found.append((left + x0 / zoom, top + y0 / zoom, left + x1 / zoom, top + y1 / zoom, s))
        return [(b[0], b[1], b[2], b[3]) for b in _nms(found)]
