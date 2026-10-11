# GitHub Actions

The `Build and test` workflow runs on pushes to `main`, pull requests, version tags,
manual dispatch, and Mondays at 03:23 UTC. All fixtures and detection benchmarks are
synthetic. Private documents, local model packs, development environments, and local
qualification installers are excluded from Git.

## Required checks

- Workflow validation with pinned actionlint, shell checking, JavaScript syntax
  checking, and redacted Gitleaks scanning of repository history.
- Frozen dependency installation, Ruff, and a Python dependency vulnerability audit.
- Windows fast regression tests, Python branch coverage with overall and critical
  module floors, and real WebView2 JavaScript action coverage.
- Model-free portable regression tests on Linux and Apple Silicon macOS.
- Verified model/runtime downloads, real API and export leakage regressions, Windows
  desktop tests, and the source application self-test.
- Production Windows installer, macOS DMG, and Linux AppImage builds, component
  inventories, isolated installed-package qualification, and SHA-256 sidecars.

Builds require all fast, portable, and workflow security checks to pass. A required
advanced qualification failure also blocks builds. Evidence is retained even when
tests or qualification fail; distribution packages are uploaded only on success.
QA installers are excluded from distribution artifacts. Diagnostic upload failures
are visible but do not suppress remaining qualification checks. Package upload
failures still fail the build and block release publication. Package artifacts
expire after seven days. The real model checksum test runs after downloading models,
not in the model-free regression lanes.

## Extended qualification

Manual, weekly, and version-tag runs additionally download the real advanced-lite
pack and require both advanced tests to run without skips. Windows also produces a
40-document synthetic detection report including scanned variants and a cold/warm
CPU processing profile. Detection reports are diagnostics, not a claim of complete
automatic anonymization; verified export and manual review remain required.

## Releases

A `v<project-version>` tag publishes a GitHub release only after all three platforms
and advanced qualification succeed. The release job checks the tag against
`pyproject.toml` and verifies all three package sidecars before uploading the six
package/hash assets. Only this job has repository write permission. Tags are not
created by ordinary pushes or manual workflow dispatch.

## Security and limits

Actions are pinned to immutable commit hashes and Dependabot proposes weekly
updates for Actions and the uv lockfile. Checkout credentials are not persisted.
Scanners are version-pinned and secret findings are redacted. These checks do not
certify third-party native binaries or replace review of dependency updates.
GitHub-hosted runners process public fixtures only. CI results qualify those runner
environments; they do not certify every desktop, GPU, or user profile. macOS signing
and notarization require the corresponding repository secrets.

The repository is private. This workflow uses dependency auditing and Gitleaks
without requiring a paid GitHub code-scanning entitlement.
