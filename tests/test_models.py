"""Model manifest, integrity and offline installation."""
import hashlib
import io
import json
import zipfile

import pytest

from app.engine import models


def test_manifest_is_pinned():
    manifest = models.load_manifest()
    for group in ("base", "runtime", "advanced", "advanced_lite"):
        for item in manifest[group]:
            assert item.sha256 and len(item.sha256) == 64, item.id
            assert item.size is not None and 0 < item.size <= models.MAX_MODEL_BYTES, item.id
            assert item.url.startswith("https://"), item.id


def test_base_models_match_their_checksums():
    for item in models.load_manifest()["base"]:
        assert models.is_installed(item, verify=True), item.id


@pytest.fixture
def fake_manifest(tmp_path, monkeypatch):
    payload = b"modelo de prueba" * 1000
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {"base": [], "advanced": [
        {"id": "vlm", "file": "advanced/vlm.gguf", "url": "https://example.invalid/x", "license": "MIT", "sha256": digest}],
        "advanced_lite": []}
    root = tmp_path / "bundle"
    (root / "models").mkdir(parents=True)
    (root / "models" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(models, "bundled_models_dir", lambda: root / "models")
    monkeypatch.setattr(models, "user_models_dir", lambda: tmp_path / "user")
    return payload


def test_offline_import_verifies_checksums(tmp_path, fake_manifest):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("advanced/vlm.gguf", fake_manifest)
    assert models.import_zip(good) == ["vlm"]
    assert models.group_installed("advanced")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("advanced/vlm.gguf", b"alterado")
    (tmp_path / "user" / "advanced" / "vlm.gguf").unlink()
    with pytest.raises(RuntimeError):
        models.import_zip(bad)
    assert not models.group_installed("advanced")


def test_offline_pack_installs_the_base_models_and_runtime(tmp_path, monkeypatch):
    runtime = io.BytesIO()
    with zipfile.ZipFile(runtime, "w") as archive:
        archive.writestr("llama-server", b"trusted executable")
    model, runtime = b"modelo base" * 100, runtime.getvalue()
    manifest = {
        "base": [{"id": "m", "file": "base/m.onnx", "url": "https://example.invalid/m", "license": "MIT",
                  "sha256": hashlib.sha256(model).hexdigest(), "size": len(model)}],
        "runtime": [{"id": "rt", "file": "../runtime/llama/rt.zip", "url": "https://example.invalid/rt", "license": "MIT",
                     "sha256": hashlib.sha256(runtime).hexdigest(), "size": len(runtime), "unzip": True}],
        "advanced": [], "advanced_lite": []}
    root = tmp_path / "checkout"
    (root / "models").mkdir(parents=True)
    (root / "models" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(models, "bundled_models_dir", lambda: root / "models")
    pack = tmp_path / "pack.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("base/m.onnx", model)
        archive.writestr("runtime/rt.zip", runtime)
    assert [item.id for item in models.required_missing()] == ["m", "rt"]
    assert sorted(models.import_zip(pack)) == ["m", "rt"]
    assert models.required_missing() == []
    assert (root / "runtime" / "llama" / "llama-server").read_bytes() == b"trusted executable"


def test_unexpected_backend_library_is_refused(tmp_path, monkeypatch):
    llama = tmp_path / "llama"
    llama.mkdir()
    monkeypatch.setattr(models, "runtime_dir", lambda: tmp_path)
    trusted = llama / "llama-server"
    trusted.write_bytes(b"trusted")
    monkeypatch.setattr(models, "_runtime_files", lambda: {
        "llama/llama-server": hashlib.sha256(b"trusted").hexdigest()})
    intruder = llama / "ggml-intruso.dll"
    intruder.write_bytes(b"MZ")
    try:
        assert any("ggml-intruso" in item for item in models.verify_runtime())
    finally:
        intruder.unlink()
    assert models.verify_runtime() == []


@pytest.fixture
def bundled_runtime(tmp_path, monkeypatch):
    archive = tmp_path / "bundle" / "runtime" / "runtime.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("llama-server", b"trusted executable")
        output.writestr("LICENSE", b"MIT")
    item = models.ModelFile("runtime", "../runtime/runtime.zip", "https://example.invalid/runtime", "MIT",
                            models.sha256_of(archive), "runtime", unzip=True)
    monkeypatch.setattr(models, "app_root", lambda: tmp_path / "bundle")
    monkeypatch.setattr(models, "user_data_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(models, "load_manifest", lambda: {"runtime": [item]})
    monkeypatch.setattr(models, "_runtime_files", lambda: {
        "llama/llama-server": hashlib.sha256(b"trusted executable").hexdigest()})
    monkeypatch.setattr(models, "runtime_dir", models._installed_runtime)
    return archive, item


def test_bundled_runtime_extracts_original_bytes_and_rechecks_cached_files(bundled_runtime):
    archive, item = bundled_runtime
    destination = models.runtime_dir()
    assert destination.name == item.sha256
    assert (destination / "llama" / "LICENSE").read_bytes() == b"MIT"
    assert models.verify_runtime() == []
    assert models.runtime_dir() == destination
    (destination / "llama" / "llama-server").write_bytes(b"tampered")
    assert models.verify_runtime() == ["runtime/llama/llama-server"]
    assert archive.exists()
    assert not list(destination.parent.glob(".extract-*"))


def test_bundled_runtime_rejects_an_altered_archive(bundled_runtime):
    archive, _ = bundled_runtime
    archive.write_bytes(b"untrusted replacement")
    with pytest.raises(RuntimeError, match="SHA-256"):
        models.runtime_dir()
    assert not (archive.parents[2] / "user" / "runtime").exists()


def test_runtime_counts_as_absent_until_its_archive_is_downloaded(bundled_runtime):
    archive, item = bundled_runtime
    archive.unlink()
    destination = models.runtime_dir()
    assert destination.name == item.sha256 and not destination.exists()
    assert models.verify_runtime() == []  # nothing to run yet, nothing altered


def test_concurrent_runtime_extraction_publishes_one_complete_directory(bundled_runtime):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as pool:
        destinations = list(pool.map(lambda _: models.runtime_dir(), range(3)))
    assert len(set(destinations)) == 1
    assert models.verify_runtime() == []
    assert sorted(path.name for path in destinations[0].parent.iterdir()) == [destinations[0].name]
