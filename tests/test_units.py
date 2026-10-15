"""Unit tests for the paths the end-to-end tests do not exercise deterministically:
metadata stripping, runtime extraction, downloads, integrity, services, the LLM review and
handwriting readers (with fake servers), logs, pipeline heuristics (propagation, small images,
doubtful handwriting, failures of optional models), file names, documents, API and window glue."""
import hashlib
import http.server
import io
import json
import socketserver
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from app.engine import document, logs, models, pipeline, rules, sanitize, verify
from app.engine.types import Finding, OcrLine, Options, PageText
from tests.fixtures.generate import DNI, NAME


# ------------------------------------------------------------------ JPEG metadata
def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def test_jpeg_metadata_segments_are_removed_losslessly():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "JPEG")
    jpeg = buffer.getvalue()
    app1 = _segment(0xE1, b"Exif\x00\x00" + NAME.encode())
    iptc = _segment(0xED, b"Photoshop 3.0\x00" + DNI.encode())
    comment = _segment(0xFE, NAME.encode())
    icc = _segment(0xE2, b"ICC_PROFILE\x00profile")
    xmp_in_app2 = _segment(0xE2, b"NOT_ICC" + NAME.encode())
    adobe = _segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
    dirty = jpeg[:2] + app1 + iptc + comment + icc + xmp_in_app2 + adobe + jpeg[2:]
    clean = sanitize.strip_jpeg_metadata(dirty)
    assert NAME.encode() not in clean and DNI.encode() not in clean
    assert b"ICC_PROFILE" in clean and b"Adobe" in clean              # colour information is kept
    assert clean.endswith(jpeg[-200:])                                  # entropy-coded data untouched
    Image.open(io.BytesIO(clean)).load()                                # still a valid JPEG
    assert sanitize.strip_jpeg_metadata(b"not a jpeg") == b"not a jpeg"


def test_marked_content_properties_are_cleaned():
    import pikepdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "texto", fontsize=11)
    pdf = pikepdf.open(io.BytesIO(doc.tobytes()))
    page = pdf.pages[0]
    page.Resources.Properties = pikepdf.Dictionary(MC0=pikepdf.Dictionary(ActualText=pikepdf.String(NAME)))
    page.contents_add(pikepdf.Stream(pdf, b"/Span <</ActualText (" + DNI.encode() + b")>> BDC\n"), prepend=True)
    page.contents_add(pikepdf.Stream(pdf, b"\nEMC\n"))
    out = io.BytesIO()
    pdf.save(out)
    cleaned = sanitize.sanitize(out.getvalue())
    report = verify.verify(cleaned, [Finding("a", 0, "name", NAME, [(0, 0, 1, 1)], 1, "text"),
                                     Finding("b", 0, "dni", DNI, [(0, 0, 1, 1)], 1, "text")])
    assert report.ok, report.to_json()


# ------------------------------------------------------------------ runtime archives and downloads
def test_extract_runtime_tar_strips_top_folder_and_keeps_links(tmp_path):
    archive = tmp_path / "llama.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"\x7fELF fake library"
        info = tarfile.TarInfo("llama-b1/libllama.so.0.5.0")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("llama-b1/libllama.so.0")
        link.type = tarfile.SYMTYPE
        link.linkname = "libllama.so.0.5.0"
        tar.addfile(link)
        exe = tarfile.TarInfo("llama-b1/llama-server")
        exe.size = 4
        exe.mode = 0o755
        tar.addfile(exe, io.BytesIO(b"exe!"))
    models.extract_runtime(archive)
    assert (tmp_path / "libllama.so.0.5.0").read_bytes() == data
    assert (tmp_path / "llama-server").read_bytes() == b"exe!"
    assert (tmp_path / "libllama.so.0").exists() or (tmp_path / "libllama.so.0").is_symlink()
    zipped = tmp_path / "w.zip"
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("llama-server.exe", b"MZ")
    models.extract_runtime(zipped)
    assert (tmp_path / "llama-server.exe").read_bytes() == b"MZ"


