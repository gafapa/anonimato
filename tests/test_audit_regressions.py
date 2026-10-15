"""Adversarial identity, session cleanup, model repair and quality-gate regressions."""
import hashlib
import threading
from unittest.mock import Mock

import pytest

from app.api import Api, Doc, State
from app.engine import models, pipeline
from app.engine.types import Finding, Options
from tools.detection_quality import failures


def person(index, value):
    return Finding(str(index), 0, "name", value, [(0, index * 10, 100, index * 10 + 5)], 1, "text")


def session():
    api = object.__new__(Api)
    api._lock = threading.RLock()
    api._state = State()
    api._status_cache = None
    return api


def add_analysis(api, identifier, names):
    analysis = pipeline.Analysis(id=identifier, filename=identifier, working=b"", pages=[pipeline.PageInfo(100, 100, 0)],
                                 findings=[person(index, value) for index, value in enumerate(names)],
                                 options=Options(categories={"name"}))
    doc = Doc(identifier, identifier, 0, b"", status="ready", analysis=analysis)
    api._state.docs[identifier] = doc
    api._state.order.append(identifier)
    api._reconcile_tokens()
    return doc


def test_two_word_ambiguous_mention_never_selects_the_first_person():
    findings = [person(0, "Ana Lopez Martin"), person(1, "Ana Lopez Garcia"), person(2, "Ana Lopez")]
    pipeline.assign_tokens(findings)
    assert len({finding.token for finding in findings}) == 3


@pytest.mark.parametrize("names", [("Ana Varela", "Ana Varela Souto"), ("Ana Varela Souto", "Ana Varela")])
def test_partial_and_full_names_resolve_across_documents_in_both_orders(names):
    api = session()
    first = add_analysis(api, "first", [names[0]])
    second = add_analysis(api, "second", [names[1]])
    assert first.analysis.findings[0].token == second.analysis.findings[0].token
    revision = first.revision
    api._reconcile_tokens()
    assert first.revision == revision


def test_new_ambiguity_invalidates_previously_saved_identity_mapping():
    api = session()
    first = add_analysis(api, "first", ["Ana Varela"])
    second = add_analysis(api, "second", ["Ana Varela Souto"])
    assert first.analysis.findings[0].token == second.analysis.findings[0].token
    second.report = {"ok": True}
    second.saved_revision = second.revision
    second.preview_key, second.preview_bytes = "old", b"old preview"
    add_analysis(api, "third", ["Ana Varela Ruiz"])
    assert len({doc.analysis.findings[0].token for doc in api._state.docs.values()}) == 3
    assert second.saved_revision != second.revision
    assert second.report is None and second.preview_bytes is None and not second.preview_key


def test_clear_and_remove_release_all_name_registry_entries():
    api = session()
    add_analysis(api, "first", ["Fictitious Person"])
    assert api.remove("first")
    assert not api._state.tokens.tokens and not api._state.tokens.full_names
    add_analysis(api, "second", ["Other Fictitious Person"])
    assert api.clear()
    assert not api._state.tokens.tokens and not api._state.tokens.full_names
    assert not api._state.docs and not api._state.order


def test_corrupt_required_model_is_repaired_only_after_staged_verification(tmp_path, monkeypatch):
    content = b"verified synthetic model"
    item = models.ModelFile(id="synthetic", file="model.onnx", url="https://example.invalid/model",
                            sha256=hashlib.sha256(content).hexdigest(), license="synthetic", group="base", size=len(content))
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "required_items", lambda: [item])
    item.path.write_bytes(b"corrupt")
    assert models.required_missing() == []
    assert models.required_missing(verify=True) == [item]

    def download(item, target, progress):
        assert item.path.read_bytes() == b"corrupt"
        target.write_bytes(content)
        models._check_model(item, target)
        return target

    monkeypatch.setattr(models, "_download_to", download)
    models.install_required()
    assert item.path.read_bytes() == content
    assert not models.required_missing(verify=True)


def test_detection_gate_rejects_missing_categories_and_positional_regressions():
    policy = {"values": {"scanned/name": 0.98}, "occurrences": {"scanned/name": 0.95}, "precision": 0.98}
    assert not failures({("scanned", "name"): [100, 100]}, {("scanned", "name"): [95, 100]}, 99, 100, policy)
    assert failures({}, {("scanned", "name"): [95, 100]}, 99, 100, policy)
    assert failures({("scanned", "name"): [100, 100]}, {("scanned", "name"): [94, 100]}, 99, 100, policy)
    assert failures({("scanned", "name"): [100, 100]}, {("scanned", "name"): [95, 100]}, 97, 100, policy)


def test_integrity_recheck_repairs_required_models_and_reloads_services(monkeypatch):
    api = session()
    api._engine = Mock()
    api._engine.call.side_effect = [False, True]
    install = Mock()
    monkeypatch.setattr(models, "install_required", install)
    assert api.recheck_integrity()
    # Join only the owned operation using its completion flag.
    import time
    deadline = time.monotonic() + 5
    while api._state.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not api._state.busy
    install.assert_called_once()
    assert [call.args[0] for call in api._engine.call.call_args_list] == ["integrity", "reload_models"]


def test_runtime_group_extracts_only_after_archive_publication(tmp_path, monkeypatch):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("llama/fictitious.exe", b"synthetic runtime")
    content = buffer.getvalue()
    item = models.ModelFile(id="runtime", file="runtime/synthetic.zip", url="https://example.invalid/runtime",
                            sha256=hashlib.sha256(content).hexdigest(), license="synthetic", group="runtime",
                            size=len(content), unzip=True)
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "runtime_dir", lambda: tmp_path / "runtime")

    def download(item, target, progress, *, extract=True):
        assert not extract and not item.path.exists()
        target.write_bytes(content)
        return target

    monkeypatch.setattr(models, "_download_to", download)
    models.download_group([item])
    assert (tmp_path / "runtime/llama/fictitious.exe").read_bytes() == b"synthetic runtime"
    assert item.path.read_bytes() == content


def test_parallel_integrity_reads_changed_bytes_even_with_preserved_metadata(tmp_path, monkeypatch):
    import os

    item = models.ModelFile(id="weight", file="weight.onnx", url="https://example.invalid/weight",
                            sha256=hashlib.sha256(b"good").hexdigest(), license="synthetic", group="base", size=4)
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "load_manifest", lambda: {"base": [item]})
    monkeypatch.setattr(models, "verify_runtime", lambda: [])
    item.path.write_bytes(b"good")
    original = item.path.stat()
    assert not models.verify_all()
    item.path.write_bytes(b"evil")
    os.utime(item.path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert models.verify_all() == ["weight"]


@pytest.mark.parametrize("minimum", [-1, 2, float("nan"), True])
def test_invalid_precision_policy_is_rejected(minimum):
    with pytest.raises(ValueError, match="precision"):
        failures({}, {}, 0, 1, {"values": {}, "occurrences": {}, "precision": minimum})
