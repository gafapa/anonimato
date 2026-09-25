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

import numpy as np
from PIL import Image

from . import models

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _exe() -> str:
    return str(models.runtime_dir() / "llama" / "llama-server.exe")


def installed_variant() -> str | None:
    """Advanced pack installed: "advanced" (Qwen3-VL-8B) is preferred over "advanced_lite" (4B)."""
    for group in ("advanced", "advanced_lite"):
        if models.group_installed(group):
            return group
    return None


def recommended_variant() -> str:
    """8B needs about 7 GB of free video memory; smaller GPUs get the 4B model."""
    _, free = pick_device(_exe()) if os.path.exists(_exe()) else (None, 0)
    return "advanced" if free >= 7000 else "advanced_lite"


def available() -> bool:
    return os.path.exists(_exe()) and installed_variant() is not None


def pick_device(exe: str) -> tuple[str | None, int]:
    """Best discrete GPU (most free memory, not an integrated Intel GPU)."""
    try:
        output = subprocess.run([exe, "--list-devices"], capture_output=True, text=True, timeout=60,
                                creationflags=CREATE_NO_WINDOW).stdout
    except Exception:  # noqa: BLE001
        return None, 0
    best, best_free = None, 0
    for line in output.splitlines():
        match = re.match(r"\s*(\w+\d+):\s*(.+?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", line)
        if not match:
            continue
        name, label, free = match.group(1), match.group(2), int(match.group(4))
        integrated = "Intel" in label and ("UHD" in label or "Iris" in label)
        if not integrated and free > best_free:
            best, best_free = name, free
    return best, best_free


class LlamaServer:
    def __init__(self, model_path: str, mmproj_path: str | None, context: int = 8192):
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.context = context
        self.process: subprocess.Popen | None = None
        self.port = 0
        self.key = ""
        self.device: str | None = None
        self.lock = threading.Lock()
        self.last_used = 0.0
        atexit.register(self.stop)

    @classmethod
    def default(cls) -> "LlamaServer":
        prefix = "vlm" if installed_variant() == "advanced" else "vlm-lite"
        return cls(str(models.model(prefix).path), str(models.model(f"{prefix}-mmproj").path))

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, timeout: float = 240) -> None:
        with self.lock:
            if self.running():
                return
            exe = _exe()
            self.device, free = pick_device(exe)
            self.port = _free_port()
            self.key = secrets.token_hex(24)
            args = [exe, "-m", self.model_path, "--host", "127.0.0.1", "--port", str(self.port),
                    "--api-key", self.key, "-c", str(self.context), "-np", "1", "--no-webui",
                    "--temp", "0", "--log-disable"]
            if self.mmproj_path:
                args += ["--mmproj", self.mmproj_path]
            if self.device and free > 3000:
                args += ["--device", self.device, "-ngl", "999"]
            else:
                args += ["-ngl", "0", "--device", "none"]
            self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("El motor de IA local no pudo arrancar")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as response:
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
        with urllib.request.urlopen(request, timeout=300) as response:
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
