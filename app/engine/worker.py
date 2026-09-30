"""Isolated engine processes.

Every operation that parses a document (untrusted input) runs in a child process:
  * limited memory (Windows Job Object; child processes such as llama-server are included),
  * stall watchdog: if no progress is reported for a while, the process is killed,
  * a crash or a kill never takes the window down: the process is restarted and the
    operation fails with a clear message.

Two processes are used: a heavy one with the AI models (analysis and export) and a light
one without models (page previews, unlocking), so the review stays responsive while a
document is being analysed.
"""
from __future__ import annotations

import ctypes
import multiprocessing as mp
import os
import threading
import time
import traceback
from ctypes import wintypes
from collections.abc import Callable


class EngineError(RuntimeError):
    """The operation failed inside the engine (message suitable for the user)."""

    def __init__(self, message: str, kind: str = ""):
        super().__init__(message)
        self.kind = kind


class EngineCrashed(EngineError):
    pass


class EngineTimeout(EngineError):
    pass


# ------------------------------------------------------------------ Windows job object
class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_ALL_ACCESS = 0x1F0FFF


class JobObject:
    """Kill-on-close job with a per-process memory limit (no-op outside Windows)."""

    def __init__(self, memory_limit_mb: int):
        self.handle = None
        if os.name != "nt":
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.handle = kernel32.CreateJobObjectW(None, None)
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        info.ProcessMemoryLimit = memory_limit_mb * 1024 * 1024
        kernel32.SetInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                         ctypes.byref(info), ctypes.sizeof(info))

    def assign(self, pid: int) -> None:
        if not self.handle:
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if process:
            kernel32.AssignProcessToJobObject(self.handle, process)
            kernel32.CloseHandle(process)

    def close(self) -> None:
        """Terminates every process in the job (the engine and e.g. llama-server)."""
        if self.handle:
            ctypes.windll.kernel32.TerminateJobObject(self.handle, 1)
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


# ------------------------------------------------------------------ child side
def _handlers():
    from . import document, pipeline, rasterize, redact, sanitize

    def analyze(ctx, data, filename, options):
        ctx.services.require_integrity(ctx.progress)
        ctx.cancel.clear()
        return pipeline.analyze(data, filename, options, ctx.services, ctx.progress, ctx.cancel.is_set)

    def export(ctx, analysis, options, index, keep_name):
        ctx.services.require_integrity(ctx.progress)
        return pipeline.export(analysis, options, ctx.services, ctx.progress, index=index, keep_name=keep_name)

    def build_preview(ctx, analysis, options):
        import pymupdf
        doc = pymupdf.open("pdf", analysis.working)
        redact.apply(doc, analysis.findings, options.mode, options.uniform_tokens)
        data = sanitize.sanitize(redact.render_output(doc.tobytes()))
        doc.close()
        if options.max_security:
            data = sanitize.sanitize(rasterize.rasterize(data, options.raster_dpi, None))
        return data

    def page_png(ctx, data, page, width):
        return pipeline.preview(data, page, width)

    def unlock(ctx, data, password):
        return document.unlock(data, password)

    def status(ctx):
        return ctx.services.status() if ctx.services else {}

    def integrity(ctx):
        return ctx.services.check_integrity() if ctx.services else True

    def reload_models(ctx):
        if ctx.services is not None:
            ctx.services.reset_advanced()
            if not ctx.services.check_integrity(force=True):
                raise RuntimeError(ctx.services.errors["integrity"])
        return True

    def ping(ctx):
        return os.getpid()

    # Test hooks (used by tests/test_worker.py).
    def _test_crash(ctx):
        os._exit(3)

    def _test_hang(ctx, seconds):
        time.sleep(seconds)

    def _test_alloc(ctx, megabytes):
        blocks = [bytearray(1024 * 1024) for _ in range(megabytes)]
        return len(blocks)

    return {name: fn for name, fn in locals().items() if callable(fn)}


class _Context:
    def __init__(self, conn, cancel, services):
        self.conn = conn
        self.cancel = cancel
        self.services = services

    def progress(self, event: dict) -> None:
        self.conn.send(("progress", event))


def serve(conn, cancel, use_gpu: bool, with_models: bool, memory_limit_mb: int = 0) -> None:
    from .system import child_setup
    child_setup(memory_limit_mb, limit_memory=not with_models)
    debug_log = os.environ.get("ANONIMATO_DEBUG_LOG")
    if debug_log:  # diagnostics only: periodic stack dumps of every thread (no document content)
        import faulthandler
        import sys as _sys
        handle = open(f"{debug_log}.{os.getpid()}.txt", "w", encoding="utf-8")
        _sys.stderr = handle
        faulthandler.enable(handle)
        faulthandler.dump_traceback_later(20, repeat=True, file=handle)
    services = None
    if with_models:
        from .services import Services
        services = Services(use_gpu=use_gpu)
        services.warm_up()
    handlers = _handlers()
    ctx = _Context(conn, cancel, services)
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            break
        if message is None:
            break
        op, args = message
        try:
            conn.send(("result", handlers[op](ctx, *args)))
        except MemoryError:
            conn.send(("error", {"kind": "MemoryError", "message":
                                 "El documento necesita más memoria de la permitida para procesarse con seguridad"}))
        except BaseException as error:  # reported to the parent
            name = type(error).__name__
            if name == "Cancelled":
                conn.send(("cancelled", None))
            else:
                traceback.print_exc()
                conn.send(("error", {"kind": name, "message": str(error) or name}))
    if services is not None:
        services.shutdown()


