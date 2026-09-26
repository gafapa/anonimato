"""The window bridge end to end, with a fake window (file dialogs) and CPU inference."""
import json
import time
from pathlib import Path

import pymupdf
import pytest

from app.api import Api
from app.engine.system import font as system_font
from tests.fixtures.generate import DNI, NAME, build_all
from tests.test_leaks import independent_scan


class FakeWindow:
    def __init__(self, answers):
        self.answers = list(answers)

    def create_file_dialog(self, *args, **kwargs):
        return self.answers.pop(0)


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    folder = tmp_path_factory.mktemp("in")
    fixtures = {f.number: f for f in build_all()}
    for number in (1, 10, 22):
        (folder / fixtures[number].filename).write_bytes(fixtures[number].data)
    bridge = Api(use_gpu=False)
    bridge.add_paths([str(folder)])
    yield bridge
    bridge.shutdown()


OPTIONS = {"ai": False, "handwriting": False, "llmReview": False, "dpi": 150}


def wait(api):
    deadline = time.time() + 900
    while api.poll()["busy"]:
        assert time.time() < deadline
        time.sleep(0.5)


def test_process_and_review(api):
    assert len(api.documents()) == 3
    assert api.process(OPTIONS)
    wait(api)
    docs = api.documents()
    assert all(d["status"] == "ready" for d in docs), docs
    details = api.details(docs[0]["id"])
    assert details["findings"] and all("rects" not in f for f in details["findings"])
    assert all(0 <= v <= 1 for f in details["findings"] for r in f["view"] for v in r)


def test_manual_zone_and_toggle(api):
    doc_id = api.documents()[0]["id"]
    manual = api.add_manual(doc_id, 0, [0.1, 0.5, 0.4, 0.55])
    assert manual["type"] == "manual" and manual["token"].startswith("[MANUAL")
    first = api.details(doc_id)["findings"][0]["id"]
    assert api.set_enabled(doc_id, [first], False) == 1
    assert api.set_enabled(doc_id, [first], True) == 1
    assert api.remove_manual(doc_id, manual["id"])


def test_previews_never_show_the_original_in_result(api):
    doc_id = api.documents()[0]["id"]
    original = api.page_image(doc_id, 0, "original", OPTIONS)
    result = api.page_image(doc_id, 0, "result", OPTIONS)
    assert original.startswith("data:image/png;base64,") and result != original


def test_save_pdf_writes_only_verified_file(api, tmp_path):
    doc_id = api.documents()[0]["id"]
    target = tmp_path / "salida.pdf"
    api.attach(FakeWindow([str(target)]))
    result = api.save_pdf(doc_id, OPTIONS)
    assert result["ok"] and result["saved"], result
    data = target.read_bytes()
    assert not independent_scan(data)
    assert result["report"]["ok"]


def test_save_all_to_folder(api, tmp_path):
    result = api.export_folder(str(tmp_path), OPTIONS)
    assert result["ok"] and result["saved"] == 3, result
    names = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert names == ["documento-1_anonimizado.pdf", "documento-2_anonimizado.pdf", "documento-3_anonimizado.pdf"]
    report = json.loads((tmp_path / "informe_verificacion.json").read_text(encoding="utf-8"))
    assert all(d["ok"] for d in report["documentos"])
    for pdf in tmp_path.glob("*.pdf"):
        assert not independent_scan(pdf.read_bytes())
        assert pymupdf.open(pdf).metadata.get("author") in ("", None)


def test_logs_exclude_originals_by_default(api, tmp_path):
    doc_id = api.documents()[0]["id"]
    csv_path, json_path = tmp_path / "r.csv", tmp_path / "r.json"
    api.attach(FakeWindow([str(csv_path), str(json_path)]))
    api.save_log(doc_id, "csv", False, False)
    api.save_log(doc_id, "json", False, False)
    for path in (csv_path, json_path):
        text = path.read_text(encoding="utf-8")
        assert NAME not in text and DNI not in text and "García" not in text
    csv_path2 = tmp_path / "r2.csv"
    api.attach(FakeWindow([str(csv_path2)]))
    api.save_log(doc_id, "csv", True, False)
    assert DNI in csv_path2.read_text(encoding="utf-8")


