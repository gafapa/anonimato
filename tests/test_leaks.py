"""End-to-end leak tests over the adversarial corpus.

Each fixture is analysed and exported with the real engine. The output is then
checked by an independent scanner (not the app's verifier) for any copy of the
canary data.
"""
import io
import re
import sys
import unicodedata

import pikepdf
import pymupdf
import pytest

from app.engine import pipeline, rules
from app.engine.services import Services
from app.engine.types import Options
from tests.fixtures.generate import CANARIES, DNI, NAME, build_all

FIXTURES = build_all()
COMBINING_MARKS = dict.fromkeys(codepoint for codepoint in range(sys.maxunicode + 1)
                               if unicodedata.category(chr(codepoint)) == "Mn")


def _plain(text: str) -> str:
    # Native translation avoids a Python object per character when checking large decoded image streams.
    text = unicodedata.normalize("NFD", text).translate(COMBINING_MARKS)
    return re.sub(r"\s+", " ", text).casefold()


def independent_scan(data: bytes) -> list[str]:
    """Return descriptions of every place where a canary survives."""
    needles = [_plain(NAME), DNI.casefold(), "garcia perez", "12345678"]
    raw_needles = [NAME.encode("utf-8"), NAME.encode("latin-1"), NAME.encode("utf-16-be"), DNI.encode(),
                   DNI.encode("utf-16-be"), b"Garc\\355a", "García".encode("utf-16-be")]
    leaks = []
    for needle in raw_needles:
        if needle in data:
            leaks.append(f"raw bytes: {needle!r}")
    pdf = pikepdf.open(io.BytesIO(data))
    for obj in pdf.objects:
        blobs = [bytes(repr(obj), "utf-8", "ignore")] if not isinstance(obj, pikepdf.Stream) else []
        if isinstance(obj, pikepdf.Stream):
            try:
                blobs.append(obj.read_bytes())
            except Exception:
                blobs.append(obj.read_raw_bytes())
            blobs.append(bytes(repr(obj.stream_dict), "utf-8", "ignore"))
        for blob in blobs:
            for encoding in ("latin-1", "utf-8", "utf-16-be"):
                text = _plain(blob.decode(encoding, errors="ignore"))
                for needle in needles:
                    if needle in text:
                        leaks.append(f"object {obj.objgen}: {needle} ({encoding})")
    if "/Info" in pdf.trailer and len(pdf.trailer.Info.keys()):
        leaks.append("Info dictionary present")
    for key in ("/Metadata", "/Outlines", "/StructTreeRoot", "/AcroForm", "/Names", "/OpenAction", "/PageLabels"):
        if key in pdf.Root:
            leaks.append(f"catalog {key}")
    doc = pymupdf.open("pdf", data)
    for page in doc:
        text = _plain(page.get_text("text", clip=pymupdf.INFINITE_RECT()))
        for needle in needles:
            if needle in text:
                leaks.append(f"page {page.number + 1} text: {needle}")
        if page.first_annot is not None:
            leaks.append(f"page {page.number + 1} has annotations")
        if doc.embfile_count():
            leaks.append("embedded files")
    return sorted(set(leaks))


@pytest.fixture(scope="module")
def services():
    svc = Services(use_gpu=True)
    svc.ocr().warm_up()
    yield svc
    svc.shutdown()


def _options(**overrides) -> Options:
    base = dict(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF, handwriting=False, llm_review=False)
    base.update(overrides)
    return Options(**base)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f"{f.number:02d}_{f.key}")
def test_no_trace_left(fixture, services):
    options = _options()
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    values = {rules.canonical(f.type, f.value) for f in analysis.findings if f.value}
    if NAME in fixture.canaries:
        assert rules.canonical("name", NAME) in values, "canary name not detected"
    if DNI in fixture.canaries:
        assert rules.canonical("dni", DNI) in values, "canary DNI not detected"
    result = pipeline.export(analysis, options, services, index=fixture.number)
    leaks = independent_scan(result.data)
    assert not leaks, leaks
    assert result.report.ok, result.report.to_json()
    for canary in CANARIES:
        plain = _plain(canary).replace(" ", "_")
        assert plain not in _plain(result.filename)
    assert "12345678" not in result.filename and "juan" not in result.filename.lower()
    if fixture.needs_faces:
        faces = [f for f in analysis.findings if f.type == "face"]
        assert faces, "face not detected"


