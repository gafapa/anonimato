"""Model files: location, integrity checks and downloads.

Installed builds ship no model weights: the base models and the llama.cpp runtime are
downloaded on first launch (``install_required``) and the advanced pack on request.
Downloads only fetch files listed in ``models/manifest.json``. Documents never leave
the machine.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from filelock import FileLock

CHUNK = 1 << 20
MAX_MODEL_BYTES = 8 * 1024**3
MAX_PACK_BYTES = 12 * 1024**3
DISK_RESERVE = 32 * 1024**2


def installation_lock() -> FileLock:
    """Serialize model writers and verification across threads and application instances."""
    root = user_models_dir()
    root.mkdir(parents=True, exist_ok=True)
    return FileLock(root / ".install.lock", timeout=60, is_singleton=True)


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
    """Downloaded models are installed per user, outside the program folder (a source checkout keeps them in the tree)."""
    if getattr(sys, "frozen", False):
        return user_data_dir() / "models"
    return bundled_models_dir()


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _installed_runtime()
    return app_root() / "runtime"


def _installed_runtime() -> Path:
    """Extract the downloaded pinned archive into a private cache keyed by its checksum.

    Until the archive has been downloaded the returned folder does not exist, so the runtime counts as absent."""
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
    archive = item.path
    if not archive.is_file():
        return target
    if sha256_of(archive) != item.sha256:
        raise RuntimeError("Runtime archive failed its SHA-256 check")
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
    size: int | None = None   # exact byte length, pinned with the checksum

    @property
    def path(self) -> Path:
        return (user_models_dir() / self.file).resolve()


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


def require_model_paths(paths: list[Path]) -> None:
    """Verify registered GGUF files immediately before handing them to the native runtime."""
    registered = {item.path: item for items in load_manifest().values() for item in items}
    with installation_lock():
        for path in paths:
            item = registered.get(path.resolve())
            if item is None:
                raise RuntimeError("El modelo no está incluido en el manifiesto de confianza")
            _check_model(item, path)


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
    with installation_lock():
        return _download_to(item, item.path, progress)


def _byte_limit(item: ModelFile) -> int:
    if item.size is not None and (not isinstance(item.size, int) or isinstance(item.size, bool)
                                 or not 0 < item.size <= MAX_MODEL_BYTES):
        raise RuntimeError(f"Invalid pinned size for {item.id}")
    return item.size or MAX_MODEL_BYTES


def _require_space(root: Path, size: int) -> None:
    if size + DISK_RESERVE > shutil.disk_usage(root).free:
        raise RuntimeError("No hay espacio libre suficiente para instalar los modelos con seguridad")


def _check_model(item: ModelFile, path: Path) -> None:
    if path.stat().st_size > _byte_limit(item) or (item.size is not None and path.stat().st_size != item.size):
        raise RuntimeError(f"Tamaño incorrecto para {item.id}")
    if not item.sha256 or sha256_of(path) != item.sha256:
        raise RuntimeError(f"Checksum incorrecto para {item.id}")


def _download_to(item: ModelFile, target: Path, progress: Progress | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256_of(target) == item.sha256:
        _check_model(item, target)
        if item.unzip and not getattr(sys, "frozen", False):
            extract_runtime(target, preserve_verified=True)
        return target
    partial = target.with_suffix(target.suffix + ".part")
    limit = _byte_limit(item)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > limit:
        partial.unlink()
        offset = 0
    request = urllib.request.Request(item.url, headers={"User-Agent": "Anonimato-model-installer"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        if offset and response.status != 206:
            offset = 0
        elif offset:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if not match or int(match[1]) != offset or int(match[3]) > limit:
                raise RuntimeError(f"Respuesta de descarga parcial no válida para {item.id}")
        total = int(response.headers.get("Content-Length") or 0) + offset
        if total > limit:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"La descarga supera el tamaño permitido para {item.id}")
        _require_space(target.parent, max(0, (item.size or total or limit) - offset))
        with partial.open("ab" if offset else "wb") as handle:
            done = offset
            while chunk := response.read(CHUNK):
                if done + len(chunk) > limit:
                    handle.close()
                    partial.unlink(missing_ok=True)
                    raise RuntimeError(f"La descarga supera el tamaño permitido para {item.id}")
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(item.id, done, total)
    try:
        _check_model(item, partial)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    if item.unzip and not getattr(sys, "frozen", False):  # installed builds extract into their private cache
        extract_runtime(target, preserve_verified=True)
    return target


def _publish_models(staged: list[tuple[ModelFile, Path]]) -> None:
    """Rollback every published file if any replacement fails; readers hold the installation lock."""
    backup_root = Path(tempfile.mkdtemp(prefix=".backup-", dir=user_models_dir()))
    changed = []
    recovered = True
    try:
        for index, (item, source) in enumerate(staged):
            target = item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = backup_root / str(index)
            existed = target.exists()
            if existed:
                target.replace(backup)
            changed.append((target, backup, existed))
            source.replace(target)
    except Exception as error:
        for target, backup, existed in reversed(changed):
            try:
                if existed:
                    backup.replace(target)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                recovered = False
        if not recovered:
            raise RuntimeError(f"No se pudo restaurar la instalación; conserva la copia de seguridad en {backup_root}") from error
        raise
    finally:
        if recovered:
            shutil.rmtree(backup_root)


def download_group(items: list[ModelFile], progress: Progress | None = None) -> None:
    """Verify the whole group before replacing installed models; failed downloads remain resumable."""
    with installation_lock():
        root = user_models_dir()
        pending = [item for item in items if not is_installed(item, verify=True)]
        if sum(_byte_limit(item) for item in pending) > MAX_PACK_BYTES:
            raise RuntimeError("El paquete supera el tamaño total permitido")
        downloads = root / ".downloads"
        downloads.mkdir(exist_ok=True)
        needed = 0
        for item in pending:
            cached = downloads / f"{item.id}-{item.sha256}"
            if cached.is_file():
                try:
                    _check_model(item, cached)
                except RuntimeError:
                    pass
                else:
                    continue
            partial = cached.with_suffix(".part")
            offset = min(_byte_limit(item), partial.stat().st_size) if partial.exists() else 0
            needed += _byte_limit(item) - offset
        _require_space(root, needed)
        staged = []
        for item in pending:
            target = downloads / f"{item.id}-{item.sha256}"
            staged.append((item, _download_to(item, target, progress)))
        _publish_models(staged)


def required_items() -> list[ModelFile]:
    """What the application needs before it can process anything: the base models and this platform's runtime."""
    manifest = load_manifest()
    return manifest.get("base", []) + for_this_platform(manifest.get("runtime", []))


