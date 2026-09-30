"""The real window, driven end to end (tools/ui_smoke.py) in its own process.

Skipped where no desktop session is available (set ANONIMATO_SKIP_UI=1).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(os.environ.get("ANONIMATO_SKIP_UI") == "1", reason="no desktop session")


def test_every_interface_feature(tmp_path):
    out = tmp_path / "ui.json"
    completed = subprocess.run([sys.executable, str(ROOT / "tools" / "ui_smoke.py"), "--out", str(out)],
                               cwd=ROOT, capture_output=True, text=True, timeout=2400, check=False)
    assert out.exists(), completed.stderr[-3000:]
    results = json.loads(out.read_text(encoding="utf-8"))
    assert results["errors"] == [], results["errors"]
    failed = {name: step for name, step in results["steps"].items() if not step["ok"]}
    assert not failed, failed
    expected = {"detection categories are available", "queue contains five documents", "cancel button is visible during analysis",
                "review shows findings and boxes", "password-protected PDF is unlocked and analyzed",
                "include and exclude all findings", "filter findings by type", "J and Space shortcuts", "keyboard page navigation",
                "manual area selection and deletion", "integrity warning blocks analysis",
                "remaining traces appear in red on the page", "save verified PDF",
                "CSV and JSON logs omit original values", "save all PDFs to a folder", "maximum-security preview",
                "settings are collapsed during review", "detection changes request reanalysis",
                "restoring detection clears the warning"}
    assert expected <= set(results["steps"]), expected - set(results["steps"])
