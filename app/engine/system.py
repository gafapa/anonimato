"""Everything that depends on the operating system, in one place.

Windows is the primary platform; macOS (Apple Silicon) and Linux (x86-64) are supported
with the equivalent native pieces:

                    Windows            macOS                 Linux
ONNX acceleration   DirectML           CoreML                CUDA / ROCm (if installed), else CPU
llama.cpp build     Vulkan             Metal                 Vulkan
Memory limit        Job Object         RLIMIT_AS (light)     RLIMIT_AS (light)
Window              WebView2           WKWebView             Qt WebEngine
User data           %LOCALAPPDATA%     ~/Library/App. Supp.  $XDG_DATA_HOME
"""
from __future__ import annotations

import os
import platform as _platform
import signal
import sys
from pathlib import Path

if sys.platform == "win32":
    SYSTEM = "windows"
elif sys.platform == "darwin":
    SYSTEM = "macos"
else:
    SYSTEM = "linux"

IS_WINDOWS = SYSTEM == "windows"


def exe(name: str) -> str:
    return name + ".exe" if IS_WINDOWS else name


def user_data_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        path = base / "Anonimato"
    elif SYSTEM == "macos":
        path = Path.home() / "Library" / "Application Support" / "Anonimato"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "anonimato"
    path.mkdir(parents=True, exist_ok=True)
    return path


def onnx_gpu_providers(available: list[str]) -> list[str]:
    """GPU execution providers to try first, in order, among those available."""
    preferred = {
        "windows": ["DmlExecutionProvider"],
        "macos": ["CoreMLExecutionProvider"],
        "linux": ["CUDAExecutionProvider", "ROCMExecutionProvider"],
    }[SYSTEM]
    return [p for p in preferred if p in available]


def webview_gui() -> str | None:
    return "edgechromium" if IS_WINDOWS else ("qt" if SYSTEM == "linux" else None)


def llama_env(runtime: Path) -> dict[str, str]:
    """Environment for llama-server: its shared libraries live next to it."""
    env = dict(os.environ)
    if SYSTEM == "linux":
        env["LD_LIBRARY_PATH"] = f"{runtime}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    elif SYSTEM == "macos":
        env["DYLD_LIBRARY_PATH"] = f"{runtime}:{env.get('DYLD_LIBRARY_PATH', '')}".rstrip(":")
    return env


def is_integrated_gpu(label: str) -> bool:
    return "Intel" in label and any(word in label for word in ("UHD", "Iris", "HD Graphics"))


def physical_memory_mb() -> int:
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.ullTotalPhys // (1024 * 1024))
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 16384


def child_setup(memory_limit_mb: int, limit_memory: bool) -> None:
    """Runs first inside an engine process on macOS/Linux.

    A new process group lets the parent kill the engine together with anything it started
    (llama-server). The address-space limit is only applied to the light engine: GPU drivers
    reserve huge virtual ranges, so limiting the model engine would break GPU acceleration.
    """
    if IS_WINDOWS:
        return
    try:
        os.setsid()
    except OSError:
        pass
    if limit_memory:
        import resource
        limit = memory_limit_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass


def kill_process_tree(pid: int) -> None:
    """macOS/Linux: kill the engine's process group (Windows uses the Job Object)."""
    if IS_WINDOWS or not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# Fonts used by the test corpus, the evaluation tools and the benchmark (not by the app itself).
_FONTS = {
    "windows": {"sans": ["C:/Windows/Fonts/arial.ttf"], "serif": ["C:/Windows/Fonts/times.ttf"],
                "hand": ["C:/Windows/Fonts/Inkfree.ttf", "C:/Windows/Fonts/segoesc.ttf"],
                "hand2": ["C:/Windows/Fonts/segoesc.ttf"], "hand3": ["C:/Windows/Fonts/segoepr.ttf"],
                "comic": ["C:/Windows/Fonts/comic.ttf"]},
    "macos": {"sans": ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"],
              "serif": ["/System/Library/Fonts/Supplemental/Times New Roman.ttf"],
              "hand": ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
                       "/System/Library/Fonts/Supplemental/Chalkduster.ttf"],
              "hand2": ["/System/Library/Fonts/Supplemental/Chalkduster.ttf"],
              "hand3": ["/System/Library/Fonts/Supplemental/Trattatello.ttf"],
              "comic": ["/System/Library/Fonts/Supplemental/Comic Sans MS.ttf"]},
    "linux": {"sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
              "serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"],
              "hand": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
              "hand2": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"],
              "hand3": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf"],
              "comic": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]},
}


def font(kind: str) -> str:
    """Path of a TrueType font of the given kind: sans, serif, hand, hand2, hand3, comic."""
    for candidate in _FONTS[SYSTEM].get(kind, []) + _FONTS[SYSTEM]["sans"]:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(f"No hay ninguna fuente «{kind}» instalada en {SYSTEM}")


def description() -> str:
    return f"{SYSTEM} {_platform.machine()}"