def required_missing() -> list[ModelFile]:
    return [item for item in required_items() if not is_installed(item)]


def install_required(progress: Progress | None = None) -> None:
    """First-launch download: each file is resumable and checked against its pinned size and SHA-256."""
    with installation_lock():
        for item in required_missing():
            _download_to(item, item.path, progress)


def extract_runtime(archive_path: Path, *, preserve_verified: bool = False) -> None:
    """Unpack a llama.cpp release next to the archive (top-level folder stripped, links kept)."""
    destination = archive_path.parent
    # Leave verified libraries in place, including while another process is using them.
    if (preserve_verified and destination.resolve() == runtime_dir().resolve()
            and (destination / "llama").is_dir() and not verify_runtime()):
        return
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


PACK_GROUPS = ("base", "runtime", "advanced", "advanced_lite")


def pack_name(item: ModelFile) -> str:
    """Entry name inside an offline pack: the manifest path (e.g. advanced/vlm.gguf), runtime/<archive> for the runtime."""
    return f"runtime/{Path(item.file).name}" if item.group == "runtime" else item.file


def import_zip(archive_path: Path) -> list[str]:
    """Offline installation: a zip whose entries are named like ``pack_name`` (base models, runtime, advanced packs)."""
    with installation_lock():
        return _import_zip(archive_path)


def _import_zip(archive_path: Path) -> list[str]:
    manifest = load_manifest()
    groups = {group: for_this_platform(manifest.get(group, [])) for group in PACK_GROUPS}
    items = {pack_name(item): item for group_items in groups.values() for item in group_items}
    root = user_models_dir()
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(prefix=".import-", dir=root) as temporary:
        stage = Path(temporary)
        selected = []
        seen = set()
        total = 0
        for member in archive.infolist():
            item = items.get(member.filename.replace("\\", "/"))
            if item is None:
                continue
            if item.id in seen or member.is_dir() or member.flag_bits & 1:
                raise RuntimeError("El paquete contiene entradas duplicadas o no válidas")
            if member.file_size > _byte_limit(item) or (item.size is not None and member.file_size != item.size):
                raise RuntimeError(f"Tamaño incorrecto para {item.id}")
            seen.add(item.id)
            total += member.file_size
            selected.append((item, member))
        if not selected:
            raise RuntimeError("El archivo no contiene ningún modelo reconocido")
        for group in {item.group for item, _ in selected}:
            if not {item.id for item in groups[group]} <= seen:
                raise RuntimeError("El paquete no contiene el grupo completo de modelos")
        if total > MAX_PACK_BYTES:
            raise RuntimeError("El paquete supera el tamaño total permitido")
        _require_space(root, total)
        staged = []
        for index, (item, member) in enumerate(selected):
            partial = stage / f"{index}.part"
            done = 0
            with archive.open(member) as source, partial.open("wb") as destination:
                while chunk := source.read(CHUNK):
                    done += len(chunk)
                    if done > member.file_size or done > _byte_limit(item):
                        raise RuntimeError(f"El modelo supera el tamaño permitido para {item.id}")
                    destination.write(chunk)
            _check_model(item, partial)
            staged.append((item, partial))
        _publish_models(staged)
    for item, _ in selected:
        if item.unzip and not getattr(sys, "frozen", False):  # installed builds extract into their private cache
            extract_runtime(item.path, preserve_verified=True)
    return [item.id for item, _ in selected]


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
