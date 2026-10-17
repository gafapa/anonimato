"""Build the multilingual Privelto site from verified, qualified CI artifacts."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website"
OUTPUT = SOURCE / "dist"
ARTIFACTS = ROOT / "tmp/privelto-2.3-final-artifacts"
VERSION = "2.3.0"
COMMIT = "cecd1f9e0b22b9fbf7c1103b270da0879e681b5f"
RUN = "https://github.com/gafapa/anonimato/actions/runs/39061449297"
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
LEGAL_COPY = {language: json.loads((SOURCE / "legal" / f"{language}.json").read_text(encoding="utf-8")) for language in LANGUAGE_NAMES}
LEGAL_PAGES = ("legal", "privacy", "cookies", "accessibility")
LEGAL_OWNER: dict[str, str | bool] = {}


def load_legal_owner(path: Path, *, preview: bool = False) -> dict:
    for language, content in LEGAL_COPY.items():
        if set(content) != set(LEGAL_COPY["en"]) or set(content["labels"]) != set(LEGAL_COPY["en"]["labels"]):
            raise RuntimeError(f"Incomplete legal navigation: {language}")
        for section in LEGAL_PAGES:
            translated = content[section]["sections"]
            original = LEGAL_COPY["en"][section]["sections"]
            if len(translated) != len(original):
                raise RuntimeError(f"Incomplete legal sections: {language}: {section}")
            for source, target in zip(original, translated, strict=True):
                if len(source["paragraphs"]) != len(target["paragraphs"]):
                    raise RuntimeError(f"Incomplete legal paragraphs: {language}: {section}")
                for before, after in zip(source["paragraphs"], target["paragraphs"], strict=True):
                    if not after.strip() or re.findall(r"\{[^}]*\}", before) != re.findall(r"\{[^}]*\}", after):
                        raise RuntimeError(f"Invalid legal placeholders: {language}: {section}")
    if preview:
        return {"name": "Example owner — preview only", "tax_id": "NOT CONFIGURED", "address": "NOT CONFIGURED",
                "email": "hello@privelto.com", "registration": "", "regulated_profession": "",
                "commercial_model": "free_downloads", "hosting_dpa_verified": False,
                "hosting_dpa_url": "https://www.oracle.com/contracts/cloud-services/",
                "international_transfer_safeguards": "pending_verification"}
    if not path.is_file():
        raise RuntimeError("Legal publication requires the owner's confirmed public details and hosting DPA. See website/legal/owner.example.json.")
    owner = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "tax_id", "address", "email", "hosting_dpa_url"):
        if not isinstance(owner.get(key), str) or not owner[key].strip():
            raise RuntimeError(f"Missing confirmed legal-owner field: {key}")
    if owner["email"] not in ("hello@privelto.com", "pablo@privelto.com") or owner.get("commercial_model") not in ("free_downloads", "free_with_donations"):
        raise RuntimeError("Legal copy must be reviewed for a changed contact or commercial model")
    if owner.get("hosting_dpa_verified") is not True:
        print("Operational item pending: verify the account's actual Oracle DPA and transfer safeguards; public Oracle terms are not proof of the account agreement.")
    agreement = urlsplit(owner["hosting_dpa_url"])
    if agreement.scheme != "https" or agreement.netloc != "www.oracle.com":
        raise RuntimeError("The confirmed hosting DPA must link to the official Oracle contract")
    return owner


def language_path(language: str) -> str:
    return "/" if language == "en" else f"/{language}/"



def header(language: str, *, section: str = "") -> str:
    copy = COPY[language]
    home = language_path(language)
    suffix = section + "/" if section else ""
    title = "Privelto — " + LEGAL_COPY[language]["labels"][section] if section else copy["title"]
    options = "".join(f'<option value="{language_path(code)}{suffix}" lang="{code}" {"selected" if code == language else ""}>{name}</option>'
                      for code, name in LANGUAGE_NAMES.items())
    alternatives = "".join(f'<link rel="alternate" hreflang="{code}" href="https://privelto.com{language_path(code)}{suffix}">'
                           for code in LANGUAGE_NAMES)
    return f'''<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(copy['description'])}">
<meta name="theme-color" content="#1d3f8f"><link rel="canonical" href="https://privelto.com{home}{suffix}">
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
    legal_links = "".join(f'<a href="{home}{section}/">{escape(LEGAL_COPY[language]["labels"][section])}</a>' for section in LEGAL_PAGES)
    return f'''<footer class="site-footer"><div><a class="brand" href="{home}">privelto<span class="brand-dot">.</span></a><p>{copy['footer']}</p></div><div class="footer-links">{legal_links}<a href="https://github.com/gafapa/anonimato">{copy['source']}</a><a href="mailto:hello@privelto.com">hello@privelto.com</a><span>AGPL-3.0-or-later</span></div></footer></body></html>'''


def legal_page(language: str, section: str) -> str:
    copy = LEGAL_COPY[language]
    labels = copy["labels"]
    content = copy[section]
    email = escape(str(LEGAL_OWNER["email"]))

    def paragraph_html(paragraph: str) -> str:
        text = escape(paragraph.format(email=LEGAL_OWNER["email"]))
        return text.replace(email, f'<a href="mailto:{email}">{email}</a>')
    identity = ""
    if section in ("legal", "privacy"):
        fields = "".join(f'<div><dt>{escape(labels[key])}</dt><dd>{escape(str(LEGAL_OWNER[key]))}</dd></div>'
                         for key in ("name", "tax_id", "address", "email", "registration", "regulated_profession") if LEGAL_OWNER.get(key))
        identity = f'<section class="legal-section"><h2>{escape(labels["owner"])}</h2><dl class="legal-owner">{fields}</dl></section>'
    sections = "".join('<section class="legal-section"><h2>' + escape(item["title"]) + '</h2>' +
                       "".join('<p>' + paragraph_html(paragraph) + '</p>' for paragraph in item["paragraphs"]) + '</section>'
                       for item in content["sections"])
    sources = {
        "legal": [("LSSI — Ley 34/2002", "https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758"),
                  ("GNU AGPL-3.0-or-later", "https://github.com/gafapa/anonimato/blob/" + COMMIT + "/LICENSE"),
                  ("Third-party licences", "https://github.com/gafapa/anonimato/blob/" + COMMIT + "/THIRD_PARTY.md")],
        "privacy": [("GDPR / RGPD", "https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679"),
                    ("LOPDGDD — Ley Orgánica 3/2018", "https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673"),
                    ("AEPD", "https://www.aepd.es/"), ("Oracle — Privacy", "https://www.oracle.com/legal/privacy/services-privacy-policy/"),
                    ("Oracle — Contracts", str(LEGAL_OWNER["hosting_dpa_url"]))],
        "cookies": [("AEPD — Cookies", "https://www.aepd.es/guias/guia-cookies.pdf"),
                    ("LSSI — Article 22.2", "https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a22")],
        "accessibility": [("WCAG 2.2", "https://www.w3.org/TR/WCAG22/")],
    }
    references = "".join(f'<li><a href="{escape(url)}">{escape(title)}</a></li>' for title, url in sources[section])
    return header(language, section=section) + f'''<main id="main" class="section privacy-page legal-page"><h1>{escape(labels[section])}</h1><p class="updated">{escape(labels['updated'])}</p><p>{escape(content['intro'])}</p>{identity}{sections}<section class="legal-section"><h2>{escape(labels['resources'])}</h2><ul>{references}</ul></section><a class="text-link" href="{language_path(language)}">{escape(labels['back'])}</a></main>''' + footer(language)


def render_pages(manifest: list[dict]) -> None:
    for language in COPY:
        target = OUTPUT / language_path(language).strip("/")
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.html").write_text(page(language, manifest), encoding="utf-8")
        for section in LEGAL_PAGES:
            folder = target / section
            folder.mkdir(exist_ok=True)
            (folder / "index.html").write_text(legal_page(language, section), encoding="utf-8")
    shutil.copytree(SOURCE / "assets", OUTPUT / "assets", dirs_exist_ok=True)
    font_root = OUTPUT / "assets/fonts"
    font_root.mkdir(exist_ok=True)
    for filename in ["plex-sans-400.woff2", "plex-sans-500.woff2", "plex-sans-600.woff2", "plex-mono-400.woff2", "OFL.txt"]:
        shutil.copy2(ROOT / "app/ui/fonts" / filename, font_root / filename)
    (OUTPUT / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://privelto.com/sitemap.xml\n", encoding="utf-8")
    paths = [language_path(language) + suffix for language in LANGUAGE_NAMES for suffix in ["", *(section + "/" for section in LEGAL_PAGES)]]
    (OUTPUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>https://privelto.com{path}</loc></url>' for path in paths) + '</urlset>\n', encoding="utf-8")


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
    render_pages(manifest)
    print(json.dumps({"output": str(OUTPUT), "packages": manifest}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--run-id", default=RUN.rsplit("/", 1)[1])
    parser.add_argument("--commit", default=COMMIT)
    parser.add_argument("--legal-owner", type=Path, default=SOURCE / "legal/owner.json")
    parser.add_argument("--legal-preview", action="store_true", help="Render into tmp with fictional owner fields; never changes the publishable site")
    args = parser.parse_args()
    ARTIFACTS = args.artifacts.resolve()
    RUN = "https://github.com/gafapa/anonimato/actions/runs/" + args.run_id
    COMMIT = args.commit
    LEGAL_OWNER = load_legal_owner(args.legal_owner, preview=args.legal_preview)
    if args.legal_preview:
        manifest = json.loads((OUTPUT / "downloads/release.json").read_text(encoding="utf-8"))["packages"]
        OUTPUT = ROOT / "tmp/privelto-legal-preview"
        render_pages(manifest)
        print(f"Legal preview only: {OUTPUT}")
    else:
        build()
