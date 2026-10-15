"""Keep the performance log of every test run (and its subprocesses) out of the user profile."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("ANONIMATO_PERF_LOG", str(Path(tempfile.mkdtemp(prefix="anonimato-perf-")) / "rendimiento.jsonl"))
