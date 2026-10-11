"""Regression tests for fail-closed verification, integrity, resource limits and safe exports."""
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.api import Api, Doc, _options
from app.engine import document, files, llm_server, logs, models, pipeline, rasterize, verify
from app.engine.services import Services
from app.engine.types import Finding, Options
from app.engine.worker import EngineError


def pdf_with_text(text="Ana"):
    with pymupdf.open() as pdf:
        pdf.new_page(width=300, height=150).insert_text((40, 70), text)
        return pdf.tobytes()


class NoEngine:
    gpu_disabled = ""

    def __init__(self):
        self.cancel = threading.Event()

    def ensure_started(self):
        pass

    def call(self, *args, **kwargs):
        return {"base": True, "errors": {}}

    def stop(self):
        pass


@pytest.fixture
def api():
    bridge = Api(engine=NoEngine(), light=NoEngine())
    yield bridge
    bridge.shutdown()


class MissingServices:
    def ocr(self):
        return None

    def faces(self):
        return None

    def advanced_available(self):
        return False


def test_scanned_value_cannot_pass_without_ocr():
    image = Image.new("RGB", (400, 100), "white")
    ImageDraw.Draw(image).text((10, 20), "12345678Z", fill="black", font_size=32)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    with pymupdf.open() as pdf:
        pdf.new_page(width=300, height=150).insert_image((0, 0, 300, 150), stream=buffer.getvalue())
        finding = Finding("f", 0, "dni", "12345678Z", [(10, 20, 290, 90)], 1, "ocr")
        with pytest.raises(verify.VerificationUnavailable, match="OCR"):
            verify.verify(pdf.tobytes(), [finding], services=MissingServices())


def test_selected_face_requires_a_face_verifier():
    services = MissingServices()
    services.ocr = lambda: SimpleNamespace(read=lambda image: [])
    finding = Finding("f", 0, "face", None, [(40, 40, 80, 90)], 1, "face")
    with pytest.raises(verify.VerificationUnavailable, match="rostros"):
        verify.verify(pdf_with_text(), [finding], services=services)


def test_installed_but_unavailable_handwriting_verifier_blocks_export():
    services = MissingServices()
    services.ocr = lambda: SimpleNamespace(read=lambda *args, **kwargs: [])
    services.advanced_available = lambda: True
    services.llm = lambda: None
    finding = Finding("f", 0, "name", "Ana", [(40, 50, 100, 80)], 1, "handwriting")
    with pytest.raises(verify.VerificationUnavailable, match="manuscritos"):
        verify.verify(pdf_with_text("public text"), [finding], services=services)


def test_handwriting_verification_failure_is_not_silently_ignored(monkeypatch):
    from app.engine.ocr.handwriting import HandwritingReader
    services = MissingServices()
    services.ocr = lambda: SimpleNamespace(read=lambda *args, **kwargs: [])
    services.advanced_available = lambda: True
    services.llm = object
    monkeypatch.setattr(HandwritingReader, "read", Mock(side_effect=RuntimeError("unavailable")))
    finding = Finding("f", 0, "name", "Ana", [(40, 50, 100, 80)], 1, "handwriting")
    with pytest.raises(verify.VerificationUnavailable, match="manuscrito"):
        verify.verify(pdf_with_text("public text"), [finding], services=services)


@pytest.mark.parametrize("redirect", [False, True])
def test_local_ai_never_uses_proxies_or_follows_redirects(monkeypatch, redirect):
    import http.server
    import urllib.error
    import urllib.request

    destination_requests, proxy_requests = [], []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            proxy_requests.append(self.path)
            self.send_error(500)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy:
        class Destination(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                destination_requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{proxy.server_port}/outside")
                    self.end_headers()
                else:
                    data = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            def log_message(self, *args):
                pass

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Destination) as destination:
            workers = [threading.Thread(target=server.serve_forever, daemon=True) for server in (proxy, destination)]
            for worker in workers:
                worker.start()
            monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
            monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
            monkeypatch.setenv("no_proxy", "")
            monkeypatch.setenv("NO_PROXY", "")
            monkeypatch.setattr(urllib.request, "_opener", None)
            server = llm_server.LlamaServer("unused", None)
            server.port, server.key = destination.server_port, "test-session"
            monkeypatch.setattr(server, "start", lambda: None)
            try:
                messages = [{"role": "user", "content": "private-document-canary"}]
                if redirect:
                    with pytest.raises(urllib.error.HTTPError) as error:
                        server.chat(messages)
                    assert error.value.code == 302
                else:
                    assert server.chat(messages) == "ok"
                assert destination_requests[0]["messages"] == messages
                assert proxy_requests == []
            finally:
                destination.shutdown()
                proxy.shutdown()
                for worker in workers:
                    worker.join(5)


