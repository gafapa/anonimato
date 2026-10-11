"""V8 coverage of the task-owned real Windows WebView2 window."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != 'win32' or os.environ.get('ANONIMATO_SKIP_UI') == '1', reason='Windows desktop required')
@pytest.mark.timeout(150)
def test_real_javascript_action_coverage(tmp_path):
    output = tmp_path / 'batch.json'
    coverage = tmp_path / 'javascript.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'tools/ui_batch_smoke.py'), str(output),
                                '--js-coverage', str(coverage)], cwd=ROOT, capture_output=True, text=True,
                               timeout=140, check=False)
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert json.loads(output.read_text('utf-8'))['ok']
    report = json.loads(coverage.read_text('utf-8'))
    if destination := os.environ.get('ANONIMATO_JS_COVERAGE_OUTPUT'):
        Path(destination).write_text(json.dumps(report, indent=2), encoding='utf-8')
    minimum = json.loads((ROOT / 'packaging/coverage-policy.json').read_text('utf-8'))['javascript_blocks']
    source = (ROOT / 'app/ui/app.js').read_bytes().decode('utf-8')
    assert report['total'] == len(source.encode('utf-16-le')) // 2
    assert report['percent'] >= minimum, report
    assert report['coveredFunctions'] > 50
    assert report['raw']['url'] == (ROOT / 'app/ui/app.js').as_uri()
