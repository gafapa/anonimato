"""Opening documents, preparing them for analysis, extracting text and rendering."""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pymupdf
from PIL import Image, ImageOps

from .types import PageText, Rect

LIMITS = {"max_bytes": 300 * 1024 * 1024, "max_pages": 1000, "max_page_pixels": 60_000_000}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
# Real glyphs, not /ActualText replacements (which can hide the visible text from extraction).
TEXT_FLAGS = (pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_ACCURATE_BBOXES
              | pymupdf.TEXT_IGNORE_ACTUALTEXT)
TEXT_FLAGS_ACTUAL = TEXT_FLAGS & ~pymupdf.TEXT_IGNORE_ACTUALTEXT

pymupdf.TOOLS.mupdf_display_errors(False)


class DocumentError(Exception):
    pass


class PasswordRequired(DocumentError):
    pass


def unlock(data: bytes, password: str) -> bytes:
    """Decrypt a password-protected PDF. The anonymised output is never encrypted."""
    doc = pymupdf.open("pdf", data)
    try:
        if doc.needs_pass and not doc.authenticate(password):
            raise DocumentError("Contraseña incorrecta")
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=1)
    finally:
        doc.close()


def is_signed(data: bytes) -> bool:
    """The PDF carries digital signatures (they cannot survive any modification)."""
    doc = pymupdf.open("pdf", data)
    try:
        if doc.get_sigflags() > 0:
            return True
        for page in doc:
            for widget in page.widgets() or []:
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                    return True
        return False
    finally:
        doc.close()


def _order_quad(pts: np.ndarray) -> np.ndarray:
    total = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(total)], pts[np.argmin(diff)], pts[np.argmax(total)], pts[np.argmax(diff)]],
                    dtype=np.float32)


def correct_perspective(image: Image.Image) -> Image.Image:
    """Phone photo of a sheet: find the page outline and flatten it. Scans are returned unchanged."""
    import cv2
    rgb = np.asarray(image.convert("RGB"))
    h, w = rgb.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(rgb, (int(w * scale), int(h * scale))) if scale < 1 else rgb.copy()
    scale = min(scale, 1.0)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        region = cv2.contourArea(approx)
        if len(approx) != 4 or region < 0.25 * area:
            continue
        if region > 0.97 * area:
            return image  # the sheet already fills the frame (scanner)
        quad = _order_quad(approx.reshape(4, 2).astype(np.float32) / scale)
        width = int(max(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])))
        height = int(max(np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])))
        if width < 200 or height < 200:
            return image
        # Only correct clearly skewed outlines; a straight crop of a scan is left alone.
        if np.abs(quad - np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)).max() < 0.02 * max(w, h):
            return image
        target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
        warped = cv2.warpPerspective(rgb, cv2.getPerspectiveTransform(quad, target), (width, height),
                                     flags=cv2.INTER_CUBIC)
        return Image.fromarray(warped)
    return image


def images_to_pdf(data: bytes, suffix: str) -> bytes:
    """Convert a (possibly multi-page) image into a PDF, one page per frame, at its real size."""
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as error:  # noqa: BLE001
        raise DocumentError("La imagen no se puede leer") from error
    out = pymupdf.open()
    frame = 0
    while True:
        try:
            image.seek(frame)
        except EOFError:
            break
        page_image = correct_perspective(ImageOps.exif_transpose(image.convert("RGB")))
        dpi = image.info.get("dpi", (200, 200))[0] or 200
        dpi = dpi if 50 <= dpi <= 1200 else 200
        if suffix in (".jpg", ".jpeg"):
            buffer = io.BytesIO()
            page_image.save(buffer, "JPEG", quality=95)  # re-encode: drops EXIF/GPS metadata
        else:
            buffer = io.BytesIO()
            page_image.save(buffer, "PNG")
        width, height = page_image.size[0] * 72 / dpi, page_image.size[1] * 72 / dpi
        page = out.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=buffer.getvalue())
        frame += 1
    if frame == 0:
        raise DocumentError("La imagen no contiene páginas")
    return out.tobytes(garbage=4, deflate=True)


def load_bytes(data: bytes, filename: str) -> bytes:
    """Validate the input and return PDF bytes (images are converted)."""
    if len(data) > LIMITS["max_bytes"]:
        raise DocumentError(f"El archivo supera {LIMITS['max_bytes'] >> 20} MB")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in IMAGE_SUFFIXES:
        return images_to_pdf(data, suffix)
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise DocumentError("El archivo no es un PDF ni una imagen compatible")
    try:
        doc = pymupdf.open("pdf", data)
    except Exception as error:  # noqa: BLE001
        raise DocumentError("El PDF está dañado o no se puede abrir") from error
    try:
        if doc.needs_pass:
            raise PasswordRequired("El PDF está protegido con contraseña")
        if doc.page_count == 0:
            raise DocumentError("El PDF no tiene páginas")
        if doc.page_count > LIMITS["max_pages"]:
            raise DocumentError(f"El documento supera {LIMITS['max_pages']} páginas")
    finally:
        doc.close()
    return data