@pytest.mark.parametrize("value", ["Ana", "Li", "X"])
def test_short_selected_names_are_verified(value):
    finding = Finding("f", 0, "name", value, [(40, 50, 100, 80)], 1, "ai")
    report = verify.verify(pdf_with_text(value), [finding])
    assert not report.ok and report.values == 1
    assert any(leak.check == "texto" for leak in report.leaks)
    assert not verify.Target.build("name", value).found_in(f"prefix{value}suffix")


def test_short_identifiers_keep_separator_normalization():
    finding = Finding("f", 0, "id_other", "1/2", [(40, 50, 100, 80)], 1, "text")
    report = verify.verify(pdf_with_text("1 / 2"), [finding])
    assert not report.ok and report.values == 1
    assert not verify.Target.build("id_other", "1/2").found_in("A1/2B")


def test_short_values_in_private_streams_are_verified():
    import pikepdf
    with pikepdf.open(io.BytesIO(pdf_with_text("public text"))) as pdf:
        pdf.Root.Private = pikepdf.Stream(pdf, b"copy of Ana")
        output = io.BytesIO()
        pdf.save(output)
    finding = Finding("f", 0, "name", "Ana", [(40, 50, 100, 80)], 1, "text")
    report = verify.verify(output.getvalue(), [finding])
    assert not report.ok
    assert any(leak.check == "objetos" and leak.value == "Ana" for leak in report.leaks)


def test_integrity_exception_blocks_processing_and_warmup(monkeypatch):
    services = Services(use_gpu=False)
    monkeypatch.setattr(models, "verify_all", Mock(side_effect=ValueError("unreadable manifest")))
    assert not services.check_integrity()
    with pytest.raises(RuntimeError, match="integridad"):
        services.require_integrity()
    loader = Mock()
    monkeypatch.setattr(services, "ocr", loader)
    services.warm_up()
    assert services._ready.wait(5)
    loader.assert_not_called()


def test_integrity_rejects_same_size_same_timestamp_tampering(tmp_path, monkeypatch):
    target = tmp_path / "base" / "model.bin"
    target.parent.mkdir()
    target.write_bytes(b"good")
    item = models.ModelFile("test", "base/model.bin", "https://example.invalid/model", "MIT",
                            hashlib.sha256(b"good").hexdigest(), "base")
    monkeypatch.setattr(models, "bundled_models_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "load_manifest", lambda: {"base": [item]})
    monkeypatch.setattr(models, "verify_runtime", lambda: [])
    assert models.verify_all() == []
    previous = target.stat()
    target.write_bytes(b"evil")
    os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert models.verify_all() == ["test"]


def test_untrusted_runtime_is_never_executed(monkeypatch):
    monkeypatch.setattr(models, "verify_runtime", lambda: ["runtime/llama/llama-server"])
    run = Mock()
    monkeypatch.setattr(llm_server.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="alterado"):
        llm_server.pick_device("llama-server")
    run.assert_not_called()


def test_partial_runtime_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "llama").mkdir()
    monkeypatch.setattr(models, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "_runtime_files", lambda: {"llama/llama-server": "0" * 64})
    assert any("no encontrado" in item for item in models.verify_runtime())


