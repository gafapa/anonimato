"""Write complete exports atomically, without leaving truncated destination files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: bytes | str, *, encoding: str = "utf-8", overwrite: bool = True) -> None:
    data = content.encode(encoding) if isinstance(content, str) else content
    descriptor, name = tempfile.mkstemp(prefix=".anonimato-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            os.rename(temporary, path)  # Windows rename refuses an existing destination, including on FAT/exFAT.
        else:
            # Linking is an atomic exclusive publication: a concurrent export cannot be overwritten.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