def test_images_are_accepted(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 400), "white")
    ImageDraw.Draw(image).text((40, 150), f"DNI: {DNI}", fill="black", font=ImageFont.truetype(system_font("sans"), 60))
    exif = Image.Exif()
    exif[0x013B] = NAME
    path = tmp_path / "foto.jpg"
    image.save(path, "JPEG", exif=exif.tobytes())
    bridge = Api(use_gpu=False)
    bridge.add_paths([str(path)])
    bridge.process({**OPTIONS, "faces": False})
    wait(bridge)
    doc = bridge.documents()[0]
    assert doc["status"] == "ready", doc
    values = [f["value"] for f in bridge.details(doc["id"])["findings"]]
    assert any(v and "12345678" in v for v in values)
    result = bridge.export_folder(str(tmp_path), {**OPTIONS, "faces": False})
    bridge.shutdown()
    assert result["saved"] == 1
    assert not independent_scan((tmp_path / "documento-1_anonimizado.pdf").read_bytes())


def test_phone_photo_perspective_is_corrected():
    import io

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from app.engine import document
    sheet = Image.new("RGB", (850, 1100), "white")
    ImageDraw.Draw(sheet).text((80, 200), f"DNI: {DNI}", fill="black", font=ImageFont.truetype(system_font("sans"), 48))
    src = np.float32([[0, 0], [850, 0], [850, 1100], [0, 1100]])
    dst = np.float32([[180, 120], [1020, 200], [960, 1380], [120, 1300]])
    photo = cv2.warpPerspective(np.asarray(sheet), cv2.getPerspectiveTransform(src, dst), (1200, 1500),
                                borderValue=(70, 60, 50))
    buffer = io.BytesIO()
    Image.fromarray(photo).save(buffer, "JPEG", quality=92)
    flattened = document.correct_perspective(Image.open(io.BytesIO(buffer.getvalue())))
    w, h = flattened.size
    assert (w, h) != (1200, 1500) and abs(w / h - 850 / 1100) < 0.08, flattened.size
    pdf = document.load_bytes(buffer.getvalue(), "foto.jpg")
    assert pymupdf.open("pdf", pdf).page_count == 1
    from app.engine.ocr.engine import OcrEngine
    lines = OcrEngine(use_gpu=False).read(np.asarray(flattened))
    assert any("12345678" in line.text for line in lines)


def test_status_reports_engine_state(api):
    status = api.status()
    assert status["services"]["base"] and not status["blocked"]
    assert status["errors"] == {}


def test_cancel_leaves_remaining_documents_pending(tmp_path):
    fixtures = {f.number: f for f in build_all()}
    for number in (13, 22, 23, 24):
        (tmp_path / fixtures[number].filename).write_bytes(fixtures[number].data)
    bridge = Api(use_gpu=False)
    try:
        bridge.add_paths([str(tmp_path)])
        assert bridge.process(OPTIONS)
        time.sleep(1.0)
        bridge.cancel()
        wait(bridge)
        statuses = [d["status"] for d in bridge.documents()]
        assert "pending" in statuses and "processing" not in statuses, statuses
        assert bridge.process(OPTIONS)  # the engine is usable again after cancelling
        wait(bridge)
        assert all(d["status"] == "ready" for d in bridge.documents())
    finally:
        bridge.shutdown()


def test_password_protected_pdf(tmp_path):
    source = pymupdf.open("pdf", next(f for f in build_all() if f.number == 21).data)
    path = tmp_path / "cifrado.pdf"
    path.write_bytes(source.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="propietario", user_pw="1234"))
    bridge = Api(use_gpu=False)
    try:
        bridge.add_paths([str(path)])
        bridge.process(OPTIONS)
        wait(bridge)
        doc = bridge.documents()[0]
        assert doc["status"] == "locked", doc
        assert not bridge.unlock(doc["id"], "mala")["ok"]
        assert bridge.unlock(doc["id"], "1234")["ok"]
        bridge.process(OPTIONS)
        wait(bridge)
        assert bridge.documents()[0]["status"] == "ready"
        result = bridge.export_folder(str(tmp_path), OPTIONS)
        assert result["saved"] == 1
        output = tmp_path / "documento-1_anonimizado.pdf"
        out = pymupdf.open(output)
        assert not out.needs_pass and not out.is_encrypted
        assert not independent_scan(output.read_bytes())
    finally:
        bridge.shutdown()


