"""Review preservation, bounded history, selective execution and lazy services."""
import copy
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.engine import llm_server, pipeline, review
from app.engine.services import Services
from app.engine.types import Options
from tests import test_review_fixes


@pytest.fixture
def review_bridge():
    yield from test_review_fixes.bridge.__wrapped__()


def test_history_restores_all_fields_and_invalidates_verification(review_bridge):
    api, doc = review_bridge
    added = api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.3])
    api.set_enabled(doc.id, [added["id"]], False)
    api.restore_review(doc.id)
    assert doc.analysis.findings[0].enabled
    api.restore_review(doc.id)
    assert not doc.analysis.findings
    api.restore_review(doc.id, True)
    assert doc.analysis.findings[0].id == added["id"]
    assert doc.report is None and doc.saved_revision != doc.revision
    api.set_enabled(doc.id, [added["id"]], False)
    assert not doc.history.redo


def test_history_is_bounded_and_never_written(review_bridge, monkeypatch):
    api, doc = review_bridge
    monkeypatch.setattr(review, "MAX_HISTORY_STEPS", 3)
    for offset in range(5):
        api.add_manual(doc.id, 0, [0.1, 0.1 + offset * 0.1, 0.2, 0.15 + offset * 0.1])
    assert len(doc.history.undo) == 3
    monkeypatch.setattr(review, "MAX_HISTORY_BYTES", 1)
    doc.history.record(doc.analysis.findings)
    assert not doc.history.undo


@pytest.mark.parametrize("rect", [[0, 0, 0, 1], [0, 0, 1.1, 1], [0, float("nan"), 1, 1], [True, 0, 1, 1]])
def test_invalid_coordinates_do_not_change_history(review_bridge, rect):
    api, doc = review_bridge
    with pytest.raises(ValueError):
        api.add_manual(doc.id, 0, rect)
    assert not doc.history.undo and not doc.analysis.findings


def test_coordinate_edit_and_undo(review_bridge):
    api, doc = review_bridge
    added = api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.3])
    result = api.update_manual(doc.id, added["id"], 0, [0.2, 0.3, 0.5, 0.4])
    assert result["findings"][0]["view"][0] == pytest.approx([0.2, 0.3, 0.5, 0.4])
    result = api.restore_review(doc.id)
    assert result["findings"][0]["view"][0] == pytest.approx([0.1, 0.2, 0.4, 0.3])


@pytest.mark.parametrize("changed", [None, "bytes", "geometry"])
def test_reanalysis_preserves_manual_review_or_keeps_old_analysis(review_bridge, changed):
    api, doc = review_bridge
    options = Options(categories=set(), ocr=False, ai=False, faces=False, signatures=False)
    api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.3])
    api.set_enabled(doc.id, [doc.analysis.findings[0].id], False)
    old = doc.analysis
    doc.analysis_hash = hashlib.sha256(doc.data).hexdigest()
    fresh = pipeline.analyze(doc.data, doc.name, options)
    if changed == "bytes":
        doc.data += b"changed"
    elif changed == "geometry":
        fresh.pages[0].width += 10
    api._engine.call = Mock(return_value=fresh)
    api._run([doc.id], options)
    if changed:
        assert doc.analysis is old and doc.error and doc.status == "ready"
    else:
        assert doc.analysis is fresh and len(fresh.findings) == 1
        assert fresh.findings[0].type == "manual" and not fresh.findings[0].enabled
        assert not doc.history.undo


def test_selective_reanalysis_leaves_other_document_untouched(review_bridge):
    api, doc = review_bridge
    other = copy.deepcopy(doc)
    other.id = "d2"
    api._state.docs[other.id] = other
    api._state.order.append(other.id)
    api._engine.call = Mock(side_effect=lambda op, data, name, options, **kwargs: pipeline.analyze(data, name, options))
    api._run([doc.id], Options(categories=set(), ocr=False, ai=False, faces=False, signatures=False))
    assert other.revision == 0
    api._engine.call.assert_called_once()


def test_close_warning_tracks_review_revision(review_bridge):
    api, doc = review_bridge
    confirm = Mock(return_value=False)
    api.attach(SimpleNamespace(create_confirmation_dialog=confirm))
    assert api.confirm_close()
    api.details(doc.id)
    assert not api.confirm_close()
    doc.saved_revision = doc.revision
    assert api.confirm_close()
    api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.3])
    assert not api.confirm_close()