def test_platform_filter_of_runtime_entries():
    from app.engine.system import SYSTEM
    runtime = models.load_manifest()["runtime"]
    chosen = models.for_this_platform(runtime)
    assert len(chosen) == 1 and chosen[0].platform == SYSTEM
    assert {item.platform for item in runtime} == {"windows", "macos", "linux"}


@pytest.fixture
def file_server(tmp_path):
    served = tmp_path / "served"
    served.mkdir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield served, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_first_launch_downloads_only_the_missing_required_models(tmp_path, file_server, monkeypatch):
    served, base = file_server
    payloads = {"a": b"modelo a" * 500, "b": b"modelo b" * 700}
    for name, data in payloads.items():
        (served / f"{name}.bin").write_bytes(data)
    items = [models.ModelFile(id=name, file=f"base/{name}.bin", url=f"{base}/{name}.bin", license="MIT",
                              sha256=hashlib.sha256(data).hexdigest(), group="base", size=len(data))
             for name, data in payloads.items()]
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(models, "load_manifest", lambda: {"base": items, "runtime": []})
    items[0].path.parent.mkdir(parents=True)
    items[0].path.write_bytes(payloads["a"])
    assert [item.id for item in models.required_missing()] == ["b"]
    seen = []
    models.install_required(lambda model_id, done, total: seen.append(model_id))
    assert models.required_missing() == [] and set(seen) == {"b"}
    assert items[1].path.read_bytes() == payloads["b"]


def test_download_restarts_when_the_server_ignores_ranges(tmp_path, file_server, monkeypatch):
    served, base = file_server
    payload = b"0123456789" * 3000
    (served / "m.bin").write_bytes(payload)
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path / "user")
    item = models.ModelFile(id="m", file="advanced/m.bin", url=f"{base}/m.bin", license="MIT",
                            sha256=hashlib.sha256(payload).hexdigest(), group="advanced")
    item.path.parent.mkdir(parents=True)
    Path(str(item.path) + ".part").write_bytes(b"garbage from an interrupted download")
    seen = []
    models.download(item, lambda _id, done, total: seen.append((done, total)))
    assert item.path.read_bytes() == payload and seen[-1][0] == len(payload)
    assert models.download(item) == item.path  # already present and valid: no new download


