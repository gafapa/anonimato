"""Model files: location, integrity checks and downloads.

Downloads only fetch model weights listed in ``models/manifest.json``. Documents
never leave the machine.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

CHUNK = 1 << 20


def app_root() -> Path:
    """Directory holding bundled resources (source tree or PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def bundled_models_dir() -> Path:
    return app_root() / "models"


def user_data_dir() -> Path:
    from .system import user_data_dir as _user_data_dir
    return _user_data_dir()


def user_models_dir() -> Path:
    """Advanced models are installed per user, outside the program folder."""
    if getattr(sys, "frozen", False):
        return user_data_dir() / "models"
    return bundled_models_dir()


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _installed_bundled_runtime()
    return app_root() / "runtime"


def _installed_bundled_runtime() -> Path:
    """Extract the pinned archive without allowing packaging tools to rewrite native binaries."""
    import shutil
    import tempfile

    items = for_this_platform(load_manifest().get("runtime", []))
    if len(items) != 1:
        raise RuntimeError("Exactly one pinned runtime archive is required for this platform")
    item = items[0]
    if len(item.sha256) != 64 or any(char not in "0123456789abcdef" for char in item.sha256):
        raise RuntimeError("Invalid runtime archive checksum")
    cache = user_data_dir() / "runtime"
    target = cache / item.sha256
    if target.is_dir():
        return target  # verify_runtime still hashes every extracted executable and library.
    archive = app_root() / "runtime" / Path(item.file).name
    if sha256_of(archive) != item.sha256:
        raise RuntimeError("Bundled runtime archive failed its SHA-256 check")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=cache) as temporary:
        payload = Path(temporary) / "payload"
        destination = payload / "llama"
        destination.mkdir(parents=True)
        staged_archive = destination / archive.name
        shutil.copyfile(archive, staged_archive)
        if sha256_of(staged_archive) != item.sha256:
            raise RuntimeError("Runtime archive changed during extraction preparation")
        extract_runtime(staged_archive)
        staged_archive.unlink()
        try:
            payload.rename(target)
        except OSError:
            if not target.is_dir():
                raise
    return target


@dataclass(frozen=True)
class ModelFile:
    id: str
    file: str
    url: str
    license: str
    sha256: str
    group: str
    unzip: bool = False
    platform: str = ""        # "", "windows", "macos" or "linux"

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
    items = load_manifest().get(group, [])
    return bool(items) and all(is_installed(item) for item in items)


Progress = Callable[[str, int, int], None]


def download(item: ModelFile, progress: Progress | None = None) -> Path:
    """Download with resume and SHA-256 verification."""
    target = item.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not item.sha256 or sha256_of(target) == item.sha256):
        if item.unzip:
            extract_runtime(target)
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
        extract_runtime(target)
    return target


def extract_runtime(archive_path: Path) -> None:
    """Unpack a llama.cpp release next to the archive (top-level folder stripped, links kept)."""
    destination = archive_path.parent
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
        return
    with tarfile.open(archive_path) as archive:
        members = []
        for member in archive.getmembers():
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            member.name = parts[1]
            members.append(member)
        archive.extractall(destination, members=members, filter="data")


def for_this_platform(items: list[ModelFile]) -> list[ModelFile]:
    from .system import SYSTEM
    return [item for item in items if item.platform in ("", SYSTEM)]


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
    from .system import SYSTEM
    raw = json.loads(manifest_path().read_text(encoding="utf-8"))
    return raw.get("runtime_files", {}).get(SYSTEM, {})


def verify_all(force: bool = False) -> list[str]:
    """Hash installed models and runtime files on every check.

    ``force`` is retained for callers; no writable on-disk cache is trusted.
    Optional models may be absent, but a partially installed runtime is refused.
    """
    targets: list[tuple[str, Path, str]] = []
    manifest = load_manifest()
    for group in INTEGRITY_GROUPS:
        for item in manifest.get(group, []):
            if item.sha256:
                targets.append((item.id, item.path, item.sha256))
    bad = []
    for label, path, expected in targets:
        if path.exists() and sha256_of(path) != expected:
            bad.append(label)
    return bad + verify_runtime()


def verify_runtime() -> list[str]:
    """Check the executable and every pinned library before executing llama.cpp."""
    runtime_files = _runtime_files()
    # llama.cpp loads every ggml backend library found next to it: an unexpected one is refused.
    pinned = set(runtime_files)
    llama_dir = runtime_dir() / "llama"
    unexpected = []
    if llama_dir.exists() and not pinned:
        return ["runtime/llama (sin hashes de integridad)"]
    if pinned and llama_dir.exists():
        for path in llama_dir.iterdir():
            name = path.name.lower()
            is_backend = name.startswith(("ggml", "libggml")) and any(ext in name for ext in (".dll", ".so", ".dylib"))
            if is_backend and f"llama/{path.name}" not in pinned:
                unexpected.append(f"runtime/llama/{path.name} (no esperado)")
    targets = []
    if llama_dir.exists():
        for name, digest in runtime_files.items():
            path = runtime_dir() / name
            if not path.is_file():
                unexpected.append(f"runtime/{name} (no encontrado)")
            else:
                targets.append((f"runtime/{name}", path, digest))
    bad = []
    for label, path, expected in targets:
        actual = sha256_of(path)
        if actual != expected:
            bad.append(label)
    return bad + unexpected