def test_digitally_signed_pdf_is_flagged(tmp_path):
    fixture = next(f for f in build_all() if f.number == 25)
    path = tmp_path / fixture.filename
    path.write_bytes(fixture.data)
    bridge = Api(use_gpu=False)
    try:
        bridge.add_paths([str(path)])
        bridge.process(OPTIONS)
        wait(bridge)
        details = bridge.details(bridge.documents()[0]["id"])
        assert details["signed"] and any("firma digital" in note for note in details["notes"])
    finally:
        bridge.shutdown()


def test_blocked_export_shows_where_the_leak_is(api):
    """Verifying the unredacted working copy must locate the leak on the page."""
    from app.engine import verify
    doc_id = api.documents()[0]["id"]
    doc, analysis = api._analysis(doc_id)
    finding = next(f for f in analysis.findings if f.type == "dni")
    report = verify.verify(analysis.working, [finding]).to_json()
    view = api._report_view(analysis, report)
    located = [leak for leak in view["leaks"] if leak["page"] == 0 and leak.get("view")]
    assert located, view["leaks"]
    x0, y0, x1, y1 = located[0]["view"][0]
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_uniform_token_width_hides_length():
    from app.engine import pipeline, rules
    from app.engine.types import Options
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Paciente: Ana Gil", fontsize=11)
    page.insert_text((72, 130), "Paciente: Maximiliano Barreiro-Loureiro", fontsize=11)
    base = dict(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF, ocr=False, ai=False, faces=False,
                signatures=False, handwriting=False, llm_review=False, mode="blank")
    widths = {}
    for uniform in (False, True):
        options = Options(**base, uniform_tokens=uniform)
        analysis = pipeline.analyze(doc.tobytes(), "x.pdf", options, None)
        result = pipeline.export(analysis, options, None, verify_pixels=False)
        assert result.report.ok
        out = pymupdf.open("pdf", result.data)[0]
        assert out.get_text().count("Paciente:") == 2  # neighbouring text is never removed
        blocks = [b for b in out.get_text("blocks") if "Paciente" in b[4]]
        widths[uniform] = [round(b[2] - b[0]) for b in blocks]
        assert not independent_scan(result.data)
    assert widths[True] == widths[False]  # labels untouched in both modes


def test_advanced_download_flow(tmp_path, monkeypatch):
    """The in-app installer downloads, verifies the checksum and refuses altered files."""
    import hashlib
    import http.server
    import socketserver
    import threading

    from app import api as api_module
    from app.engine import models

    served = tmp_path / "served"
    served.mkdir()
    good = b"modelo" * 5000
    (served / "vlm.gguf").write_bytes(good)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/vlm.gguf"

    def manifest(digest):
        return {"advanced": [models.ModelFile(id="vlm", file="advanced/vlm.gguf", url=url, license="MIT",
                                              sha256=digest, group="advanced")]}

    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path / "user")

    class NoEngine:
        def call(self, *args, **kwargs):
            return True

    bridge = api_module.Api.__new__(api_module.Api)
    bridge._state = api_module.State()
    bridge._engine = NoEngine()
    bridge._status_cache = None
    monkeypatch.setattr(models, "load_manifest", lambda: manifest(hashlib.sha256(good).hexdigest()))
    bridge._install("advanced")
    assert bridge._state.install.get("done"), bridge._state.install
    assert (tmp_path / "user" / "advanced" / "vlm.gguf").read_bytes() == good
    (tmp_path / "user" / "advanced" / "vlm.gguf").unlink()
    monkeypatch.setattr(models, "load_manifest", lambda: manifest("0" * 64))
    bridge._install("advanced")
    assert bridge._state.install.get("error"), bridge._state.install
    assert not (tmp_path / "user" / "advanced" / "vlm.gguf").exists()
    server.shutdown()


def test_uniform_width_is_quantised_but_never_eats_neighbours():
    from app.engine.redact import UNIFORM_STEP, _uniform
    short = _uniform(pymupdf.Rect(100, 100, 120, 112), [])
    long = _uniform(pymupdf.Rect(100, 100, 170, 112), [])
    assert short.width == UNIFORM_STEP and long.width == 2 * UNIFORM_STEP
    blocked = _uniform(pymupdf.Rect(100, 100, 120, 112), [pymupdf.Rect(125, 100, 160, 112)])
    assert blocked.x1 <= 124.5
