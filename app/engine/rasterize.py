"""Maximum-security mode: every page becomes a flat image of its anonymised appearance.

Nothing that is not visible can survive. An optional invisible text layer is built by
OCR *from the anonymised image*, so it can only contain what is visible.
"""
from __future__ import annotations

import io

import pymupdf
from PIL import Image

from . import document


def rasterize(data: bytes, dpi: int = 300, ocr=None) -> bytes:
    source = pymupdf.open("pdf", data)
    output = pymupdf.open()
    for page in source:
        rendered = document.render(page, dpi)
        scale, image = rendered.scale, rendered.image
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, "JPEG", quality=92, subsampling=0, optimize=True)
        target = output.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=buffer.getvalue())
        if ocr is not None:
            for line in ocr.read(image):
                x0, y0, x1, y1 = (v / scale for v in line.rect)
                height = y1 - y0
                if height <= 1 or not line.text.strip():
                    continue
                size = height * 0.8
                width = pymupdf.get_text_length(line.text, fontname="helv", fontsize=size)
                if width > 0 and width > (x1 - x0):
                    size *= (x1 - x0) / width
                target.insert_text((x0, y1 - height * 0.2), line.text, fontname="helv", fontsize=max(1.0, size),
                                   render_mode=3)
    source.close()
    result = output.tobytes(garbage=4, deflate=True, deflate_fonts=True, no_new_id=False)
    output.close()
    return result
