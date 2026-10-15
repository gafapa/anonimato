"""Inventory the actual packaged payload, native libraries, Python metadata and model pins."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE_SUFFIXES = {".dll", ".pyd", ".so", ".dylib", ".exe"}


def is_native(name: str) -> bool:
    return Path(name).suffix.lower() in NATIVE_SUFFIXES or ".so." in name


def native_version(path: Path) -> str | None:
    """Read embedded Windows version resources; never infer a version from a filename."""
    if platform.system() != "Windows":
        return None
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    size = api.GetFileVersionInfoSizeW(str(path.resolve()), None)
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.GetFileVersionInfoW(str(path.resolve()), 0, size, buffer) or not api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return None
    if length.value < 52:
        return None
    values = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if values[0] != 0xFEEF04BD:
        return None
    return ".".join(map(str, (values[2] >> 16, values[2] & 65535, values[3] >> 16, values[3] & 65535)))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root: Path, *, allow_models: bool = True) -> dict:
    """``allow_models=False`` refuses a release payload that carries model weights or the runtime archive:
    the application downloads them on first launch."""
    files, packages, archives = [], [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "component-inventory.json":
            continue
        relative = path.relative_to(root).as_posix()
        native = is_native(path.name)
        entry = {"path": relative, "size": path.stat().st_size, "sha256": digest(path), "native": native}
        if native:
            entry.update(version=native_version(path), license="UNKNOWN", license_reference="THIRD_PARTY.md")
        files.append(entry)
        if path.name == "METADATA" and path.parent.name.endswith(".dist-info"):
            metadata = BytesParser().parsebytes(path.read_bytes())
            packages.append({"name": metadata.get("Name"), "version": metadata.get("Version"),
                             "license": metadata.get("License-Expression") or metadata.get("License") or "UNKNOWN",
                             "license_files": metadata.get_all("License-File", []), "metadata_path": relative})
        if path.suffix == ".zip" and "runtime" in relative:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    if is_native(entry.filename):
                        with archive.open(entry) as stream:
                            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                        archives.append({"archive": relative, "entry": entry.filename, "size": entry.file_size, "sha256": checksum})
        elif relative.endswith((".tar.gz", ".tgz")) and "runtime" in relative:
            with tarfile.open(path) as archive:
                for entry in archive.getmembers():
                    if is_native(entry.name) and (entry.isfile() or entry.issym() or entry.islnk()):
                        stream = archive.extractfile(entry)
                        if stream is None:
                            raise ValueError(f"Unreadable native archive member: {entry.name}")
                        with stream:
                            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                        archives.append({"archive": relative, "entry": entry.name, "size": entry.size,
                                         "sha256": checksum, "link_target": entry.linkname or None})
    catalog = json.loads((ROOT / "models/manifest.json").read_text(encoding="utf-8"))
    current_platform = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    bundled_models = []
    for group, items in catalog.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if item.get("platform") and item["platform"] != current_platform:
                continue
            suffix = "runtime/" + Path(item["file"]).name if group == "runtime" else "models/" + item["file"]
            matches = [entry for entry in files if entry["path"] == suffix or entry["path"].endswith("/" + suffix)]
            if matches:
                if not allow_models:
                    raise ValueError(f"Model files must not be packaged: {item['id']}")
                if any(entry["sha256"] != item["sha256"] for entry in matches):
                    raise ValueError(f"Packaged model hash mismatch: {item['id']}")
                bundled_models.append({"id": item["id"], "group": group, "license": item.get("license", "UNKNOWN"),
                                       "files": [entry["path"] for entry in matches], "sha256": item["sha256"]})
    return {"schema": "anonimato-component-inventory-v1", "platform": platform.system(),
            "lock_sha256": digest(ROOT / "uv.lock"), "manifest_sha256": digest(ROOT / "models/manifest.json"),
            "model_catalog": catalog, "bundled_models": bundled_models,
            "python_packages": packages, "files": files, "archived_native_files": archives,
            "limitations": "Hashes describe the packaged payload. UNKNOWN licenses and native versions need supplier review; this is not a vulnerability certification."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.root / "component-inventory.json"
    output.write_text(json.dumps(inventory(args.root, allow_models=False), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