def test_runtime_without_hashes_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "llama").mkdir()
    monkeypatch.setattr(models, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(models, "_runtime_files", lambda: {})
    assert models.verify_runtime()


def test_empty_model_group_is_not_installed(monkeypatch):
    monkeypatch.setattr(models, "load_manifest", lambda: {"advanced": []})
    assert not models.group_installed("advanced")
    assert not models.group_installed("advanced_lite")


def test_cached_runtime_archive_repairs_missing_extracted_files(tmp_path, monkeypatch):
    import zipfile
    archive = tmp_path / "runtime" / "archive.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("llama-server", b"trusted runtime")
    item = models.ModelFile("runtime", "runtime/archive.zip", "https://example.invalid/runtime", "MIT",
                            models.sha256_of(archive), "runtime", unzip=True)
    monkeypatch.setattr(models, "bundled_models_dir", lambda: tmp_path)
    monkeypatch.setattr(models.urllib.request, "urlopen", Mock(side_effect=AssertionError("unexpected download")))
    models.download(item)
    assert (archive.parent / "llama-server").read_bytes() == b"trusted runtime"


def test_input_size_is_checked_before_read(api, monkeypatch):
    path = Mock(spec=Path)
    path.suffix = ".pdf"
    path.stat.return_value = SimpleNamespace(st_size=11)
    monkeypatch.setitem(document.LIMITS, "max_bytes", 10)
    with pytest.raises(document.DocumentError, match="supera"):
        api._add_path(path)
    path.open.assert_not_called()


def test_queue_limit_is_enforced_and_released(api, tmp_path, monkeypatch):
    monkeypatch.setitem(document.LIMITS, "max_queue_bytes", 4)
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"123")
    second.write_bytes(b"456")
    added = api._add_path(first)
    with pytest.raises(document.DocumentError, match="cola"):
        api._add_path(second)
    assert api.remove(added["id"])
    assert api._add_path(second)["size"] == 3


def test_unlock_cannot_exceed_the_queue_budget(api, monkeypatch):
    monkeypatch.setitem(document.LIMITS, "max_queue_bytes", 5)
    original = b"locked"
    doc = Doc("d1", "locked.pdf", len(original), original, status="locked")
    api._state.docs[doc.id] = doc
    monkeypatch.setattr(api._light, "call", lambda *args: b"unlocked")
    assert not api.unlock(doc.id, "password")["ok"]
    assert doc.data == original and doc.status == "locked"


def test_growing_input_is_read_with_a_bound(api, monkeypatch):
    monkeypatch.setitem(document.LIMITS, "max_bytes", 8)
    path = Mock(spec=Path)
    path.suffix = ".pdf"
    path.stat.return_value = SimpleNamespace(st_size=1)
    handle = Mock()
    handle.read.return_value = b"123456789"
    path.open.return_value.__enter__ = Mock(return_value=handle)
    path.open.return_value.__exit__ = Mock(return_value=False)
    with pytest.raises(document.DocumentError, match="límite"):
        api._add_path(path)
    handle.read.assert_called_once_with(9)
    assert api.documents() == []


def test_multipage_images_obey_page_limit(monkeypatch):
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (30, 30), color) for color in ("white", "red", "blue")]
    frames[0].save(buffer, "TIFF", save_all=True, append_images=frames[1:])
    monkeypatch.setitem(document.LIMITS, "max_pages", 2)
    with pytest.raises(document.DocumentError, match="páginas"):
        document.load_bytes(buffer.getvalue(), "many.tiff")


def test_image_pixel_limit_precedes_conversion(monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40)).save(buffer, "PNG")
    monkeypatch.setitem(document.LIMITS, "max_page_pixels", 1000)
    conversion = Mock()
    monkeypatch.setattr(document, "correct_perspective", conversion)
    with pytest.raises(document.DocumentError, match="píxeles"):
        document.load_bytes(buffer.getvalue(), "large.png")
    conversion.assert_not_called()


def test_max_security_rasterization_obeys_pixel_limit(monkeypatch):
    monkeypatch.setitem(document.LIMITS, "max_page_pixels", 4000)
    output = rasterize.rasterize(pdf_with_text(), dpi=300)
    with pymupdf.open("pdf", output) as pdf:
        images = pdf[0].get_image_info()
        assert images and images[0]["width"] * images[0]["height"] <= 4000


def test_empty_categories_remain_empty():
    assert _options({"categories": []}).categories == {"manual"}


@pytest.mark.parametrize("dpi", ["invalid", True, -1, 1201, 50.5, float("nan"), float("inf")])
def test_invalid_options_do_not_lock_the_api(api, dpi):
    with pytest.raises(ValueError):
        api.process({"dpi": dpi})
    assert not api.poll()["busy"]


def test_thread_start_failure_restores_api_state(api, monkeypatch):
    monkeypatch.setattr(api, "status", lambda: {"blocked": False})
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("thread unavailable")))
    with pytest.raises(RuntimeError, match="unavailable"):
        api.process({})
    assert not api.poll()["busy"]


