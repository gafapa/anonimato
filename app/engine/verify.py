"""Proof of absence: checks the exact output bytes before they are written.

A leak blocks the export. Checks:
1. structure (forbidden dictionaries/keys),
2. every string and every decoded stream of every object (several encodings),
3. text extraction of every page (visible, invisible, outside the crop box, hidden layers),
4. OCR of the rendered pages and zoomed OCR of the redacted areas (fuzzy match),
5. faces in the rendered output inside redacted face areas,
6. residual detection of new personal data (warnings only).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
import pikepdf
import pymupdf
import regex as re

from . import document
from .rules import no_accents
from .types import Finding

ID_TYPES = {"dni", "nie", "cif", "nss", "iban", "card", "phone", "passport", "bic", "ip", "plate", "id_other"}
FORBIDDEN_ROOT = ["/Metadata", "/Outlines", "/StructTreeRoot", "/AcroForm", "/Names", "/OpenAction", "/AA",
                  "/PageLabels", "/PieceInfo", "/Dests", "/SpiderInfo", "/Collection"]
FORBIDDEN_PAGE = ["/Annots", "/Thumb", "/Metadata", "/PieceInfo", "/AA", "/B"]
FORBIDDEN_ANY = ["/Metadata", "/PieceInfo", "/Alternates", "/OPI", "/JS", "/JavaScript", "/EmbeddedFile",
                 "/EmbeddedFiles", "/Thumb", "/ActualText"]
MAX_OBJECT_DEPTH = 128
MAX_OBJECT_NODES = 1_000_000
MAX_STREAM_BYTES = 256 * 1024**2
SCAN_CHUNK_BYTES = 1024**2


class VerificationUnavailable(RuntimeError):
    """A required verification service could not complete its check."""


@dataclass
class Leak:
    check: str
    where: str
    value: str
    detail: str = ""
    page: int | None = None                       # 0-based; None = in the file structure
    rects: list = field(default_factory=list)     # unrotated page coordinates


@dataclass
class Report:
    ok: bool = True
    leaks: list[Leak] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    objects: int = 0
    pages: int = 0
    values: int = 0
    checks: list[str] = field(default_factory=list)

    def add(self, leak: Leak) -> None:
        self.leaks.append(leak)
        self.ok = False

    def to_json(self) -> dict:
        return {
            "ok": self.ok, "objects": self.objects, "pages": self.pages, "values": self.values,
            "checks": self.checks, "warnings": self.warnings,
            "leaks": [{"check": leak.check, "where": leak.where, "value": "…", "detail": leak.detail,
                       "page": leak.page, "rects": [list(r) for r in leak.rects]} for leak in self.leaks],
        }


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", no_accents(text).casefold())


def norm_id(text: str) -> str:
    return re.sub(r"[\W_]+", "", no_accents(text).casefold())


@dataclass
class Target:
    kind: str
    value: str
    text_form: str
    id_form: str

    @classmethod
    def build(cls, kind: str, value: str) -> Target:
        return cls(kind, value, norm_text(value).strip(), norm_id(value))

    def found_in(self, haystack: str, normalized: dict[str, str] | None = None) -> bool:
        if not self.id_form:
            return False
        forms = normalized if normalized is not None else {}

        def cached_form(key, transform):
            if key not in forms:
                forms[key] = transform(haystack)
            return forms[key]

        if self.kind in ID_TYPES:
            if len(self.id_form) < 4:
                pattern = r"[\W_]*".join(re.escape(character) for character in self.id_form)
                return re.search(r"(?<!\w)" + pattern + r"(?!\w)", cached_form("text", norm_text)) is not None
            return self.id_form in cached_form("id", norm_id)
        text = cached_form("words", lambda value: norm_text(re.sub(r"[^\w\s]", " ", value)))
        needle = norm_text(re.sub(r"[^\w\s]", " ", self.value)).strip()
        return bool(needle) and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text) is not None


def protected_targets(findings: list[Finding]) -> list[Target]:
    """Values that must be absent: every occurrence of them was selected for redaction."""
    by_key: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.value and finding.type not in ("face", "signature", "manual"):
            by_key.setdefault(finding.key or finding.value, []).append(finding)
    targets = []
    seen = set()
    for items in by_key.values():
        if not all(item.enabled for item in items):
            continue
        for item in items:
            target = Target.build(item.type, item.value)
            if target.id_form not in seen and target.id_form:
                seen.add(target.id_form)
                targets.append(target)
    return targets


def _decode_variants(raw: bytes) -> list[str]:
    out = [raw.decode("latin-1")]
    try:
        out.append(raw.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    for encoding in ("utf-16-be", "utf-16-le"):
        for start in (0, 1):
            chunk = raw[start:]
            if len(chunk) >= 4:
                out.append(chunk[: len(chunk) // 2 * 2].decode(encoding, errors="ignore"))
    try:
        out.append(bytes.fromhex(re.sub(rb"[^0-9a-fA-F]", b"", raw).decode()).decode("latin-1"))
    except ValueError:
        pass
    return out


def _string_text(value: pikepdf.String) -> list[str]:
    raw = bytes(value)
    texts = [str(value)]
    texts.extend(_decode_variants(raw))
    return texts


def _check_structure(pdf: pikepdf.Pdf, report: Report) -> None:
    for key in FORBIDDEN_ROOT:
        if key in pdf.Root:
            report.add(Leak("estructura", "catálogo", key, "estructura no permitida"))
    if "/Info" in pdf.trailer and len(pdf.trailer.Info.keys()) > 0:
        report.add(Leak("estructura", "Info", "/Info", "metadatos de documento"))
    for number, page in enumerate(pdf.pages, start=1):
        for key in FORBIDDEN_PAGE:
            if key in page.obj:
                report.add(Leak("estructura", f"página {number}", key, "estructura no permitida"))
    for obj in pdf.objects:
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            for key in FORBIDDEN_ANY:
                if key in obj:
                    report.add(Leak("estructura", f"objeto {obj.objgen[0]}", key, "clave no permitida"))
            if obj.get("/S") == pikepdf.Name.JavaScript:
                report.add(Leak("estructura", f"objeto {obj.objgen[0]}", "JavaScript", "acción de script"))


def _scan_objects(pdf: pikepdf.Pdf, targets: list[Target], report: Report) -> None:
    content_ids = set()
    font_ids = set()
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Dictionary):
            for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                stream = obj.get(key)
                if isinstance(stream, pikepdf.Stream):
                    font_ids.add(stream.objgen)
    for page in pdf.pages:
        contents = page.obj.get("/Contents")
        items = contents if isinstance(contents, pikepdf.Array) else [contents] if contents is not None else []
        for item in items:
            content_ids.add(item.objgen)

    def check(texts: list[str], where: str, binary: bool = False) -> None:
        if not targets:
            return
        joined = "\n".join(texts)
        normalized = {}
        for target in targets:
            # Short strings occur by chance in binary fonts and image samples. PDF strings,
            # parsed text operands and page text still check all target lengths.
            if binary and len(target.id_form) < 4:
                continue
            if target.found_in(joined, normalized):
                report.add(Leak("objetos", where, target.value, "copia del dato dentro del archivo"))

    visited_nodes = 0

    def walk(value, where: str, depth: int = 0) -> None:
        nonlocal visited_nodes
        visited_nodes += 1
        if depth > MAX_OBJECT_DEPTH or visited_nodes > MAX_OBJECT_NODES:
            raise VerificationUnavailable("La estructura del PDF supera el límite de verificación segura")
        if isinstance(value, pikepdf.String):
            check(_string_text(value), where)
        elif isinstance(value, pikepdf.Name):
            check([str(value)[1:]], where)
        elif isinstance(value, pikepdf.Array):
            for item in value:
                if not getattr(item, "is_indirect", False):
                    walk(item, where, depth + 1)
        elif isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            for key, item in value.items():
                if key in FORBIDDEN_ANY:
                    report.add(Leak("estructura", where, key, "clave no permitida"))
                check([key[1:]], where)
                if not getattr(item, "is_indirect", False):
                    walk(item, where, depth + 1)

    count = 0
    for obj in pdf.objects:
        count += 1
        where = f"objeto {obj.objgen[0]}"
        walk(obj, where)
        if isinstance(obj, pikepdf.Stream):
            try:
                data = obj.read_bytes()
            except Exception:  # images with lossy filters cannot be decoded here
                try:
                    data = obj.read_raw_bytes()
                except Exception as error:
                    raise VerificationUnavailable("No se pudo leer un flujo del PDF para verificarlo") from error
            if len(data) > MAX_STREAM_BYTES:
                raise VerificationUnavailable("Un flujo del PDF supera el límite de verificación segura")
            binary = obj.get("/Subtype") == pikepdf.Name.Image or obj.objgen in font_ids
            # Scan large image/font streams in overlapping chunks instead of silently skipping them.
            overlap = max([128] + [8 * len(target.value.encode("utf-8")) for target in targets])
            if any(not binary or len(target.id_form) >= 4 for target in targets):
                for offset in range(0, len(data), SCAN_CHUNK_BYTES):
                    check(_decode_variants(data[max(0, offset - overlap):offset + SCAN_CHUNK_BYTES + overlap]),
                          where, binary=binary)
            is_content = obj.objgen in content_ids or obj.get("/Subtype") == pikepdf.Name.Form
            if is_content:
                try:
                    strings = []
                    for instruction in pikepdf.parse_content_stream(obj):
                        if isinstance(instruction, pikepdf.ContentStreamInlineImage):
                            continue
                        for operand in instruction.operands:
                            if isinstance(operand, pikepdf.String):
                                strings.extend(_string_text(operand))
                            elif isinstance(operand, pikepdf.Array):
                                strings.extend(t for item in operand if isinstance(item, pikepdf.String)
                                               for t in _string_text(item))
                    check(["".join(strings), " ".join(strings)], where + " (contenido)")
                except Exception as error:
                    raise VerificationUnavailable("No se pudo verificar un flujo de contenido del PDF") from error
    report.objects = count


def _locate(source, target: Target) -> list:
    """Rectangles of every occurrence of the value in a page text (to show the user where it is)."""
    from .propagate import NormalizedText
    norm = NormalizedText(source.text)
    if target.kind in ID_TYPES:
        pattern = r"[\s.\-/]?".join(re.escape(c) for c in target.id_form)
    else:
        pattern = r"[\W_]+".join(re.escape(w) for w in target.text_form.split())
    rects = []
    for match in re.finditer(pattern, norm.text):
        start, end = norm.span(match.start(), match.end())
        rects += source.rects_for(start, end)
    return rects


def _scan_text(data: bytes, targets: list[Target], report: Report, progress=None) -> None:
    doc = document.analysis_copy(document.open_pdf(data))
    report.pages = doc.page_count
    for index, page in enumerate(doc):
        if progress:
            progress({"stage": "verify", "page": index + 1, "total": doc.page_count,
                      "message": f"Verificando el texto de la página {index + 1} de {doc.page_count}"})
        source = document.page_text(page)
        actual = page.get_text("text", flags=document.TEXT_FLAGS_ACTUAL, clip=pymupdf.INFINITE_RECT())
        for target in targets:
            if target.found_in(source.text + "\n" + actual):
                report.add(Leak("texto", f"página {index + 1}", target.value, "texto extraíble",
                                page=index, rects=_locate(source, target)))
    doc.close()


def substring_distance(needle: str, hay: str) -> int:
    """Smallest edit distance between ``needle`` and any substring of ``hay`` (semi-global alignment)."""
    if not needle:
        return 0
    previous = [0] * (len(hay) + 1)
    for i, a in enumerate(needle, start=1):
        current = [i] + [0] * len(hay)
        for j, b in enumerate(hay, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b))
        previous = current
    return min(previous)


def fuzzy_found(target: Target, text: str) -> bool:
    """The value (allowing OCR errors: 1 edit up to 8 characters, 2 above) appears in ``text``."""
    needle = target.id_form if target.kind in ID_TYPES else target.text_form
    hay = norm_id(text) if target.kind in ID_TYPES else norm_text(text)
    if len(needle) < 5:
        return target.found_in(text)
    if needle in hay:
        return True
    if len(hay) < len(needle) - 2:
        return False
    allowed = 1 if len(needle) < 9 else 2
    return substring_distance(needle, hay) <= allowed


def _scan_pixels(data: bytes, findings: list[Finding], targets: list[Target], services, report: Report,
                 progress=None) -> dict[int, str]:
    """Rendered pages: OCR, zoomed OCR of every redacted area, handwriting re-read and faces.

    Returns the OCR text of each page (reused by the residual detection)."""
    ocr = services.ocr() if services else None
    faces = services.faces() if services and any(f.enabled and f.type == "face" for f in findings) else None
    if ocr is None:
        raise VerificationUnavailable("No se puede verificar el resultado: OCR no disponible")
    if faces is None and any(f.enabled and f.type == "face" for f in findings):
        raise VerificationUnavailable("No se puede verificar el resultado: detector de rostros no disponible")
    reader = None
    if any(f.enabled and f.source == "handwriting" and f.value for f in findings):
        llm = services.llm() if services.advanced_available() else None
        if llm is None:
            raise VerificationUnavailable("No se puede verificar el resultado: lector de manuscritos no disponible")
        from .ocr.handwriting import HandwritingReader
        reader = HandwritingReader(llm)
    with document.open_pdf(data) as doc:
        return _scan_pixel_pages(doc, findings, targets, ocr, faces, reader, report, progress)


def _scan_pixel_pages(doc, findings, targets, ocr, faces, reader, report, progress) -> dict[int, str]:
    handwriting_checked = False
    faces_checked = False
    protected = {target.id_form for target in targets}
    texts: dict[int, str] = {}
    for index, page in enumerate(doc):
        if progress:
            progress({"stage": "verify", "page": index + 1, "total": doc.page_count,
                      "message": f"Verificando la imagen de la página {index + 1} de {doc.page_count}"})
        rendered = document.render(page, 200)
        if ocr is not None:
            lines = ocr.read(rendered.image)
            text = "\n".join(line.text for line in lines)
            texts[index] = text
            for target in targets:
                if fuzzy_found(target, text):
                    rects = [rendered.to_page(line.rect) for line in lines if fuzzy_found(target, line.text)]
                    report.add(Leak("ocr", f"página {index + 1}", target.value, "visible en la página renderizada",
                                    page=index, rects=rects))
            # Zoomed OCR of each redacted area (catches half-covered characters). Handwritten areas are
            # also re-read with the vision-language model when it is installed.
            for finding in findings:
                if finding.page != index or not finding.enabled or not finding.value:
                    continue
                target = Target.build(finding.type, finding.value)
                if target.id_form not in protected:
                    continue
                for rect in finding.rects:
                    r = pymupdf.Rect(rect)
                    zone = pymupdf.Rect(r.x0 - r.height * 2, r.y0 - r.height * 0.8, r.x1 + r.height * 2,
                                        r.y1 + r.height * 0.8)
                    clip = (zone * page.rotation_matrix) & page.rect
                    if clip.is_empty:
                        continue
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=clip, alpha=False, colorspace=pymupdf.csRGB)
                    if pix.height < 12 or pix.width < 12:
                        continue  # too small to be legible as pixels (its text was already checked above)
                    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                    # Full OCR (line detection + recognition): recognising the padded crop directly as a
                    # single line misreads it.
                    readings = [" ".join(line.text for line in ocr.read(image, detect_orientation=False))]
                    if reader is not None and finding.source == "handwriting":
                        try:
                            readings.append(reader.read(image))
                            handwriting_checked = True
                        except Exception as error:
                            raise VerificationUnavailable("No se pudo verificar el texto manuscrito") from error
                    if any(fuzzy_found(target, reading) for reading in readings):
                        report.add(Leak("ocr-zona", f"página {index + 1}", finding.value,
                                        "legible dentro o junto a la zona tachada", page=index,
                                        rects=[(zone.x0, zone.y0, zone.x1, zone.y1)]))
        if faces is not None:
            face_findings = [f for f in findings if f.page == index and f.enabled and f.type == "face"]
            if face_findings:
                faces_checked = True
                for box in faces.detect(rendered.image):
                    rect = pymupdf.Rect(rendered.to_page(box))
                    for finding in face_findings:
                        if any(rect.intersects(pymupdf.Rect(r)) for r in finding.rects):
                            report.add(Leak("rostros", f"página {index + 1}", "rostro", "rostro reconocible",
                                            page=index, rects=[tuple(rect)]))
    report.checks.append("OCR de la página renderizada")
    if handwriting_checked:
        report.checks.append("relectura de manuscritos con IA")
    if faces_checked:
        report.checks.append("rostros")
    return texts


def verify(data: bytes, findings: list[Finding], services=None, residual=None, progress=None) -> Report:
    report = Report()
    targets = protected_targets(findings)
    report.values = len(targets)
    pdf = pikepdf.open(io.BytesIO(data))
    with pdf:
        _check_structure(pdf, report)
        report.checks.append("estructura")
        _scan_objects(pdf, targets, report)
        report.checks.append("objetos y flujos")
    _scan_text(data, targets, report, progress)
    report.checks.append("texto de páginas")
    ocr_texts: dict[int, str] = {}
    if services is not None:
        ocr_texts = _scan_pixels(data, findings, targets, services, report, progress)
    if residual is not None:
        try:
            for message in residual(data, ocr_texts):
                report.warnings.append(message)
            report.checks.append("detección residual")
        except Exception:
            report.warnings.append("Detección residual no disponible; revisa el documento")
    # Deduplicate identical leaks.
    unique = {}
    for leak in report.leaks:
        key = (leak.check, leak.where, leak.value)
        if key in unique:
            unique[key].rects.extend(r for r in leak.rects if r not in unique[key].rects)
        else:
            unique[key] = leak
    report.leaks = list(unique.values())
    return report
