"""Deterministic, entirely fictitious Galician review cases with challenging layout."""
from __future__ import annotations

import random

import pymupdf
from PIL import Image, ImageFont
import io


def challenging_documents(seed: int, *, include_scanned: bool = False) -> list[tuple]:
    from tools.evaluate_detection import scanned

    rng = random.Random(seed + 103)
    corpus = []
    for index, name in enumerate(("Uxía Mouriño Rial", "Xoán Quintairos Varela", "Ánxela Seoane Otero", "Brais Bouzas Castro")):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 60), "REXISTRO FICTICIO DE AVALIACION", fontsize=14)
        for row in range(4):
            y = 120 + row * 70
            page.draw_rect((40, y - 20, 555, y + 30))
            page.draw_line((270, y - 20), (270, y + 30))
            page.insert_text((50, y), "Nome e apelidos:", fontsize=10)
            page.insert_text((280, y), name, fontsize=8 + index)
        page.insert_text((40, 780), f"Nota marxinal: {name}", fontsize=7)
        page.set_rotation(90 if index % 2 else 0)
        data = doc.tobytes()
        doc.close()
        from tools.occurrence_evaluation import annotate, project
        truth = annotate(data, [{"type": "name", "value": name}])
        corpus.append(("layout", f"galician-table-{index}", data, truth))
        if include_scanned:
            scan, scan_truth = scanned(data, rng, truth)
            corpus.append(("noisy-layout", f"galician-table-{index}", scan, scan_truth))
            with pymupdf.open("pdf", data) as opened:
                pix = opened[0].get_pixmap(dpi=80)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            image = image.transform(image.size, Image.Transform.AFFINE, (1, 0.025, 0, 0.015, 1, 0), fillcolor="white")
            stream = io.BytesIO()
            image.save(stream, "JPEG", quality=45)
            with pymupdf.open() as photo:
                target = photo.new_page(width=595, height=842)
                target.insert_image(target.rect, stream=stream.getvalue())
                with pymupdf.open("pdf", data) as original:
                    photo_truth = project(truth, original[0], target, image.size, affine=(1, 0.025, 0, 0.015, 1, 0))
                corpus.append(("low-resolution-photo", f"galician-table-{index}", photo.tobytes(), photo_truth))
    from tests.fixtures.generate import DNI, NAME, f23_handwritten, system_font
    data = f23_handwritten()
    font = ImageFont.truetype(system_font("hand"), 44)
    with pymupdf.open('pdf', data) as opened:
        placement = opened[0].get_image_rects(opened[0].get_images()[0][0], transform=True)[0][1]
        handwritten_truth = []
        for category, value, position in [('name', NAME, (300, 290)), ('dni', DNI, (300, 370))]:
            x0, y0, x1, y1 = font.getbbox(value)
            rectangle = pymupdf.Rect((position[0] + x0) / 1240, (position[1] + y0) / 1754,
                                     (position[0] + x1) / 1240, (position[1] + y1) / 1754) * placement
            handwritten_truth.append({'type': category, 'value': value,
                                       'occurrences': [{'page': 0, 'rects': [list(rectangle)]}]})
    corpus.append(("synthetic-handwriting", "mixed-print-handwriting", data, handwritten_truth))
    return corpus
