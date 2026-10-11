"""Deterministic service concurrency, integrity recovery and native runtime lifecycle tests."""
import subprocess
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from filelock import Timeout

from app.engine import llm_server, models, services as service_module
from app.engine.services import Services
from app.engine.types import Options


def test_concurrent_requests_initialize_a_service_only_once():
    services = Services()
    entered, release = threading.Event(), threading.Event()
    instance = object()
    def initialize():
        entered.set()
        assert release.wait(2)
        return instance
    factory = Mock(side_effect=initialize)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(services._load, "pii", factory)
        assert entered.wait(2)
        second = pool.submit(services._load, "pii", factory)
        release.set()
        assert first.result(timeout=2) is instance and second.result(timeout=2) is instance
    factory.assert_called_once()
    assert services.timings["load_pii"] >= 0


def test_failed_loader_is_cached_until_advanced_reset():
    services = Services()
    factory = Mock(side_effect=RuntimeError("synthetic load failure"))
    assert services._load("llm", factory) is None
    assert services._load("llm", factory) is None
    factory.assert_called_once()
    assert services.errors == {"llm": "synthetic load failure"}
    services.reset_advanced()
    replacement = object()
    factory.side_effect = None
    factory.return_value = replacement
    assert services._load("llm", factory) is replacement and not services.errors


def test_changing_model_preference_stops_old_server_before_next_load(monkeypatch):
    services = Services()
    old = Mock()
    services._llm = old
    services.errors["llm"] = "previous failure"
    services.prepare(Options(categories=set(), ocr=False, ai=False, faces=False, advanced_mode="memory"))
    old.stop.assert_called_once()
    assert services._llm is None and "llm" not in services.errors and services.advanced_mode == "memory"
    replacement = object()
    factory = Mock(return_value=replacement)
    monkeypatch.setattr(services, "advanced_available", lambda: True)
    monkeypatch.setattr(llm_server.LlamaServer, "default", factory)
    assert services.llm() is replacement
    factory.assert_called_once_with(use_gpu=True, mode="memory")


@pytest.mark.parametrize("running,age,expected", [(True, 301, True), (True, 299, False), (False, 301, False)])
def test_idle_release_preserves_active_or_recent_server(monkeypatch, running, age, expected):
    services = Services()
    server = Mock(last_used=100)
    server.running.return_value = running
    services._llm = server
    monkeypatch.setattr(service_module, "time", SimpleNamespace(time=lambda: 100 + age))
    services.release_llm_if_idle()
    assert server.stop.called is expected


def test_integrity_lock_deadline_blocks_without_hashing_and_can_retry(monkeypatch):
    services = Services()
    lock = Mock()
    lock.acquire.side_effect = Timeout("synthetic.lock")
    monkeypatch.setattr(models, "installation_lock", lambda: lock)
    verify = Mock(return_value=[])
    monkeypatch.setattr(models, "verify_all", verify)
    monkeypatch.setattr(service_module, "time", SimpleNamespace(perf_counter=Mock(side_effect=[0, 301, 302])))
    assert not services.check_integrity(force=True)
    assert services._integrity_checked.is_set() and "Otro proceso" in services.errors["integrity"]
    verify.assert_not_called()
    lock.acquire.side_effect = None
    lock.acquire.return_value = nullcontext()
    monkeypatch.setattr(service_module, "time", SimpleNamespace(perf_counter=Mock(side_effect=[303, 304])))
    assert services.check_integrity(force=True) and "integrity" not in services.errors
    verify.assert_called_once_with(force=True)


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    model_paths = {}
    for name in ("vlm", "vlm-mmproj", "vlm-lite", "vlm-lite-mmproj"):
        path = tmp_path / (name + ".gguf")
        path.write_bytes(b"fictitious model")
        model_paths[name] = SimpleNamespace(path=path)
    monkeypatch.delenv("ANONIMATO_CPU", raising=False)
    monkeypatch.setattr(models, "group_installed", lambda group: group in ("advanced", "advanced_lite"))
    monkeypatch.setattr(models, "model", model_paths.__getitem__)
    monkeypatch.setattr(models, "verify_runtime", Mock(return_value=[]))
    trusted = Mock()
    monkeypatch.setattr(models, "require_model_paths", trusted)
    monkeypatch.setattr(llm_server.system, "available_memory_mb", lambda: 32768)
    monkeypatch.setattr(llm_server.system, "llama_env", lambda path: {})
    monkeypatch.setattr(llm_server, "_exe", lambda: str(tmp_path / "llama-server.exe"))
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(llm_server.subprocess, "Popen", launch)
    http = Mock()
    http.open.return_value = nullcontext(SimpleNamespace(status=200))
    monkeypatch.setattr(llm_server, "_LOCAL_HTTP", http)
    server = llm_server.LlamaServer.default()
    yield SimpleNamespace(server=server, process=process, launch=launch, http=http, trusted=trusted, models=model_paths)
    server.stop()


