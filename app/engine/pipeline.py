"""Analysis (detection) and export (redaction → cleaning → verification) pipeline."""
from __future__ import annotations

import time
import math
import unicodedata
import uuid
from dataclasses import dataclass, field
from collections.abc import Callable

import numpy as np
import pymupdf
import regex as re
from rapidfuzz.distance import Levenshtein

from . import document, propagate, rasterize, redact, rules, sanitize, signatures, verify
from .rules import CATEGORIES, Match, canonical
from .types import Finding, OcrLine, Options, PageText, Rect

Progress = Callable[[dict], None]
EXTENDABLE = {"name", "address", "org", "health", "other"}
PERSONAL_LABELS = re.compile(
    r"(?i)\b(?:nombre|apellidos?|d\.?n\.?i|n\.?i\.?f|n\.?i\.?e|domicilio|direcci[oó]n|tel[eé]fono|m[oó]vil|e-?mail|correo|"
    r"firma|fdo|paciente|alumn[oa]|titular|solicitante|nacimiento|localidad|c[oó]digo\s+postal|name|address|phone)\b")


class Cancelled(Exception):
    pass


@dataclass
class PageInfo:
    width: float
    height: float
    rotation: int
    matrix: tuple = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)   # unrotated -> displayed (rotated) page coordinates


