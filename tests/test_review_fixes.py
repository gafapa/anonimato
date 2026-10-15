"""Publication, model installation and process-protection regressions from the project review."""
import hashlib
import io
import json
import os
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pikepdf
import pytest

from app.api import Api, Doc
from app.engine import files, models, pipeline, verify, worker
from app.engine.services import Services
from app.engine.types import Options
from tests.test_security import NoEngine, pdf_with_text


@pytest.fixture
def bridge():
    api = Api(engine=NoEngine(), light=NoEngine())
    options = Options(categories={"manual"}, ocr=False, ai=False, faces=False, signatures=False,
                      handwriting=False, llm_review=False)
    data = pdf_with_text("SYNTHETIC PRIVATE TEXT")
    analysis = pipeline.analyze(data, "synthetic.pdf", options)
    doc = Doc("d1", "synthetic.pdf", len(data), data, status="ready", analysis=analysis)
    api._state.docs[doc.id] = doc
    api._state.order = [doc.id]
    api._engine.call = lambda *args, **kwargs: pipeline.ExportResult(data, verify.Report(), "documento-1_anonimizado.pdf", 0)
    yield api, doc
    api.shutdown()


@pytest.mark.parametrize("operation", ["add", "remove", "toggle"])
def test_review_edits_are_rejected_while_exporting(bridge, operation):
    api, doc = bridge
    manual = api.add_manual(doc.id, 0, [0.1, 0.3, 0.95, 0.55])
    api._state.busy = True
    calls = {"add": lambda: api.add_manual(doc.id, 0, [0.1, 0.3, 0.95, 0.55]),
             "remove": lambda: api.remove_manual(doc.id, manual["id"]),
             "toggle": lambda: api.set_enabled(doc.id, [manual["id"]], False)}
    with pytest.raises(ValueError, match="termine"):
        calls[operation]()
    assert len(doc.analysis.findings) == 1 and doc.analysis.findings[0].enabled


@pytest.mark.parametrize("when", ["export", "dialog"])
def test_single_export_never_publishes_a_stale_revision(bridge, tmp_path, when):
    api, doc = bridge
    target = tmp_path / "output.pdf"
    target.write_bytes(b"existing document")
    export = api._engine.call

    def call(*args, **kwargs):
        if when == "export":
            api.invalidate_report(doc.id)
        return export(*args, **kwargs)

    def dialog(*args, **kwargs):
        if when == "dialog":
            api.invalidate_report(doc.id)
        return str(target)

    api._engine.call = call
    api.attach(SimpleNamespace(create_file_dialog=dialog))
    result = api.save_pdf(doc.id, {})
    assert not result["ok"] and "cambió" in result["message"]
    assert target.read_bytes() == b"existing document"
    assert not api.poll()["busy"]


def test_batch_exports_preserve_all_previous_reports(bridge, tmp_path):
    api, _ = bridge
    first = api.export_folder(str(tmp_path), {})
    report = (tmp_path / "informe_verificacion.json").read_bytes()
    second = api.export_folder(str(tmp_path), {})
    assert first["saved"] == second["saved"] == 1
    assert (tmp_path / "informe_verificacion.json").read_bytes() == report
    assert (tmp_path / "informe_verificacion_2.json").exists()
    assert len(list(tmp_path.glob("*.pdf"))) == 2


def test_empty_batch_leaves_existing_report_untouched(bridge, tmp_path):
    api, doc = bridge
    doc.status = "pending"
    report = tmp_path / "informe_verificacion.json"
    report.write_text("existing report", encoding="utf-8")
    assert api.export_folder(str(tmp_path), {})["saved"] == 0
    assert report.read_text(encoding="utf-8") == "existing report"


def test_report_write_failure_returns_the_actual_saved_count(bridge, tmp_path, monkeypatch):
    api, _ = bridge
    write = files.atomic_write

    def fail_report(path, *args, **kwargs):
        if path.suffix == ".json":
            raise OSError("synthetic report failure")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(files, "atomic_write", fail_report)
    result = api.export_folder(str(tmp_path), {})
    assert not result["ok"] and result["saved"] == 1 and result["reportError"]
    assert len(list(tmp_path.glob("*.pdf"))) == 1 and not api.poll()["busy"]