def test_integrity_rehashes_models_instead_of_trusting_disk_metadata(tmp_path, monkeypatch):
    target = tmp_path / "bundle" / "models" / "base" / "m.onnx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model")
    digest = hashlib.sha256(b"model").hexdigest()
    manifest = {"base": [{"id": "m", "file": "base/m.onnx", "url": "https://x/m", "license": "MIT", "sha256": digest}]}
    (tmp_path / "bundle" / "models" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(models, "bundled_models_dir", lambda: tmp_path / "bundle" / "models")
    monkeypatch.setattr(models, "runtime_dir", lambda: tmp_path / "runtime")
    assert models.verify_all(force=True) == []
    calls = []
    original = models.sha256_of
    monkeypatch.setattr(models, "sha256_of", lambda p: calls.append(p) or original(p))
    assert models.verify_all() == [] and calls == [target]  # every explicit check hashes the content
    time.sleep(0.01)
    target.write_bytes(b"MODEL")                        # same size, new content and mtime
    assert models.verify_all() == ["m"]


# ------------------------------------------------------------------ services
def test_services_retry_base_engines_after_the_first_launch_download():
    from app.engine.services import Services
    services = Services(use_gpu=False)
    attempts = []

    def missing():
        attempts.append(1)
        raise FileNotFoundError("pii/model.onnx")

    assert services._load("pii", missing) is None and services._load("pii", missing) is None
    assert len(attempts) == 1 and "pii" in services.errors  # a failed load is not retried by itself
    loaded = services._load("faces", lambda: "faces")
    services.reset_base()  # the download finished
    assert "pii" not in services.errors and services._load("pii", lambda: "pii") == "pii"
    assert services._faces is loaded  # engines that did load are kept


def test_services_integrity_gate_and_warmup_timeout(monkeypatch):
    from app.engine.services import Services, WarmupTimeout
    services = Services(use_gpu=False)
    monkeypatch.setattr(models, "verify_all", lambda force=False: ["m"])
    assert not services.check_integrity()
    with pytest.raises(RuntimeError, match="alterados"):
        services.require_integrity()
    monkeypatch.setattr(models, "verify_all", lambda force=False: [])
    assert services.check_integrity() and "integrity" not in services.errors
    services._ready.clear()                              # a warm-up that never finishes
    with pytest.raises(WarmupTimeout):
        services.require_integrity(timeout=5)


def test_services_release_idle_llm():
    from app.engine.services import Services

    class FakeLlm:
        stopped = False
        last_used = 0.0

        def running(self):
            return not self.stopped

        def stop(self):
            self.stopped = True

    services = Services(use_gpu=False)
    services._llm = FakeLlm()
    services.release_llm_if_idle(0)
    assert services._llm.stopped
    services.reset_advanced()
    assert services._llm is None


# ------------------------------------------------------------------ LLM review and handwriting (fake servers)
class FakeServer:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def chat(self, messages, max_tokens=512, json_mode=False):
        self.requests.append((messages, json_mode))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_llm_review_only_accepts_literal_fragments():
    from app.engine import llm_review
    text = "La menor, hija del alcalde de Lalín, sufre ansiedad. Contacto: Juan García Pérez."
    known = [(text.index("Juan"), text.index("Juan") + len("Juan García Pérez"), "NOMBRE")]
    answer = json.dumps({"datos": [
        {"texto": "hija del alcalde de Lalín", "tipo": "otro"},
        {"texto": "ansiedad", "tipo": "salud"},
        {"texto": "Pedro Inventado Ruiz", "tipo": "nombre"},        # hallucinated: not in the text
        {"texto": "Juan García Pérez", "tipo": "nombre"},          # already known
        {"texto": "[NOMBRE 1]", "tipo": "nombre"},                  # a token
        "cadena suelta",
    ]})
    server = FakeServer([answer])
    found = llm_review.review(server, text, known)
    values = {m.value: m.type for m in found}
    assert values == {"hija del alcalde de Lalín": "other", "ansiedad": "health"}
    sent = server.requests[0][0][0]["content"]
    assert "Juan García Pérez" not in sent and "[NOMBRE]" in sent and server.requests[0][1]
    assert llm_review.review(FakeServer(["esto no es JSON"]), text, []) == []
    with pytest.raises(RuntimeError, match="caído"):  # the pipeline notes why the review is missing
        llm_review.review(FakeServer([RuntimeError("caído")]), text, [])


def test_handwriting_reader_pads_small_crops_and_cleans_output():
    from app.engine.ocr.handwriting import HandwritingReader
    server = FakeServer(['  "Juan   García"  '])
    text = HandwritingReader(server).read(np.full((12, 80, 3), 255, dtype=np.uint8))
    assert text == "Juan García"
    image_part = server.requests[0][0][0]["content"][0]["image_url"]["url"]
    decoded = Image.open(io.BytesIO(__import__("base64").b64decode(image_part.split(",", 1)[1])))
    assert decoded.size[1] >= 64


def test_llm_server_device_selection(monkeypatch):
    from app.engine import llm_server

    monkeypatch.setattr(models, "verify_runtime", lambda: [])

    class Result:
        stdout = ("Available devices:\n  Vulkan0: Intel(R) UHD Graphics (16299 MiB, 15531 MiB free)\n"
                  "  Vulkan1: NVIDIA GeForce RTX 2070 (8220 MiB, 7434 MiB free)\n")

    monkeypatch.setattr(llm_server.subprocess, "run", lambda *a, **k: Result())
    assert llm_server.pick_device("llama-server") == ("Vulkan1", 7434)

    def boom(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(llm_server.subprocess, "run", boom)
    assert llm_server.pick_device("llama-server") == (None, 0)


# ------------------------------------------------------------------ logs
def test_logs_escape_formulas_and_respect_privacy_options():
    findings = [Finding("a", 0, "name", "=HYPERLINK(\"x\")", [(1, 2, 3, 4)], 0.9, "text", token="[NOMBRE 1]"),
                Finding("b", 0, "dni", DNI, [(5, 6, 7, 8)], 1.0, "text", token="[DNI 1]"),
                Finding("c", 0, "dni", "00000000T", [(5, 6, 7, 8)], 1.0, "text", token="[DNI 2]", enabled=False)]
    private = logs.build_csv(findings)
    assert DNI not in private and "00000000T" not in private and "x0" not in private
    full = logs.build_csv(findings, include_originals=True, include_coords=True)
    assert "'=HYPERLINK" in full and DNI in full and "x0" in full and "[DNI 2]" not in full
    data = json.loads(logs.build_json(findings, 1, {"ok": True}, include_originals=True, include_coords=True))
    assert data["resumen"]["sustituciones"] == 2 and data["sustituciones"][1]["original"] == DNI
    assert "rect" in data["sustituciones"][0] and data["verificacion"] == {"ok": True}
    assert "original" not in json.loads(logs.build_json(findings, 1, None))["sustituciones"][0]


# ------------------------------------------------------------------ pipeline heuristics
RULES_ONLY = Options(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF, ocr=False, ai=False, faces=False,
                     signatures=False, handwriting=False, llm_review=False)


def _pdf(*lines):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + 22 * i), line, fontsize=11)
    return doc.tobytes()


