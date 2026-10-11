"""Protect shared startup resources and report bootstrap failures without hidden dialogs."""
import gc
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

import pytest

from app.engine import worker


@pytest.mark.parametrize('outcome', [False, OSError('fictitious invalid handle')])
def test_failed_protection_gate_never_loads_or_parses(monkeypatch, outcome):
    connection, gate = Mock(), Mock()
    if isinstance(outcome, OSError):
        gate.wait.side_effect = outcome
    else:
        gate.wait.return_value = outcome
    handlers = Mock(side_effect=AssertionError('No parsing is allowed before protection'))
    monkeypatch.setattr(worker, '_handlers', handlers)
    worker.serve(connection, None, False, True, startup_gate=gate)
    handlers.assert_not_called()
    connection.close.assert_called_once()
    if isinstance(outcome, OSError):
        message = connection.send.call_args.args[0]
        assert message[0] == 'error' and message[1]['kind'] == 'ProcessProtectionError'
    else:
        connection.send.assert_not_called()


def test_parent_preserves_gate_until_child_stops():
    engine = worker.EngineProcess(with_models=False, use_gpu=False)
    context = engine._ctx
    references = []

    def event():
        result = context.Event()
        references.append(weakref.ref(result))
        return result

    engine._ctx = SimpleNamespace(Pipe=context.Pipe, Process=context.Process, Event=event)
    try:
        engine.ensure_started()
        gc.collect()
        assert references[0]() is not None, 'Parent must preserve the shared protection gate during child startup'
        assert engine.call('ping') > 0
    finally:
        engine.stop()
    gc.collect()
    assert references[0]() is None, 'Shared startup resources must be released after child termination'


def test_windowed_bootstrap_can_write_errors_without_standard_streams():
    root = Path(__file__).resolve().parents[1]
    script = '''import multiprocessing, runpy, sys
def bootstrap():
    sys.stderr.write('fictitious bootstrap error')
    sys.stdout.write('fictitious bootstrap output')
    raise SystemExit(0)
multiprocessing.freeze_support = bootstrap
sys.stdout = sys.stderr = None
runpy.run_path('packaging/launcher.py', run_name='__main__')
'''
    completed = subprocess.run([sys.executable, '-c', script], cwd=root, capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
