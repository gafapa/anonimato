"""Verify a portable archive's executable, profile location and relocation with fictitious data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def qualify(package: Path, output: Path) -> None:
    package = package.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="privelto-portable-qualification-") as temporary:
        root = Path(temporary)
        if package.name.endswith(".tar.gz"):
            with tarfile.open(package) as archive:
                archive.extractall(root, filter="data")
        else:
            with zipfile.ZipFile(package) as archive:
                for member in archive.infolist():
                    destination = (root / member.filename).resolve()
                    if not destination.is_relative_to(root):
                        raise ValueError("Unsafe portable archive path")
                if sys.platform != "darwin":
                    archive.extractall(root)
            if sys.platform == "darwin":
                subprocess.run(["ditto", "-x", "-k", str(package), str(root)], check=True)
        folder = root / "Privelto"
        if json.loads((folder / "privelto-portable.json").read_text(encoding="utf-8")) != {"schema": 1}:
            raise ValueError("Missing portable marker")
        environment = dict(os.environ, ANONIMATO_CPU="1", QT_QPA_PLATFORM="offscreen", PRIVELTO_LANGUAGE="en")
        for stage in ["launch", "relocate"]:
            if stage == "relocate":
                previous = folder
                folder = root / "relocated" / "Privelto"
                folder.parent.mkdir()
                shutil.move(previous, folder)
                assert (folder / "PriveltoData/fictitious-profile-marker.txt").read_text(encoding="utf-8") == "fictitious"
            binary = folder / ("Privelto.exe" if sys.platform == "win32" else
                               "Privelto.app/Contents/MacOS/Privelto" if sys.platform == "darwin" else "Privelto")
            report = output.with_name(output.stem + f"-{stage}.json")
            subprocess.run([str(binary), f"--selftest={report}"], env=environment, check=True, timeout=1200)
            result = json.loads(report.read_text(encoding="utf-8"))
            if not all(result.get(key) is True for key in ["ok", "integrity", "crash_recovery"]):
                raise RuntimeError("Portable executable self-test failed")
            data = folder / "PriveltoData"
            if not (data / "models").is_dir():
                raise RuntimeError("Portable models were not stored next to the application")
            (data / "fictitious-profile-marker.txt").write_text("fictitious", encoding="utf-8")
    output.write_text(json.dumps({"ok": True, "launch": True, "relocate": True, "portable_data": True,
                                  "platform": sys.platform, "package": package.name}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    qualify(arguments.package, arguments.output)