def test_propagation_finds_unlabelled_repeats_and_variants():
    data = _pdf("Paciente: Xabier Etxeberria Goikoetxea", "Visto en consulta, X. Etxeberria Goikoetxea refiere dolor.",
                "El Sr. Goikoetxea no acude.", "DNI 12345678Z. Se remite copia a 12.345.678-Z.")
    analysis = pipeline.analyze(data, "p.pdf", RULES_ONLY, None)
    propagated = [f for f in analysis.findings if f.source == "propagation"]
    texts = " | ".join(f.value for f in propagated)
    assert "X. Etxeberria Goikoetxea" in texts and "Goikoetxea" in texts
    tokens = {f.token for f in analysis.findings if f.type == "name"}
    assert tokens == {"[NOMBRE 1]"}                                 # every mention shares the token
    dni_tokens = {f.token for f in analysis.findings if f.type == "dni"}
    assert dni_tokens == {"[DNI 1]"}
    result = pipeline.export(analysis, RULES_ONLY, None, verify_pixels=False)
    text = pymupdf.open("pdf", result.data)[0].get_text()
    assert "Goikoetxea" not in text and "12345678" not in text and "345.678" not in text


class StubOcr:
    """Page-level OCR sees nothing; the zoomed re-read of small images reads a DNI."""

    def __init__(self, page_lines=(), small_lines=()):
        self.page_lines, self.small_lines, self.calls = list(page_lines), list(small_lines), []

    def read(self, rgb, detect_orientation=True):
        self.calls.append(detect_orientation)
        lines = self.page_lines if detect_orientation else self.small_lines
        return [OcrLine(**vars(line)) for line in lines]



class StubServices:
    def __init__(self, ocr=None, pii=None):
        self._ocr, self._pii, self.errors = ocr, pii, {}

    def ocr(self):
        return self._ocr

    def pii(self):
        return self._pii

    def faces(self):
        return None

    def llm(self):
        return None

    def advanced_available(self):
        return False


def _page_with_small_image():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Informe", fontsize=11)
    buffer = io.BytesIO()
    Image.new("RGB", (200, 50), (240, 240, 240)).save(buffer, "PNG")
    page.insert_image(pymupdf.Rect(72, 300, 272, 350), stream=buffer.getvalue())
    return doc.tobytes()