def open_pdf(data: bytes) -> pymupdf.Document:
    return pymupdf.open("pdf", data)


def prepare_working_copy(data: bytes) -> pymupdf.Document:
    """Document used for detection *and* as the base of the output.

    Annotations and form fields are baked into page content so their visible text is
    detected and redacted like any other content.
    """
    doc = open_pdf(data)
    try:
        doc.bake(annots=True, widgets=True)
    except Exception:  # noqa: BLE001 - some damaged annotations cannot be baked; they are removed later
        pass
    return pymupdf.open("pdf", doc.tobytes(garbage=1))


def analysis_copy(doc: pymupdf.Document) -> pymupdf.Document:
    """Copy with every optional-content layer switched on, so hidden text is found."""
    copy = pymupdf.open("pdf", doc.tobytes())
    catalog = copy.pdf_catalog()
    if copy.xref_get_key(catalog, "OCProperties")[0] != "null":
        ocgs = " ".join(f"{xref} 0 R" for xref in copy.get_ocgs())
        copy.xref_set_key(catalog, "OCProperties/D/OFF", "[]")
        copy.xref_set_key(catalog, "OCProperties/D/ON", f"[{ocgs}]")
        copy.xref_set_key(catalog, "OCProperties/D/AS", "null")
        copy = pymupdf.open("pdf", copy.tobytes())
    return copy


def page_text(page: pymupdf.Page) -> PageText:
    """All text of the page (including invisible text and text outside the crop box)."""
    raw = page.get_text("rawdict", flags=TEXT_FLAGS, clip=pymupdf.INFINITE_RECT())
    chars: list[str] = []
    boxes: list[Rect | None] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    chars.append(char["c"])
                    bbox = char["bbox"]
                    # Degenerate boxes (spaces) carry no position.
                    ok = bbox[2] - bbox[0] > 0.01 and bbox[3] - bbox[1] > 0.01
                    boxes.append((bbox[0], bbox[1], bbox[2], bbox[3]) if ok else None)
            chars.append("\n")
            boxes.append(None)
        chars.append("\n")
        boxes.append(None)
    return PageText("".join(chars), boxes)


@dataclass
class Render:
    image: np.ndarray       # RGB, rotated page appearance
    scale: float            # pixels per point
    derotation: pymupdf.Matrix

    def to_page(self, box: tuple[float, float, float, float]) -> Rect:
        """Pixel box (rendered, rotated) -> unrotated page coordinates."""
        rect = pymupdf.Rect(box[0] / self.scale, box[1] / self.scale, box[2] / self.scale, box[3] / self.scale)
        rect = rect * self.derotation
        return (rect.x0, rect.y0, rect.x1, rect.y1)

    def from_page(self, rect: Rect) -> tuple[int, int, int, int]:
        r = pymupdf.Rect(rect) * ~self.derotation
        return (int(r.x0 * self.scale), int(r.y0 * self.scale), int(r.x1 * self.scale) + 1, int(r.y1 * self.scale) + 1)


def render(page: pymupdf.Page, dpi: int) -> Render:
    scale = dpi / 72
    width, height = page.rect.width * scale, page.rect.height * scale
    if width * height > LIMITS["max_page_pixels"]:
        scale = (LIMITS["max_page_pixels"] / (page.rect.width * page.rect.height)) ** 0.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB, annots=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    return Render(image, scale, page.derotation_matrix)


def small_image_boxes(page: pymupdf.Page, max_fraction: float = 0.25) -> list[Rect]:
    """Images that cover a small part of the page (their text is re-read at higher resolution)."""
    area = abs(page.rect) or 1.0
    boxes = []
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & page.rect
        if not bbox.is_empty and 0.002 < abs(bbox) / area < max_fraction:
            boxes.append((bbox.x0, bbox.y0, bbox.x1, bbox.y1))
    return boxes


def image_area_ratio(page: pymupdf.Page) -> float:
    """Fraction of the page covered by raster images."""
    area = abs(page.rect)
    if not area:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & page.rect
        covered += abs(bbox)
    return min(1.0, covered / area)


def has_vector_graphics(page: pymupdf.Page) -> bool:
    try:
        return len(page.get_drawings()) > 20
    except Exception:  # noqa: BLE001
        return False
