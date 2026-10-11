"""Write SHA-256 sidecars for production distribution packages only."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def hash_packages(directory: Path) -> list[Path]:
    packages = sorted(path for path in directory.iterdir()
                      if path.is_file() and path.suffix in {".exe", ".dmg", ".AppImage"}
                      and not path.name.startswith("AnonimatoQualificationSetup-"))
    if not packages:
        raise ValueError("No production distribution packages found")
    outputs = []
    for package in packages:
        with package.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        output = package.with_name(package.name + ".sha256")
        output.write_text(f"{digest}  {package.name}\n", encoding="utf-8")
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    for sidecar in hash_packages(arguments.directory):
        print(sidecar)
