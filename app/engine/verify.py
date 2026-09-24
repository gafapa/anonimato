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


@dataclass
class Leak:
    check: str
    where: str
    value: str
    detail: str = ""


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
            "leaks": [{"check": l.check, "where": l.where, "value": _mask(l.value), "detail": l.detail} for l in self.leaks],
        }


def _mask(value: str) -> str:
    return value[:2] + "…" if len(value) > 3 else "…"


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
    def build(cls, kind: str, value: str) -> "Target":
        return cls(kind, value, norm_text(value).strip(), norm_id(value))

    def found_in(self, haystack: str) -> bool:
        if len(self.id_form) < 4:
            return False
        if self.kind in ID_TYPES:
            return self.id_form in norm_id(haystack)
        text = norm_text(re.sub(r"[^\w\s]", " ", haystack))
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
            if target.id_form not in seen and len(target.id_form) >= 4:
                seen.add(target.id_form)
                targets.append(target)
    return targets


def _decode_variants(raw: bytes) -> list[str]:
    out = [raw.decode("latin-1")]
    try:
        out.append(raw.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    for start in (0, 1):
        chunk = raw[start:]
        if len(chunk) >= 4:
            out.append(chunk[: len(chunk) // 2 * 2].decode("utf-16-be", errors="ignore"))
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
    for page in pdf.pages:
        contents = page.obj.get("/Contents")
        items = contents if isinstance(contents, pikepdf.Array) else [contents] if contents is not None else []
        for item in items:
            content_ids.add(item.objgen)

    def check(texts: list[str], where: str) -> None:
        joined = "\n".join(texts)
        for target in targets:
            if target.found_in(joined):
                report.add(Leak("objetos", where, target.value, "copia del dato dentro del archivo"))

    def walk(value, where: str, depth: int = 0) -> None:
        if depth > 12:
            return
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
            except Exception:  # noqa: BLE001 - images with lossy filters cannot be decoded here
                try:
                    data = obj.read_raw_bytes()
                except Exception:  # noqa: BLE001
                    continue
            if obj.get("/Subtype") == pikepdf.Name.Image and len(data) > 4_000_000:
                continue
            check(_decode_variants(data), where)
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
                except Exception:  # noqa: BLE001
                    pass
    report.objects = count


def _scan_text(data: bytes, targets: list[Target], report: Report) -> None:
    doc = document.analysis_copy(document.open_pdf(data))
    report.pages = doc.page_count
    for index, page in enumerate(doc):
        text = "\n".join(page.get_text("text", flags=flags, clip=pymupdf.INFINITE_RECT())
                         for flags in (document.TEXT_FLAGS, document.TEXT_FLAGS_ACTUAL))
        for target in targets:
            if target.found_in(text):
                report.add(Leak("texto", f"página {index + 1}", target.value, "texto extraíble"))
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
        return needle in hay
    if needle in hay:
        return True
    if len(hay) < len(needle) - 2:
        return False
    allowed = 1 if len(needle) < 9 else 2
    return substring_distance(needle, hay) <= allowed


def _scan_pixels(data: bytes, findings: list[Finding], targets: list[Target], services, report: Report) -> None:
    doc = document.open_pdf(data)
    ocr = services.ocr() if services else None
    faces = services.faces() if services else None
    protected = {target.id_form for target in targets}
    for index, page in enumerate(doc):
        needs_ocr = ocr is not None
        rendered = document.render(page, 200)
        if needs_ocr:
            lines = ocr.read(rendered.image)
            text = "\n".join(line.text for line in lines)
            for target in targets:
                if fuzzy_found(target, text):
                    report.add(Leak("ocr", f"página {index + 1}", target.value, "visible en la página renderizada"))
            # Zoomed OCR of each redacted area (catches half-covered characters).
            for finding in findings:
                if finding.page != index or not finding.enabled or not finding.value:
                    continue
                for rect in finding.rects:
                    r = pymupdf.Rect(rect)
                    zone = pymupdf.Rect(r.x0 - r.height * 2, r.y0 - r.height * 0.8, r.x1 + r.height * 2, r.y1 + r.height * 0.8)
                    clip = (zone * page.rotation_matrix) & page.rect
                    if clip.is_empty:
                        continue
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=clip, alpha=False, colorspace=pymupdf.csRGB)
                    if pix.height < 12 or pix.width < 12:
                        continue  # too small to be legible as pixels (its text was already checked above)
                    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                    zone_text = ocr.read_line(image)
                    target = Target.build(finding.type, finding.value)
                    if target.id_form in protected and fuzzy_found(target, zone_text):
                        report.add(Leak("ocr-zona", f"página {index + 1}", finding.value,
                                        "legible dentro o junto a la zona tachada"))
        if faces is not None:
            face_findings = [f for f in findings if f.page == index and f.enabled and f.type == "face"]
            if face_findings:
                for box in faces.detect(rendered.image):
                    rect = pymupdf.Rect(rendered.to_page(box))
                    for finding in face_findings:
                        if any(rect.intersects(pymupdf.Rect(r)) for r in finding.rects):
                            report.add(Leak("rostros", f"página {index + 1}", "rostro", "rostro reconocible"))
    doc.close()


def verify(data: bytes, findings: list[Finding], services=None, residual=None) -> Report:
    report = Report()
    targets = protected_targets(findings)
    report.values = len(targets)
    pdf = pikepdf.open(io.BytesIO(data))
    with pdf:
        _check_structure(pdf, report)
        report.checks.append("estructura")
        _scan_objects(pdf, targets, report)
        report.checks.append("objetos y flujos")
    _scan_text(data, targets, report)
    report.checks.append("texto de páginas")
    if services is not None:
        _scan_pixels(data, findings, targets, services, report)
        report.checks.append("OCR de la página renderizada")
        if services.faces() is not None:
            report.checks.append("rostros")
    if residual is not None:
        try:
            for message in residual(data):
                report.warnings.append(message)
            report.checks.append("detección residual")
        except Exception as error:  # noqa: BLE001
            report.warnings.append(f"Detección residual no disponible: {error}")
    # Deduplicate identical leaks.
    unique = {}
    for leak in report.leaks:
        unique.setdefault((leak.check, leak.where, leak.value), leak)
    report.leaks = list(unique.values())
    return report