@dataclass
class Analysis:
    id: str
    filename: str
    working: bytes
    pages: list[PageInfo]
    findings: list[Finding]
    options: Options
    sources: dict[int, list[tuple[str, PageText]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    native_chars: int = 0
    seconds: float = 0.0
    next_id: int = 1
    signed: bool = False

    def new_id(self, page: int) -> str:
        self.next_id += 1
        return f"p{page + 1}-{self.next_id - 1}"


@dataclass
class ExportResult:
    data: bytes
    report: verify.Report
    filename: str
    seconds: float
    revision: int | None = None  # bound by the window bridge before publication


# ---------------------------------------------------------------- detection helpers
def combine(matches: list[Match]) -> list[Match]:
    """Resolve overlaps: higher priority wins, but a longer span of the same type absorbs shorter ones."""
    kept: list[Match] = []
    for cand in sorted(matches, key=lambda m: (-m.prio, m.start, -(m.end - m.start))):
        if cand.end <= cand.start:
            continue
        overlapping = [k for k in kept if cand.start < k.end and cand.end > k.start]
        if not overlapping:
            kept.append(cand)
        elif cand.type in EXTENDABLE and all(k.type == cand.type and cand.start <= k.start and cand.end >= k.end
                                             for k in overlapping):
            for k in overlapping:
                kept.remove(k)
            cand.confidence = max([cand.confidence] + [k.confidence for k in overlapping])
            kept.append(cand)
    return sorted(kept, key=lambda m: m.start)


NUMERIC_TYPES = {"nss", "card", "iban", "phone", "passport", "plate", "id_other", "ip"}


def _useful_ai(match: Match) -> bool:
    words = len(match.value.split())
    if match.type in NUMERIC_TYPES:
        digits = sum(c.isdigit() for c in match.value)
        return digits >= 4 and digits >= 0.4 * len(match.value.replace(" ", ""))
    if match.type == "name":
        tokens = [rules.no_accents(t.lower()).strip(".,") for t in match.value.split()]
        if sum(t in rules.NAME_STOPS for t in tokens) * 2 >= len(tokens):
            return False  # "Estimado cliente", "Sr. Director"…
    if match.type == "address" and words == 1:
        return match.confidence >= 0.9
    if match.type == "name" and words == 1:
        return match.confidence >= 0.7 and len(match.value) >= 3
    if match.type in ("org", "other"):
        return match.confidence >= 0.7
    return len(match.value.strip()) >= 2


def detect_text(text: str, categories: set[str], pii=None, notes: list[str] | None = None) -> list[Match]:
    matches = rules.detect_all(text)
    if pii is not None and text.strip():
        try:
            matches += [m for m in pii.detect(text) if _useful_ai(m)]
        except Exception as error:  # rules still apply, but the user is told
            message = f"IA de datos personales con error ({error}); en este texto solo se han aplicado las reglas."
            if notes is not None and message not in notes:
                notes.append(message)
    return [m for m in combine(matches) if m.type in categories]


def _coverage(rect: Rect, boxes: list[Rect]) -> float:
    x0, y0, x1, y1 = rect
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    covered = 0.0
    for b in boxes:
        w = min(x1, b[2]) - max(x0, b[0])
        h = min(y1, b[3]) - max(y0, b[1])
        if w > 0 and h > 0:
            covered += w * h
    return min(1.0, covered / area)


def _uniform_boxes(text: str, rect: Rect) -> list[Rect]:
    n = max(1, len(text))
    step = (rect[2] - rect[0]) / n
    return [(rect[0] + i * step, rect[1], rect[0] + (i + 1) * step, rect[3]) for i in range(n)]


def ocr_page_text(lines: list[OcrLine], texts: list[str] | None = None) -> PageText:
    """Group OCR lines into rows (so labels and values on the same row share context)."""
    texts = texts or [line.text for line in lines]
    order = sorted(range(len(lines)), key=lambda i: ((lines[i].rect[1] + lines[i].rect[3]) / 2, lines[i].rect[0]))
    rows: list[list[int]] = []
    for i in order:
        cy = (lines[i].rect[1] + lines[i].rect[3]) / 2
        height = lines[i].rect[3] - lines[i].rect[1]
        if rows:
            last = lines[rows[-1][-1]]
            if abs(cy - (last.rect[1] + last.rect[3]) / 2) < 0.5 * max(height, last.rect[3] - last.rect[1]):
                rows[-1].append(i)
                continue
        rows.append([i])
    chars: list[str] = []
    boxes: list[Rect | None] = []
    for row in rows:
        for position, i in enumerate(sorted(row, key=lambda k: lines[k].rect[0])):
            if position:
                chars.append(" ")
                boxes.append(None)
            text = texts[i]
            line = lines[i]
            char_boxes = line.char_rects if texts[i] == line.text and len(line.char_rects) == len(text) else \
                _uniform_boxes(text, line.rect)
            chars.extend(text)
            boxes.extend(char_boxes)
        chars.append("\n")
        boxes.append(None)
    return PageText("".join(chars), boxes)


# ---------------------------------------------------------------- analysis
def analyze(data: bytes, filename: str, options: Options, services=None, progress: Progress | None = None,
            cancelled: Callable[[], bool] | None = None) -> Analysis:
    started = time.time()
    progress = progress or (lambda event: None)
    cancelled = cancelled or (lambda: False)
    pdf_bytes = document.load_bytes(data, filename)
    working_doc = document.prepare_working_copy(pdf_bytes)
    working = working_doc.tobytes(garbage=1)
    scan = document.analysis_copy(working_doc)
    analysis = Analysis(id=uuid.uuid4().hex, filename=filename, working=working, findings=[], options=options,
                        pages=[PageInfo(p.rect.width, p.rect.height, p.rotation, tuple(p.rotation_matrix))
                               for p in working_doc])
    try:
        analysis.signed = document.is_signed(pdf_bytes)
    except Exception:
        analysis.signed = False
    if analysis.signed:
        analysis.notes.append("El PDF original tiene firma digital: el documento anonimizado no conservará una firma "
                              "válida (cualquier modificación la invalida). Los datos del firmante se eliminan.")
    pii = services.pii() if services is not None and options.ai else None
    if services is not None and options.ai and pii is None:
        analysis.notes.append("IA de datos personales no disponible: " + services.errors.get("pii", "error al cargar")
                              + ". Se han aplicado solo las reglas.")
    ocr = services.ocr() if services is not None and options.ocr else None
    faces = services.faces() if services is not None and options.faces else None
    llm = services.llm() if services is not None and (options.handwriting or options.llm_review) else None
    reader = None
    if llm is not None and options.handwriting:
        from .ocr.handwriting import HandwritingReader
        reader = HandwritingReader(llm)
    categories = set(options.categories)
    total = scan.page_count

    def add(page: int, kind: str, value: str | None, rects: list[Rect], confidence: float, source: str,
            warning: str | None = None, detail: str = "", key: str = "") -> Finding:
        finding = Finding(id=analysis.new_id(page), page=page, type=kind, value=value,
                          rects=rects, confidence=round(float(confidence), 3), source=source, warning=warning,
                          detail=detail, key=key)
        analysis.findings.append(finding)
        return finding

    for index, page in enumerate(scan):
        if cancelled():
            raise Cancelled()
        progress({"stage": "page", "page": index + 1, "total": total, "message": f"Analizando página {index + 1} de {total}"})
        native = document.page_text(page)
        analysis.native_chars += len(native.text.strip())
        page_sources: list[tuple[str, PageText]] = [("text", native)]
        for match in detect_text(native.text, categories, pii, analysis.notes):
            rects = native.rects_for(match.start, match.end)
            if rects:
                add(index, match.type, match.value.strip(), rects, match.confidence,
                    "ai" if match.source == "ai" else "text", match.warning)
        needs_ocr = ocr is not None and (document.image_area_ratio(page) > 0.02 or document.has_vector_graphics(page)
                                         or len(native.text.strip()) < 40)
        if not (needs_ocr or faces is not None or options.signatures):
            analysis.sources[index] = page_sources
            continue
        rendered = document.render(page, options.dpi)
        native_boxes = [b for b in native.boxes if b is not None]
        lines: list[OcrLine] = []
        if needs_ocr:
            progress({"stage": "ocr", "page": index + 1, "total": total, "message": f"OCR de la página {index + 1}"})
            page_area = rendered.image.shape[0] * rendered.image.shape[1]
            for line in ocr.read(rendered.image):
                pixel_rect = line.rect
                if (pixel_rect[2] - pixel_rect[0]) * (pixel_rect[3] - pixel_rect[1]) > 0.15 * page_area:
                    continue  # not a text line (noise, photo, stain)
                line.rect = rendered.to_page(line.rect)
                line.char_rects = [rendered.to_page(r) for r in line.char_rects]
                line.pixel_rect = pixel_rect  # type: ignore[attr-defined]
                if _coverage(line.rect, native_boxes) < 0.5:
                    lines.append(line)
            # Small images (stamps, ID cards, pasted photos) are re-read at a higher resolution.
            for box in document.small_image_boxes(page):
                clip = pymupdf.Rect(box) * page.rotation_matrix
                zoom = min(8.0, max(options.dpi / 72 * 2, 1200 / max(1.0, clip.width)))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False,
                                      colorspace=pymupdf.csRGB, annots=False)
                if pix.width < 32 or pix.height < 32:
                    continue
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                for line in ocr.read(image, detect_orientation=False):
                    def to_page(r, clip=clip, zoom=zoom, page=page):
                        rect = pymupdf.Rect(clip.x0 + r[0] / zoom, clip.y0 + r[1] / zoom,
                                            clip.x0 + r[2] / zoom, clip.y0 + r[3] / zoom) * page.derotation_matrix
                        return (rect.x0, rect.y0, rect.x1, rect.y1)
                    line.pixel_rect = rendered.from_page(to_page(line.rect))  # type: ignore[attr-defined]
                    line.rect = to_page(line.rect)
                    line.char_rects = [to_page(r) for r in line.char_rects]
                    if not any(_coverage(line.rect, [other.rect]) > 0.5 for other in lines)                             and _coverage(line.rect, native_boxes) < 0.5:
                        lines.append(line)
        alternatives: list[str] = [line.text for line in lines]
        if reader is not None:
            for position, line in enumerate(lines):
                if not line.handwritten:
                    continue
                progress({"stage": "handwriting", "page": index + 1, "total": total,
                          "message": f"Leyendo manuscritos en la página {index + 1}"})
                x0, y0, x1, y1 = (int(v) for v in line.pixel_rect)  # type: ignore[attr-defined]
                pad = max(3, (y1 - y0) // 6)
                crop = rendered.image[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
                try:
                    alternatives[position] = reader.read(crop) or line.text
                    line.engine = "vlm"
                except Exception as error:
                    analysis.notes.append(f"Lectura de manuscritos no disponible: {error}")
                    reader = None
                    break
        if lines:
            primary = ocr_page_text(lines)
            page_sources.append(("ocr", primary))
            texts = [primary]
            if alternatives != [line.text for line in lines]:
                alt = ocr_page_text(lines, alternatives)
                page_sources.append(("ocr-alt", alt))
                texts.append(alt)
            # Whole-line covering only for lines whose reading is uncertain (clearly handwritten or the
            # two readers disagree); confidently read printed lines keep their tight boxes.
            hand_rects = [line.rect for position, line in enumerate(lines) if line.handwritten and (
                line.confidence < 0.9 or (line.engine == "vlm" and Levenshtein.normalized_distance(
                    line.text.lower(), alternatives[position].lower()) > 0.15))]
            for source_text in texts:
                for match in detect_text(source_text.text, categories, pii, analysis.notes):
                    rects = source_text.rects_for(match.start, match.end)
                    if not rects:
                        continue
                    handwritten = [h for h in hand_rects if any(_coverage(r, [h]) > 0.3 for r in rects)]
                    if handwritten:  # conservative: cover the whole handwritten line *in addition* to the data
                        rects = rects + [h for h in handwritten if h not in rects]
                    add(index, match.type, match.value.strip(), rects, match.confidence,
                        "handwriting" if handwritten else "ocr", match.warning,
                        detail="manuscrito" if handwritten else "")
            # Illegible or doubtful handwriting next to a personal-data label.
            if "handwriting" in categories:
                for position, line in enumerate(lines):
                    if not line.handwritten:
                        continue
                    reading = alternatives[position]
                    if line.engine == "vlm":
                        # Illegible for the model, or the two readers disagree: treat as doubtful.
                        disagreement = Levenshtein.normalized_distance(line.text.lower(), reading.lower())
                        doubtful = "[ilegible]" in reading or disagreement > 0.4
                    else:
                        doubtful = line.confidence < 0.9
                    row_text = " ".join(other.text for other in lines if abs((other.rect[1] + other.rect[3]) / 2 - (line.rect[1] + line.rect[3]) / 2)
                                        < (line.rect[3] - line.rect[1]) * 0.6 and other.rect[0] < line.rect[0])
                    labelled = bool(PERSONAL_LABELS.search(row_text)) or bool(PERSONAL_LABELS.search(
                        _native_left_of(native, line.rect)))
                    if labelled and doubtful:
                        add(index, "handwriting", None, [line.rect], 0.6, "handwriting",
                            detail="manuscrito dudoso junto a un campo personal")
        if faces is not None and "face" in categories:
            for box in faces.detect(rendered.image):
                add(index, "face", None, [rendered.to_page(box)], 0.9, "face")
        if options.signatures and "signature" in categories:
            labels_px, text_px = [], []
            for _, source_text in page_sources:
                for match in signatures.LABEL.finditer(source_text.text):
                    for rect in source_text.rects_for(match.start(), match.end()):
                        labels_px.append(rendered.from_page(rect))
            text_px += [rendered.from_page(b) for b in native_boxes]
            text_px += [line.pixel_rect for line in lines if not line.handwritten]  # type: ignore[attr-defined]
            # Handwritten lines that are already findings (e.g. a DNI above the signature) are not ink to cover again.
            found_here = [r for f in analysis.findings if f.page == index and f.value for r in f.rects]
            text_px += [line.pixel_rect for line in lines  # type: ignore[attr-defined]
                        if line.handwritten and any(_coverage(line.rect, [r]) > 0.5 for r in found_here)]
            for box in signatures.find(rendered.image, labels_px, text_px):
                add(index, "signature", None, [rendered.to_page(box)], 0.75, "signature", detail="posible firma")
        analysis.sources[index] = page_sources
    scan.close()
    working_doc.close()

    if options.propagate:
        progress({"stage": "propagation", "message": "Buscando cada dato en todo el documento"})
        _propagate(analysis, add)
    if llm is not None and options.llm_review:
        _llm_review(analysis, llm, categories, add, progress, cancelled)
    _dedupe(analysis)
    assign_tokens(analysis.findings)
    analysis.findings.sort(key=lambda f: (f.page, f.rects[0][1] if f.rects else 0, f.rects[0][0] if f.rects else 0))
    analysis.seconds = round(time.time() - started, 1)
    progress({"stage": "done", "message": "Análisis terminado"})
    return analysis


def _native_left_of(native: PageText, rect: Rect) -> str:
    cy = (rect[1] + rect[3]) / 2
    h = rect[3] - rect[1]
    out = []
    for ch, box in zip(native.text, native.boxes, strict=True):
        if box is not None and box[2] <= rect[0] + 2 and abs((box[1] + box[3]) / 2 - cy) < h * 0.7:
            out.append(ch)
    return "".join(out)


def _propagate(analysis: Analysis, add) -> None:
    seen: dict[str, tuple[str, str]] = {}
    for finding in analysis.findings:
        if finding.value and finding.type not in ("face", "signature", "manual", "handwriting"):
            key = finding.type + "|" + canonical(finding.type, finding.value)
            seen.setdefault(key, (finding.type, finding.value))
    existing = [(f.page, r) for f in analysis.findings for r in f.rects]
    for key, (kind, value) in seen.items():
        patterns = [p for p in propagate.variants(kind, value) if p[0]]
        if not patterns:
            continue
        for page, sources in analysis.sources.items():
            for _, source in sources:
                # Longest mentions first, so "X. Etxeberria Goikoetxea" is covered whole (initial included)
                # before its shorter variant "Etxeberria Goikoetxea" is considered.
                matches = sorted(propagate.search(source, patterns), key=lambda m: m[0] - m[1])
                for start, end, confidence in matches:
                    rects = source.rects_for(start, end)
                    if not rects:
                        continue
                    covered = [r for r in rects if any(p == page and _coverage(r, [e]) > 0.95 for p, e in existing)]
                    if len(covered) == len(rects):
                        continue
                    add(page, kind, source.text[start:end].strip(), rects, confidence, "propagation",
                        detail="misma persona/dato en otro lugar", key=key)
                    existing.extend((page, r) for r in rects)


def _llm_review(analysis: Analysis, llm, categories: set[str], add, progress, cancelled) -> None:
    from . import llm_review
    for page, sources in analysis.sources.items():
        if cancelled():
            raise Cancelled()
        progress({"stage": "review", "page": page + 1, "total": len(analysis.pages),
                  "message": f"Revisión con IA de la página {page + 1}"})
        page_findings = [f for f in analysis.findings if f.page == page]
        for name, source in sources:
            if name == "ocr-alt" or len(source.text.strip()) < 20:
                continue
            known = []
            for finding in page_findings:
                if not finding.value:
                    continue
                for match in re.finditer(re.escape(finding.value), source.text):
                    known.append((match.start(), match.end(), CATEGORIES[finding.type]["token"]))
            try:
                extra = llm_review.review(llm, source.text, known)
            except Exception as error:
                analysis.notes.append(f"Revisión con IA no disponible: {error}")
                return
            for match in extra:
                if match.type not in categories and "other" not in categories:
                    continue
                rects = source.rects_for(match.start, match.end)
                if rects:
                    add(page, match.type if match.type in categories else "other", match.value.strip(), rects,
                        match.confidence, "llm", detail="propuesto por la revisión con IA")


def _dedupe(analysis: Analysis) -> None:
    priority = {"text": 6, "form": 6, "ai": 5, "ocr": 4, "handwriting": 4, "propagation": 3, "llm": 2,
                "face": 5, "signature": 3, "manual": 9}
    ordered = sorted(analysis.findings, key=lambda f: (-priority.get(f.source, 1), -f.confidence))
    kept: list[Finding] = []
    for finding in ordered:
        duplicate = False
        for other in kept:
            if other.page != finding.page:
                continue
            if all(any(_coverage(r, [o]) > 0.6 for o in other.rects) for r in finding.rects):
                if other.type == finding.type or (other.value and finding.value):
                    duplicate = True
                    break
        if not duplicate:
            kept.append(finding)
    analysis.findings = kept


@dataclass
class TokenRegistry:
    """Replacement identifiers of one session, shared by all its documents: the same value gets the same
    token in every file and numbers continue from one document to the next."""
    tokens: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    full_names: dict[str, frozenset[str]] = field(default_factory=dict)   # name key -> its words

    def next(self, kind: str) -> str:
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return f"[{CATEGORIES[kind]['token']} {self.counters[kind]}]"

    def token(self, kind: str, key: str) -> str:
        if key not in self.tokens:
            self.tokens[key] = self.next(kind)
        return self.tokens[key]


def assign_tokens(findings: list[Finding], registry: TokenRegistry | None = None, scope: str = "") -> None:
    """Number the findings of one document. With a session ``registry`` values keep the tokens they received in
    earlier documents; ``scope`` (the document) keeps faces, signatures and manual zones apart between files."""
    registry = registry if registry is not None else TokenRegistry()
    ordered = sorted(findings, key=lambda f: (f.page, f.rects[0][1] if f.rects else 0, f.rects[0][0] if f.rects else 0))
    names = [f for f in ordered if f.type == "name" and f.value]
    full_names: list[tuple[set[str], str]] = []
    for finding in ordered:
        if finding.value and finding.type not in ("face", "signature", "manual", "handwriting"):
            if not finding.key:
                finding.key = finding.type + "|" + canonical(finding.type, finding.value)
        else:
            finding.key = f"{scope}#{finding.id}" if scope else finding.key or finding.id
    # Partial mentions of a detected full name share its token. A single word ("Sr. Goikoetxea") only when it
    # belongs to exactly one person in the document: two people sharing a surname keep separate tokens.
    # Without a full name in the document, two or more words ("Ana Varela") join the only session name holding them.
    for finding in sorted(names, key=lambda f: -len(f.value.split())):
        words = {w for w in canonical("name", finding.value).split() if w not in rules.PARTICLES}
        parents = list(dict.fromkeys(key for full, key in full_names if words and words < full))
        if not parents and len(words) >= 2:
            session = [key for key, full in registry.full_names.items() if words < full]
            parents = session if len(session) == 1 else []
        parent = parents[0] if parents and (len(words) >= 2 or len(parents) == 1) else None
        if parent and finding.source != "propagation":
            finding.key = parent
        else:
            full_names.append((words, finding.key))
    for words, key in full_names:
        registry.full_names.setdefault(key, frozenset(words))
    for finding in ordered:
        if finding.type == "manual" and finding.token:
            continue  # a zone kept from an earlier review keeps its number
        finding.token = registry.token(finding.type, finding.key)


def add_manual(analysis: Analysis, page: int, rect: Rect, registry: TokenRegistry | None = None) -> Finding:
    if registry is not None:
        token = registry.next("manual")
    else:
        number = max((int(re.search(r"(\d+)\]$", f.token).group(1)) for f in analysis.findings
                      if f.type == "manual" and re.search(r"(\d+)\]$", f.token)), default=0) + 1
        token = f"[{CATEGORIES['manual']['token']} {number}]"
    finding = Finding(id=analysis.new_id(page), page=page, type="manual", value=None,
                      rects=[rect], confidence=1.0, source="manual", token=token)
    finding.key = finding.id
    analysis.findings.append(finding)
    return finding


# ---------------------------------------------------------------- export
def safe_filename(original: str, findings: list[Finding], index: int, keep_name: bool) -> str:
    stem = original.rsplit(".", 1)[0] if "." in original else original
    if not keep_name:
        return f"documento-{index}_anonimizado.pdf"
    # Identifiers that contain dots or dashes (e-mails, URLs, IBANs…) are replaced before the separators
    # are turned into spaces, which would otherwise break them apart and hide them from the rules.
    for match in reversed(rules.detect_all(stem)):
        stem = stem[:match.start] + CATEGORIES[match.type]["token"] + stem[match.end:]
    readable = re.sub(r"[_\-.]+", " ", stem)
    for finding in findings:
        if finding.value:
            for pattern, _ in propagate.variants(finding.type, finding.value):
                norm = propagate.NormalizedText(readable)
                for match in reversed(list(re.finditer(pattern, norm.text))):
                    start, end = norm.span(match.start(), match.end())
                    readable = readable[:start] + finding.token.strip("[]").replace(" ", "-") + readable[end:]
    for match in reversed(list(re.finditer(r"\d{6,}", readable))):
        readable = readable[:match.start()] + "ID" + readable[match.end():]
    for match in reversed(rules.detect_all(readable)):
        readable = readable[:match.start] + CATEGORIES[match.type]["token"] + readable[match.end:]
    cleaned = re.sub(r"[^\w\-]+", "_", readable).strip("_") or f"documento-{index}"
    return f"{cleaned}_anonimizado.pdf"


def residual_detector(categories: set[str], services=None):
    """Personal data still present in the output (warnings): rules and, if available, the AI model,
    over the extractable text and the OCR text of each page."""
    # Replacement tokens, also as OCR reads them ("NOMBRE 1]", "(DNI 2)", "[TELEFONO 3").
    words = "|".join(re.escape(rules.no_accents(c["token"])) for c in CATEGORIES.values())
    token = re.compile(r"[\[\(\{|]?\s*(?:" + words + r")\s*\d{1,3}\s*[\]\)\}|]?", re.IGNORECASE)
    pii = services.pii() if services is not None else None

    def run(data: bytes, ocr_texts: dict[int, str] | None = None) -> list[str]:
        doc = document.analysis_copy(document.open_pdf(data))
        messages = []
        for index, page in enumerate(doc):
            native = page.get_text("text", flags=document.TEXT_FLAGS, clip=pymupdf.INFINITE_RECT())
            text = unicodedata.normalize("NFC", native + "\n" + (ocr_texts or {}).get(index, ""))
            plain = rules.no_accents(text)  # same length as the NFC text: spans can be reused
            for match in reversed(list(token.finditer(plain))):
                text = text[:match.start()] + " " * (match.end() - match.start()) + text[match.end():]
            matches = [m for m in rules.detect_all(text) if m.confidence >= 0.8]
            if pii is not None and text.strip():
                try:
                    matches += [m for m in pii.detect(text) if _useful_ai(m) and m.confidence >= 0.8]
                except Exception:
                    messages.append(f"Página {index + 1}: revisión residual con IA no disponible; revisa el documento")
            seen = set()
            for match in matches:
                key = (match.type, match.value.lower())
                if match.type in categories and key not in seen:
                    seen.add(key)
                    messages.append(f"Página {index + 1}: posible {CATEGORIES[match.type]['label'].lower()} sin ocultar "
                                    "(revisa el documento)")
        doc.close()
        return messages

    return run


def export(analysis: Analysis, options: Options, services=None, progress: Progress | None = None,
           index: int = 1, keep_name: bool = False, verify_pixels: bool = True) -> ExportResult:
    started = time.time()
    progress = progress or (lambda event: None)
    progress({"stage": "redact", "message": "Aplicando tachado destructivo"})
    doc = pymupdf.open("pdf", analysis.working)
    redact.apply(doc, analysis.findings, options.mode, options.uniform_tokens)
    data = redact.render_output(doc.tobytes())
    doc.close()
    progress({"stage": "sanitize", "message": "Limpiando la estructura del PDF"})
    data = sanitize.sanitize(data)
    if options.max_security:
        progress({"stage": "rasterize", "message": "Modo máxima seguridad: convirtiendo páginas en imagen"})
        ocr = services.ocr() if services is not None and options.ocr_text_layer else None
        data = sanitize.sanitize(rasterize.rasterize(data, options.raster_dpi, ocr))
    progress({"stage": "verify", "message": "Verificando que no queda ningún rastro"})
    report = verify.verify(data, analysis.findings, services if verify_pixels else None,
                           residual=residual_detector(set(options.categories), services), progress=progress)
    return ExportResult(data, report, safe_filename(analysis.filename, analysis.findings, index, keep_name),
                        round(time.time() - started, 1))


def preview(data: bytes, page: int, width: int = 1000) -> bytes:
    doc = document.open_pdf(data)
    try:
        target = doc[page]
        zoom = min(6.0, width / max(1.0, target.rect.width))
        while math.ceil(target.rect.width * zoom) * math.ceil(target.rect.height * zoom) > document.LIMITS["max_page_pixels"]:
            pixels = math.ceil(target.rect.width * zoom) * math.ceil(target.rect.height * zoom)
            zoom *= (document.LIMITS["max_page_pixels"] / pixels) ** 0.5 * 0.999
        return target.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, annots=False).tobytes("png")
    finally:
        doc.close()
