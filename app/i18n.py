"""Persist the interface language without changing document data or engine identifiers."""
from __future__ import annotations

import json
import locale
import os
from pathlib import Path
import tempfile

LANGUAGES = {"en": "English", "es": "Español", "gl": "Galego", "fr": "Français", "de": "Deutsch", "it": "Italiano", "pt": "Português"}


def normalize_language(value: str) -> str:
    language = str(value).lower().replace("_", "-").split("-", 1)[0]
    return language if language in LANGUAGES else "en"


def preferences_path() -> Path:
    from .engine.system import user_data_dir
    return user_data_dir() / "preferences.json"


def get_language() -> str:
    override = os.environ.get("PRIVELTO_LANGUAGE")
    if override:
        return normalize_language(override)
    try:
        stored = json.loads(preferences_path().read_text(encoding="utf-8"))
        if stored.get("language") in LANGUAGES:
            return stored["language"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return normalize_language(locale.getlocale()[0] or "en")


def set_language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError("Unsupported interface language")
    target = preferences_path()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".preferences-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"language": language}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return language


def translate(message: str, language: str | None = None) -> str:
    from .engine.models import app_root
    selected = normalize_language(language or get_language())
    try:
        catalog = json.loads((app_root() / "app/ui/locales" / f"{selected}.json").read_text(encoding="utf-8"))
        return catalog["messages"].get(message, message)
    except (OSError, ValueError, KeyError, TypeError):
        return message
