# Audit remediation: 2.2.2

## Identity consistency and privacy

Name resolution refuses ambiguous multi-word partial mentions. The API resolves the
current document set together before numbering names, using an indexed catalogue of
maximal names. A partial mention seen before its full name therefore receives the
same identifier after both documents have been analyzed. New ambiguous evidence
keeps distinct identities separate. Original propagated associations remain intact.

When this reconciliation changes an existing document's tokens, its revision is
advanced, export report and preview are invalidated, and review history is cleared.
Previously exported files are not rewritten: the document becomes unsaved and must
be exported again. The UI compares document revisions before reusing cached details.
Removing documents rebuilds the current identifier catalogue; clearing the list
also drops all registry values and name fragments. This releases application
references; it is not a forensic memory-erasure guarantee.

## Verified model repair

The model installer checks existing files, stages missing or corrupt weights, and
publishes replacements only after verification. Required models use the existing
transactional group publisher. Source runtime archives are extracted after
publication, never from extensionless staging names. Installed builds keep their
checksum-keyed runtime extraction path. Retrying a failed integrity check attempts
required-model repair and reloads the services. Model downloads contain no documents.

## Detection quality gate

Every Windows build runs the fixed seed-2028 synthetic evaluation with 40 generated
documents plus scanned/layout variants, 93 documents in total. The policy in
`packaging/detection-policy.json` checks value recall, complete positional occurrence
coverage and precision. Missing categories and invalid policy floors fail the gate.
Private evaluation inputs cannot be used with this public corpus gate.

The measured run took 255 seconds and achieved 98.5% precision (459/466), 100%
positional DNI/NIE coverage on native and scanned documents, and 74/77 (96.1%)
positional scanned-name coverage. The scanned-name floor is 95%; identifier floors
are 100% for this fixed corpus. These are regression guards, not a claim of complete
anonymization on real documents. Manual review and verified export remain necessary.
The complete measured report is `docs/detection-evaluation-2.2.2.md`.

## Integrity performance and dependencies

Integrity checking uses two bounded readers for independent model files. Every
installed weight is still read completely; no timestamp/size cache is trusted.
An adversarial regression changes bytes while preserving file length and mtime and
requires the next check to reject the weight. On this machine, concurrent validation
measurements over 8.79 GiB of weights took 32.6/53.6 seconds with two readers and
63.4/79.5 seconds serially. These were shared-load measurements, not a controlled
cross-platform performance benchmark; rotational disks may behave differently.

The workflow also updates setup-node to 7.1.0 and setup-uv to 10.3.0 using verified immutable commit hashes.

The frozen lock updates filelock to 4.2.0, pikepdf to 10.17.0, NumPy to 2.5.4,
ONNX Runtime to 1.31.0, tokenizers to 0.23.3, Ruff to 0.17.1 and Hypothesis to
6.169.4. Windows retains its platform-specific ONNX Runtime DirectML dependency.
The local dependency audit matched all 56 installed distributions exactly and found
no known vulnerabilities. Native executable vulnerability certification remains
outside that Python dependency audit.

## Validation and qualification boundaries

- 301 fast tests passed with zero skips/failures in 149.7 seconds.
- Combined Python statement/branch coverage: 73.33%; all critical module floors pass.
- Real owned-window JavaScript action coverage: 66.84%, above the 65% floor.
- Fourteen new adversarial regressions cover identities, invalidation, cleanup,
  staged model repair/extraction, byte-level integrity and detection policy failures.
- A separate state-machine/identity/real-window subset passed all 11 tests, including
  both the batch fixture and the WebView2 coverage scenario.
- The source application self-test passes, including export verification and crash recovery.
- Ruff, JavaScript syntax, actionlint and whitespace validation pass locally.

The Windows batch fixture uses a private per-run WebView2 profile, the supported
loopback debugging setting, and startup exception diagnostics. It waits explicitly
for the window's load event before invoking the JavaScript bridge, rather than
relying on pywebview's 20-second API-call startup timeout. Its local real-window
checks pass; the hosted Windows failure requires a fresh Actions run for confirmation.
No 2.2.1 installer or previous CI run qualifies this 2.2.2 source/dependency snapshot.
Cross-platform packages, the real advanced model and release publication must pass
the new workflow before a release can be considered qualified.
