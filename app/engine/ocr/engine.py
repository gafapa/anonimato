"""OCR engine: orientation → line detection → recognition, with character boxes."""
from __future__ import annotations

import cv2
import numpy as np

from ..types import OcrLine
from .detect import LineDetector, OrientationClassifier
from .printed import Recognizer, crop_quad

# Lines read with lower confidence are candidates for the handwriting model.
HANDWRITING_CONFIDENCE = 0.985  # measured in tools/benchmark_handwriting.py (docs/benchmark.md)

# cv2.rotate code that turns an image predicted as rotated by N degrees upright.
# (The classifier answers 90 for an image turned 90° clockwise.)
_UPRIGHT = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_CLOCKWISE}


def _unrotate_points(points: np.ndarray, angle: int, width: int, height: int) -> np.ndarray:
    """Map points of the upright image back to the original image (width/height of the original)."""
    x, y = points[:, 0], points[:, 1]
    if angle == 90:    # upright = original turned counter-clockwise
        return np.stack([width - y, x], axis=1).astype(np.float32)
    if angle == 180:
        return np.stack([width - x, height - y], axis=1).astype(np.float32)
    if angle == 270:   # upright = original turned clockwise
        return np.stack([y, height - x], axis=1).astype(np.float32)
    return points


class OcrEngine:
    def __init__(self, use_gpu: bool = True):
        self.detector = LineDetector(use_gpu)
        self.recognizer = Recognizer(use_gpu)
        self.orientation = OrientationClassifier(use_gpu)

    def page_angle(self, rgb: np.ndarray) -> int:
        angle, confidence = self.orientation.predict(rgb)
        return angle if confidence >= 0.6 else 0

    def warm_up(self) -> None:
        """Compile the GPU graphs for the usual shapes (runs in the background at start-up)."""
        import numpy as _np
        for h, w in ((2048, 1536), (1536, 2048), (2048, 2048), (1536, 1280), (1280, 1536), (1024, 1024)):
            with self.detector._run_lock:
                self.detector.session.run(None, {self.detector.input: _np.zeros((1, 3, h, w), dtype=_np.float32)})

    def read_line(self, rgb: np.ndarray) -> str:
        """Recognise a single-line crop directly (no detection)."""
        return self.recognizer.recognize([rgb])[0][0]

    def read(self, rgb: np.ndarray, detect_orientation: bool = True) -> list[OcrLine]:
        height, width = rgb.shape[:2]
        angle = self.page_angle(rgb) if detect_orientation and min(height, width) > 300 else 0
        work = cv2.rotate(rgb, _UPRIGHT[angle]) if angle else rgb
        quads = self.detector.detect(work)
        crops, inverses, vertical = [], [], []
        for quad in quads:
            crop, inverse = crop_quad(work, quad)
            is_vertical = crop.shape[0] > crop.shape[1] * 1.5
            if is_vertical:
                crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
            crops.append(crop)
            inverses.append(inverse)
            vertical.append(is_vertical)
        results = self.recognizer.recognize(crops) if crops else []
        lines = []
        for quad, crop, inverse, is_vertical, (text, confidence, spans) in zip(quads, crops, inverses, vertical, results):
            if not text.strip() or (confidence < 0.5 and len(text.strip()) <= 2):
                continue
            ch, cw = crop.shape[:2]
            char_rects = []
            for x0, x1 in spans:
                corners = np.array([[x0, 0], [x1, 0], [x1, ch], [x0, ch]], dtype=np.float32)
                if is_vertical:  # undo the counter-clockwise crop rotation
                    corners = np.stack([ch - corners[:, 1], corners[:, 0]], axis=1).astype(np.float32)
                mapped = cv2.perspectiveTransform(corners[None], inverse)[0]
                mapped = _unrotate_points(mapped, angle, width, height)
                char_rects.append((float(mapped[:, 0].min()), float(mapped[:, 1].min()),
                                   float(mapped[:, 0].max()), float(mapped[:, 1].max())))
            box = _unrotate_points(quad, angle, width, height)
            rect = (float(box[:, 0].min()), float(box[:, 1].min()), float(box[:, 0].max()), float(box[:, 1].max()))
            # Characters appended by CTC (e.g. spaces) keep their slot so indices match the text.
            if len(char_rects) != len(text):
                char_rects = []
            lines.append(OcrLine(text=text, rect=rect, confidence=confidence, char_rects=char_rects,
                                 handwritten=confidence < HANDWRITING_CONFIDENCE))
        return lines
