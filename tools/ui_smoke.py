"""Drive the real window: add documents, analyse, review, save; capture screenshots and JS errors.

Usage: uv run python tools/ui_smoke.py [--gpu]
Screenshots: tmp/ui_*.png
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from app.api import Api  # noqa: E402
from app.engine.services import Services  # noqa: E402
from app.main import _ui_path  # noqa: E402
from tests.fixtures.generate import build_all  # noqa: E402

OUT = ROOT / "tmp"
results = {"errors": [], "steps": []}


def shot(window, name):
    """Capture only this window's own content (PrintWindow), never the rest of the screen."""
    time.sleep(0.8)
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
        user32.PrintWindow(hwnd, memdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

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
    except Exception as error:  # noqa: BLE001
        results["errors"].append(f"screenshot {name}: {error}")


def js(window, code):
    return window.evaluate_js(code)


def wait_js(window, condition, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js(window, condition):
            return True
        time.sleep(0.5)
    raise TimeoutError(condition)


def scenario(window, api):
    try:
        wait_js(window, "!!(window.pywebview && window.app && document.querySelectorAll('#catGrid input').length)", 120)
        js(window, "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
                   "window.addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));")
        shot(window, "0_start")
        folder = Path(tempfile.mkdtemp())
        fixtures = {f.number: f for f in build_all()}
        for number in (22, 23, 10):
            (folder / fixtures[number].filename).write_bytes(fixtures[number].data)
        api.add_paths([str(folder)])
        js(window, "window.app.refreshDocuments()")
        wait_js(window, "document.querySelectorAll('.document-item').length === 3")
        results["steps"].append("3 documentos en la cola")
        js(window, "document.getElementById('btnRun').click()")
        time.sleep(1)
        shot(window, "1_processing")
        wait_js(window, "!document.getElementById('resultsCard').hidden && document.querySelectorAll('#rowsBody tr').length > 0")
        wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 120)
        results["steps"].append("análisis terminado y revisión visible")
        shot(window, "2_review")
        rows = js(window, "document.querySelectorAll('#rowsBody tr').length")
        boxes = js(window, "document.querySelectorAll('#originalWrap .box').length")
        results["steps"].append(f"{rows} filas, {boxes} cajas en la página")
        js(window, "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j'}))")
        js(window, "document.dispatchEvent(new KeyboardEvent('keydown', {key: ' '}))")
        time.sleep(0.5)
        off = js(window, "document.querySelectorAll('#rowsBody tr.off').length")
        results["steps"].append(f"atajo J + Espacio: {off} fila(s) excluidas")
        js(window, "document.dispatchEvent(new KeyboardEvent('keydown', {key: ' '}))")
        js(window, "document.querySelectorAll('.document-select')[2].click()")
        wait_js(window, "document.getElementById('currentFileName').textContent.includes('23_')", 60)
        wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 120)
        shot(window, "3_handwritten")
        js(window, "document.getElementById('optMaxSecurity').click()")
        wait_js(window, "!!document.getElementById('resultImg').getAttribute('src')", 180)
        results["steps"].append("vista previa en máxima seguridad")
        target = OUT / "ui_saved.pdf"
        target.unlink(missing_ok=True)

        class Dialogs:
            title = window.title

            def __getattr__(self, name):
                return getattr(window, name)

            def create_file_dialog(self, *args, **kwargs):
                return str(target)

        api.attach(Dialogs())
        js(window, "document.getElementById('btnPdf').click()")
        wait_js(window, "!document.getElementById('verifyCard').hidden", 300)
        verify_text = js(window, "document.getElementById('verifyCard').textContent")
        results["steps"].append(f"guardado: {target.exists()} · {verify_text[:120]}")
        shot(window, "4_saved")
        results["errors"] += js(window, "window.__errors") or []
    except Exception as error:  # noqa: BLE001
        results["errors"].append(f"{type(error).__name__}: {error}")
        shot(window, "error")
    finally:
        (OUT / "ui_smoke.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        window.destroy()


def main():
    services = Services(use_gpu="--gpu" in sys.argv)
    api = Api(services)
    window = webview.create_window("Anonimato (prueba)", url=_ui_path().as_uri(), js_api=api, width=1480, height=940)
    api.attach(window)
    webview.start(scenario, (window, api), gui="edgechromium", private_mode=True)
    services.shutdown()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