def test_integrity_is_verified_once_per_session_and_rechecked_after_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path)
    checker = Mock(side_effect=[["changed model"], [], ["changed model"], ["changed model"]])
    monkeypatch.setattr(models, "verify_all", checker)
    services = Services(use_gpu=False)
    services._ready.set()
    with pytest.raises(RuntimeError, match="alterados"):
        services.require_integrity()
    services.require_integrity()          # a failed check is repeated: the repaired files unblock processing
    services.require_integrity()          # verified in this session: no further hashing per document
    assert checker.call_count == 2
    assert not services.check_integrity(force=True)   # an explicit recheck still hashes and blocks again
    with pytest.raises(RuntimeError, match="alterados"):
        services.require_integrity()


def model_item(identifier, payload, size=None):
    return models.ModelFile(identifier, f"advanced/{identifier}.bin", "https://example.invalid/model", "MIT",
                            hashlib.sha256(payload).hexdigest(), "advanced", size=size or len(payload))


def set_models(monkeypatch, tmp_path, items):
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(models, "load_manifest", lambda: {"advanced": items})


def test_failed_offline_group_preserves_installed_models(tmp_path, monkeypatch):
    items = [model_item("first", b"first"), model_item("second", b"second")]
    set_models(monkeypatch, tmp_path, items)
    for item in items:
        item.path.parent.mkdir(parents=True, exist_ok=True)
        item.path.write_bytes(b"old installation")
    pack = tmp_path / "pack.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr(items[0].file, b"first")
        archive.writestr(items[1].file, b"broken")
    with pytest.raises(RuntimeError, match="Checksum"):
        models.import_zip(pack)
    assert all(item.path.read_bytes() == b"old installation" for item in items)
    assert not list((tmp_path / "models").glob(".import-*"))


