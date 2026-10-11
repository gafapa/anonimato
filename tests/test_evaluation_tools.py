"""Public evaluation provenance and actual package inventory regressions."""
import hashlib
import subprocess
import sys
import json
from unittest.mock import Mock

import pymupdf
import pytest

from tools import evaluate_detection, package_inventory
from tools.evaluation_corpus import challenging_documents


def test_public_corpus_contains_native_noisy_photo_and_handwriting_cases():
    cases = challenging_documents(2026, include_scanned=True)
    assert len(cases) == 13
    assert {kind for kind, *_ in cases} == {"layout", "noisy-layout", "low-resolution-photo", "synthetic-handwriting"}
    for _, _, data, truth in cases:
        with pymupdf.open("pdf", data) as doc:
            assert len(doc) == 1
        assert truth and all(item["value"] for item in truth)


def test_private_evaluation_requires_ignored_output(tmp_path):
    result = subprocess.run([sys.executable, "tools/evaluate_detection.py", "--private", "--output", str(tmp_path / "report.md")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "ignored tmp/" in result.stderr
    assert not (tmp_path / "report.md").exists()


def test_private_category_cannot_disclose_a_value_in_aggregate_labels(tmp_path, monkeypatch, capsys):
    directory = tmp_path / 'eval/docs'
    directory.mkdir(parents=True)
    (directory / 'fictitious.pdf').write_bytes(b'FICTITIOUS INPUT - MUST NEVER REACH PARSING')
    sensitive = 'Fictitious private person'
    (directory / 'fictitious.json').write_text(json.dumps([{'type': sensitive, 'value': sensitive}]), encoding='utf-8')
    output = tmp_path / 'tmp/private.md'
    monkeypatch.setattr(evaluate_detection, 'ROOT', tmp_path)
    monkeypatch.setattr(evaluate_detection, 'Services', Mock())
    analysis = Mock(side_effect=AssertionError('Invalid annotations must be rejected before analysis'))
    monkeypatch.setattr(evaluate_detection.pipeline, 'analyze', analysis)
    monkeypatch.setattr(sys, 'argv', ['evaluate', '--private', '--output', str(output), '--docs', '0'])
    with pytest.raises(SystemExit) as error:
        evaluate_detection.main()
    assert error.value.code == 2
    analysis.assert_not_called()
    assert not output.exists()
    captured = capsys.readouterr()
    assert sensitive not in captured.out + captured.err


def test_coverage_cannot_use_another_page():
    from app.engine.types import Finding
    from types import SimpleNamespace
    finding = Finding("x", 1, "name", "Synthetic", [(0, 0, 10, 10)], 1, "text")
    analysis = SimpleNamespace(findings=[finding])
    assert not evaluate_detection._rect_covered(analysis, (0, 0, 10, 10), 0)
    assert evaluate_detection._rect_covered(analysis, (0, 0, 10, 10), 1)


def test_inventory_hashes_actual_bytes_and_metadata(tmp_path):
    binary = tmp_path / "sample.dll"
    binary.write_bytes(b"synthetic native payload")
    metadata = tmp_path / "example-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: example\nVersion: 1.0\nLicense-Expression: MIT\n")
    inventory = package_inventory.inventory(tmp_path)
    native = next(entry for entry in inventory["files"] if entry["native"])
    assert native["sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert inventory["python_packages"][0]["license"] == "MIT"
