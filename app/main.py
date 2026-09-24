"""Desktop entry point: native window (WebView2) with the local interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ui_path() -> Path:
    from .engine.models import app_root
    return app_root() / "app" / "ui" / "index.html"


def main() -> None:
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