def test_lazy_startup_only_checks_integrity(monkeypatch):
    services = Services()
    monkeypatch.setattr(services, "check_integrity", Mock(return_value=True))
    monkeypatch.setattr(services, "ocr", Mock())
    monkeypatch.setattr(services, "pii", Mock())
    services.warm_up()
    assert services._ready.wait(2)
    services.ocr.assert_not_called()
    services.pii.assert_not_called()
    options = Options(categories=set(), ocr=False, ai=False, faces=False)
    services.prepare(options)
    services.ocr.assert_not_called()
    services.prepare(options, export=True)
    services.ocr.assert_called_once()
    services.pii.assert_called_once()


@pytest.mark.parametrize(("mode", "vram", "expected"), [("auto", 8000, "advanced"), ("auto", 2000, "advanced_lite"),
                                                        ("accuracy", 0, "advanced"), ("memory", 8000, "advanced_lite")])
def test_model_selection_at_actual_start(mode, vram, expected):
    assert llm_server.choose_variant(["advanced", "advanced_lite"], mode, vram, 32768) == expected


def test_automatic_model_refuses_insufficient_memory():
    with pytest.raises(RuntimeError, match="memoria"):
        llm_server.choose_variant(["advanced"], "auto", 0, 8000)


def test_high_resolution_preview_obeys_pixel_limit(review_bridge, monkeypatch):
    import pymupdf
    from app.engine import document
    _, doc = review_bridge
    monkeypatch.setitem(document.LIMITS, "max_page_pixels", 100_000)
    image = pymupdf.Pixmap(pipeline.preview(doc.data, 0, 3300))
    assert image.width * image.height <= 100_000


def test_batch_retry_only_exports_requested_document(review_bridge, tmp_path):
    api, doc = review_bridge
    other = copy.deepcopy(doc)
    other.id = "d2"
    api._state.docs[other.id] = other
    api._state.order.append(other.id)
    result = api.export_folder(str(tmp_path), {}, [doc.id])
    assert result["saved"] == 1 and result["results"][0]["id"] == doc.id
    assert other.saved_revision is None


def test_integrity_lock_wait_reports_progress_then_checks(monkeypatch):
    from unittest.mock import MagicMock
    from filelock import Timeout
    from app.engine import models
    services = Services()
    guard = MagicMock()
    lock = Mock(acquire=Mock(side_effect=[Timeout("synthetic-lock"), guard]))
    monkeypatch.setattr(models, "installation_lock", Mock(return_value=lock))
    check = Mock(return_value=[])
    monkeypatch.setattr(models, "verify_all", check)
    progress = Mock()
    assert services.check_integrity(force=True, progress=progress)
    progress.assert_called_once()
    check.assert_called_once_with(force=True)


def test_integrity_retry_preserves_review_and_clears_busy(review_bridge):
    import time
    api, doc = review_bridge
    api.add_manual(doc.id, 0, [0.1, 0.2, 0.4, 0.3])
    revision = doc.revision
    api._engine.call = Mock(return_value=True)
    assert api.recheck_integrity()
    deadline = time.monotonic() + 2
    while api._state.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not api._state.busy and doc.revision == revision and len(doc.analysis.findings) == 1
    assert api._engine.call.call_args.args == ("integrity",)


def test_default_process_skips_an_existing_review(review_bridge):
    import time
    api, doc = review_bridge
    other = copy.deepcopy(doc)
    other.id, other.status, other.analysis = "d2", "pending", None
    api._state.docs[other.id] = other
    api._state.order.append(other.id)
    api.status = Mock(return_value={"blocked": False})
    api._engine.call = Mock(side_effect=lambda op, data, name, options, **kwargs: pipeline.analyze(data, name, options))
    assert api.process({"ocr": False, "ai": False, "faces": False, "signatures": False})
    deadline = time.monotonic() + 2
    while api._state.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert other.status == "ready" and doc.revision == 0
    api._engine.call.assert_called_once()


def test_available_memory_is_a_current_positive_budget():
    from app.engine import system
    assert 0 < system.available_memory_mb() <= system.physical_memory_mb()


def test_macos_available_memory_parser(monkeypatch):
    import subprocess
    from app.engine import system
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setattr(system, "SYSTEM", "macos")
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(
        stdout="Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 1024.\nPages inactive: 2048.\nPages speculative: 1024.\n")))
    assert system.available_memory_mb() == 64
