"""Bridge between the window (JavaScript) and the engine.

The window process never parses a document: analysis, export and previews run in
isolated engine processes (see engine/worker.py). Everything stays in memory; the only
files written are the ones the user saves.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .engine import document, llm_server, logs, models, pipeline, rules
from .engine.types import Options
from .engine.worker import EngineError, EngineProcess

VERSION = "2.1.0"


@dataclass
class Doc:
    id: str
    name: str
    size: int
    data: bytes
    status: str = "pending"          # pending | processing | ready | failed | locked
    error: str = ""
    analysis: pipeline.Analysis | None = None
    preview_key: str = ""
    preview_bytes: bytes | None = None
    report: dict | None = None


@dataclass
class State:
    docs: dict[str, Doc] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    busy: bool = False
    cancel: bool = False
    progress: dict = field(default_factory=dict)
    install: dict = field(default_factory=dict)
    counter: int = 0


def _options(raw: dict) -> Options:
    categories = set(raw.get("categories") or (set(rules.SELECTABLE) - rules.DEFAULT_OFF))
    categories |= {"manual"}
    return Options(
        categories=categories,
        ocr=bool(raw.get("ocr", True)),
        handwriting=bool(raw.get("handwriting", True)),
        ai=bool(raw.get("ai", True)),
        llm_review=bool(raw.get("llmReview", True)),
        faces=bool(raw.get("faces", True)),
        signatures=bool(raw.get("signatures", True)),
        propagate=bool(raw.get("propagate", True)),
        mode=raw.get("mode", "label"),
        max_security=bool(raw.get("maxSecurity", False)),
        ocr_text_layer=bool(raw.get("textLayer", True)),
        uniform_tokens=bool(raw.get("uniform", False)),
        dpi=int(raw.get("dpi", 200)),
    )


def _transform(matrix: tuple, rect) -> tuple[float, float, float, float]:
    a, b, c, d, e, f = matrix
    xs, ys = [], []
    for x, y in ((rect[0], rect[1]), (rect[2], rect[1]), (rect[0], rect[3]), (rect[2], rect[3])):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return min(xs), min(ys), max(xs), max(ys)


def _invert(matrix: tuple) -> tuple:
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_)


class Api:
    def __init__(self, use_gpu: bool = True, engine: EngineProcess | None = None, light: EngineProcess | None = None):
        self._engine = engine or EngineProcess(with_models=True, use_gpu=use_gpu)
        self._light = light or EngineProcess(with_models=False, use_gpu=False, stall_seconds=180)
        self._state = State()
        self._lock = threading.RLock()
        self._window = None
        self._status_cache: dict | None = None
        threading.Thread(target=self._engine.ensure_started, daemon=True).start()
        threading.Thread(target=self._light.ensure_started, daemon=True).start()

    def attach(self, window) -> None:
        self._window = window

    def shutdown(self) -> None:
        self._engine.stop()
        self._light.stop()

    # ------------------------------------------------------------ status
    def _engine_status(self) -> dict:
        if self._state.busy and self._status_cache is not None:
            return self._status_cache
        try:
            status = self._engine.call("status", stall_seconds=600)
        except EngineError as error:
            status = {"base": False, "advanced": False, "gpu": False, "errors": {"engine": str(error)}}
        if self._engine.gpu_disabled:
            status = {**status, "gpu": False, "errors": {**status.get("errors", {}), "gpu": self._engine.gpu_disabled}}
        self._status_cache = status
        return status

    def status(self) -> dict:
        variant = llm_server.installed_variant() or llm_server.recommended_variant()
        services = self._engine_status()
        return {
            "version": VERSION,
            "services": services,
            "errors": services.get("errors", {}),
            "blocked": "integrity" in services.get("errors", {}),
            "advancedInstalled": llm_server.available(),
            "advancedVariant": variant,
            "advancedLabel": "Qwen3-VL 8B · ≈ 5,5 GB" if variant == "advanced" else "Qwen3-VL 4B · ≈ 2,8 GB",
            "categories": [
                {"key": key, "label": value["label"], "token": value["token"], "default": key not in rules.DEFAULT_OFF}
                for key, value in rules.CATEGORIES.items() if key in rules.SELECTABLE
            ],
        }

    # ------------------------------------------------------------ documents
    def _add_path(self, path: Path) -> dict | None:
        suffix = path.suffix.lower()
        if suffix != ".pdf" and suffix not in document.IMAGE_SUFFIXES:
            return None
        data = path.read_bytes()
        with self._lock:
            self._state.counter += 1
            doc = Doc(id=f"d{self._state.counter}", name=path.name, size=len(data), data=data)
            self._state.docs[doc.id] = doc
            self._state.order.append(doc.id)
        return self._doc_summary(doc)

    def pick_files(self) -> list[dict]:
        import webview
        paths = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Documentos (*.pdf;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp)", "Todos los archivos (*.*)"))
        return [s for s in (self._add_path(Path(p)) for p in (paths or [])) if s]

    def pick_folder(self, recursive: bool = False) -> list[dict]:
        import webview
        folders = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not folders:
            return []
        root = Path(folders[0])
        items = root.rglob("*") if recursive else root.glob("*")
        return [s for s in (self._add_path(p) for p in sorted(items) if p.is_file()) if s]

    def add_paths(self, paths: list[str]) -> list[dict]:
        out = []
        for raw in paths or []:
            path = Path(raw)
            if path.is_dir():
                out += [s for s in (self._add_path(p) for p in sorted(path.glob("*")) if p.is_file()) if s]
            elif path.is_file():
                summary = self._add_path(path)
                if summary:
                    out.append(summary)
        return out

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.docs.pop(doc_id, None)
            if doc_id in self._state.order:
                self._state.order.remove(doc_id)
        return True

    def clear(self) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.docs.clear()
            self._state.order.clear()
        return True

    def _doc_summary(self, doc: Doc) -> dict:
        analysis = doc.analysis
        return {
            "id": doc.id, "name": doc.name, "size": doc.size, "status": doc.status, "error": doc.error,
            "pages": len(analysis.pages) if analysis else None,
            "findings": len(analysis.findings) if analysis else None,
        }

    def documents(self) -> list[dict]:
        with self._lock:
            return [self._doc_summary(self._state.docs[i]) for i in self._state.order]

    def unlock(self, doc_id: str, password: str) -> dict:
        """Decrypt a password-protected PDF (in the isolated process); the output is never encrypted."""
        doc = self._state.docs[doc_id]
        try:
            doc.data = self._light.call("unlock", doc.data, password)
        except EngineError as error:
            return {"ok": False, "message": str(error)}
        doc.status, doc.error, doc.size = "pending", "", len(doc.data)
        return {"ok": True}

    # ------------------------------------------------------------ processing
    def process(self, raw_options: dict, only: list[str] | None = None) -> bool:
        if self.status().get("blocked"):
            self._state.progress = {"message": "Modelos alterados: reinstala la aplicación", "percent": 0}
            return False
        with self._lock:
            if self._state.busy:
                return False
            self._state.busy = True
            self._state.cancel = False
            self._state.progress = {"message": "Preparando…", "percent": 0}
        self._engine.cancel.clear()
        options = _options(raw_options)
        targets = only or [i for i in self._state.order if self._state.docs[i].status != "locked"]
        threading.Thread(target=self._run, args=(targets, options), daemon=True).start()
        return True

    def cancel(self) -> None:
        self._state.cancel = True
        self._engine.cancel.set()

    def _run(self, targets: list[str], options: Options) -> None:
        try:
            total = len(targets)
            for position, doc_id in enumerate(targets):
                doc = self._state.docs.get(doc_id)
                if doc is None:
                    continue
                if self._state.cancel:
                    break
                doc.status, doc.error = "processing", ""
                doc.preview_bytes, doc.preview_key, doc.report = None, "", None

                def progress(event: dict, position=position, doc=doc) -> None:
                    page, pages = event.get("page"), event.get("total")
                    fraction = (page - 0.5) / pages if page and pages else 0.0
                    self._state.progress = {
                        "doc": doc.id, "name": doc.name, "message": event.get("message", ""),
                        "percent": round(100 * (position + min(1.0, fraction)) / max(1, total), 1),
                    }

                try:
                    doc.analysis = self._engine.call("analyze", doc.data, doc.name, options, progress=progress)
                    doc.status = "ready"
                except pipeline.Cancelled:
                    doc.status, doc.error = "pending", ""
                except EngineError as error:
                    if error.kind == "PasswordRequired":
                        doc.status, doc.error = "locked", "Protegido con contraseña"
                    else:
                        doc.status, doc.error = "failed", str(error)
        finally:
            with self._lock:
                self._state.busy = False
                self._state.progress = {"message": "", "percent": 100}

    def poll(self) -> dict:
        return {"busy": self._state.busy, "progress": self._state.progress, "documents": self.documents(),
                "install": self._state.install}

    # ------------------------------------------------------------ review
    def _analysis(self, doc_id: str) -> tuple[Doc, pipeline.Analysis]:
        doc = self._state.docs[doc_id]
        if doc.analysis is None:
            raise ValueError("El documento no está analizado")
        return doc, doc.analysis

    def _view_rects(self, analysis: pipeline.Analysis, page: int, rects) -> list[list[float]]:
        """Unrotated page rects -> normalised rects on the displayed (rotated) page."""
        info = analysis.pages[page]
        out = []
        for rect in rects:
            x0, y0, x1, y1 = _transform(info.matrix, rect)
            out.append([x0 / info.width, y0 / info.height, x1 / info.width, y1 / info.height])
        return out

    def _report_view(self, analysis: pipeline.Analysis, report: dict | None) -> dict | None:
        if not report:
            return report
        for leak in report.get("leaks", []):
            page = leak.get("page")
            if page is not None and 0 <= page < len(analysis.pages):
                leak["view"] = self._view_rects(analysis, page, leak.get("rects", []))
            leak.pop("rects", None)
        return report

    def details(self, doc_id: str) -> dict:
        doc, analysis = self._analysis(doc_id)
        findings = []
        for f in analysis.findings:
            data = f.to_json()
            data["label"] = rules.CATEGORIES[f.type]["label"]
            data["view"] = self._view_rects(analysis, f.page, f.rects)
            del data["rects"]
            findings.append(data)
        return {
            "id": doc.id, "name": doc.name, "pages": [{"width": p.width, "height": p.height} for p in analysis.pages],
            "findings": findings, "notes": analysis.notes, "seconds": analysis.seconds,
            "nativeChars": analysis.native_chars, "report": doc.report, "signed": analysis.signed,
        }

    def set_enabled(self, doc_id: str, finding_ids: list[str], enabled: bool) -> int:
        _, analysis = self._analysis(doc_id)
        wanted = set(finding_ids)
        count = 0
        for f in analysis.findings:
            if f.id in wanted:
                f.enabled = bool(enabled)
                count += 1
        return count

    def add_manual(self, doc_id: str, page: int, view_rect: list[float]) -> dict:
        _, analysis = self._analysis(doc_id)
        info = analysis.pages[page]
        shown = (view_rect[0] * info.width, view_rect[1] * info.height, view_rect[2] * info.width, view_rect[3] * info.height)
        finding = pipeline.add_manual(analysis, page, _transform(_invert(info.matrix), shown))
        data = finding.to_json()
        data["label"] = rules.CATEGORIES["manual"]["label"]
        data["view"] = self._view_rects(analysis, page, finding.rects)
        del data["rects"]
        return data

    def remove_manual(self, doc_id: str, finding_id: str) -> bool:
        _, analysis = self._analysis(doc_id)
        before = len(analysis.findings)
        analysis.findings = [f for f in analysis.findings if not (f.id == finding_id and f.type == "manual")]
        return len(analysis.findings) < before

    # ------------------------------------------------------------ previews
    def _state_key(self, analysis: pipeline.Analysis, options: Options) -> str:
        enabled = ",".join(sorted(f.id + str(f.rects) for f in analysis.findings if f.enabled))
        return f"{options.mode}|{options.max_security}|{options.uniform_tokens}|{enabled}"

    def page_image(self, doc_id: str, page: int, which: str, raw_options: dict) -> str:
        doc, analysis = self._analysis(doc_id)
        if which == "original":
            data = analysis.working
        else:
            options = _options(raw_options)
            key = self._state_key(analysis, options)
            if doc.preview_key != key or doc.preview_bytes is None:
                # Exactly the pipeline used for saving, minus the (slow) verification.
                doc.preview_bytes = self._light.call("build_preview", analysis, options)
                doc.preview_key = key
            data = doc.preview_bytes
        png = self._light.call("page_png", data, page, 1100)
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    # ------------------------------------------------------------ export
    def _export(self, doc: Doc, options: Options, index: int, keep_name: bool, share: tuple[int, int] = (0, 1)):
        def progress(event: dict) -> None:
            page, pages = event.get("page"), event.get("total")
            fraction = page / pages if page and pages else 0.0
            self._state.progress = {"message": f"{doc.name}: {event.get('message', '')}",
                                    "percent": round(100 * (share[0] + fraction) / max(1, share[1]), 1)}

        result = self._engine.call("export", doc.analysis, options, index, keep_name, progress=progress)
        doc.report = self._report_view(doc.analysis, result.report.to_json())
        return result

    def _begin(self) -> bool:
        with self._lock:
            if self._state.busy:
                return False
            self._state.busy = True
            self._state.progress = {"message": "Generando y verificando…", "percent": 0}
            return True

    def _end(self) -> None:
        with self._lock:
            self._state.busy = False
            self._state.progress = {"message": "", "percent": 100}

    def save_pdf(self, doc_id: str, raw_options: dict) -> dict:
        import webview
        doc, _ = self._analysis(doc_id)
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        index = self._state.order.index(doc_id) + 1
        if not self._begin():
            return {"ok": False, "message": "Hay un proceso en curso"}
        try:
            try:
                result = self._export(doc, options, index, keep)
            except EngineError as error:
                return {"ok": False, "message": f"No se pudo generar el PDF: {error}"}
            if not result.report.ok:
                return {"ok": False, "report": doc.report,
                        "message": "La verificación ha encontrado restos del dato original. No se ha guardado nada."}
            target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=result.filename,
                                                     file_types=("PDF (*.pdf)",))
            if not target:
                return {"ok": True, "saved": False, "report": doc.report}
            path = Path(target if isinstance(target, str) else target[0])
            path.write_bytes(result.data)
            return {"ok": True, "saved": True, "path": str(path), "report": doc.report}
        finally:
            self._end()

    def save_all(self, raw_options: dict) -> dict:
        import webview
        folders = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not folders:
            return {"ok": True, "saved": 0, "results": []}
        return self.export_folder(folders[0], raw_options)

    def export_folder(self, folder: str, raw_options: dict) -> dict:
        options = _options(raw_options)
        keep = bool(raw_options.get("keepName", False))
        root = Path(folder)
        results = []
        if not self._begin():
            return {"ok": False, "message": "Hay un proceso en curso"}
        try:
            ready = [self._state.docs[i] for i in self._state.order if self._state.docs[i].status == "ready"]
            for position, doc in enumerate(ready):
                number = self._state.order.index(doc.id) + 1
                entry = {"documento": f"documento-{number}"}
                try:
                    result = self._export(doc, options, number, keep, share=(position, len(ready)))
                except EngineError as error:
                    entry.update(ok=False, error=str(error))
                    results.append(entry)
                    continue
                entry.update(ok=result.report.ok, verificacion=doc.report)
                if result.report.ok:
                    path = root / result.filename
                    counter = 2
                    while path.exists():
                        path = root / result.filename.replace("_anonimizado.pdf", f"_anonimizado_{counter}.pdf")
                        counter += 1
                    path.write_bytes(result.data)
                    entry["archivo"] = path.name
                results.append(entry)
            (root / "informe_verificacion.json").write_text(json.dumps(
                {"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "documentos": results}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return {"ok": all(r["ok"] for r in results), "saved": sum(1 for r in results if r["ok"]),
                    "failed": sum(1 for r in results if not r["ok"]), "folder": str(root)}
        finally:
            self._end()

    def save_log(self, doc_id: str, fmt: str, include_originals: bool, include_coords: bool) -> dict:
        import webview
        doc, analysis = self._analysis(doc_id)
        index = self._state.order.index(doc_id) + 1
        if fmt == "csv":
            content = logs.build_csv(analysis.findings, include_originals, include_coords)
            name, types = f"documento-{index}_registro.csv", ("CSV (*.csv)",)
        else:
            content = logs.build_json(analysis.findings, len(analysis.pages), doc.report, include_originals, include_coords)
            name, types = f"documento-{index}_registro.json", ("JSON (*.json)",)
        target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=types)
        if not target:
            return {"saved": False}
        path = Path(target if isinstance(target, str) else target[0])
        path.write_text(content, encoding="utf-8")
        return {"saved": True, "path": str(path)}

    # ------------------------------------------------------------ advanced models
    def install_advanced(self) -> bool:
        if self._state.install.get("running"):
            return False
        self._state.install = {"running": True, "message": "Descargando…", "percent": 0}
        threading.Thread(target=self._install, daemon=True).start()
        return True

    def _install(self, group: str | None = None) -> None:
        try:
            items = models.load_manifest()[group or llm_server.recommended_variant()]
            sizes: dict[str, tuple[int, int]] = {}

            def progress(model_id: str, done: int, total: int) -> None:
                sizes[model_id] = (done, total)
                got = sum(d for d, _ in sizes.values())
                tot = sum(t for _, t in sizes.values()) or 1
                self._state.install = {"running": True, "percent": round(100 * got / tot, 1),
                                       "message": f"Descargando modelos de IA ({got >> 20} MB)"}

            for item in items:
                models.download(item, progress)
            self._engine.call("reload_models")
            self._status_cache = None
            self._state.install = {"running": False, "done": True, "percent": 100, "message": "IA avanzada instalada"}
        except Exception as error:  # noqa: BLE001
            self._state.install = {"running": False, "error": str(error), "message": f"Error: {error}"}

    def import_advanced(self) -> dict:
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Paquete de IA (*.zip)",))
        if not paths:
            return {"ok": False}
        try:
            models.import_zip(Path(paths[0]))
            self._engine.call("reload_models")
            self._status_cache = None
            return {"ok": True}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "message": str(error)}
