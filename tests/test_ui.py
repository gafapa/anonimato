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


@pytest.mark.timeout(120)
def test_mixed_batch_retry_in_real_window(tmp_path):
    output = tmp_path / "batch-ui.json"
    completed = subprocess.run([sys.executable, str(ROOT / "tools/ui_batch_smoke.py"), str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert output.exists(), completed.stderr[-3000:]
    result = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0 and result["ok"], (result, completed.stderr[-3000:])  # WebView2 start-up errors


@pytest.mark.timeout(2400)
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
                "restoring detection clears the warning", "original and result show the same document",
                "a password being typed survives queue refreshes", "the previous review is hidden while re-analysing",
                "Space on a focused button is not taken by the shortcut"}
    expected.add("editing is blocked while saving")
    expected.update({"undo and redo review changes", "keyboard coordinate zone creation", "page zoom keeps normalized overlays",
                     "batch shows individual saved results", "verification announcements are accessible",
                     "compact desktop has no horizontal page overflow"})
    expected.add("keyboard coordinate zone editing")
    assert expected <= set(results["steps"]), expected - set(results["steps"])