def test_finding_changes_invalidate_export_reports(api):
    options = Options(categories={"manual"}, ai=False, ocr=False, faces=False, signatures=False,
                      handwriting=False, llm_review=False)
    analysis = pipeline.analyze(pdf_with_text(), "x.pdf", options)
    doc = Doc("d1", "x.pdf", 1, b"", status="ready", analysis=analysis)
    api._state.docs[doc.id] = doc
    manual = api.add_manual(doc.id, 0, [0.1, 0.1, 0.2, 0.2])
    doc.report = {"ok": True}
    api.set_enabled(doc.id, [manual["id"]], False)
    assert doc.report is None
    doc.report = {"ok": True}
    api.remove_manual(doc.id, manual["id"])
    assert doc.report is None
    doc.report = {"ok": True}
    api.add_manual(doc.id, 0, [0.1, 0.1, 0.2, 0.2])
    assert doc.report is None
    doc.report = {"ok": True}
    api.invalidate_report(doc.id)
    assert doc.report is None


def test_export_snapshot_does_not_restore_an_obsolete_report(api, monkeypatch):
    options = Options(categories={"manual"}, ocr=False, ai=False, faces=False, signatures=False,
                      handwriting=False, llm_review=False)
    analysis = pipeline.analyze(pdf_with_text(), "x.pdf", options)
    finding = pipeline.add_manual(analysis, 0, (40, 50, 100, 80))
    doc = Doc("d1", "x.pdf", 1, b"", status="ready", analysis=analysis)
    api._state.docs[doc.id] = doc

    def export_call(operation, snapshot, *args, **kwargs):
        api.set_enabled(doc.id, [finding.id], False)
        assert snapshot.findings[0].enabled and not analysis.findings[0].enabled
        assert snapshot.sources == {}
        return pipeline.ExportResult(b"verified", verify.Report(), "export.pdf", 0)

    monkeypatch.setattr(api._engine, "call", export_call)
    with pytest.raises(EngineError, match="cambió"):
        api._export(doc, options, 1, False)
    assert doc.report is None


def test_failed_atomic_publication_preserves_destination(tmp_path, monkeypatch):
    target = tmp_path / "export.pdf"
    target.write_bytes(b"original")
    monkeypatch.setattr(files.os, "replace", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError):
        files.atomic_write(target, b"replacement")
    assert target.read_bytes() == b"original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["export.pdf"]


def test_atomic_publication_does_not_overwrite_colliding_exports(tmp_path):
    target = tmp_path / "export.pdf"
    files.atomic_write(target, b"first", overwrite=False)
    with pytest.raises(FileExistsError):
        files.atomic_write(target, b"second", overwrite=False)
    assert target.read_bytes() == b"first"
    assert len(list(tmp_path.iterdir())) == 1


def test_logs_include_all_variants_and_obey_coordinate_privacy():
    findings = [Finding(str(index), 0, "name", value, [(1, 2, 3, 4)], 1, "text", token="[NOMBRE 1]")
                for index, value in enumerate(("Ana García", "Ana", "García"))]
    report = {"ok": False, "leaks": [{"rects": [[1, 2, 3, 4]], "view": [[0.1, 0.2, 0.3, 0.4]]}]}
    output = json.loads(logs.build_json(findings, 1, report, include_originals=True))
    assert output["mapeo"][0]["originales"] == ["Ana", "Ana García", "García"]
    assert output["verificacion"]["leaks"] == [{}]
    assert "view" in report["leaks"][0]  # serialization must not mutate the active report


@pytest.mark.parametrize("value", [" =SUM(1,2)", "\n=HYPERLINK(\"x\")", "\t@cmd", "\r+1"])
def test_csv_formulas_are_escaped_after_leading_whitespace(value):
    import csv
    finding = Finding("f", 0, "name", value, [], 1, "text", token="[NOMBRE 1]")
    output = logs.build_csv([finding], include_originals=True).lstrip("\ufeff")
    rows = list(csv.reader(io.StringIO(output)))
    assert rows[1][4] == "'" + value


def test_build_tool_checksum_failure_prevents_publication(tmp_path, monkeypatch):
    from tools import fetch_build_tool
    manifest = tmp_path / "packaging"
    manifest.mkdir()
    (manifest / "build-tools.json").write_text(json.dumps({"test": {"url": "https://example.invalid/tool",
                                                                  "sha256": "0" * 64}}))
    monkeypatch.setattr(fetch_build_tool, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_build_tool.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"untrusted"))
    target = tmp_path / "tool"
    with pytest.raises(RuntimeError, match="SHA-256"):
        fetch_build_tool.fetch("test", target)
    assert not target.exists()
    assert not list(tmp_path.glob(".build-tool-*"))
