"""Drive the real window through every feature of the interface.

Adds documents (including a password-protected one), analyses them, reviews (filters, include/exclude,
keyboard shortcuts, page navigation, manual zones), shows errors and leak boxes, saves the PDF, the logs
and a batch export. Collects JavaScript errors and window-only screenshots.

Usage: uv run python tools/ui_smoke.py [--gpu] [--out results.json]
Used by tests/test_ui.py. Screenshots: tmp/ui_*.png
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
import webview  # noqa: E402

from app.api import Api  # noqa: E402
from app.main import _ui_path  # noqa: E402
from tests.fixtures.generate import DNI, NAME, build_all  # noqa: E402

OUT = ROOT / "tmp"
OUT.mkdir(exist_ok=True)
results = {"errors": [], "steps": {}, "diagnostics": []}


def step(name: str, ok: bool, detail: str = "") -> None:
    results["steps"][name] = {"ok": bool(ok), "detail": detail}


def shot(window, name):
    """Capture only this window's own content (PrintWindow), never the rest of the screen."""
    if sys.platform != "win32":
        return
    time.sleep(0.6)
    try:
        import ctypes
        from ctypes import wintypes

        from PIL import Image
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hwnd = user32.FindWindowW(None, window.title)
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        width, height = rect.right, rect.bottom
        hdc = user32.GetDC(hwnd)
        memdc = gdi32.CreateCompatibleDC(hdc)
        bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
        gdi32.SelectObject(memdc, bitmap)
        user32.PrintWindow(hwnd, memdc, 3)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memdc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB").save(OUT / f"ui_{name}.png")
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)
    except Exception as error:  # screenshots are diagnostics only (e.g. a locked session gives empty images)
        results["diagnostics"].append(f"screenshot {name}: {error}")


def js(window, code):
    return window.evaluate_js(code)


def wait_js(window, condition, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js(window, condition):
            return True
        time.sleep(0.4)
    raise TimeoutError(condition)


def wait_for(predicate, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.3)
    raise TimeoutError(getattr(predicate, "__name__", "condition"))


def click(window, element_id):
    js(window, f"document.getElementById('{element_id}').click()")


def key(window, name):
    js(window, f"document.dispatchEvent(new KeyboardEvent('keydown', {{key: '{name}'}}))")


def rows(window) -> int:
    return js(window, "document.querySelectorAll('#rowsBody tr').length")


def excluded(window) -> int:
    return js(window, "document.querySelectorAll('#rowsBody tr.off').length")


def select_document(window, prefix):
    js(window, f"[...document.querySelectorAll('.document-select')].find(b => b.textContent.includes('{prefix}')).click()")
    wait_js(window, f"document.getElementById('currentFileName').textContent.includes('{prefix}')", 60)
    wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 180)


class Dialogs:
    """Stands in for the native file dialogs; everything else goes to the real window."""

    def __init__(self, window, answers):
        self.window, self.answers, self.title = window, list(answers), window.title

    def __getattr__(self, name):
        return getattr(self.window, name)

    def create_file_dialog(self, *args, **kwargs):
        return self.answers.pop(0)


