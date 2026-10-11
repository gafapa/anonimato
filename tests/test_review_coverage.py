"""Review recovery, rotated geometry and publication boundaries using fictitious PDFs."""
import copy
import hashlib
import json
from unittest.mock import Mock

import pymupdf
import pytest

from app.engine import pipeline, review, verify
from app.engine.types import Finding, Options
from app.engine.worker import EngineError
from tests import test_review_fixes


@pytest.fixture
def bridge():
    yield from test_review_fixes.bridge.__wrapped__()


@pytest.mark.parametrize("action", ["toggle", "remove", "undo", "redo"])
def test_noop_review_keeps_saved_revision_and_verification(bridge, action):
    api, doc = bridge
    item = api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.5])
    doc.history.clear()
    doc.saved_revision = doc.revision
    doc.report = {"ok": True}
    revision = doc.revision
    actions = {"toggle": lambda: api.set_enabled(doc.id, [item["id"]], True),
               "remove": lambda: api.remove_manual(doc.id, "missing"),
               "undo": lambda: api.restore_review(doc.id),
               "redo": lambda: api.restore_review(doc.id, True)}
    actions[action]()
    assert doc.revision == revision and doc.report == {"ok": True}
    assert api.documents()[0]["saved"]
    assert not doc.history.undo and not doc.history.redo


@pytest.mark.parametrize("operation", ["update", "undo", "redo"])
@pytest.mark.parametrize("state", ["processing", "installing"])
def test_history_and_coordinate_edits_are_blocked_during_work(bridge, operation, state):
    api, doc = bridge
    item = api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.5])
    before = review.encode(doc.analysis.findings)
    revision = doc.revision
    api._state.busy = state == "processing"
    api._state.install["running"] = state == "installing"
    action = (lambda: api.update_manual(doc.id, item["id"], 0, [0.2, 0.3, 0.5, 0.6])) if operation == "update" else (
        lambda: api.restore_review(doc.id, operation == "redo"))
    with pytest.raises(ValueError, match="termine"):
        action()
    assert doc.revision == revision and review.encode(doc.analysis.findings) == before


@pytest.mark.parametrize("page", [-1, 1, True, 0.5, "0"])
def test_invalid_page_does_not_record_or_mutate_review(bridge, page):
    api, doc = bridge
    with pytest.raises(ValueError):
        api.add_manual(doc.id, page, [0.1, 0.2, 0.4, 0.5])
    assert doc.revision == 0 and not doc.history.undo and not doc.analysis.findings


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_coordinate_edit_roundtrip_on_rotated_pages(bridge, rotation):
    api, doc = bridge
    pdf = pymupdf.open()
    page = pdf.new_page(width=200, height=400)
    page.set_rotation(rotation)
    doc.data = pdf.tobytes()
    doc.analysis = pipeline.analyze(doc.data, doc.name, Options(categories=set(), ocr=False, ai=False,
                                                               faces=False, signatures=False))
    first = [0.1, 0.2, 0.4, 0.5]
    second = [0.5, 0.6, 0.8, 0.9]
    item = api.add_manual(doc.id, 0, first)
    assert item["view"][0] == pytest.approx(first)
    expected = pymupdf.Rect(first[0] * page.rect.width, first[1] * page.rect.height,
                           first[2] * page.rect.width, first[3] * page.rect.height) * page.derotation_matrix
    assert doc.analysis.findings[0].rects[0] == pytest.approx(tuple(expected))
    result = api.update_manual(doc.id, item["id"], 0, second)
    assert result["findings"][0]["view"][0] == pytest.approx(second)
    assert api.restore_review(doc.id)["findings"][0]["view"][0] == pytest.approx(first)
    assert api.restore_review(doc.id, True)["findings"][0]["view"][0] == pytest.approx(second)


def test_automatic_finding_cannot_be_deleted_or_edited_as_manual(bridge):
    api, doc = bridge
    doc.analysis.findings.append(Finding("automatic", 0, "name", "Fictitious Name", [(10, 20, 30, 40)], 1, "text"))
    assert not api.remove_manual(doc.id, "automatic")
    with pytest.raises(ValueError, match="no existe"):
        api.update_manual(doc.id, "automatic", 0, [0.1, 0.2, 0.4, 0.5])
    assert doc.revision == 0 and not doc.history.undo and len(doc.analysis.findings) == 1


@pytest.mark.parametrize("error", [pipeline.Cancelled(), EngineError("synthetic engine failure")])
def test_failed_reanalysis_preserves_manual_history_and_previous_analysis(bridge, error):
    api, doc = bridge
    api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.5])
    previous, revision = doc.analysis, doc.revision
    history = list(doc.history.undo)
    api._engine.call = Mock(side_effect=error)
    api._state.busy = True
    api._run([doc.id], Options(categories=set()))
    assert doc.analysis is previous and doc.status == "ready" and doc.revision == revision
    assert doc.history.undo == history and not api.poll()["busy"]
    assert len(api.restore_review(doc.id)["findings"]) == 0