def test_small_images_are_re_read_at_higher_resolution():
    text = f"DNI {DNI}"
    line = OcrLine(text=text, rect=(10, 10, 600, 60), confidence=0.99,
                   char_rects=[(10 + i * 20, 10, 30 + i * 20, 60) for i in range(len(text))])
    ocr = StubOcr(page_lines=[], small_lines=[line])
    options = Options(categories=set(rules.SELECTABLE), ocr=True, ai=False, faces=False, signatures=False,
                      handwriting=False, llm_review=False)
    analysis = pipeline.analyze(_page_with_small_image(), "s.pdf", options, StubServices(ocr=ocr))
    dni = [f for f in analysis.findings if f.type == "dni"]
    assert dni and dni[0].source == "ocr" and False in ocr.calls
    x0, y0, x1, y1 = dni[0].rects[0]
    assert 72 <= x0 <= x1 <= 273 and 300 <= y0 <= y1 <= 351  # mapped back inside the image


def test_doubtful_handwriting_next_to_a_label_is_covered():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 110), "Nombre:", fontsize=12)
    data = doc.tobytes()
    scale = 200 / 72
    scribble = OcrLine(text="Jxw Grc", rect=(140 * scale, 95 * scale, 330 * scale, 115 * scale), confidence=0.42,
                       handwritten=True)
    options = Options(categories=set(rules.SELECTABLE), ocr=True, ai=False, faces=False, signatures=False,
                      handwriting=False, llm_review=False)
    analysis = pipeline.analyze(data, "h.pdf", options, StubServices(ocr=StubOcr(page_lines=[scribble])))
    hand = [f for f in analysis.findings if f.type == "handwriting"]
    assert hand and hand[0].value is None and hand[0].token.startswith("[MANUSCRITO")


def test_failures_of_optional_models_are_reported_not_hidden():
    class BrokenPii:
        def detect(self, text):
            raise RuntimeError("GPU perdida")

    analysis = pipeline.analyze(_pdf("Paciente: Juan García Pérez"), "x.pdf",
                                Options(categories=set(rules.SELECTABLE), ocr=False, faces=False, signatures=False,
                                        handwriting=False, llm_review=False), StubServices(pii=BrokenPii()))
    assert any("IA de datos personales con error" in note for note in analysis.notes)
    assert any(f.type == "name" for f in analysis.findings)          # the rules still worked

    missing = StubServices(pii=None)
    missing.errors["pii"] = "modelo dañado"
    analysis = pipeline.analyze(_pdf("texto"), "x.pdf", Options(categories=set(rules.SELECTABLE), ocr=False,
                                faces=False, signatures=False, handwriting=False, llm_review=False), missing)
    assert any("modelo dañado" in note for note in analysis.notes)


def test_vlm_failure_during_handwriting_is_noted(monkeypatch):
    from app.engine.ocr import handwriting

    class Broken:
        def __init__(self, server):
            pass

        def read(self, crop):
            raise RuntimeError("servidor caído")

    class WithLlm(StubServices):
        def llm(self):
            return object()

    monkeypatch.setattr(handwriting, "HandwritingReader", Broken)
    scale = 200 / 72
    line = OcrLine(text="algo", rect=(100 * scale, 100 * scale, 300 * scale, 120 * scale), confidence=0.5, handwritten=True)
    options = Options(categories=set(rules.SELECTABLE), ocr=True, ai=False, faces=False, signatures=False,
                      handwriting=True, llm_review=False)
    doc = pymupdf.open()
    doc.new_page()
    analysis = pipeline.analyze(doc.tobytes(), "v.pdf", options, WithLlm(ocr=StubOcr(page_lines=[line])))
    assert any("Lectura de manuscritos no disponible" in note for note in analysis.notes)


