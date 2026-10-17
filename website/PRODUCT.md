# Privelto website

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML, CSS and JavaScript, deployed to the user's existing Nginx and Traefik infrastructure. The existing infrastructure determines this stack.

## Product Purpose

Introduce Privelto, the new public brand for Anonimato, and provide working desktop downloads at privelto.com.

## Capabilities and Constraints

The application processes PDFs and images locally, detects personal information, faces and signatures, supports manual review, destructively redacts selected content and verifies the output before saving. Model downloads require a network connection; an offline package workflow exists. Detection requires human review. No guarantee of perfect detection is appropriate.

The 2.3.0 release adds English, Spanish, Galician, French, German, Italian and
Portuguese interfaces, installable packages and portable archives. Windows x64,
macOS 15+ Apple Silicon and Linux x86_64 are the packaging targets. CI run
39061449297 must qualify the actual packages before publication. Windows
executables are unsigned; macOS notarization requires configured credentials.
Do not imply Intel Mac support, universal Linux compatibility, or identical
national identifier detection coverage from interface localization.

The website includes an execution-requirements section and a fictional
four-field demonstration whose date is also redacted. Portable app-managed data
belongs in a writable PriveltoData folder beside the extracted program.


## Brand Commitments

The user selected Privelto and owns privelto.com. The existing application uses IBM Plex Sans, IBM Plex Mono and a navy blue accent. Preserve those assets for continuity.

## Evidence on Hand

README.md, AGPL-3.0-or-later project license, app/ui/styles.css, bundled OFL fonts, and downloaded CI artifacts under tmp/privelto-artifacts.

## Open Decisions

The user requested broader app and website language support. The site provides the same seven interface languages. The user approved preserving the existing typography and blue identity and delegated visual details. The user requested the same mail arrangement as other domains: aliases to the existing account. No standing workflow preference is inferred from silence.

## Product Principles

- Never upload visitor documents or provide an upload control on the marketing site.
- Provide verifiable downloads and honest package identity.
- Use fictional data in demonstrations.
- Make downloads, setup requirements and human review limits easy to find.
