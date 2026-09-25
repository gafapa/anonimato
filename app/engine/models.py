"""Model files: location, integrity checks and downloads.

Downloads only fetch model weights listed in ``models/manifest.json``. Documents
never leave the machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CHUNK = 1 << 20


def app_root() -> Path:
    """Directory holding bundled resources (source tree or PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def bundled_models_dir() -> Path:
    return app_root() / "models"


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "Anonimato"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_models_dir() -> Path:
    """Advanced models are installed per user, outside the program folder."""
    if getattr(sys, "frozen", False):
        return user_data_dir() / "models"
    return bundled_models_dir()


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return app_root() / "runtime"
    return app_root() / "runtime"


@dataclass(frozen=True)
class ModelFile:
    id: str
    file: str
    url: str
    license: str
    sha256: str
    group: str
    unzip: bool = False

    @property
    def path(self) -> Path:
        if self.group in ("advanced", "advanced_lite", "candidates"):
            return (user_models_dir() / self.file).resolve()
        return (bundled_models_dir() / self.file).resolve()


def manifest_path() -> Path:
    return bundled_models_dir() / "manifest.json"


def load_manifest() -> dict[str, list[ModelFile]]:
    raw = json.loads(manifest_path().read_text(encoding="utf-8"))
    return {
        group: [ModelFile(group=group, unzip=item.get("unzip", False), **{k: v for k, v in item.items() if k != "unzip"})
                for item in items]
        for group, items in raw.items() if isinstance(items, list)
    }


def model(model_id: str) -> ModelFile:
    for items in load_manifest().values():
        for item in items:
            if item.id == model_id:
                return item
    raise KeyError(model_id)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def is_installed(item: ModelFile, verify: bool = False) -> bool:
    if not item.path.exists():
        return False
    if verify and item.sha256:
        return sha256_of(item.path) == item.sha256
    return True


def group_installed(group: str) -> bool:
    return all(is_installed(item) for item in load_manifest().get(group, []))


Progress = Callable[[str, int, int], None]


def download(item: ModelFile, progress: Progress | None = None) -> Path:
    """Download with resume and SHA-256 verification."""
    target = item.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not item.sha256 or sha256_of(target) == item.sha256):
        return target
    partial = target.with_suffix(target.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(item.url, headers={"User-Agent": "Anonimato-model-installer"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        if offset and response.status != 206:
            offset = 0
        total = int(response.headers.get("Content-Length") or 0) + offset
        with partial.open("ab" if offset else "wb") as handle:
            done = offset
            while chunk := response.read(CHUNK):
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(item.id, done, total)
    if item.sha256:
        actual = sha256_of(partial)
        if actual != item.sha256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum incorrecto para {item.id}: {actual}")
    partial.replace(target)
    if item.unzip:
        with zipfile.ZipFile(target) as archive:
            archive.extractall(target.parent)
    return target


def import_zip(archive_path: Path) -> list[str]:
    """Offline installation: a zip whose entries are named like the manifest files (e.g. advanced/vlm.gguf)."""
    manifest = load_manifest()
    items = {item.file: item for group in ("advanced", "advanced_lite") for item in manifest.get(group, [])}
    imported = []
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.namelist():
            item = items.get(member.replace("\\", "/"))
            if item is None:
                continue
            item.path.parent.mkdir(parents=True, exist_ok=True)
            partial = item.path.with_suffix(item.path.suffix + ".part")
            with archive.open(member) as source, partial.open("wb") as destination:
                while chunk := source.read(CHUNK):
                    destination.write(chunk)
            if item.sha256 and sha256_of(partial) != item.sha256:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum incorrecto para {item.id}")
            partial.replace(item.path)
            imported.append(item.id)
    if not imported:
        raise RuntimeError("El archivo no contiene ningún modelo reconocido")
    return imported


INTEGRITY_GROUPS = ("base", "advanced", "advanced_lite")


def _runtime_files() -> dict[str, str]:
    raw = json.loads(manifest_path().read_text(encoding="utf-8"))
    return raw.get("runtime_files", {})


def _integrity_cache_path() -> Path:
    return user_data_dir() / "integrity.json"


def verify_all(force: bool = False) -> list[str]:
    """Names of files whose SHA-256 does not match the manifest (models and llama.cpp runtime)."""
    targets: list[tuple[str, Path, str]] = []
    manifest = load_manifest()
    for group in INTEGRITY_GROUPS:
        for item in manifest.get(group, []):
            if item.sha256:
                targets.append((item.id, item.path, item.sha256))
    for name, digest in _runtime_files().items():
        targets.append((f"runtime/{name}", runtime_dir() / name, digest))
    try:
        cache = {} if force else json.loads(_integrity_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    bad = []
    for label, path, expected in targets:
        if not path.exists():
            continue
        stat = path.stat()
        key = str(path)
        entry = cache.get(key)
        if entry and entry[0] == stat.st_size and entry[1] == stat.st_mtime_ns and entry[2] == expected:
            continue
        actual = sha256_of(path)
        if actual != expected:
            bad.append(label)
            cache.pop(key, None)
        else:
            cache[key] = [stat.st_size, stat.st_mtime_ns, expected]
    try:
        _integrity_cache_path().write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return bad
