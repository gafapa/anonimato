"""Release inventory integrity with tiny fictitious archives, never production payloads."""
import hashlib
import io
import json
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from tools import package_inventory


@pytest.fixture
def package(monkeypatch, tmp_path):
    source, payload = tmp_path / "source", tmp_path / "payload"
    (source / "models").mkdir(parents=True)
    (source / "uv.lock").write_bytes(b"fictitious dependency lock")
    base = payload / "_internal/models/base/synthetic.onnx"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"fictitious model")
    runtime = payload / "_internal/runtime/windows.zip"
    runtime.parent.mkdir(parents=True)
    with zipfile.ZipFile(runtime, "w") as archive:
        archive.writestr("nested/library.dll", b"fictitious native library")
        archive.writestr("README.txt", "fictitious archive")
    catalog = {"base": [{"id": "synthetic", "file": "base/synthetic.onnx", "license": "MIT",
                         "sha256": hashlib.sha256(base.read_bytes()).hexdigest()}],
               "runtime": [{"id": "synthetic-runtime", "file": "runtime/windows.zip", "platform": "windows",
                            "sha256": hashlib.sha256(runtime.read_bytes()).hexdigest()}],
               "advanced": [{"id": "optional", "file": "advanced/optional.gguf", "sha256": "not bundled"}]}
    manifest = source / "models/manifest.json"
    manifest.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(package_inventory, "ROOT", source)
    monkeypatch.setattr(package_inventory.platform, "system", lambda: "Windows")
    monkeypatch.setattr(package_inventory, "native_version", lambda path: None)
    return SimpleNamespace(payload=payload, base=base, runtime=runtime, catalog=catalog, manifest=manifest)


def test_inventory_reports_only_actual_bundled_models(package):
    report = package_inventory.inventory(package.payload)
    assert {item["id"] for item in report["bundled_models"]} == {"synthetic", "synthetic-runtime"}
    assert report["model_catalog"]["advanced"][0]["id"] == "optional"
    entry = report["archived_native_files"][0]
    assert entry["entry"] == "nested/library.dll"
    assert entry["sha256"] == hashlib.sha256(b"fictitious native library").hexdigest()
    assert len(report["archived_native_files"]) == 1
    assert not (package.payload / "nested").exists()


@pytest.mark.parametrize("artifact", ["base", "runtime"])
def test_release_inventory_rejects_packaged_models(package, artifact):
    other = {"base": package.runtime, "runtime": package.base}[artifact]
    other.unlink()
    with pytest.raises(ValueError, match="must not be packaged"):
        package_inventory.inventory(package.payload, allow_models=False)
    getattr(package, artifact).unlink()
    report = package_inventory.inventory(package.payload, allow_models=False)  # downloaded on first launch
    assert report["bundled_models"] == []


@pytest.mark.parametrize("artifact", ["base", "runtime"])
def test_inventory_rejects_changed_model_or_runtime_bytes(package, artifact):
    path = getattr(package, artifact)
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    if artifact == "runtime":
        # Keep a valid archive while changing the catalogued bytes.
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("extra.txt", "fictitious extra")
    with pytest.raises(ValueError, match="Packaged model hash mismatch"):
        package_inventory.inventory(package.payload)


def test_required_runtime_for_another_platform_is_not_required(package):
    package.catalog["runtime"].append({"id": "foreign", "file": "runtime/linux.tar.gz", "platform": "linux",
                                       "sha256": "not shipped on Windows"})
    package.manifest.write_text(json.dumps(package.catalog), encoding="utf-8")
    assert len(package_inventory.inventory(package.payload)["bundled_models"]) == 2


def test_tar_inventory_resolves_native_links_without_extracting(package):
    path = package.runtime.parent / "linux.tar.gz"
    native = b"fictitious shared library"
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo("lib/library.so.1")
        entry.size = len(native)
        archive.addfile(entry, io.BytesIO(native))
        link = tarfile.TarInfo("lib/library.so")
        link.type, link.linkname = tarfile.SYMTYPE, "library.so.1"
        archive.addfile(link)
    report = package_inventory.inventory(package.payload)
    entries = [item for item in report["archived_native_files"] if item["archive"].endswith(".tar.gz")]
    assert len(entries) == 2 and {item["sha256"] for item in entries} == {hashlib.sha256(native).hexdigest()}
    assert next(item for item in entries if item["entry"].endswith(".so"))["link_target"] == "library.so.1"
    assert not (package.payload / "lib").exists()


def test_previous_inventory_is_excluded_from_its_own_hashes(package):
    (package.payload / "component-inventory.json").write_text("fictitious previous inventory", encoding="utf-8")
    report = package_inventory.inventory(package.payload)
    assert all(item["path"] != "component-inventory.json" for item in report["files"])
