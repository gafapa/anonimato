"""Local llama.cpp server (Vulkan) for the vision-language model.

Listens only on 127.0.0.1, on a random port, protected with a random per-session
key, and is terminated together with the application.
"""
from __future__ import annotations

import atexit
import base64
import io
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from . import models, system

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


# Neither system proxies nor HTTP redirects may send document content away from loopback.
_LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _exe() -> str:
    return str(models.runtime_dir() / "llama" / system.exe("llama-server"))


def installed_variant() -> str | None:
    """Advanced pack installed: "advanced" (Qwen3-VL-8B) is preferred over "advanced_lite" (4B)."""
    for group in ("advanced", "advanced_lite"):
        if models.group_installed(group):
            return group
    return None


def choose_variant(available: list[str], mode: str, free_vram: int, ram: int) -> str:
    """Select among installed packs; preserve an explicit accuracy choice even on CPU."""
    if mode not in ("auto", "accuracy", "memory") or not available:
        raise RuntimeError("No hay un modelo avanzado disponible para esta configuración")
    preferred = "advanced" if mode == "accuracy" or (mode == "auto" and free_vram >= 7000) else "advanced_lite"
    selected = preferred if preferred in available else available[0]
    required_vram = 7000 if selected == "advanced" else 3000
    required_ram = 16384 if selected == "advanced" else 8192
    if mode == "auto" and free_vram < required_vram and ram < required_ram:
        raise RuntimeError("No hay memoria suficiente para el modelo instalado. Usa el paquete 4B o libera memoria.")
    return selected


def recommended_variant() -> str:
    """8B needs about 7 GB of free video memory; smaller GPUs get the 4B model."""
    _, free = pick_device(_exe()) if os.path.exists(_exe()) else (None, 0)
    return "advanced" if free >= 7000 else "advanced_lite"


def available() -> bool:
    return os.path.exists(_exe()) and installed_variant() is not None


def pick_device(exe: str) -> tuple[str | None, int]:
    """Best discrete GPU (most free memory, not an integrated Intel GPU)."""
    bad = models.verify_runtime()
    if bad:
        raise RuntimeError("Motor de IA alterado o incompleto: " + ", ".join(bad))
    try:
        output = subprocess.run([exe, "--list-devices"], capture_output=True, text=True, timeout=60, check=False,
                                creationflags=CREATE_NO_WINDOW, env=system.llama_env(Path(exe).parent)).stdout
    except Exception:
        return None, 0
    best, best_free = None, 0
    for line in output.splitlines():
        match = re.match(r"\s*(\w+\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", line)
        if not match:
            continue
        name, label, free = match.group(1), match.group(2), int(match.group(4))
        integrated = system.is_integrated_gpu(label)
        if not integrated and free > best_free:
            best, best_free = name, free
    return best, best_free


class LlamaServer:
    def __init__(self, model_path: str, mmproj_path: str | None, context: int = 8192, use_gpu: bool = True):
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.context = context
        self.use_gpu = use_gpu
        self.mode = "auto"
        self.managed = False
        self.variant: str | None = None
        self.backend = "Sin iniciar"
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.key = ""
        self.device: str | None = None
        self.lock = threading.Lock()
        self.last_used = 0.0
        atexit.register(self.stop)

    @classmethod
    def default(cls, use_gpu: bool = True, mode: str = "auto") -> LlamaServer:
        prefix = "vlm" if installed_variant() == "advanced" else "vlm-lite"
        server = cls(str(models.model(prefix).path), str(models.model(f"{prefix}-mmproj").path), use_gpu=use_gpu)
        server.mode, server.managed = mode, True
        return server

    def execution_status(self) -> str:
        label = "8B" if self.variant == "advanced" else "4B" if self.variant else "modelo local"
        return f"{label} · {self.backend}" if self.running() else f"{label} · Sin iniciar"

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, timeout: float = 240) -> None:
        with self.lock:
            if self.running():
                return
            exe = _exe()
            if self.use_gpu and os.environ.get("ANONIMATO_CPU") != "1":
                self.device, free = pick_device(exe)
            else:
                bad = models.verify_runtime()
                if bad:
                    raise RuntimeError("Motor de IA alterado o incompleto: " + ", ".join(bad))
                self.device, free = None, 0
            if self.managed:
                available = [group for group in ("advanced", "advanced_lite") if models.group_installed(group)]
                self.variant = choose_variant(available, self.mode, free, system.available_memory_mb())
                prefix = "vlm" if self.variant == "advanced" else "vlm-lite"
                self.model_path = str(models.model(prefix).path)
                self.mmproj_path = str(models.model(f"{prefix}-mmproj").path)
            models.require_model_paths([Path(path) for path in (self.model_path, self.mmproj_path) if path])
            self.port = _free_port()
            self.key = secrets.token_hex(24)
            args = [exe, "-m", self.model_path, "--host", "127.0.0.1", "--port", str(self.port),
                    "--api-key", self.key, "-c", str(self.context), "-np", "1", "--no-webui",
                    "--temp", "0", "--log-disable"]
            if self.mmproj_path:
                args += ["--mmproj", self.mmproj_path]
            minimum_free = 7000 if Path(self.model_path).stat().st_size >= 4 * 1024**3 else 3000
            if self.device and free >= minimum_free:
                self.backend = f"GPU ({self.device})"
                args += ["--device", self.device, "-ngl", "999"]
            else:
                self.backend = "CPU"
                args += ["-ngl", "0", "--device", "none"]
            self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                                            env=system.llama_env(Path(exe).parent))
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("El motor de IA local no pudo arrancar")
                try:
                    with _LOCAL_HTTP.open(f"http://127.0.0.1:{self.port}/health", timeout=2) as response:
                        if response.status == 200:
                            self.last_used = time.time()
                            return
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    pass
                time.sleep(0.5)
            self.stop()
            raise RuntimeError("El motor de IA local tardó demasiado en arrancar")

    def stop(self) -> None:
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()

    def chat(self, messages: list[dict], max_tokens: int = 512, json_mode: bool = False) -> str:
        self.start()
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0, "top_k": 1, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with _LOCAL_HTTP.open(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.last_used = time.time()
        return data["choices"][0]["message"]["content"] or ""


def image_part(rgb: np.ndarray, max_side: int = 1400) -> dict:
    image = Image.fromarray(rgb)
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