def test_reanalysis_assigns_distinct_manual_ids_and_keys(bridge):
    api, doc = bridge
    original = api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.5])
    api.set_enabled(doc.id, [original["id"]], False)
    options = Options(categories=set(), ocr=False, ai=False, faces=False, signatures=False)
    fresh = pipeline.analyze(doc.data, doc.name, options)
    fresh.findings.append(Finding(fresh.new_id(0), 0, "name", "Fictitious Name", [(10, 20, 30, 40)], 1, "text"))
    api._engine.call = Mock(return_value=fresh)
    api._run([doc.id], options)
    automatic, manual = fresh.findings
    assert manual.id != automatic.id and manual.key != automatic.key
    assert manual.token == original["token"] and not manual.enabled
    api.set_enabled(doc.id, [manual.id], True)
    assert automatic.enabled and manual.enabled


def test_export_refuses_changed_source_before_engine_or_publication(bridge, tmp_path):
    api, doc = bridge
    doc.analysis_hash = hashlib.sha256(doc.data).hexdigest()
    doc.data += b"changed"
    api._engine.call = Mock()
    result = api.export_folder(str(tmp_path), {})
    assert result["saved"] == 0 and result["results"][0]["status"] == "processing_error"
    api._engine.call.assert_not_called()
    assert not list(tmp_path.glob("*.pdf")) and not api.documents()[0]["saved"]


def test_mixed_batch_reports_distinct_causes_without_original_values(bridge, tmp_path):
    api, doc = bridge
    for index in range(2, 4):
        other = copy.deepcopy(doc)
        other.id = f"d{index}"
        api._state.docs[other.id] = other
        api._state.order.append(other.id)
    def export(operation, analysis, options, index, keep_name, **kwargs):
        if index == 3:
            raise EngineError("synthetic engine failure")
        report = verify.Report()
        if index == 2:
            report.add(verify.Leak("text", "page", "FICTITIOUS ORIGINAL", page=0))
        return pipeline.ExportResult(doc.data, report, f"documento-{index}_anonimizado.pdf", 0)
    api._engine.call = export
    result = api.export_folder(str(tmp_path), {})
    assert result["saved"] == 1 and result["failed"] == 2 and not result["ok"]
    assert [item["status"] for item in result["results"]] == ["saved", "verification_blocked", "processing_error"]
    report_text = (tmp_path / "informe_verificacion.json").read_text(encoding="utf-8")
    assert "FICTITIOUS ORIGINAL" not in report_text
    assert [item["id"] for item in json.loads(report_text)["documentos"]] == ["d1", "d2", "d3"]
    assert [item["saved"] for item in api.documents()] == [True, False, False]


def test_invalid_batch_retry_releases_busy_state_without_writing(bridge, tmp_path):
    api, _ = bridge
    with pytest.raises(EngineError, match="no disponible"):
        api.export_folder(str(tmp_path), {}, ["missing"])
    assert not api.poll()["busy"] and not list(tmp_path.iterdir())


def test_history_byte_limit_applies_to_undo_and_redo_together(monkeypatch):
    findings = [Finding("manual", 0, "manual", "", [(10, 20, 30, 40)], 1, "manual")]
    history = review.ReviewHistory()
    size = len(review.encode(findings))
    monkeypatch.setattr(review, "MAX_HISTORY_BYTES", size * 2)
    for _ in range(3):
        history.record(findings)
    assert len(history.undo) == 2
    assert history.restore(findings) is not None
    larger = copy.deepcopy(findings)
    larger[0].value = "fictitious" * size
    assert history.restore(larger) is not None
    assert sum(map(len, history.undo + history.redo)) <= size * 2
    assert history.restore(findings, redo=True) is None


@pytest.mark.parametrize("width", [True, 599, 3301, "1100", 1000.5])
def test_invalid_preview_resolution_never_renders(bridge, width):
    api, doc = bridge
    api._light.call = Mock()
    with pytest.raises(ValueError, match="Resolución"):
        api.page_image(doc.id, 0, "original", {"previewWidth": width})
    api._light.call.assert_not_called()


def test_zoom_reuses_redacted_bytes_but_edit_invalidates_preview(bridge):
    api, doc = bridge
    def light_call(operation, *args):
        return b"fictitious preview PDF" if operation == "build_preview" else b"fictitious PNG"
    api._light.call = Mock(side_effect=light_call)
    first = api.page_image(doc.id, 0, "result", {"previewWidth": 600})
    second = api.page_image(doc.id, 0, "result", {"previewWidth": 3300})
    assert first.startswith("data:image/png;base64,") and first == second
    assert [call.args[0] for call in api._light.call.call_args_list].count("build_preview") == 1
    api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.5])
    api.page_image(doc.id, 0, "result", {})
    assert [call.args[0] for call in api._light.call.call_args_list].count("build_preview") == 2
    assert [call.args[-1] for call in api._light.call.call_args_list if call.args[0] == "page_png"] == [600, 3300, 1100]
