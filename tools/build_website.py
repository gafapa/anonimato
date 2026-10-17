"""Build the multilingual Privelto site from verified, qualified CI artifacts."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website"
OUTPUT = SOURCE / "dist"
ARTIFACTS = ROOT / "tmp/privelto-2.3-artifacts"
VERSION = "2.3.0"
COMMIT = "2ddc9e87f7383d53e6947c06186ef4f299fe51f5"
RUN = "https://github.com/gafapa/anonimato/actions/runs/39058857003"
PACKAGES = [
    ("Windows", "Windows 10 / 11 · x64", "anonimato-Windows", f"PriveltoSetup-{VERSION}.exe", "installer"),
    ("Windows", "Windows 10 / 11 · x64", "anonimato-Windows", f"Privelto-{VERSION}-windows-x64-portable.zip", "portable"),
    ("macOS", "Apple Silicon · arm64", "anonimato-macOS", f"Privelto-{VERSION}-macos-arm64.dmg", "installer"),
    ("macOS", "Apple Silicon · arm64", "anonimato-macOS", f"Privelto-{VERSION}-macos-arm64-portable.zip", "portable"),
    ("Linux", "Linux · x86_64", "anonimato-Linux", f"Privelto-{VERSION}-linux-x86_64.AppImage", "installer"),
    ("Linux", "Linux · x86_64", "anonimato-Linux", f"Privelto-{VERSION}-linux-x86_64-portable.tar.gz", "portable"),
]

LANGUAGE_NAMES = {"en": "English", "es": "Español", "gl": "Galego", "fr": "Français", "de": "Deutsch", "it": "Italiano", "pt": "Português"}
COPY = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in (SOURCE / "locales").glob("*.json")}


def language_path(language: str) -> str:
    return "/" if language == "en" else f"/{language}/"



def header(language: str, *, privacy: bool = False) -> str:
    copy = COPY[language]
    home = language_path(language)
    suffix = "privacy/" if privacy else ""
    options = "".join(f'<option value="{language_path(code)}{suffix}" lang="{code}" {"selected" if code == language else ""}>{name}</option>'
                      for code, name in LANGUAGE_NAMES.items())
    alternatives = "".join(f'<link rel="alternate" hreflang="{code}" href="https://privelto.com{language_path(code)}{suffix}">'
                           for code in LANGUAGE_NAMES)
    return f'''<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(copy['title'] if not privacy else 'Privelto — ' + copy['privacy'])}</title><meta name="description" content="{escape(copy['description'])}">
<meta name="theme-color" content="#1d3f8f"><link rel="canonical" href="https://privelto.com{home}{'privacy/' if privacy else ''}">
{alternatives}<link rel="alternate" hreflang="x-default" href="https://privelto.com/{suffix}">
<meta property="og:title" content="Privelto"><meta property="og:description" content="{escape(copy['description'])}"><meta property="og:type" content="website"><meta property="og:url" content="https://privelto.com{home}{suffix}">
<link rel="icon" type="image/svg+xml" href="/assets/mark.svg"><link rel="stylesheet" href="/assets/site.css"><script src="/assets/site.js" defer></script>
</head><body>
<!-- THESIS: Make local redaction tangible through a fictional document with reversible redaction.
OWN-WORLD: Inherit IBM Plex and navy from the desktop app; white document paper on a cool pale surface.
STORY: Understand removal, try the example, review requirements, download an original verified package.
FIRST VIEWPORT: Large left-aligned proposition beside a real HTML document example and an explicit download action.
FORM: Document demonstration, established app identity; surface seed e42f1300. Code-first implementation for the existing visual world.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance -->
<a class="skip" href="#main">{copy['skip']}</a>
<header class="site-header"><a class="brand" href="{home}" aria-label="Privelto"><img src="/assets/mark.svg" width="30" height="30" alt="">privelto<span class="brand-dot">.</span></a>
<nav aria-label="Privelto"><a class="nav-how" href="{home}#how">{copy['how']}</a><a class="nav-requirements" href="{home}#requirements">{copy['requirements']}</a><a href="{home}#downloads">{copy['downloads']}</a><label class="website-language"><span class="visually-hidden">{copy['language']}</span><select data-language aria-label="{escape(copy['language'])}">{options}</select></label></nav></header>'''


def footer(language: str) -> str:
    copy = COPY[language]
    home = language_path(language)
    return f'''<footer class="site-footer"><div><a class="brand" href="{home}">privelto<span class="brand-dot">.</span></a><p>{copy['footer']}</p></div><div class="footer-links"><a href="{home}privacy/">{copy['privacy']}</a><a href="https://github.com/gafapa/anonimato">{copy['source']}</a><a href="mailto:hello@privelto.com">hello@privelto.com</a><span>AGPL-3.0-or-later</span></div></footer></body></html>'''


def page(language: str, manifest: list[dict]) -> str:
    c = COPY[language]
    download_rows = ""
    for platform in ["Windows", "macOS", "Linux"]:
        packages = [package for package in manifest if package["platform"] == platform]
        choices = ""
        for package in packages:
            package_label = f"Privelto — {platform} ({package['architecture']}) — {c[package['kind']]}"
            choices += f'''<div class="package-choice"><a class="button package-download" href="/downloads/{package['filename']}" aria-label="{escape(c['downloadButton'] + ' ' + package_label)}" download>{c[package['kind']]} <span aria-hidden="true">↓</span></a><p><span>{package['size_mb']:.1f} MB</span> · <a class="hash-link" href="/downloads/{package['filename']}.sha256" aria-label="{escape('SHA-256 — ' + package_label)}">{c['checksum']}</a></p></div>'''
        download_rows += f'''<div class="download-row"><div><h3>{platform}</h3><p>{packages[0]['architecture']}</p></div><div class="download-actions">{choices}</div></div>'''
    requirements = "".join(f'<div class="requirement-row"><dt>{escape(title)}</dt><dd>{escape(body)}</dd></div>' for title, body in [
        ("Windows", c["reqWindows"]), ("macOS", c["reqMac"]), ("Linux", c["reqLinux"]),
        (c["reqMemoryTitle"], c["reqMemory"]), (c["reqStorageTitle"], c["reqStorage"]),
        (c["reqAdvancedTitle"], c["reqAdvanced"]), (c["reqPortableTitle"], c["reqPortable"]),
        (c["reqOfflineTitle"], c["reqOffline"]),
    ])
    faq = "".join(f"<details><summary>{c[f'q{i}']}</summary><p>{c[f'a{i}']}</p></details>" for i in range(1, 6))
    return header(language) + f'''
<main id="main"><section class="hero section"><div class="hero-copy"><h1>{c['headline']}</h1><p class="intro">{c['intro']}</p><div class="hero-actions"><a class="button primary" href="#downloads">{c['primary']} <span aria-hidden="true">↓</span></a><a class="text-link" href="#how">{c['secondary']} <span aria-hidden="true">↗</span></a></div><ul class="trust-list"><li>{c['license']}</li><li>{c['local']}</li></ul></div>
<div class="demo" data-demo data-redacted="false"><div class="demo-heading"><span>{c['demoTitle']}</span><span class="status-dot" aria-hidden="true"></span></div><div class="document-stage"><article class="document" aria-label="{escape(c['demoNote'])}"><div class="document-top"><span class="document-brand">NORTH / STUDIO</span><span class="document-ref">DOC—014</span></div><p class="document-kind">{c['docHeading']}</p><h2>{c['docSub']}</h2><dl><dt>{c['nameLabel']}</dt><dd><span class="private-value" data-private="Alex Morgan" data-label="[NAME 1]">Alex Morgan</span></dd><dt>{c['emailLabel']}</dt><dd><span class="private-value" data-private="alex@example.com" data-label="[EMAIL 1]">alex@example.com</span></dd><dt>{c['refLabel']}</dt><dd><span class="private-value" data-private="DEMO-042-918" data-label="[REFERENCE 1]">DEMO-042-918</span></dd><dt>{c['dateLabel']}</dt><dd><span class="private-value" data-private="17 / 10 / 2026" data-label="[DATE 1]">17 / 10 / 2026</span></dd></dl><p class="document-body">{c['docBody']}</p><div class="document-lines" aria-hidden="true"><span></span><span></span><span></span></div><div class="document-bottom"><span>PROJECT / 2026</span><span>1 / 1</span></div></article></div><div class="demo-controls"><p class="demo-note">{c['demoNote']}</p><button class="button demo-button" type="button" data-toggle aria-pressed="false" data-before="{escape(c['toggle'])}" data-after="{escape(c['restore'])}" data-status-before="{escape(c['demoStatus'])}" data-status-after="{escape(c['demoDone'])}">{c['toggle']}</button><p class="demo-status" data-status role="status">{c['demoStatus']}</p></div></div></section>
<section class="method section" id="how"><div class="section-heading"><h2>{c['mechanism']}</h2><p>{c['mechanismBody']}</p></div><div class="steps">{''.join(f'<article><span class="step-mark" aria-hidden="true">{mark}</span><h3>{c[f"step{i}"]}</h3><p>{c[f"step{i}Body"]}</p></article>' for i, mark in [(1, '⌕'), (2, '↔'), (3, '✓')])}</div></section>
<section class="downloads section" id="downloads"><div class="section-heading"><h2>{c['downloadTitle']}</h2><p>{c['downloadIntro']}</p></div><div class="download-layout"><div><div class="release-label">{c['release'].format(version=VERSION)}</div><div class="download-table">{download_rows}</div><div class="release-links"><a href="/downloads/SHA256SUMS.txt">{c['checksums']}</a><a href="{RUN}">{c['evidence']}</a><a href="https://github.com/gafapa/anonimato/tree/{COMMIT}">{c['source']}</a></div><p class="rename-note">{c['rename']}</p></div><aside class="setup"><h3>{c['setupTitle']}</h3>{''.join(f'<p>{c[f"setup{i}"]}</p>' for i in range(1,5))}</aside></div></section>
<section class="requirements section" id="requirements"><div class="section-heading"><h2>{c['requirementsTitle']}</h2><p>{c['requirementsIntro']}</p></div><dl class="requirements-grid">{requirements}</dl></section>
<section class="faq section"><h2>{c['faqTitle']}</h2><div>{faq}</div></section>
<section class="closing section"><h2>{c['closing']}</h2><div><a class="button primary" href="#downloads">{c['download']} <span aria-hidden="true">↓</span></a><p>{c['contact']} <a href="mailto:hello@privelto.com">hello@privelto.com</a></p></div></section></main>''' + footer(language)


def build() -> None:
    for platform in ["linux", "macos"]:
        folder = "anonimato-Linux" if platform == "linux" else "anonimato-macOS"
        report = json.loads((ARTIFACTS / folder / "dist" / f"package-qualification-{platform}.json").read_text(encoding="utf-8-sig"))
        if not all(report.get(key) is True for key in ["ok", "install", "replace", "remove"]):
            raise RuntimeError(f"Package qualification failed: {platform}")
    windows_reports = list((ARTIFACTS / "anonimato-Windows/tmp/installer-qualification").rglob("result.json"))
    if len(windows_reports) != 1:
        raise RuntimeError("Expected exactly one Windows qualification report")
    report = json.loads(windows_reports[0].read_text(encoding="utf-8-sig"))
    if report.get("version") != VERSION or not all(report.get(key) is True for key in ["ok", "profilePreserved", "uninstallVerified", "productionRegistrationUnchanged"]):
        raise RuntimeError("Windows installer qualification failed")
    for platform, folder in [("Windows", "anonimato-Windows"), ("macOS", "anonimato-macOS"), ("Linux", "anonimato-Linux")]:
        portable = json.loads((ARTIFACTS / folder / "dist" / f"portable-qualification-{platform}.json").read_text(encoding="utf-8-sig"))
        if not all(portable.get(key) is True for key in ["ok", "launch", "relocate", "portable_data"]):
            raise RuntimeError(f"Portable qualification failed: {platform}")
    if set(COPY) != set(LANGUAGE_NAMES):
        raise RuntimeError("Missing website language")
    if any(set(copy) != set(COPY["en"]) for copy in COPY.values()):
        raise RuntimeError("Incomplete website translation")
    for language, copy in COPY.items():
        for key, value in copy.items():
            if not value.strip() or sorted(re.findall(r"\{\w+\}", value)) != sorted(re.findall(r"\{\w+\}", COPY["en"][key])):
                raise RuntimeError(f"Invalid website translation placeholders: {language}: {key}")
        emphasis = re.search(r"<em>(.*?)</em>", copy["headline"])
        if emphasis is None or not any(character.isalpha() for character in emphasis[1]):
            raise RuntimeError(f"Missing meaningful hero emphasis: {language}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    download_root = OUTPUT / "downloads"
    download_root.mkdir(exist_ok=True)
    manifest = []
    for platform, architecture, folder, filename, kind in PACKAGES:
        package = ARTIFACTS / folder / "dist" / filename
        with package.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        expected = package.with_name(filename + ".sha256").read_text().split()[0]
        if digest != expected:
            raise RuntimeError(f"Checksum mismatch: {filename}")
        shutil.copy2(package, download_root / filename)
        (download_root / (filename + ".sha256")).write_text(f"{digest}  {filename}\n", encoding="utf-8")
        manifest.append({"platform": platform, "architecture": architecture, "kind": kind, "filename": filename, "sha256": digest, "size_bytes": package.stat().st_size, "size_mb": package.stat().st_size / 1_000_000})
    (download_root / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['filename']}\n" for item in manifest), encoding="utf-8")
    (download_root / "release.json").write_text(json.dumps({"version": VERSION, "source_commit": COMMIT, "ci_run": RUN, "package_brand": "Privelto", "site_brand": "Privelto", "packages": manifest}, indent=2) + "\n", encoding="utf-8")
    for language, c in COPY.items():
        target = OUTPUT / language_path(language).strip("/")
        target.mkdir(exist_ok=True)
        (target / "index.html").write_text(page(language, manifest), encoding="utf-8")
        privacy = target / "privacy"
        privacy.mkdir(exist_ok=True)
        (privacy / "index.html").write_text(header(language, privacy=True) + f'<main id="main" class="privacy-page section"><h1>{c["privacyTitle"]}</h1><p class="updated">{c["updated"]}</p><p>{c["privacyBody"]}</p><a class="text-link" href="{language_path(language)}">{c["back"]}</a></main>' + footer(language), encoding="utf-8")
    shutil.copytree(SOURCE / "assets", OUTPUT / "assets", dirs_exist_ok=True)
    font_root = OUTPUT / "assets/fonts"
    font_root.mkdir(exist_ok=True)
    for filename in ["plex-sans-400.woff2", "plex-sans-500.woff2", "plex-sans-600.woff2", "plex-mono-400.woff2", "OFL.txt"]:
        shutil.copy2(ROOT / "app/ui/fonts" / filename, font_root / filename)
    (OUTPUT / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://privelto.com/sitemap.xml\n", encoding="utf-8")
    (OUTPUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>https://privelto.com{path}</loc></url>' for path in [language_path(language) + suffix for language in LANGUAGE_NAMES for suffix in ['', 'privacy/']]) + '</urlset>\n', encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "packages": manifest}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--run-id", default=RUN.rsplit("/", 1)[1])
    parser.add_argument("--commit", default=COMMIT)
    args = parser.parse_args()
    ARTIFACTS = args.artifacts.resolve()
    RUN = "https://github.com/gafapa/anonimato/actions/runs/" + args.run_id
    COMMIT = args.commit
    build()
