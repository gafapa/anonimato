"""Distribution hashes must exclude qualification installers."""
import hashlib

import pytest

from tools.hash_packages import hash_packages


def test_hashes_cover_production_packages_only(tmp_path):
    for name in ("AnonimatoSetup-2.2.1.exe", "Anonimato-2.2.1.dmg", "Anonimato-2.2.1.AppImage"):
        (tmp_path / name).write_bytes(b"synthetic package")
    (tmp_path / "AnonimatoQualificationSetup-2.2.1.exe").write_bytes(b"qualification only")
    (tmp_path / "selftest.json").write_text("{}")
    (tmp_path / "nested.exe").mkdir()
    outputs = hash_packages(tmp_path)
    assert len(outputs) == 3
    digest = hashlib.sha256(b"synthetic package").hexdigest()
    for output in outputs:
        assert output.read_text() == f"{digest}  {output.name.removesuffix('.sha256')}\n"
    assert not (tmp_path / "AnonimatoQualificationSetup-2.2.1.exe.sha256").exists()


def test_missing_production_package_fails(tmp_path):
    (tmp_path / "AnonimatoQualificationSetup-2.2.1.exe").write_bytes(b"qualification only")
    with pytest.raises(ValueError, match="No production"):
        hash_packages(tmp_path)
