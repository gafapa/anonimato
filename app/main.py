"""Desktop entry point: native window (WebView2) with the local interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ui_path() -> Path:
    from .engine.models import app_root
    return app_root() / "app" / "ui" / "index.html"


def selftest(report_path: str) -> int:
    """Headless check of the installed application through the isolated engine process:
    analyse, redact, clean and verify a generated document; also checks crash recovery."""
    import json
    import time

    import pymupdf

    from .engine import rules
    from .engine.types import Options
    from .engine.worker import EngineCrashed, EngineProcess

    started = time.time()
    result: dict = {"ok": False}
    engine = EngineProcess(with_models=True, use_gpu=os.environ.get("ANONIMATO_CPU") != "1")
    try:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Paciente: Juan García Pérez, DNI 12345678Z, teléfono 612 345 678", fontsize=11)
        doc.set_metadata({"author": "Juan García Pérez"})
        options = Options(categories=set(rules.SELECTABLE) - rules.DEFAULT_OFF, handwriting=False, llm_review=False)
        analysis = engine.call("analyze", doc.tobytes(), "prueba.pdf", options)
        exported = engine.call("export", analysis, options, 1, False)
        text = pymupdf.open("pdf", exported.data)[0].get_text()
        try:
            engine.call("_test_crash")
            recovered = False
        except EngineCrashed:
            recovered = engine.call("ping") > 0
        status = engine.call("status")
        result = {
            "ok": exported.report.ok and "12345678Z" not in text and "García" not in text and recovered
                  and "integrity" not in status.get("errors", {}),
            "findings": sorted({f.type for f in analysis.findings}),
            "report": exported.report.to_json(),
            "services": status,
            "integrity": engine.call("integrity"),
            "crash_recovery": recovered,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as error:
        result = {"ok": False, "error": repr(error)}
    finally:
        engine.stop()
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.get("ok") else 1


def dropped_paths(event: dict) -> list[str]:
    """Full paths of the files dropped on the window (pywebview adds them to the DOM event)."""
    files = (event or {}).get("dataTransfer", {}).get("files", []) or []
    return [f["pywebviewFullPath"] for f in files if isinstance(f, dict) and f.get("pywebviewFullPath")]


def handle_drop(api, window, event: dict) -> int:
    import json

    from .engine.document import DocumentError
    paths = dropped_paths(event)
    try:
        added = api.add_paths(paths) if paths else []
    except (DocumentError, OSError) as error:
        window.evaluate_js("window.app && window.app.notifyError(" + json.dumps(str(error)) + ")")
        window.evaluate_js("window.app && window.app.refreshDocuments()")
        return 0
    if added:
        window.evaluate_js("window.app && window.app.refreshDocuments()")
    return len(added)


def main() -> None:
    for arg in sys.argv[1:]:
        if arg.startswith("--selftest="):
            sys.exit(selftest(arg.split("=", 1)[1]))
    import webview
    from webview.dom import DOMEventHandler

    from .api import Api

    api = Api(use_gpu=os.environ.get("ANONIMATO_CPU") != "1")
    window = webview.create_window(
        "Anonimato", url=_ui_path().as_uri(), js_api=api, width=1480, height=940, min_size=(980, 640),
        background_color="#0b111c", text_select=True,
    )
    api.attach(window)

    def on_drop(event) -> None:
        handle_drop(api, window, event)

    def on_loaded() -> None:
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    try:
        from .engine.system import webview_gui
        webview.start(gui=webview_gui(), private_mode=True, debug="--debug" in sys.argv)
    finally:
        api.shutdown()


if __name__ == "__main__":
    main()
