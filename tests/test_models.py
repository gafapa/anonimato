"""Model manifest, integrity and offline installation."""
import hashlib
import json
import zipfile

import pytest

from app.engine import models


def test_manifest_is_pinned():
    manifest = models.load_manifest()
    for group in ("base", "runtime", "advanced", "advanced_lite"):
        for item in manifest[group]:
            assert item.sha256 and len(item.sha256) == 64, item.id
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
