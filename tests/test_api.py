"""The window bridge end to end, with a fake window (file dialogs) and CPU inference."""
import json
import time
from pathlib import Path

import pymupdf
import pytest

from app.api import Api
from app.engine.services import Services
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
    bridge = Api(Services(use_gpu=False))
    bridge.add_paths([str(folder)])
    yield bridge
    bridge._services.shutdown()


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
    ImageDraw.Draw(image).text((40, 150), f"DNI: {DNI}", fill="black", font=ImageFont.truetype("arial.ttf", 60))
    exif = Image.Exif()
    exif[0x013B] = NAME
    path = tmp_path / "foto.jpg"
    image.save(path, "JPEG", exif=exif.tobytes())
    bridge = Api(Services(use_gpu=False))
    bridge.add_paths([str(path)])
    bridge.process({**OPTIONS, "faces": False})
    wait(bridge)
    doc = bridge.documents()[0]
    assert doc["status"] == "ready", doc
    values = [f["value"] for f in bridge.details(doc["id"])["findings"]]
    assert any(v and "12345678" in v for v in values)
    result = bridge.export_folder(str(tmp_path), {**OPTIONS, "faces": False})
    assert result["saved"] == 1
    assert not independent_scan((tmp_path / "documento-1_anonimizado.pdf").read_bytes())


def test_phone_photo_perspective_is_corrected():
    import io

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from app.engine import document
    sheet = Image.new("RGB", (850, 1100), "white")
    ImageDraw.Draw(sheet).text((80, 200), f"DNI: {DNI}", fill="black", font=ImageFont.truetype("arial.ttf", 48))
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
