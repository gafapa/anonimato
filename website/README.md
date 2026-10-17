# Privelto website

Production: https://privelto.com/ (English), with Spanish, Galician, French, German, Italian and Portuguese under /es/, /gl/, /fr/, /de/, /it/ and /pt/.

This static website uses the desktop application's self-hosted IBM Plex fonts
and navy identity. It contains no document upload, tracking scripts or account
system. The reversible document demonstration uses fictional data only.

## Build

From the application repository root:

```powershell
gh run download 39059938202 -n anonimato-Windows -n anonimato-macOS -n anonimato-Linux -D tmp/privelto-2.3-artifacts
python tools/build_website.py
python -m http.server 8766 --bind 127.0.0.1 --directory website/dist
```

The generator validates package qualification reports and original SHA-256
files before copying all six packages. `dist/` is generated and ignored.
GitHub CI artifacts expire; retain the deployed downloads and original
qualification evidence when preparing a future release. Do not silently
replace an expired build with a different build under the same versioned URL.

Localized copy lives in `website/locales/`; the build and verified package metadata live in `tools/build_website.py`; styles, the geometric brand mark and
the demonstration behavior live in `website/assets/`. No generated bitmap
assets are used. Font provenance and license: `app/ui/fonts/OFL.txt`.

## Release identity and limits

Privelto 2.3.0 provides seven interface languages and uses the Privelto name in
its application and distributions. Package source commit:
`223ce8707bc5e07b2087d619b7f0e4e4a3598c56`. Qualification workflow:
https://github.com/gafapa/anonimato/actions/runs/39059938202.

- Windows x64: per-user EXE installer and portable ZIP; unsigned.
- macOS Apple Silicon arm64: DMG and portable ZIP; not notarized without configured credentials.
- Linux x86_64: AppImage and portable tar.gz; qualification is environment-specific.

The build refuses missing, unsuccessful installation or portable-relocation
qualification reports. Release metadata records the exact source commit and CI
run. A metadata field cannot substitute for successful package qualification.

Model and runtime downloads are separate from the application packages.
Human review remains necessary. Package checksums prove byte identity,
not perfect detection, platform universality or security certification.

## Publish

Server operations follow `D:/gallego.top/runbooks/static-site-content.md`.
The canonical deployment directory is
`D:/Otros IA/gestion_gallego_top/static-sites/sites/privelto.com`.

```powershell
python tools/stage_website.py
& D:/gallego.top/scripts/publish_static_site.ps1 -Domain privelto.com -ManagementRoot 'D:/Otros IA/gestion_gallego_top'
```

The staging helper also prepares the domain's Nginx virtual host, adds its
Traefik routers and security middleware, and registers its server inventory
entry. Keep the local shared routing configuration synchronized with the
live server before invoking it. Do not mark a previously verified site as
pending or overwrite unrelated routers from a stale local copy.

The apex serves both languages; `www` redirects to the apex. Downloads use
attachment headers and immutable versioned URLs. Page assets are revalidated.

## Mail

The existing mail service receives `pablo`, `hello`, `support`, `contact`,
`postmaster` and `abuse` at `privelto.com`, all as aliases of
`pablo@gallego.top`. No new login or password was created.

Use https://correo.gallego.top/ with the existing account. Sender identities
for `pablo@privelto.com`, `hello@privelto.com` and `support@privelto.com`
were added transactionally without changing the default sender.

MX points to `mail.gallego.top`; SPF is `v=spf1 mx -all`, DKIM uses the
`mail` selector and DMARC uses `p=quarantine`. Server-side configuration and
webmail backups are recorded in the hub's deployment evidence.

## Verification

The publication checks included complete public downloads and SHA-256
comparison for all six packages; HTTPS and www redirection; desktop and
mobile browser checks; four-field demonstration round trips including the date; FAQ controls; accessible
download names; and local link validation for all fourteen pages.

Mail checks covered public MX/TXT records, matching DKIM, valid SMTP/IMAP
TLS, accepted alias recipients, rejection of unknown local recipients and
external relay rejection. No test message was submitted, so end-to-end
delivery and external inbox placement are not claimed.

The mechanical design detector ran in degraded regex mode because parser
dependencies were unavailable. A separate visual review closed its one
material finding (ambiguous download link names). This is not a complete
accessibility certification.
