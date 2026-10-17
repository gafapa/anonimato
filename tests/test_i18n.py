"""Language preferences and portable profiles must not change document processing state."""
import json
from pathlib import Path
import re
import sys

import pytest

from app import i18n
from app.engine import system

ROOT = Path(__file__).resolve().parents[1]


def test_catalogs_cover_every_message_and_preserve_placeholders():
    catalogs = {language: json.loads((ROOT / "app/ui/locales" / f"{language}.json").read_text(encoding="utf-8"))
                for language in i18n.LANGUAGES}
    source = catalogs["es"]["messages"]
    for language, catalog in catalogs.items():
        assert catalog["language"] == language
        assert catalog["messages"].keys() == source.keys()
        for key, value in catalog["messages"].items():
            assert value.strip(), (language, key)
            assert sorted(re.findall(r"\{\d+\}", key)) == sorted(re.findall(r"\{\d+\}", value)), (language, key)


def test_language_preference_roundtrip_and_rejected_update(tmp_path, monkeypatch):
    monkeypatch.delenv("PRIVELTO_LANGUAGE", raising=False)
    monkeypatch.setattr(i18n, "preferences_path", lambda: tmp_path / "preferences.json")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: ("de_DE", "UTF-8"))
    assert i18n.get_language() == "de"
    assert i18n.set_language("gl") == "gl"
    assert i18n.get_language() == "gl"
    before = (tmp_path / "preferences.json").read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        i18n.set_language("invalid")
    assert (tmp_path / "preferences.json").read_bytes() == before
    assert not list(tmp_path.glob(".preferences-*"))
    (tmp_path / "preferences.json").write_text("broken", encoding="utf-8")
    assert i18n.get_language() == "de"


def test_language_override_and_native_confirmation_translation(monkeypatch):
    monkeypatch.setenv("PRIVELTO_LANGUAGE", "fr-CA")
    assert i18n.get_language() == "fr"
    assert i18n.translate("Cancelar", "en") == "Cancel"
    assert i18n.translate("unrecognized diagnostic", "de") == "unrecognized diagnostic"


def test_portable_profile_moves_with_application(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(system, "SYSTEM", "windows")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Privelto.exe"))
    assert system.portable_data_dir() is None
    (tmp_path / "privelto-portable.json").write_text('{"schema":1}', encoding="utf-8")
    profile = system.user_data_dir()
    assert profile == tmp_path / "PriveltoData"
    (profile / "fictitious.txt").write_text("preserve me", encoding="utf-8")
    destination = tmp_path.parent / (tmp_path.name + "-relocated")
    tmp_path.rename(destination)
    monkeypatch.setattr(sys, "executable", str(destination / "Privelto.exe"))
    assert system.user_data_dir() == destination / "PriveltoData"
    assert (system.user_data_dir() / "fictitious.txt").read_text(encoding="utf-8") == "preserve me"


def test_invalid_portable_marker_never_falls_back_to_installed_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(system, "SYSTEM", "windows")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Privelto.exe"))
    (tmp_path / "privelto-portable.json").write_text('{"schema":2}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="portable configuration"):
        system.user_data_dir()


def test_macos_portable_profile_is_outside_the_app_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(system, "SYSTEM", "macos")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Privelto.app/Contents/MacOS/Privelto"))
    (tmp_path / "privelto-portable.json").write_text('{"schema":1}', encoding="utf-8")
    assert system.portable_data_dir() == tmp_path / "PriveltoData"