@pytest.mark.parametrize("free,mode,variant,gpu", [(8000, "auto", "advanced", True),
                                                   (2000, "auto", "advanced_lite", False),
                                                   (8000, "memory", "advanced_lite", True),
                                                   (0, "accuracy", "advanced", False)])
def test_actual_start_reselects_model_and_verifies_selected_bytes(runtime, monkeypatch, free, mode, variant, gpu):
    monkeypatch.setattr(llm_server, "pick_device", lambda executable: ("Vulkan0", free))
    runtime.server.mode = mode
    runtime.server.start()
    assert runtime.server.variant == variant
    prefix = "vlm" if variant == "advanced" else "vlm-lite"
    runtime.trusted.assert_called_once_with([runtime.models[prefix].path, runtime.models[prefix + "-mmproj"].path])
    args = runtime.launch.call_args.args[0]
    assert args[args.index("-m") + 1] == str(runtime.models[prefix].path)
    assert args[args.index("-ngl") + 1] == ("999" if gpu else "0")
    assert "GPU" in runtime.server.execution_status() if gpu else "CPU" in runtime.server.execution_status()
    assert args[args.index("--host") + 1] == "127.0.0.1" and args[args.index("--api-key") + 1]
    runtime.server.start()
    runtime.launch.assert_called_once()


def test_explicit_cpu_selection_never_probes_gpu(runtime, monkeypatch):
    monkeypatch.setenv("ANONIMATO_CPU", "1")
    probe = Mock(side_effect=AssertionError("GPU probe must not run"))
    monkeypatch.setattr(llm_server, "pick_device", probe)
    runtime.server.start()
    assert runtime.server.variant == "advanced_lite" and runtime.server.backend == "CPU"
    probe.assert_not_called()


def test_runtime_start_refuses_untrusted_selected_model_before_launch(runtime, monkeypatch):
    runtime.server.use_gpu = False
    runtime.trusted.side_effect = RuntimeError("synthetic hash mismatch")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        runtime.server.start()
    runtime.launch.assert_not_called()
    assert not runtime.server.running()


def test_runtime_health_timeout_stops_unresponsive_child(runtime, monkeypatch):
    runtime.server.use_gpu = False
    runtime.http.open.side_effect = urllib.error.URLError("not ready")
    monkeypatch.setattr(llm_server, "time", SimpleNamespace(time=Mock(side_effect=[0, 0, 2]), sleep=Mock()))
    with pytest.raises(RuntimeError, match="demasiado"):
        runtime.server.start(timeout=1)
    runtime.process.terminate.assert_called_once()
    assert runtime.server.process is None


def test_runtime_termination_timeout_kills_child(runtime):
    runtime.server.process = runtime.process
    runtime.process.wait.side_effect = subprocess.TimeoutExpired("synthetic runtime", 10)
    runtime.server.stop()
    runtime.process.terminate.assert_called_once()
    runtime.process.kill.assert_called_once()
    assert not runtime.server.running()
