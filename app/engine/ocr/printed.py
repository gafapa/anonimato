"""Text-line recognition (PP-OCRv5 latin, CTC) with per-character positions."""
from __future__ import annotations

import math

import cv2
import numpy as np
import yaml

from .. import models
from ..onnx_runtime import session

HEIGHT = 48
MAX_WIDTH = 3200
WIDTH_STEP = 32
BATCHES = tuple(range(1, 13))


def crop_quad(rgb: np.ndarray, quad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Perspective-rectified crop and the matrix mapping crop pixels back to the image."""
    width = int(max(np.linalg.norm(quad[0] - quad[1]), np.linalg.norm(quad[3] - quad[2])))
    height = int(max(np.linalg.norm(quad[0] - quad[3]), np.linalg.norm(quad[1] - quad[2])))
    width, height = max(width, 2), max(height, 2)
    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), target)
    crop = cv2.warpPerspective(rgb, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
    return crop, np.linalg.inv(matrix)


class Recognizer:
    def __init__(self, use_gpu: bool = True):
        item = models.model("ocr-rec-latin")
        config = yaml.safe_load(models.model("ocr-rec-latin-yml").path.read_text(encoding="utf-8"))
        self.chars = ["<blank>"] + [str(c) for c in config["PostProcess"]["character_dict"]] + [" "]
        # The recogniser is faster on CPU than through DirectML (and has no per-shape compilation).
        self.session = session(str(item.path), False)
        self.input = self.session.get_inputs()[0].name

    def _tensor(self, crop: np.ndarray) -> tuple[np.ndarray, int]:
        h, w = max(1, crop.shape[0]), max(1, crop.shape[1])
        width = min(MAX_WIDTH, max(16, int(math.ceil(HEIGHT * w / h))))
        resized = cv2.resize(crop, (width, HEIGHT), interpolation=cv2.INTER_CUBIC if h < HEIGHT else cv2.INTER_AREA)
        bgr = resized[:, :, ::-1].astype(np.float32) / 255.0
        return ((bgr - 0.5) / 0.5).transpose(2, 0, 1), width

    def recognize(self, crops: list[np.ndarray], batch: int = 12) -> list[tuple[str, float, list[tuple[float, float]]]]:
        """For each crop: text, mean confidence and per-character (x0, x1) spans in crop pixels."""
        results: list[tuple[str, float, list[tuple[float, float]]] | None] = [None] * len(crops)
        order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / max(1, crops[i].shape[0]))
        for start in range(0, len(order), batch):
            ids = order[start:start + batch]
            tensors = [self._tensor(crops[i]) for i in ids]
            # Fixed width/batch buckets: GPU back-ends compile one graph per input shape.
            max_w = min(MAX_WIDTH, -(-max(t[1] for t in tensors) // WIDTH_STEP) * WIDTH_STEP)
            rows = next(b for b in BATCHES if b >= len(ids))
            data = np.zeros((rows, 3, HEIGHT, max_w), dtype=np.float32)
            for row, (tensor, width) in enumerate(tensors):
                data[row, :, :, :width] = tensor
            probs = self.session.run(None, {self.input: data})[0]
            for row, index in enumerate(ids):
                results[index] = self._decode(probs[row], tensors[row][1], max_w, crops[index].shape[1])
        return [r or ("", 0.0, []) for r in results]

    def _decode(self, prob: np.ndarray, width: int, padded: int, crop_width: int):
        steps = prob.shape[0]
        best = prob.argmax(axis=1)
        scores = prob.max(axis=1)
        step_px = padded / steps
        text, confs, spans = [], [], []
        previous = 0
        for t in range(steps):
            index = int(best[t])
            if index != 0 and index != previous:
                text.append(self.chars[index] if index < len(self.chars) else "")
                confs.append(float(scores[t]))
                spans.append([t, t])
            elif index != 0 and index == previous and spans:
                spans[-1][1] = t
            previous = index
        return "".join(text), (float(np.mean(confs)) if confs else 0.0), char_extents(spans, step_px * crop_width / width,
                                                                                      crop_width)


def char_extents(spans: list[list[int]], step: float, crop_width: float) -> list[tuple[float, float]]:
    """Horizontal extent of each character from its CTC peak steps.

    A CTC peak marks where a glyph was recognised, not where it starts and ends, so peak-only boxes leave
    gaps and cut the first and last glyph of a line short. Neighbouring characters meet halfway between
    their peaks, and the outer characters reach the edges of the detected line."""
    out = []
    for i, (a, b) in enumerate(spans):
        left = 0.0 if i == 0 else min((a - 0.5) * step, (spans[i - 1][1] + 1 + a) / 2 * step)
        right = crop_width if i == len(spans) - 1 else max((b + 1.5) * step, (b + 1 + spans[i + 1][0]) / 2 * step)
        out.append((max(0.0, left), min(crop_width, right)))
    return out
