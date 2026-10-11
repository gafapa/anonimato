"""Independent positional ground truth and complete-occurrence coverage."""
import copy
import math
from itertools import pairwise
import pymupdf
import regex
from app.engine.document import page_text
from app.engine.propagate import NormalizedText


def annotate(data, truth):
    result = copy.deepcopy(truth)
    with pymupdf.open('pdf', data) as doc:
        for item in result:
            if 'occurrences' in item:
                continue
            item['occurrences'] = []
            words = NormalizedText(item['value']).text.split()
            if not words:
                continue
            pattern = r'[\s,]*'.join(regex.escape(word) for word in words)
            for index, page in enumerate(doc):
                source = page_text(page)
                normalized = NormalizedText(source.text)
                for match in regex.finditer(pattern, normalized.text):
                    rects = source.rects_for(*normalized.span(match.start(), match.end()))
                    if rects:
                        item['occurrences'].append({'page': index, 'rects': [list(rect) for rect in rects]})
    return result


def project(truth, source_page, target_page, image_size, *, angle=0, affine=None):
    result = copy.deepcopy(truth)
    width, height = image_size
    placement = target_page.get_image_rects(target_page.get_images()[0][0], transform=True)[0][1]
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    inverse = ~pymupdf.Matrix(affine[0], affine[3], affine[1], affine[4], affine[2], affine[5]) if affine else None
    def point(x, y):
        shown = pymupdf.Point(x, y) * source_page.rotation_matrix
        px, py = shown.x * width / source_page.rect.width, shown.y * height / source_page.rect.height
        px, py = (width / 2 + cosine * (px - width / 2) + sine * (py - height / 2),
                  height / 2 - sine * (px - width / 2) + cosine * (py - height / 2))
        pixel = pymupdf.Point(px, py)
        if inverse:
            pixel *= inverse
        return pymupdf.Point(pixel.x / width, pixel.y / height) * placement
    for item in result:
        for occurrence in item.get('occurrences', []):
            rectangles = []
            for x0, y0, x1, y1 in occurrence['rects']:
                points = [point(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                rectangles.append([min(p.x for p in points), min(p.y for p in points),
                                   max(p.x for p in points), max(p.y for p in points)])
            occurrence.update(page=0, rects=rectangles)
    return result


def rect_covered(analysis, rect, page):
    x0, y0, x1, y1 = rect
    area = (x1 - x0) * (y1 - y0)
    if area <= 0:
        return False
    parts = []
    for finding in analysis.findings:
        if finding.enabled and finding.page == page:
            for left, top, right, bottom in finding.rects:
                clipped = (max(x0, left - 1.5), max(y0, top - 1.5), min(x1, right + 1.5), min(y1, bottom + 1.5))
                if clipped[0] < clipped[2] and clipped[1] < clipped[3]:
                    parts.append(clipped)
    edges = sorted({x for part in parts for x in (part[0], part[2])})
    covered_area = 0
    for left, right in pairwise(edges):
        intervals = sorted((part[1], part[3]) for part in parts if part[0] <= left and part[2] >= right)
        reach, height = y0, 0
        for top, bottom in intervals:
            height += max(0, bottom - max(top, reach))
            reach = max(reach, bottom)
        covered_area += (right - left) * height
    return covered_area >= 0.98 * area


def coverage(analysis, item):
    occurrences = item.get('occurrences', [])
    hits = sum(bool(occurrence.get('rects')) and all(rect_covered(analysis, rect, occurrence['page'])
               for rect in occurrence['rects']) for occurrence in occurrences)
    return hits, len(occurrences)