@pytest.mark.parametrize("fixture", [f for f in FIXTURES if f.number in (13, 19, 22, 23)],
                         ids=lambda f: f"{f.number:02d}_{f.key}")
def test_max_security_mode(fixture, services):
    options = _options(max_security=True)
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    result = pipeline.export(analysis, options, services, index=fixture.number)
    assert not independent_scan(result.data)
    assert result.report.ok, result.report.to_json()
    doc = pymupdf.open("pdf", result.data)
    for page in doc:
        assert not page.get_drawings(), "vector content must not survive rasterisation"
        assert len(page.get_images()) == 1


def test_filename_keeps_non_personal_words(services):
    fixture = next(f for f in FIXTURES if f.number == 21)
    options = _options()
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    name = pipeline.safe_filename(fixture.filename, analysis.findings, 1, keep_name=True)
    assert "informe" in name and "Juan" not in name and "12345678" not in name


def test_verifier_blocks_a_leaky_pdf(services):
    """If redaction were skipped, verification must fail."""
    fixture = next(f for f in FIXTURES if f.number == 6)
    options = _options()
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    from app.engine import verify
    report = verify.verify(fixture.data, analysis.findings, services)
    assert not report.ok
    assert {leak.check for leak in report.leaks} >= {"texto", "objetos"}


def test_user_can_keep_a_value(services):
    fixture = next(f for f in FIXTURES if f.number == 21)
    options = _options()
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    for finding in analysis.findings:
        if finding.type == "dni":
            finding.enabled = False
    result = pipeline.export(analysis, options, services)
    assert result.report.ok  # a value the user chose to keep is not a leak
    assert DNI in pymupdf.open("pdf", result.data)[0].get_text()


def test_residual_detection_uses_the_ai_model(services):
    """A name the user decided to keep is still reported as a possible residue by the AI model."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Acta firmada por Iraitz Eguzkitza Urquiola en la sede.", fontsize=11)
    options = _options()
    analysis = pipeline.analyze(doc.tobytes(), "acta.pdf", options, services)
    for finding in analysis.findings:
        finding.enabled = False
    result = pipeline.export(analysis, options, services)
    assert any("nombre" in warning.lower() for warning in result.report.warnings), result.report.warnings


def _image_page(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(72, 100, 522, 175), stream=buffer.getvalue())
    return doc.tobytes()


def test_zoomed_ocr_catches_a_half_covered_value(services):
    """The value survives only as pixels next to a misaligned box: the text checks cannot see it,
    the OCR checks must."""
    from PIL import Image, ImageDraw, ImageFont

    from app.engine import verify
    from app.engine.system import font
    from app.engine.types import Finding
    image = Image.new("RGB", (1200, 200), "white")
    ImageDraw.Draw(image).text((30, 60), f"DNI {DNI}", fill="black", font=ImageFont.truetype(font("sans"), 80))
    data = _image_page(image)
    shifted = Finding("f", 0, "dni", DNI, [(200, 120, 330, 150)], 1.0, "ocr")  # box misaligned to the right
    report = verify.verify(data, [shifted], services)
    checks = {leak.check for leak in report.leaks}
    assert not report.ok and {"ocr", "ocr-zona"} <= checks, report.to_json()
    assert all(leak.page == 0 and leak.rects for leak in report.leaks if leak.check.startswith("ocr"))


def test_face_left_visible_is_detected(services):
    from PIL import Image

    from app.engine import verify
    from app.engine.types import Finding
    from tests.fixtures.generate import ASSETS
    portrait = Image.open(ASSETS / "lena.jpg").convert("RGB").resize((300, 300))
    canvas = Image.new("RGB", (1200, 300), "white")
    canvas.paste(portrait, (450, 0))
    data = _image_page(canvas)
    face = Finding("f", 0, "face", None, [(72, 100, 522, 175)], 0.9, "face")
    report = verify.verify(data, [face], services)
    assert any(leak.check == "rostros" and leak.page == 0 for leak in report.leaks), report.to_json()