def test_combine_and_ai_filters():
    from app.engine.rules import Match
    short = Match(0, 11, "name", "Juan García", 0.8, prio=500)
    longer = Match(0, 17, "name", "Juan García Pérez", 0.7, prio=400, source="ai")
    other = Match(5, 11, "dni", "García", 1.0, prio=870)
    kept = pipeline.combine([short, longer])
    assert [m.value for m in kept] == ["Juan García Pérez"] and kept[0].confidence == 0.8
    assert [m.type for m in pipeline.combine([other, longer])] == ["dni"]
    assert not pipeline._useful_ai(Match(0, 16, "name", "Estimado cliente", 0.99, source="ai"))
    assert not pipeline._useful_ai(Match(0, 6, "nss", "SSSEEE", 0.99, source="ai"))
    assert not pipeline._useful_ai(Match(0, 6, "address", "Madrid", 0.8, source="ai"))
    assert pipeline._useful_ai(Match(0, 6, "address", "Madrid", 0.95, source="ai"))


def test_safe_filename_variants():
    findings = [Finding("a", 0, "name", "Juan García Pérez", [(0, 0, 1, 1)], 1, "text", token="[NOMBRE 1]"),
                Finding("b", 0, "dni", DNI, [(0, 0, 1, 1)], 1, "text", token="[DNI 1]")]
    assert pipeline.safe_filename("Juan_Garcia_Perez_12345678Z_informe.pdf", findings, 1, True) == \
        "NOMBRE-1_DNI-1_informe_anonimizado.pdf"
    assert pipeline.safe_filename("x.pdf", findings, 3, False) == "documento-3_anonimizado.pdf"
    assert "ID" in pipeline.safe_filename("expediente 2024-0001234567.pdf", [], 1, True)
    assert pipeline.safe_filename("maria@correo.es.pdf", [], 1, True).startswith("EMAIL")


def test_partial_mentions_share_the_full_name_token():
    findings = [Finding("a", 0, "name", "Ana López Torres", [(0, 0, 1, 1)], 1, "text"),
                Finding("b", 0, "name", "López Torres", [(0, 50, 1, 51)], 1, "text"),
                Finding("c", 0, "name", "Luis Gil", [(0, 90, 1, 91)], 1, "text")]
    pipeline.assign_tokens(findings)
    assert findings[0].token == findings[1].token == "[NOMBRE 1]" and findings[2].token == "[NOMBRE 2]"


def test_page_text_rects_are_split_per_line():
    text = "ab\ncd"
    boxes = [(0, 0, 5, 10), (5, 0, 10, 10), None, (0, 20, 5, 30), (5, 20, 10, 30)]
    assert PageText(text, boxes).rects_for(0, 5) == [(0, 0, 10, 10), (0, 20, 10, 30)]


# ------------------------------------------------------------------ verification details
def test_verification_decodes_hidden_encodings():
    import pikepdf
    doc = pymupdf.open()
    doc.new_page()
    pdf = pikepdf.open(io.BytesIO(doc.tobytes()))
    pdf.Root.Custom = pikepdf.Dictionary(A=pikepdf.String(NAME.encode("utf-16-be")),
                                         B=pikepdf.String(DNI.encode().hex().encode()))
    out = io.BytesIO()
    pdf.save(out)
    findings = [Finding("a", 0, "name", NAME, [(0, 0, 1, 1)], 1, "text"), Finding("b", 0, "dni", DNI, [(0, 0, 1, 1)], 1, "text")]
    report = verify.verify(out.getvalue(), findings)
    leaked = {leak.value for leak in report.leaks if leak.check == "objetos"}
    assert NAME in leaked and DNI in leaked


def test_targets_skip_values_the_user_kept():
    kept = Finding("a", 0, "dni", DNI, [(0, 0, 1, 1)], 1, "text", key="dni|1")
    also = Finding("b", 1, "dni", DNI, [(0, 0, 1, 1)], 1, "text", key="dni|1", enabled=False)
    assert verify.protected_targets([kept, also]) == []
    assert len(verify.protected_targets([kept])) == 1


