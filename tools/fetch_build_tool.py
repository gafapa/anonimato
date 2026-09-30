"""Fetch a build tool only when its contents match the repository's pinned SHA-256."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 256 * 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fetch(name: str, destination: Path) -> Path:
    item = json.loads((ROOT / "packaging" / "build-tools.json").read_text(encoding="utf-8"))[name]
    expected = item["sha256"]
    if destination.is_file() and digest(destination) == expected:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent, prefix=".build-tool-")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(item["url"], timeout=60) as response:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError("Build tool exceeds the download size limit")
                output.write(chunk)
        if digest(temporary) != expected:
            raise RuntimeError(f"SHA-256 mismatch for {name}; review the upstream release before updating the pin")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    fetch(sys.argv[1], Path(sys.argv[2]))
