"""Destructive redaction and replacement tokens (PyMuPDF / MuPDF)."""
from __future__ import annotations

import pymupdf

from .types import Finding, Rect

NATIVE_SOURCES = {"text", "form", "propagation", "ai", "llm", "rules"}
BLACK_TYPES = {"face", "signature"}
UNIFORM_STEP = 36.0


def _pad(rect: Rect, finding: Finding) -> pymupdf.Rect:
    r = pymupdf.Rect(rect)
    if finding.type == "manual":
        return r
    if finding.type in BLACK_TYPES:
        dx, dy = r.width * 0.08, r.height * 0.08
        return pymupdf.Rect(r.x0 - dx, r.y0 - dy, r.x1 + dx, r.y1 + dy)
    pad = max(0.6, min(r.height * 0.12, 2.5))
    return pymupdf.Rect(r.x0 - pad, r.y0 - pad * 0.5, r.x1 + pad, r.y1 + pad * 0.5)


def _uniform(rect: pymupdf.Rect, blockers: list[pymupdf.Rect]) -> pymupdf.Rect:
    """Widen a redaction to a quantised width without touching other visible text."""
    target = max(UNIFORM_STEP, -(-rect.width // UNIFORM_STEP) * UNIFORM_STEP)
    limit = rect.x0 + target
    for other in blockers:
        if other.y1 > rect.y0 and other.y0 < rect.y1 and other.x0 >= rect.x1 - 0.5:
            limit = min(limit, other.x0 - 0.5)
    return pymupdf.Rect(rect.x0, rect.y0, max(rect.x1, limit), rect.y1)


def _text_like_drawings(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    """Vector paths that look like glyph outlines (not page backgrounds) inside the area."""
    try:
        drawings = page.get_drawings()
    except Exception:
        return False
    for drawing in drawings:
        area = pymupdf.Rect(drawing["rect"])
        if area.intersects(rect) and area.height <= max(3 * rect.height, 40):
            return True
    return False


def _remove_outside_crop(page: pymupdf.Page) -> None:
    crop = pymupdf.Rect(page.cropbox)
    media = pymupdf.Rect(page.mediabox)
    if crop.contains(media):
        return
    page.set_cropbox(media)
    outside = [
        pymupdf.Rect(media.x0, media.y0, media.x1, crop.y0),
        pymupdf.Rect(media.x0, crop.y1, media.x1, media.y1),
        pymupdf.Rect(media.x0, crop.y0, crop.x0, crop.y1),
        pymupdf.Rect(crop.x1, crop.y0, media.x1, crop.y1),
    ]
    added = 0
    for rect in outside:
        if rect.width > 0.5 and rect.height > 0.5:
            page.add_redact_annot(rect, fill=False)
            added += 1
    if added:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    page.set_cropbox(crop)


def _fit_token(page: pymupdf.Page, rect: pymupdf.Rect, token: str) -> None:
    size = max(3.0, min(rect.height * 0.72, 11.0))
    width = pymupdf.get_text_length(token, fontname="helv", fontsize=size)
    if width > rect.width - 1:
        size = max(2.5, size * (rect.width - 1) / max(width, 1))
        width = pymupdf.get_text_length(token, fontname="helv", fontsize=size)
    x = rect.x0 + max(0.0, (rect.width - width) / 2)
    y = rect.y0 + (rect.height + size * 0.7) / 2
    page.insert_text((x, y), token, fontname="helv", fontsize=size, color=(0, 0, 0),
                     rotate=0, morph=None)


def apply(doc: pymupdf.Document, findings: list[Finding], mode: str = "label", uniform: bool = False) -> None:
    by_page: dict[int, list[Finding]] = {}
    for finding in findings:
        if finding.enabled and finding.rects:
            by_page.setdefault(finding.page, []).append(finding)
    for index in range(doc.page_count):
        page = doc[index]
        _remove_outside_crop(page)
        items = by_page.get(index, [])
        if not items:
            continue
        rotation = page.rotation
        if rotation:
            page.set_rotation(0)  # annotations and text insertion in unrotated space
        native_blocks = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks", clip=pymupdf.INFINITE_RECT())]
        placements: list[tuple[Finding, list[pymupdf.Rect]]] = []
        aggressive = False
        for finding in items:
            rects = [_pad(r, finding) for r in finding.rects]
            if uniform and finding.type not in BLACK_TYPES and finding.type != "manual":
                rects = [_uniform(r, native_blocks) for r in rects]
            for rect in rects:
                page.add_redact_annot(rect, fill=False)
            if finding.source not in NATIVE_SOURCES and any(_text_like_drawings(page, r) for r in rects):
                aggressive = True
            placements.append((finding, rects))
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
            graphics=(pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED if aggressive
                      else pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED),
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        for finding, rects in placements:
            if finding.type in BLACK_TYPES:
                for rect in rects:
                    page.draw_rect(rect, color=None, fill=(0, 0, 0), overlay=True)
            elif mode == "label" and finding.token:
                main = max(rects, key=lambda r: r.width)
                _fit_token(page, main, finding.token)
        if rotation:
            page.set_rotation(rotation)


def render_output(data: bytes) -> bytes:
    doc = pymupdf.open("pdf", data)
    try:
        doc.subset_fonts()
    except Exception:
        pass
    out = doc.tobytes(garbage=4, clean=True, deflate=True, deflate_images=True, deflate_fonts=True,
                      no_new_id=False, pretty=False, preserve_metadata=False)
    doc.close()
    return out