# ------------------------------------------------------------------ parent side
class EngineProcess:
    def __init__(self, with_models: bool = True, use_gpu: bool = True, memory_limit_mb: int | None = None,
                 stall_seconds: float = 900):
        self.with_models = with_models
        self.use_gpu = use_gpu
        from .system import physical_memory_mb
        total = physical_memory_mb()
        self.memory_limit_mb = memory_limit_mb or max(2048, min(16384, int(total * 0.7)))
        self.stall_seconds = stall_seconds
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._process = None
        self._conn = None
        self._job: JobObject | None = None
        self.cancel = self._ctx.Event()
        self.restarts = 0
        self.gpu_disabled = ""   # reason, when the engine fell back to the CPU

    def _start(self) -> None:
        parent, child = self._ctx.Pipe()
        process = self._ctx.Process(target=serve, args=(child, self.cancel, self.use_gpu, self.with_models,
                                                        self.memory_limit_mb),
                                    daemon=True, name="anonimato-engine")
        process.start()
        child.close()
        self._job = JobObject(self.memory_limit_mb)
        self._job.assign(process.pid)
        self._process, self._conn = process, parent

    def _kill(self) -> None:
        if self._job is not None:
            self._job.close()
            self._job = None
        if self._process is not None:
            from .system import kill_process_tree
            kill_process_tree(self._process.pid)  # macOS/Linux: the engine and its llama-server
            if self._process.is_alive():
                self._process.kill()
            self._process.join(5)
        if self._conn is not None:
            self._conn.close()
        self._process = self._conn = None

    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def ensure_started(self) -> None:
        with self._lock:
            if not self.alive():
                self._kill()
                self._start()

    def call(self, op: str, *args, progress: Callable[[dict], None] | None = None,
             stall_seconds: float | None = None):
        """Run an operation in the engine. If the GPU stops responding while the models are being
        prepared, the engine restarts on the CPU and the operation is retried once."""
        try:
            return self._call(op, *args, progress=progress, stall_seconds=stall_seconds)
        except EngineError as error:
            gpu_hang = error.kind == "WarmupTimeout" or (isinstance(error, EngineTimeout) and op in ("analyze", "export"))
            if not (gpu_hang and self.with_models and self.use_gpu):
                raise
            self.use_gpu = False
            self.gpu_disabled = "La tarjeta gráfica no respondía: se continúa en modo CPU (más lento)"
            with self._lock:
                self._restart()
            if progress:
                progress({"stage": "prepare", "message": self.gpu_disabled})
            return self._call(op, *args, progress=progress, stall_seconds=stall_seconds)

    def _call(self, op: str, *args, progress: Callable[[dict], None] | None = None,
              stall_seconds: float | None = None):
        stall = stall_seconds or self.stall_seconds
        with self._lock:
            if not self.alive():
                self._kill()
                self._start()
            try:
                self._conn.send((op, args))
            except (OSError, EOFError) as error:
                self._restart()
                raise EngineCrashed("El motor se detuvo inesperadamente") from error
            deadline = time.time() + stall
            while True:
                try:
                    ready = self._conn.poll(0.25)
                except (OSError, EOFError):
                    ready = False
                    self._process.join(0.1)
                if ready:
                    try:
                        kind, payload = self._conn.recv()
                    except (OSError, EOFError) as error:
                        self._restart()
                        raise EngineCrashed("El motor se detuvo inesperadamente al procesar el documento") from error
                    if kind == "progress":
                        deadline = time.time() + stall
                        if progress:
                            progress(payload)
                        continue
                    if kind == "result":
                        return payload
                    if kind == "cancelled":
                        from .pipeline import Cancelled
                        raise Cancelled()
                    raise EngineError(payload.get("message", ""), payload.get("kind", ""))
                if not self._process.is_alive():
                    self._restart()
                    raise EngineCrashed("El motor se detuvo al procesar este documento (archivo dañado o malicioso, "
                                        "o sin memoria suficiente). El resto de la aplicación sigue funcionando.")
                if time.time() > deadline:
                    self._restart()
                    raise EngineTimeout("El documento dejó de avanzar y se ha detenido su procesamiento "
                                        "(posible archivo malicioso o demasiado complejo).")

    def _restart(self) -> None:
        self.restarts += 1
        self._kill()
        self._start()

    def stop(self) -> None:
        with self._lock:
            if self.alive():
                try:
                    self._conn.send(None)
                    self._process.join(10)
                except (OSError, EOFError):
                    pass
            self._kill()