def test_corrupt_offline_zip_cleans_all_staged_bytes(tmp_path, monkeypatch):
    payload = b"x" * (2 * models.CHUNK)
    item = model_item("vlm", payload)
    set_models(monkeypatch, tmp_path, [item])
    pack = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(pack, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(item.file, payload)
    data = bytearray(pack.read_bytes())
    data[100] ^= 1
    pack.write_bytes(data)
    with pytest.raises(zipfile.BadZipFile):
        models.import_zip(pack)
    assert not item.path.exists()
    assert not list((tmp_path / "models").rglob("*.part"))
    assert not list((tmp_path / "models").glob(".import-*"))


@pytest.mark.parametrize("case", ["oversized", "duplicate", "incomplete", "disk"])
def test_offline_import_rejects_unsafe_packs_before_extraction(tmp_path, monkeypatch, case):
    item = model_item("vlm", b"good")
    items = [item, model_item("projector", b"model")] if case == "incomplete" else [item]
    set_models(monkeypatch, tmp_path, items)
    pack = tmp_path / "pack.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr(item.file, b"too large" if case == "oversized" else b"good")
        if case == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(item.file, b"good")
    if case == "disk":
        monkeypatch.setattr(models.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    extract = Mock(side_effect=AssertionError("untrusted pack was extracted"))
    monkeypatch.setattr(zipfile.ZipFile, "open", extract)
    with pytest.raises(RuntimeError):
        models.import_zip(pack)
    extract.assert_not_called()
    assert not item.path.exists()


def test_failed_group_publication_restores_previous_files(tmp_path, monkeypatch):
    items = [model_item("first", b"first"), model_item("second", b"second")]
    set_models(monkeypatch, tmp_path, items)
    root = tmp_path / "models"
    root.mkdir()
    staged = []
    for index, item in enumerate(items):
        item.path.parent.mkdir(exist_ok=True)
        item.path.write_bytes(b"old installation")
        source = root / f"stage-{index}"
        source.write_bytes(b"new installation")
        staged.append((item, source))
    replace = Path.replace

    def fail_second(source, target):
        if source == staged[1][1]:
            raise OSError("synthetic publication failure")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(OSError):
        models._publish_models(staged)
    assert all(item.path.read_bytes() == b"old installation" for item in items)
    assert not list(root.glob(".backup-*"))


def test_oversized_download_stops_without_publishing(tmp_path, monkeypatch):
    item = model_item("vlm", b"good")
    set_models(monkeypatch, tmp_path, [item])
    response = io.BytesIO(b"too large")
    response.status, response.headers = 200, {}
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="tamaño permitido"):
        models.download(item)
    assert not item.path.exists() and not item.path.with_suffix(".bin.part").exists()


def test_newly_available_untrusted_gguf_is_rejected(tmp_path, monkeypatch):
    item = model_item("vlm", b"good")
    set_models(monkeypatch, tmp_path, [item])
    item.path.parent.mkdir(parents=True)
    item.path.write_bytes(b"evil")
    with pytest.raises(RuntimeError, match="Checksum"):
        models.require_model_paths([item.path])


def test_failed_reports_do_not_disclose_original_prefixes():
    from app.engine import logs
    report = verify.Report(ok=False, leaks=[verify.Leak("texto", "página 1", "PRIVATE ORIGINAL", page=0, rects=[(1, 2, 3, 4)])])
    encoded = report.to_json()
    assert encoded["leaks"][0]["value"] == "…"
    data = json.loads(logs.build_json([], 1, encoded))
    assert "rects" not in data["verificacion"]["leaks"][0]
    assert "PRIVATE" not in json.dumps(data)


def test_large_image_streams_are_scanned_for_selected_values():
    with pikepdf.open(io.BytesIO(pdf_with_text("public text"))) as pdf:
        stream = pikepdf.Stream(pdf, b"x" * 4_100_000 + b" selected-private-canary ")
        stream.Subtype = pikepdf.Name.Image
        pdf.Root.Private = stream
        report = verify.Report()
        verify._scan_objects(pdf, [verify.Target.build("name", "selected-private-canary")], report)
    assert not report.ok and report.leaks


def test_object_depth_limit_blocks_instead_of_skipping(monkeypatch):
    monkeypatch.setattr(verify, "MAX_OBJECT_DEPTH", 3)
    with pikepdf.open(io.BytesIO(pdf_with_text("public text"))) as pdf:
        nested = pikepdf.String("private-canary")
        for _ in range(8):
            nested = pikepdf.Array([nested])
        pdf.Root.Private = nested
        with pytest.raises(verify.VerificationUnavailable, match="estructura"):
            verify._scan_objects(pdf, [], verify.Report())


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@pytest.mark.parametrize("operation", ["CreateJobObjectW", "SetInformationJobObject", "OpenProcess", "AssignProcessToJobObject"])
def test_job_configuration_errors_fail_closed(monkeypatch, operation):
    api = SimpleNamespace(**{name: Mock(return_value=1) for name in (
        "CreateJobObjectW", "SetInformationJobObject", "OpenProcess", "AssignProcessToJobObject", "TerminateJobObject", "CloseHandle")})
    getattr(api, operation).return_value = 0
    monkeypatch.setattr(worker, "_job_api", lambda: api)
    job = None
    try:
        with pytest.raises(worker.EngineError, match=operation):
            job = worker.JobObject(2048)
            job.assign(123)
    finally:
        if job is not None:
            job.close()


def test_worker_does_not_initialize_before_startup_gate(monkeypatch):
    gate = Mock()
    gate.wait.return_value = False
    connection = Mock()
    handlers = Mock(side_effect=AssertionError("engine initialized before protection"))
    monkeypatch.setattr(worker, "_handlers", handlers)
    worker.serve(connection, threading.Event(), False, False, startup_gate=gate)
    connection.close.assert_called_once()
    handlers.assert_not_called()


def test_valid_download_resumes_from_the_requested_offset(tmp_path, monkeypatch):
    item = model_item("vlm", b"abcdef")
    set_models(monkeypatch, tmp_path, [item])
    item.path.parent.mkdir(parents=True)
    item.path.with_suffix(".bin.part").write_bytes(b"ab")
    response = io.BytesIO(b"cdef")
    response.status = 206
    response.headers = {"Content-Length": "4", "Content-Range": "bytes 2-5/6"}
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *args, **kwargs: response)
    assert models.download(item).read_bytes() == b"abcdef"