# ------------------------------------------------------------------ documents
def test_multipage_tiff_and_bad_inputs():
    frames = [Image.new("RGB", (400, 500), c) for c in ("white", "lightgray", "white")]
    buffer = io.BytesIO()
    frames[0].save(buffer, "TIFF", save_all=True, append_images=frames[1:], dpi=(150, 150))
    pdf = document.load_bytes(buffer.getvalue(), "escaneo.tiff")
    doc = pymupdf.open("pdf", pdf)
    assert doc.page_count == 3 and abs(doc[0].rect.width - 400 * 72 / 150) < 1
    with pytest.raises(document.DocumentError):
        document.load_bytes(b"no soy una imagen", "foto.png")
    with pytest.raises(document.DocumentError):
        document.load_bytes(b"hola", "texto.pdf")
    with pytest.raises(document.DocumentError):
        document.load_bytes(b"%PDF-1.7\n%%EOF", "roto.pdf")


def test_page_limit(monkeypatch):
    monkeypatch.setitem(document.LIMITS, "max_pages", 2)
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    with pytest.raises(document.DocumentError, match="páginas"):
        document.load_bytes(doc.tobytes(), "largo.pdf")


def test_unlock_of_an_unprotected_pdf_is_harmless():
    data = _pdf("hola")
    assert pymupdf.open("pdf", document.unlock(data, "cualquiera"))[0].get_text().strip() == "hola"
    assert not document.is_signed(data)


# ------------------------------------------------------------------ API and window glue
class FakeWindow:
    def __init__(self, answers):
        self.answers, self.evaluated = list(answers), []

    def create_file_dialog(self, *args, **kwargs):
        return self.answers.pop(0)

    def evaluate_js(self, code):
        self.evaluated.append(code)


class NoEngine:
    def __init__(self, error=None):
        self.error, self.cancel = error, threading.Event()
        self.gpu_disabled = ""

    def call(self, op, *args, **kwargs):
        if self.error:
            raise self.error
        return {"base": True, "errors": {}} if op == "status" else True

    def ensure_started(self):
        pass

    def stop(self):
        pass


def _api(engine=None):
    from app.api import Api
    return Api(engine=engine or NoEngine(), light=NoEngine())


def test_api_downloads_missing_models_before_processing(monkeypatch):
    class MissingEngine(NoEngine):
        def __init__(self):
            super().__init__()
            self.missing, self.calls = ["pii-model"], []

        def call(self, op, *args, **kwargs):
            self.calls.append(op)
            return {"base": not self.missing, "missing": list(self.missing), "errors": {}} if op == "status" else True

    engine = MissingEngine()
    pending = [models.ModelFile("pii-model", "base/pii.onnx", "https://example.invalid/pii", "MIT", "0" * 64, "base",
                                size=100)]
    monkeypatch.setattr(models, "required_missing", lambda: list(pending))

    def install(progress):
        progress("pii-model", 50, 100)
        pending.clear()
        engine.missing.clear()

    monkeypatch.setattr(models, "install_required", install)
    api = _api(engine)
    status = api.status()
    assert status["modelsMissing"] and status["blocked"]
    assert api.process({}) is False and "descarga" in api._state.progress["message"]
    assert api.install_required()
    deadline = time.time() + 5
    while api.poll()["setup"].get("running") and time.time() < deadline:
        time.sleep(0.01)
    assert api.poll()["setup"].get("done") and "reload_models" in engine.calls
    assert not api.status()["blocked"] and not api.install_required()  # nothing left to download


def test_api_file_pickers_and_queue(tmp_path):
    (tmp_path / "a.pdf").write_bytes(_pdf("uno"))
    (tmp_path / "b.png").write_bytes(b"png")
    (tmp_path / "notas.txt").write_text("ignorado")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.pdf").write_bytes(_pdf("dos"))
    api = _api()
    api.attach(FakeWindow([[str(tmp_path / "a.pdf"), str(tmp_path / "notas.txt")], [str(tmp_path)], [str(tmp_path)], None]))
    assert [d["name"] for d in api.pick_files()] == ["a.pdf"]
    assert sorted(d["name"] for d in api.pick_folder()) == ["a.pdf", "b.png"]
    assert sorted(d["name"] for d in api.pick_folder(recursive=True)) == ["a.pdf", "b.png", "c.pdf"]
    assert api.pick_folder() == []                       # dialog cancelled
    first = api.documents()[0]["id"]
    assert api.remove(first) and first not in [d["id"] for d in api.documents()]
    api._state.busy = True
    assert not api.remove(api.documents()[0]["id"]) and not api.clear()
    api._state.busy = False
    assert api.clear() and api.documents() == []


