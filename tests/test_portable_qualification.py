"""Archive checks must accept canonical temporary paths and reject traversal before extraction."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import zipfile

import pytest

from tools import qualify_portable


@pytest.mark.skipif(os.name == "nt", reason="POSIX temporary directory alias, as used by macOS /var")
def test_portable_qualification_accepts_symlinked_temporary_directory(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    package = tmp_path / "portable.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Privelto/privelto-portable.json", '{"schema":1}')
        archive.writestr("Privelto/Privelto.exe", "fictitious executable")
    monkeypatch.setattr(qualify_portable.tempfile, "TemporaryDirectory", lambda **_kwargs: nullcontext(str(alias)))
    monkeypatch.setattr(qualify_portable.sys, "platform", "win32")
    launches = []

    def launch(arguments, **_kwargs):
        folder = Path(arguments[0]).parent
        assert folder.is_relative_to(actual)
        (folder / "PriveltoData/models").mkdir(parents=True, exist_ok=True)
        report = Path(arguments[1].split("=", 1)[1])
        report.write_text(json.dumps({"ok": True, "integrity": True, "crash_recovery": True}), encoding="utf-8")
        launches.append(folder)

    monkeypatch.setattr(qualify_portable.subprocess, "run", launch)
    report = tmp_path / "qualification.json"
    qualify_portable.qualify(package, report)
    assert len(launches) == 2
    assert launches[1] == actual / "relocated/Privelto"
    assert json.loads(report.read_text(encoding="utf-8"))["portable_data"] is True


def test_portable_qualification_rejects_archive_escape(tmp_path):
    package = tmp_path / "malicious.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../../must-not-extract.txt", "fictitious payload")
    with pytest.raises(ValueError, match="Unsafe portable archive path"):
        qualify_portable.qualify(package, tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()
