# Website legal and privacy operations

Reviewed on 17 October 2026. This record covers the current free informational
website and its desktop downloads. It is an implementation and operations
record, not a legal opinion, certification or statement of universal compliance.

## Public information

All seven website languages have a legal notice with use conditions, a privacy
notice, a cookie notice and an accessibility commitment. Footer links remain
available without an account. The public owner details were supplied explicitly
by the owner for publication. The local build configuration is
`website/legal/owner.json`; it is intentionally excluded from the source
repository. `owner.example.json` documents its structure.

The builder refuses missing identity, postal address, tax identification or
contact data. It accepts only the current free-download models. Sales, paid
subscriptions, advertising, contact forms, newsletters or donation collection
need their own assessment and copy changes before activation. No checkout,
marketing opt-in or fictitious dispute-resolution scheme has been added.

## Processing record

| Activity | Data and people | Purpose and basis | Recipients | Retention |
| --- | --- | --- | --- | --- |
| Website delivery and protection | Visitors' IP, time, URL, response status, browser information and optional referrer | Deliver requests, troubleshoot and detect abuse; GDPR 6(1)(f), service operation and security | Controller, authorised technical administration, infrastructure provider, legally competent authorities | Current Traefik file plus 30 rotated files, daily/size rotation; isolated incident evidence only when justified |
| Internal audience reports | Connection data from the same access logs; report masks IP and drops query strings | Basic internal service-use statistics; GDPR 6(1)(f) | Restricted administrative report, no external analytics script | Configured 30-day report window; original access logs remain subject to the previous row |
| Project correspondence and rights requests | Sender address, optional name, message and necessary verification information | Respond to requested correspondence, GDPR 6(1)(f); legal obligations for rights requests | Controller and self-hosted mail infrastructure provider; authorities when required | While handling the enquiry, then only for applicable obligations or claims; review and remove messages without a continuing purpose |

No account, payment form, browser identifier or website document upload exists.
The server is in Oracle Cloud `eu-frankfurt-1`, confirmed through instance
metadata. Site and mail are self-managed. This is not proof that the provider's
global processing is restricted exclusively to the EEA.

## Legitimate-interest assessment

The interest is delivering and protecting the requested free service and
understanding basic aggregate use. Request handling necessarily processes
network connection data. Short operational logs help diagnose failures and
abuse. Statistics reuse those logs without adding browser tracking. The
countervailing interests are visitors' privacy, protection from identification
and freedom from cross-site profiling. Safeguards include no advertising,
limited administrative access, log rotation, IP masking in reports, query
removal in reports, self-hosted assets, no document submission and an objection
contact. Raw logs remain personal data; the masked reports must not be described
as making the original processing anonymous. Reassess necessity and retention
if traffic, purpose or risk changes.

## Verified technical facts

- Traefik logs rotate daily or at 100 MB with 30 rotated files. This is a
  rotation count, not a guarantee of precisely 30 calendar days.
- The static Nginx container uses three Docker log files capped at 10 MB each.
- GoAccess uses `--anonymize-ip`, `--no-query-string` and a 30-day window.
- No cookies, local/session storage, external fonts, advertising pixels or
  third-party runtime analytics are required by the website.
- HTTPS and security headers are configured. Download hashes are verified
  against the actual public files.
- Basic responsive, keyboard and structural checks are not a complete WCAG or
  EN 301 549 conformance audit. The accessibility page says this explicitly.
- Desktop document processing stays local. Model/runtime downloads connect to
  providers from `models/manifest.json`, including Hugging Face and GitHub.

## Operational items that text cannot complete

1. **Provider documents reviewed; account-specific DPA version remains pending.**
   The owner supplied Oracle's Spanish CSA v062223. Section 5.2 incorporates the
   applicable DPA by reference unless the order provides otherwise. This
   establishes the contractual incorporation mechanism. The order and its
   particular DPA version and transfer terms have not yet been inspected. Keep
   `hosting_dpa_verified` false for that outstanding account-specific check.
   The European hosting region alone does not establish it. Do not sign a new
   agreement or assert acceptance on the owner's behalf.
2. Review project correspondence for continued necessity. No automatic deletion
   of the user's existing shared mailbox was performed. Keep any legally
   necessary evidence restricted and remove data without an ongoing purpose.
   Review mail-backup retention and restoration handling alongside that policy.
3. Handle rights requests through the published legal contact. Record receipt,
   scope, reasonable identity verification, decision and response. Respond
   within one month unless a justified lawful extension applies. Do not demand
   an identity-document copy routinely or disclose other visitors' records.
4. For a personal-data breach, contain and document it, assess risk, and notify
   the competent supervisory authority within 72 hours of awareness where
   required by GDPR Article 33. Inform affected people when Article 34 requires
   it. Actual notifications require the owner's explicit instruction.
5. Maintain necessary processor records and reassess applicability before
   activating a commercial contract flow or new tracking. Public-sector
   accessibility duties and the scope/exemptions of Law 11/2023 depend on the
   actual operator and service; no exemption or certification is assumed here.

## Sources reviewed

- [LSSI, Law 34/2002, especially Articles 10 and 22.2](https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758)
- [GDPR, especially Articles 5, 6, 12–22, 28, 30 and 32–34](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679)
- [LOPDGDD, Organic Law 3/2018](https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673)
- [AEPD cookie guidance](https://www.aepd.es/guias/guia-cookies.pdf)
- [Law 11/2023, accessibility scope and service microenterprise exemption](https://www.boe.es/buscar/act.php?id=BOE-A-2023-11022)
- [Royal Decree 1112/2018, public-sector scope](https://www.boe.es/buscar/act.php?id=BOE-A-2018-12699)
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [Oracle Services Privacy Policy](https://www.oracle.com/legal/privacy/services-privacy-policy/)
- [Oracle contracts](https://www.oracle.com/contracts/cloud-services/)
- [Owner-supplied Oracle Spanish CSA, section 5.2](https://www.oracle.com/contracts/docs/cloud_csa_offline_v062223_es_esp.pdf#page=3)

English and Spanish notices were authored directly. The other five languages
use machine-assisted drafts of public authored copy, with corrections to
controller terminology, upload/download wording, cookie labels and important
limitations. They have not received independent legal-linguistic certification.
