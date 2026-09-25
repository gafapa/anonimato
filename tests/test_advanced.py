"""Advanced AI pack (handwriting + contextual review). Skipped when the pack is not installed."""
import pymupdf
import pytest

from app.engine import pipeline, rules
from app.engine.services import Services
from app.engine.types import Options
from tests.fixtures.generate import DNI, NAME, build_all
from tests.test_leaks import independent_scan

pytestmark = pytest.mark.skipif(not Services().advanced_available(), reason="IA avanzada no instalada")


@pytest.fixture(scope="module")
def services():
    svc = Services()
    yield svc
    svc.shutdown()


def _options(**overrides):
    base = dict(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF)
    base.update(overrides)
    return Options(**base)


def test_handwritten_form_leaves_no_trace(services):
    fixture = next(f for f in build_all() if f.number == 23)
    options = _options()
    analysis = pipeline.analyze(fixture.data, fixture.filename, options, services)
    kinds = {f.type for f in analysis.findings}
    assert {"name", "dni"} <= kinds or "handwriting" in kinds
    assert "signature" in kinds, "the signature next to «Firma:» must be proposed"
    result = pipeline.export(analysis, options, services)
    assert result.report.ok, result.report.to_json()
    assert not independent_scan(result.data)


def test_contextual_review_finds_indirect_identifiers(services):
    doc = pymupdf.open()
    page = doc.new_page()
    text = ("Informe del caso. La menor, hija del actual alcalde de Lalín, fue atendida por un cuadro de ansiedad. "
            f"Contacto del tutor: {NAME}, DNI {DNI}.")
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 300), text, fontsize=11)
    options = _options()
    analysis = pipeline.analyze(doc.tobytes(), "caso.pdf", options, services)
    llm = [f for f in analysis.findings if f.source == "llm"]
    assert llm, "the review should flag the indirect identifier / health data"
    joined = " ".join(f.value.lower() for f in llm)
    assert "alcalde" in joined or "ansiedad" in joined
