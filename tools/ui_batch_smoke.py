"""Exercise real batch UI and publication/retry with a fictitious export worker."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402
from app.api import Api, Doc  # noqa: E402
from app.engine import pipeline, verify  # noqa: E402
from app.engine.system import webview_gui  # noqa: E402
from app.engine.types import Options  # noqa: E402
from app.main import _ui_path  # noqa: E402
from tests.test_security import pdf_with_text  # noqa: E402


class SyntheticEngine:
    """No AI models, external services, or user documents are accessed."""
    gpu_disabled = ""

    def __init__(self):
        self.cancel = threading.Event()

    def call(self, op, *args, **kwargs):
        if op == "status":
            return {"base": True, "advanced": False, "gpu": False, "errors": {}, "backends": {}}
        if op == "build_preview":
            return args[0].working
        if op == "page_png":
            return pipeline.preview(*args)
        if op == "export":
            return pipeline.ExportResult(args[0].working, verify.Report(), f"documento-{args[2]}_anonimizado.pdf", 0)
        if op == "analyze":
            return pipeline.analyze(args[0], args[1], Options(categories={"manual"}, ocr=False, ai=False,
                                                             faces=False, signatures=False))
        raise AssertionError(f"Unexpected operation: {op}")

    def stop(self):
        pass

    def ensure_started(self):
        pass


def main() -> None:
    output = Path(sys.argv[1])
    result = {"ok": False, "errors": []}
    with tempfile.TemporaryDirectory(prefix="anonimato-batch-ui-") as temporary:
        folder = Path(temporary)
        api = Api(engine=SyntheticEngine(), light=SyntheticEngine())
        data = pdf_with_text("FICTITIOUS BATCH FIXTURE")
        options = Options(categories={"manual"}, ocr=False, ai=False, faces=False, signatures=False)
        for index in (1, 2):
            doc = Doc(f"d{index}", f"synthetic-{index}.pdf", len(data), data, status="ready",
                      analysis=pipeline.analyze(data, f"synthetic-{index}.pdf", options))
            api._state.docs[doc.id] = doc
            api._state.order.append(doc.id)
        publish = api._publish_export
        failing = True

        def publish_with_failure(doc, *args, **kwargs):
            if failing and doc.id == "d2":
                raise OSError("Synthetic disk error")
            return publish(doc, *args, **kwargs)

        api._publish_export = publish_with_failure
        api.save_all = lambda raw: api.export_folder(str(folder), raw)
        window = webview.create_window("Anonimato (batch fixture)", url=_ui_path().as_uri(), js_api=api,
                                       width=1480, height=940)
        api.attach(window)
        window.create_file_dialog = lambda *args, **kwargs: [str(folder / kwargs.get('save_filename', 'fictitious.pdf'))]

        def wait(condition):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if window.evaluate_js(condition):
                    return
                time.sleep(0.1)
            raise AssertionError(condition)

        collector = None
        coverage_output = Path(sys.argv[sys.argv.index("--js-coverage") + 1]).resolve() if "--js-coverage" in sys.argv else None
        if sys.platform == "win32":
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1"
            webview.settings["REMOTE_DEBUGGING_PORT"] = port
        if coverage_output:
            ready, stop = folder / "coverage-ready", folder / "coverage-stop"
            collector = subprocess.Popen(["node", str(ROOT / "tools/webview_coverage.mjs"), str(port), _ui_path().as_uri(),
                                           (ROOT / "app/ui/app.js").as_uri(), str(coverage_output), str(ready), str(stop)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def scenario():
            nonlocal failing
            try:
                # The hosted runner can need more than pywebview's default 20-second
                # API-call wait to create its first WebView2 profile.
                if not window.events.loaded.wait(60):
                    raise AssertionError("The synthetic window did not finish loading within 60 seconds")
                if collector:
                    deadline = time.monotonic() + 35
                    while not ready.exists() and time.monotonic() < deadline and collector.poll() is None:
                        time.sleep(0.1)
                    if not ready.exists():
                        if collector.poll() is None:
                            collector.kill()
                        _stdout, startup_error = collector.communicate(timeout=10)
                        raise AssertionError("JavaScript coverage failed to start: "
                                             + startup_error.decode(errors="replace")[-3000:])
                wait("document.readyState === 'complete' && !!document.getElementById('resultsCard')")
                wait("!document.getElementById('resultsCard').hidden")
                wait("document.getElementById('originalImg').dataset.doc === 'd1'")
                window.evaluate_js("""
                    document.getElementById('btnManual').click();
                    const wrap = document.getElementById('originalWrap'), r = wrap.getBoundingClientRect();
                    wrap.dispatchEvent(new PointerEvent('pointerdown', {clientX:r.left+20, clientY:r.top+20,button:0,pointerId:1,bubbles:true}));
                    wrap.dispatchEvent(new PointerEvent('pointermove', {clientX:r.left+80, clientY:r.top+80,pointerId:1,bubbles:true}));
                    document.querySelectorAll('.document-select')[1].click();
                """)
                wait("document.getElementById('originalImg').dataset.doc === 'd2'")
                window.evaluate_js("document.getElementById('originalWrap').dispatchEvent(new PointerEvent('pointerup', {pointerId:1,bubbles:true}))")
                time.sleep(0.2)
                assert not any(doc.analysis.findings for doc in api._state.docs.values()), "A gesture must not move to another document"
                window.evaluate_js("document.getElementById('btnAll').click()")
                wait("document.querySelectorAll('#batchList li').length === 2")
                assert window.evaluate_js("document.getElementById('batchList').textContent.includes('Guardado') && document.getElementById('batchList').textContent.includes('Error al escribir')")
                assert len(list(folder.glob("*.pdf"))) == 1
                failing = False
                window.evaluate_js("document.getElementById('btnRetryBatch').click()")
                wait("document.getElementById('btnRetryBatch').hidden")
                assert window.evaluate_js("document.querySelectorAll('#batchList li').length === 2 && !document.getElementById('batchList').textContent.includes('Error al escribir')")
                assert sorted(path.name for path in folder.glob("*.pdf")) == ["documento-1_anonimizado.pdf", "documento-2_anonimizado.pdf"]
                assert all(doc.saved_revision == doc.revision for doc in api._state.docs.values())
                assert window.evaluate_js("document.querySelector('[data-step=save]').classList.contains('done')")
                # Exercise keyboard editing/history, zoom, filtering and option changes in the actual window.
                window.evaluate_js("document.getElementById('manualForm').requestSubmit()")
                wait("document.querySelectorAll('#rowsBody tr').length === 1")
                window.evaluate_js("document.getElementById('btnUndo').click()")
                wait("document.querySelectorAll('#rowsBody tr').length === 0")
                window.evaluate_js("document.getElementById('btnRedo').click()")
                wait("document.querySelectorAll('#rowsBody tr').length === 1")
                window.evaluate_js("document.getElementById('btnAllOff').click()")
                wait("document.querySelectorAll('#rowsBody tr.off').length === 1")
                window.evaluate_js("document.getElementById('btnAllOn').click(); const z=document.getElementById('pageZoom');z.value='2';z.dispatchEvent(new Event('change'))")
                wait("document.getElementById('originalWrap').classList.contains('zoomed')")
                window.evaluate_js("document.getElementById('btnViewResult').click(); document.getElementById('btnViewCompare').click(); document.getElementById('btnPanelCollapse').click(); document.getElementById('btnPanelExpand').click()")
                window.evaluate_js("const f=document.getElementById('typeFilter');f.value='manual';f.dispatchEvent(new Event('change'))")
                wait("document.querySelectorAll('#rowsBody tr').length === 1")
                # G opens the save dialog with every output choice; review shortcuts stay off while it is open.
                window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'g'}))")
                wait("document.getElementById('saveDialog').open && document.getElementById('saveSummary').textContent.includes('Se ocultará 1 dato')")
                window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'd'}))")
                assert window.evaluate_js("!document.getElementById('resultsCard').classList.contains('panel-collapsed')")
                window.evaluate_js("document.getElementById('btnSaveBack').click()")
                wait("!document.getElementById('saveDialog').open")
                window.evaluate_js("document.getElementById('btnOpenSave').click()")
                wait("document.getElementById('saveDialog').open")
                window.evaluate_js("document.getElementById('btnPdf').click()")
                wait("!document.getElementById('saveDialog').open")
                wait("document.querySelector('[data-step=save]').classList.contains('done')")
                window.evaluate_js("document.getElementById('btnCsv').click(); document.getElementById('btnJson').click()")
                wait("document.getElementById('btnRun').disabled === false")
                previous_revision = api._state.docs['d2'].revision
                window.evaluate_js("window.confirm=()=>true; document.getElementById('processScope').value='all'; document.getElementById('btnRun').click()")
                deadline = time.monotonic() + 30
                while api._state.docs['d2'].revision == previous_revision and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert api._state.docs['d2'].revision > previous_revision, 'Reanalysis must execute before collecting coverage'
                wait("!document.getElementById('resultsCard').hidden && !document.getElementById('btnRun').disabled")
                if collector:
                    stop.touch()
                    _stdout, stderr = collector.communicate(timeout=30)
                    assert collector.returncode == 0, stderr.decode(errors="replace")
                    result["javascriptCoverage"] = json.loads(coverage_output.read_text(encoding="utf-8"))["percent"]
                result["ok"] = True
            except Exception as error:
                result["errors"].append(str(error))
            finally:
                if collector and collector.poll() is None:
                    collector.kill()
                    collector.communicate(timeout=10)
                window.destroy()

        try:
            webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
            webview.start(scenario, gui=webview_gui(), private_mode=True, debug=True, storage_path=str(folder / "webview-profile"))
        except Exception as error:
            result["errors"].append(f"Window startup failed: {type(error).__name__}: {error}")
        finally:
            api.shutdown()
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["ok"]:
        raise SystemExit(json.dumps(result))


if __name__ == "__main__":
    main()
