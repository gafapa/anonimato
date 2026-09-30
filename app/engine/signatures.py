"""Handwritten signature regions next to "Firma / Fdo." labels (ink without legible text)."""
from __future__ import annotations

import cv2
import numpy as np
import regex as re

LABEL = re.compile(r"(?i)\b(?:firma(?:do)?|fdo\.?|signature|signed|sinatura|signatura|sinadura|izenpea)\b")


def find(image: np.ndarray, labels: list[tuple[float, float, float, float]],
         text_boxes: list[tuple[float, float, float, float]]) -> list[tuple[int, int, int, int]]:
    """Pixel boxes of ink blobs to the right of / below each label box (all in pixel coords)."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    ink = (gray < 170).astype(np.uint8)
    for x0, y0, x1, y1 in text_boxes:  # ignore printed/recognised text
        ink[int(max(0, y0)):int(y1) + 1, int(max(0, x0)):int(x1) + 1] = 0
    h, w = gray.shape
    found = []
    for x0, y0, x1, y1 in labels:
        lh = max(8.0, y1 - y0)
        regions = [
            (x1, y0 - 0.8 * lh, min(w, x1 + 22 * lh), y1 + 3.5 * lh),       # right of the label
            (x0 - 2 * lh, y1, min(w, x0 + 22 * lh), min(h, y1 + 7 * lh)),   # below the label
        ]
        for region_box in regions:
            rx0, ry0 = int(max(0, region_box[0])), int(max(0, region_box[1]))
            rx1, ry1 = int(min(w, region_box[2])), int(min(h, region_box[3]))
            if rx1 - rx0 < 10 or ry1 - ry0 < 10:
                continue
            region = ink[ry0:ry1, rx0:rx1]
            if region.sum() < max(60, 0.002 * region.size):
                continue
            count, _, stats, _ = cv2.connectedComponentsWithStats(region, connectivity=8)
            boxes = [stats[i] for i in range(1, count) if stats[i][4] >= 15]
            if not boxes:
                continue
            bx0 = min(b[0] for b in boxes)
            by0 = min(b[1] for b in boxes)
            bx1 = max(b[0] + b[2] for b in boxes)
            by1 = max(b[1] + b[3] for b in boxes)
            if (bx1 - bx0) < 1.5 * lh:
                continue
            found.append((rx0 + bx0, ry0 + by0, rx0 + bx1, ry0 + by1))
    return found