def test_api_reports_engine_failures():
    from app.engine.worker import EngineError
    api = _api(NoEngine(EngineError("el motor falló")))
    status = api.status()
    assert status["errors"] == {"engine": "el motor falló"} and not status["blocked"]


def test_api_import_advanced_pack(tmp_path, monkeypatch):
    zipped = tmp_path / "pack.zip"
    zipped.write_bytes(b"")
    api = _api()
    calls = []
    monkeypatch.setattr(models, "import_zip", lambda path: calls.append(path) or ["vlm"])
    api.attach(FakeWindow([[str(zipped)], None]))
    assert api.import_advanced() == {"ok": True} and calls == [zipped]
    assert api.import_advanced() == {"ok": False}        # dialog cancelled
    monkeypatch.setattr(models, "import_zip", lambda path: (_ for _ in ()).throw(RuntimeError("Checksum incorrecto")))
    api.attach(FakeWindow([[str(zipped)]]))
    assert api.import_advanced() == {"ok": False, "message": "Checksum incorrecto"}


def test_window_drop_handler(tmp_path):
    from app.main import dropped_paths, handle_drop
    (tmp_path / "a.pdf").write_bytes(_pdf("uno"))
    event = {"dataTransfer": {"files": [{"name": "a.pdf", "pywebviewFullPath": str(tmp_path / "a.pdf")},
                                        {"name": "sin ruta"}]}}
    assert dropped_paths(event) == [str(tmp_path / "a.pdf")] and dropped_paths({}) == []
    api, window = _api(), FakeWindow([])
    assert handle_drop(api, window, event) == 1 and window.evaluated
    assert handle_drop(api, window, {}) == 0


def test_selftest_of_the_application(tmp_path):
    from app.main import selftest
    report = tmp_path / "selftest.json"
    assert selftest(str(report)) == 0, report.read_text(encoding="utf-8")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["ok"] and data["crash_recovery"] and data["integrity"]


def test_shared_surname_of_two_people_keeps_separate_tokens():
    findings = [Finding("a", 0, "name", "Ana García López", [(0, 0, 1, 1)], 1, "text"),
                Finding("b", 0, "name", "Luis García Pérez", [(0, 50, 1, 51)], 1, "text"),
                Finding("c", 0, "name", "García", [(0, 90, 1, 91)], 1, "text"),
                Finding("d", 0, "name", "Pérez", [(0, 95, 1, 96)], 1, "text")]
    pipeline.assign_tokens(findings)
    assert findings[2].token not in (findings[0].token, findings[1].token)   # ambiguous: its own token
    assert findings[3].token == findings[1].token                           # only Luis is Pérez


def test_ocr_character_extents_have_no_gaps_and_reach_the_line_edges():
    """CTC peaks mark where a glyph was recognised, not its extent: a value at the end of a line (the control
    letter of a DNI) must be covered up to the edge of the detected line."""
    import itertools

    from app.engine.ocr.printed import char_extents
    extents = char_extents([[2, 3], [6, 6], [10, 11]], 8.0, 110.0)
    assert extents[0][0] == 0.0 and extents[-1][1] == 110.0
    assert all(left[1] >= right[0] for left, right in itertools.pairwise(extents))  # neighbours meet
    for (a, b), (x0, x1) in zip([[2, 3], [6, 6], [10, 11]], extents, strict=True):  # never narrower than the peak
        assert x0 <= max(0.0, (a - 0.5) * 8.0) and x1 >= min(110.0, (b + 1.5) * 8.0)
    assert char_extents([], 8.0, 110.0) == []