def scenario(window, api):
    work = Path(tempfile.mkdtemp())
    try:
        wait_js(window, "!!(window.pywebview && window.app && document.querySelectorAll('#catGrid input').length)", 120)
        js(window, "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
                   "window.addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));")
        shot(window, "0_start")
        step("detection categories are available", js(window, "document.querySelectorAll('#catGrid input').length") >= 20)

        # ---- documents: a two-page PDF, a scan, a handwritten form, annotations and a locked PDF
        folder = work / "entrada"
        folder.mkdir()
        fixtures = {f.number: f for f in build_all()}
        for number in (12, 22, 23, 10):
            (folder / fixtures[number].filename).write_bytes(fixtures[number].data)
        locked = pymupdf.open("pdf", fixtures[21].data)
        (folder / "zz_cifrado.pdf").write_bytes(locked.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                                               owner_pw="propietario", user_pw="1234"))
        api.add_paths([str(folder)])
        js(window, "window.app.refreshDocuments()")
        wait_js(window, "document.querySelectorAll('.document-item').length === 5")
        step("queue contains five documents", True)

        # ---- analysis (the cancel button is visible while it runs)
        click(window, "btnRun")
        time.sleep(1)
        step("cancel button is visible during analysis", js(window, "!document.getElementById('btnCancel').hidden"))
        shot(window, "1_processing")
        wait_js(window, "document.getElementById('btnCancel').hidden", 900)
        wait_js(window, "!document.getElementById('resultsCard').hidden && document.querySelectorAll('#rowsBody tr').length > 0")
        wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 180)
        shot(window, "2_review")
        step("review shows findings and boxes",
             rows(window) > 0 and js(window, "document.querySelectorAll('#originalWrap .box').length") > 0)
        step("settings are collapsed during review",
             js(window, "!document.getElementById('detectionDetails').open && "
                        "document.getElementById('sidebar').classList.contains('reviewing')"))
        click(window, "optAi")
        step("detection changes request reanalysis",
             js(window, "!document.getElementById('settingsChangeNotice').hidden"))
        click(window, "optAi")
        step("restoring detection clears the warning",
             js(window, "document.getElementById('settingsChangeNotice').hidden"))

        # ---- locked PDF: password prompt, unlock and analysis
        has_unlock = js(window, "document.querySelectorAll('.unlock-row input').length") == 1
        # The queue is rebuilt on every poll during an analysis; a password being typed must survive it.
        js(window, "document.querySelector('.unlock-row input').value = 'abc'; window.app.refreshDocuments()")
        time.sleep(1)
        step("a password being typed survives queue refreshes",
             js(window, "document.querySelector('.unlock-row input')?.value") == "abc")
        js(window, "const i = document.querySelector('.unlock-row input'); i.value = '1234';"
                   "document.querySelector('.unlock-row button').click();")
        wait_js(window, "document.querySelectorAll('.unlock-row').length === 0", 60)
        click(window, "btnRun")
        step("the previous review is hidden while re-analysing",
             wait_js(window, "document.getElementById('resultsCard').hidden", 10))
        wait_js(window, "!document.getElementById('btnCancel').hidden || document.querySelectorAll('.document-status.ready').length === 5", 30)
        wait_js(window, "document.querySelectorAll('.document-status.ready').length === 5", 900)
        step("password-protected PDF is unlocked and analyzed", has_unlock)

        # ---- review tools on the two-page document
        select_document(window, "12_")
        total = rows(window)
        click(window, "btnAllOff")
        time.sleep(0.5)
        all_off = excluded(window) == total
        click(window, "btnAllOn")
        time.sleep(0.5)
        step("include and exclude all findings", all_off and excluded(window) == 0, f"{total} rows")
        js(window, "const f = document.getElementById('typeFilter'); f.value = 'dni'; f.dispatchEvent(new Event('change'));")
        time.sleep(0.4)
        filtered = rows(window)
        js(window, "const f = document.getElementById('typeFilter'); f.value = ''; f.dispatchEvent(new Event('change'));")
        time.sleep(0.4)
        step("filter findings by type", 0 < filtered < total, f"{filtered} of {total}")
        key(window, "j")
        key(window, " ")
        time.sleep(0.5)
        toggled = excluded(window) == 1
        key(window, " ")
        time.sleep(0.5)
        step("J and Space shortcuts", toggled and excluded(window) == 0)
        js(window, "document.getElementById('btnAllOn').dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true}))")
        time.sleep(0.5)
        step("Space on a focused button is not taken by the shortcut", excluded(window) == 0)
        indicator = js(window, "document.getElementById('pageIndicator').textContent")
        key(window, "ArrowRight")
        wait_js(window, "document.getElementById('pageIndicator').textContent.includes('Página 2')", 30)
        key(window, "ArrowLeft")
        wait_js(window, "document.getElementById('pageIndicator').textContent.includes('Página 1')", 30)
        step("keyboard page navigation", "de 2" in indicator, indicator)

        # ---- manual zone drawn with the mouse, then deleted
        wait_js(window, "!document.getElementById('originalWrap').classList.contains('loading-preview') && document.getElementById('originalImg').complete", 30)
        before = rows(window)
        key(window, "m")
        js(window, """
            const wrap = document.getElementById('originalWrap');
            const r = wrap.getBoundingClientRect();
            const fire = (type, x, y) => wrap.dispatchEvent(new PointerEvent(type, {clientX: r.left + x, clientY: r.top + y,
              button: 0, pointerId: 1, bubbles: true}));
            fire('pointerdown', 40, r.height * 0.6); fire('pointermove', 200, r.height * 0.6 + 40);
            fire('pointerup', 200, r.height * 0.6 + 40);
        """)
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before + 1}", 30)
        has_manual = js(window, "[...document.querySelectorAll('#rowsBody .tok')].some(t => t.textContent.startsWith('[MANUAL'))")
        js(window, "[...document.querySelectorAll('#rowsBody button')].find(b => b.textContent === 'Borrar').click()")
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before}", 30)
        step("manual area selection and deletion", has_manual)
        click(window, "btnUndo")
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before + 1}", 30)
        click(window, "btnRedo")
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before}", 30)
        step("undo and redo review changes", True)
        js(window, "document.getElementById('manualForm').requestSubmit()")
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before + 1}", 30)
        step("keyboard coordinate zone creation", True)
        js(window, "[...document.querySelectorAll('#rowsBody tr')].find(row => row.querySelector('.tok').textContent.startsWith('[MANUAL')).click(); document.getElementById('manualWidth').value = '25'; document.getElementById('manualForm').requestSubmit()")
        wait_js(window, "[...document.querySelectorAll('#originalWrap .box.manual')].some(box => Math.abs(parseFloat(box.style.width) - 25) < 0.01)", 30)
        step("keyboard coordinate zone editing", True)
        js(window, "const z = document.getElementById('pageZoom'); z.value = '2'; z.dispatchEvent(new Event('change'))")
        wait_js(window, "document.getElementById('originalWrap').classList.contains('zoomed')", 30)
        step("page zoom keeps normalized overlays", js(window, "document.getElementById('originalWrap').style.width === '1190px'"))
        js(window, "const z = document.getElementById('pageZoom'); z.value = '0'; z.dispatchEvent(new Event('change'))")
        click(window, "btnUndo")
        wait_js(window, "[...document.querySelectorAll('#originalWrap .box.manual')].some(box => Math.abs(parseFloat(box.style.width) - 20) < 0.01)", 30)
        click(window, "btnUndo")
        wait_js(window, f"document.querySelectorAll('#rowsBody tr').length === {before}", 30)

        # ---- engine errors banner (integrity failure blocks the analysis)
        original_status = api.status
        api.status = lambda: {**original_status(), "errors": {"integrity": "Archivos alterados: prueba"}, "blocked": True}
        js(window, "window.app.refreshStatus()")
        wait_js(window, "!document.getElementById('engineErrors').hidden", 30)
        blocked = js(window, "document.getElementById('btnRun').disabled")
        api.status = original_status
        js(window, "window.app.refreshStatus()")
        wait_js(window, "document.getElementById('engineErrors').hidden", 30)
        step("integrity warning blocks analysis", blocked)

        # ---- leak boxes when a verification fails (simulated report)
        original_save = api.save_pdf
        fake_report = {"ok": False, "objects": 1, "pages": 2, "values": 1, "checks": [], "warnings": [],
                       "leaks": [{"check": "texto", "where": "página 1", "value": "12…", "detail": "texto extraíble",
                                  "page": 0, "view": [[0.2, 0.2, 0.5, 0.26]]}]}
        api.save_pdf = lambda *a, **k: {"ok": False, "report": fake_report, "message": "La verificación ha encontrado restos"}
        click(window, "btnPdf")
        wait_js(window, "document.querySelectorAll('#resultWrap .leak-box').length === 1", 30)
        step("remaining traces appear in red on the page", js(window, "document.getElementById('verifyCard').classList.contains('fail')"))
        shot(window, "3_leak")
        api.save_pdf = original_save

        # ---- real save (verified), logs and batch export
        saved = work / "salida.pdf"
        csv_path, json_path = work / "registro.csv", work / "registro.json"
        batch = work / "lote"
        batch.mkdir()
        api.attach(Dialogs(window, [str(saved), str(csv_path), str(json_path), [str(batch)]]))
        click(window, "btnPdf")
        wait_js(window, "document.getElementById('btnPdf').disabled", 30)
        key(window, "M")
        step("editing is blocked while saving", js(window,
             "document.getElementById('btnManual').disabled && "
             "document.getElementById('optMaxSecurity').disabled && "
             "document.getElementById('btnManual').getAttribute('aria-pressed') === 'false' && "
             "[...document.querySelectorAll('#rowsBody input')].every(input => input.disabled)"))
        wait_js(window, "document.getElementById('verifyCard').classList.contains('ok')", 600)
        wait_js(window, "!document.getElementById('btnPdf').disabled", 30)
        step("save verified PDF", saved.exists())
        click(window, "btnCsv")
        wait_for(csv_path.exists)
        click(window, "btnJson")
        wait_for(json_path.exists)
        time.sleep(0.5)
        logs = csv_path.read_text(encoding="utf-8") + json_path.read_text(encoding="utf-8")
        step("CSV and JSON logs omit original values", NAME not in logs and DNI not in logs and "[DNI" in logs)
        click(window, "btnAll")
        wait_for((batch / "informe_verificacion.json").exists, 900)
        report = json.loads((batch / "informe_verificacion.json").read_text(encoding="utf-8"))
        pdfs = list(batch.glob("*.pdf"))
        step("save all PDFs to a folder", len(pdfs) == 5 and all(d["ok"] for d in report["documentos"]), f"{len(pdfs)} PDF")
        wait_js(window, "!document.getElementById('batchResults').hidden", 30)
        step("batch shows individual saved results", js(window, "document.querySelectorAll('#batchList li').length === 5 && document.getElementById('batchSummary').textContent.includes('informe_verificacion')"))
        step("verification announcements are accessible", js(window, "document.getElementById('verifyCard').getAttribute('aria-live') === 'polite'"))

        # ---- maximum-security preview on the handwritten document
        select_document(window, "23_")
        js(window, "document.getElementById('resultImg').removeAttribute('src')")
        click(window, "optMaxSecurity")
        wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 180)
        step("maximum-security preview", True)
        same = "(() => { const o = document.getElementById('originalImg'), r = document.getElementById('resultImg');"                " return !!o.dataset.doc && o.dataset.doc === r.dataset.doc; })()"
        step("original and result show the same document", wait_js(window, same, 60))
        shot(window, "4_handwritten")
        window.resize(980, 640)
        time.sleep(0.8)
        shot(window, "5_compact")
        step("compact desktop has no horizontal page overflow", js(window, "document.documentElement.scrollWidth <= window.innerWidth"))
        window.resize(1480, 940)
        results["errors"] += js(window, "window.__errors") or []
        results["finished"] = True
    except Exception as error:
        results["errors"].append(f"{type(error).__name__}: {error}")
        shot(window, "error")
    finally:
        window.destroy()


def main():
    out = OUT / "ui_smoke.json"
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    api = Api(use_gpu="--gpu" in sys.argv)
    window = webview.create_window("Anonimato (prueba)", url=_ui_path().as_uri(), js_api=api, width=1480, height=940)
    api.attach(window)
    from app.engine.system import webview_gui
    webview.start(scenario, (window, api), gui=webview_gui(), private_mode=True)
    api.shutdown()
    if not results.get("finished") and not results["errors"]:
        results["errors"].append("The window closed before the scenario finished")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
