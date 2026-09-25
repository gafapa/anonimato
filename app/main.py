"""Desktop entry point: native window (WebView2) with the local interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ui_path() -> Path:
    from .engine.models import app_root
    return app_root() / "app" / "ui" / "index.html"


def selftest(report_path: str) -> int:
    """Headless check of the installed engine: analyse, redact, clean and verify a generated document."""
    import json
    import time

    import pymupdf

    from .engine import pipeline, rules
    from .engine.services import Services
    from .engine.types import Options

    started = time.time()
    result: dict = {"ok": False}
    services = Services(use_gpu=os.environ.get("ANONIMATO_CPU") != "1")
    try:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Paciente: Juan García Pérez, DNI 12345678Z, teléfono 612 345 678", fontsize=11)
        doc.set_metadata({"author": "Juan García Pérez"})
        options = Options(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF, handwriting=False, llm_review=False)
        analysis = pipeline.analyze(doc.tobytes(), "prueba.pdf", options, services)
        exported = pipeline.export(analysis, options, services)
        text = pymupdf.open("pdf", exported.data)[0].get_text()
        result = {
            "ok": exported.report.ok and "12345678Z" not in text and "García" not in text,
            "findings": sorted({f.type for f in analysis.findings}),
            "report": exported.report.to_json(),
            "services": services.status(),
            "integrity": services.check_integrity(),
            "seconds": round(time.time() - started, 1),
        }
    except Exception as error:  # noqa: BLE001
        result = {"ok": False, "error": repr(error)}
    finally:
        services.shutdown()
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.get("ok") else 1


def main() -> None:
    for arg in sys.argv[1:]:
        if arg.startswith("--selftest="):
            sys.exit(selftest(arg.split("=", 1)[1]))
    import webview
    from webview.dom import DOMEventHandler

    from .api import Api
    from .engine.services import Services

    services = Services(use_gpu=os.environ.get("ANONIMATO_CPU") != "1")
    services.warm_up()
    api = Api(services)
    window = webview.create_window(
        "Anonimato", url=_ui_path().as_uri(), js_api=api, width=1480, height=940, min_size=(980, 640),
        background_color="#0b111c", text_select=True,
    )
    api.attach(window)

    def on_drop(event) -> None:
        files = event.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            api.add_paths(paths)
            window.evaluate_js("window.app && window.app.refreshDocuments()")

    def on_loaded() -> None:
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    try:
        webview.start(gui="edgechromium", private_mode=True, debug="--debug" in sys.argv)
    finally:
        services.shutdown()


if __name__ == "__main__":
    main()