def test_failed_rollback_preserves_the_backup_for_recovery(tmp_path, monkeypatch):
    item = model_item("vlm", b"good")
    set_models(monkeypatch, tmp_path, [item])
    item.path.parent.mkdir(parents=True)
    item.path.write_bytes(b"old installation")
    staged = tmp_path / "stage"
    staged.write_bytes(b"good")
    replace = Path.replace

    def fail_after_backup(source, target):
        if source == item.path:
            return replace(source, target)
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(Path, "replace", fail_after_backup)
    with pytest.raises(RuntimeError, match="copia de seguridad"):
        models._publish_models([(item, staged)])
    backups = list((tmp_path / "models").glob(".backup-*/0"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old installation"


def test_little_endian_private_names_are_verified():
    with pikepdf.open(io.BytesIO(pdf_with_text("public text"))) as pdf:
        pdf.Root.Private = pikepdf.Stream(pdf, "private canary".encode("utf-16-le"))
        report = verify.Report()
        verify._scan_objects(pdf, [verify.Target.build("name", "private canary")], report)
    assert not report.ok


def test_stream_size_limit_blocks_instead_of_skipping(monkeypatch):
    monkeypatch.setattr(verify, "MAX_STREAM_BYTES", 1024)
    with pikepdf.open(io.BytesIO(pdf_with_text("public text"))) as pdf:
        pdf.Root.Private = pikepdf.Stream(pdf, b"x" * 2048)
        with pytest.raises(verify.VerificationUnavailable, match="flujo"):
            verify._scan_objects(pdf, [], verify.Report())


def test_failed_assignment_cleans_the_blocked_worker(monkeypatch):
    monkeypatch.setattr(worker.JobObject, "assign", Mock(side_effect=worker.EngineError("synthetic assignment failure")))
    engine = worker.EngineProcess(with_models=False)
    try:
        with pytest.raises(worker.EngineError, match="protección"):
            engine.call("ping")
        assert not engine.alive() and engine._conn is None and engine._job is None
    finally:
        engine.stop()


@pytest.mark.parametrize("environment_cpu", [False, True])
def test_advanced_ai_honors_explicit_cpu_selection(tmp_path, monkeypatch, environment_cpu):
    from app.engine import llm_server
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"synthetic model")
    monkeypatch.setenv("ANONIMATO_CPU", "1" if environment_cpu else "0")
    monkeypatch.setattr(models, "require_model_paths", lambda paths: None)
    monkeypatch.setattr(models, "verify_runtime", lambda: [])
    monkeypatch.setattr(llm_server, "_exe", lambda: "synthetic-server")
    picker = Mock(side_effect=AssertionError("GPU was enumerated in CPU mode"))
    monkeypatch.setattr(llm_server, "pick_device", picker)
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(llm_server.subprocess, "Popen", launch)
    response = io.BytesIO()
    response.status = 200
    monkeypatch.setattr(llm_server._LOCAL_HTTP, "open", lambda *args, **kwargs: response)
    server = llm_server.LlamaServer(str(model_path), None, use_gpu=environment_cpu)
    try:
        server.start()
        args = launch.call_args.args[0]
        assert args[args.index("--device") + 1] == "none"
        picker.assert_not_called()
    finally:
        server.stop()


@pytest.mark.parametrize("enabled", [False, True])
def test_handwriting_verifier_is_loaded_only_when_needed(monkeypatch, enabled):
    services = Mock()
    services.advanced_available.return_value = True
    captured = {}

    def scan(doc, findings, targets, ocr, faces, reader, report, progress):
        captured["reader"] = reader
        return {}

    monkeypatch.setattr(verify, "_scan_pixel_pages", scan)
    finding = SimpleNamespace(enabled=enabled, source="handwriting", value="synthetic canary", type="name")
    verify._scan_pixels(pdf_with_text("public text"), [finding], [], services, verify.Report())
    assert (captured["reader"] is not None) == enabled
    assert services.llm.call_count == int(enabled)
    assert services.advanced_available.call_count == int(enabled)


@pytest.mark.parametrize("available", [False, True])
def test_missing_handwriting_verifier_blocks_export(available):
    services = Mock()
    services.advanced_available.return_value = available
    services.llm.return_value = None
    finding = SimpleNamespace(enabled=True, source="handwriting", value="synthetic canary", type="name")
    with pytest.raises(verify.VerificationUnavailable, match="manuscritos"):
        verify._scan_pixels(pdf_with_text("public text"), [finding], [], services, verify.Report())


@pytest.mark.parametrize("damaged", [False, True])
def test_runtime_extraction_preserves_verified_installations(tmp_path, monkeypatch, damaged):
    root = tmp_path / "runtime"
    (root / "llama").mkdir(parents=True)
    library = root / "llama" / "synthetic.dll"
    library.write_bytes(b"installed runtime")
    archive_path = root / ".." / "runtime" / "runtime.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("llama/synthetic.dll", b"repaired runtime")
    monkeypatch.setattr(models, "runtime_dir", lambda: root)
    monkeypatch.setattr(models, "verify_runtime", lambda: ["damaged"] if damaged else [])
    models.extract_runtime(archive_path, preserve_verified=True)
    assert library.read_bytes() == (b"repaired runtime" if damaged else b"installed runtime")
