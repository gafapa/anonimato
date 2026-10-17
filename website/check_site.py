"""Check every generated locale, linked file and downloadable byte before publication."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent / "dist"
LANGUAGES = ("en", "es", "gl", "fr", "de", "it", "pt")


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.download_names: list[str] = []
        self.private_values: dict[str, str] = {}
        self.language = ""
        self.alternates: set[str] = set()
        self.requirements = 0

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if tag == "html":
            self.language = attrs.get("lang", "")
        for name in ("href", "src"):
            if attrs.get(name, "").startswith("/"):
                self.links.append(attrs[name])
        if "package-download" in attrs.get("class", "").split():
            self.download_names.append(attrs.get("aria-label", ""))
        if "data-private" in attrs:
            self.private_values[attrs["data-private"]] = attrs.get("data-label", "")
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates.add(attrs.get("hreflang", ""))
        if "requirement-row" in attrs.get("class", "").split():
            self.requirements += 1


def check() -> None:
    for language in LANGUAGES:
        folder = ROOT / ("" if language == "en" else language)
        for suffix in ("index.html", "legal/index.html", "privacy/index.html", "cookies/index.html", "accessibility/index.html"):
            page = Page()
            page.feed((folder / suffix).read_text(encoding="utf-8"))
            assert page.language == language, (language, suffix)
            assert set(LANGUAGES) <= page.alternates, (language, "alternate languages")
            for link in page.links:
                target = ROOT / unquote(urlsplit(link).path.lstrip("/"))
                if target.is_dir():
                    target /= "index.html"
                assert target.is_file(), (language, link)
            if suffix == "index.html":
                assert len(page.download_names) == len(set(page.download_names)) == 6
                assert all(page.download_names)
                assert page.requirements == 8
                assert len(page.private_values) == 4
                assert page.private_values["17 / 10 / 2026"] == "[DATE 1]"
    manifest = json.loads((ROOT / "downloads/release.json").read_text(encoding="utf-8"))
    assert len(manifest["packages"]) == 6
    for package in manifest["packages"]:
        path = ROOT / "downloads" / package["filename"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == package["sha256"]
        assert path.stat().st_size == package["size_bytes"]
    print("Passed: 35 localized pages, all links, date redaction, requirements and six package hashes.")


if __name__ == "__main__":
    check()
