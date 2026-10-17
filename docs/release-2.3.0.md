# Privelto 2.3.0

## Interface languages

The desktop interface supports English, Spanish, Galician, French, German,
Italian and Portuguese. The header selector persists the language atomically
in the application profile. The initial language follows the operating system;
unsupported languages fall back to English. `PRIVELTO_LANGUAGE` provides a
launch-time override for controlled deployments and tests.

Translations are bundled local catalogs. They do not call a translation
service at runtime. Translation drafts were prepared from public interface
copy, with terminology corrections for security and verification messages.
No documents, detected values or other user data were used for translation.
Catalog tests check complete keys and exact placeholder preservation.

Changing the language preserves selected categories, document identities,
findings, replacement tokens and review history. Localized interface support
does not establish equal automatic detection accuracy for every language or
jurisdiction. Existing detection policies and mandatory verification remain.

## Distribution and profile compatibility

Public application and package names now use Privelto. The existing Windows
installer application ID and macOS bundle ID are preserved. Existing desktop
profiles retain their historical Anonimato path, allowing installed models to
remain usable. New Windows installations default to the Privelto program
directory; upgrades retain the previous installation location.

Each platform produces its usual installable package and a portable archive:

| Platform | Installable package | Portable archive |
| --- | --- | --- |
| Windows x64 | Per-user EXE installer | ZIP |
| macOS Apple Silicon | DMG, copy app to Applications | ZIP |
| Linux x86_64 | AppImage | tar.gz |

The portable archive contains a `privelto-portable.json` marker. Extract the
entire archive to a writable directory. Application models, runtime,
preferences and logs are stored in a sibling `PriveltoData` directory. Move
the whole folder to preserve that profile. An invalid marker fails instead of
silently writing into the installed profile. Operating-system temporary files
and GPU-driver caches are outside the portable profile guarantee.

Portable archives do not bundle AI models. Windows portable use requires the
WebView2 Runtime separately; the installer can install it. Signing and macOS
notarization depend on deployment credentials and are not implied by a
successful build.

## Verification

The build workflow retains its source, model, security and installed-package
checks. Portable qualification extracts the actual produced archive, launches
its executable with a fictitious PDF, verifies output integrity and worker
recovery, relocates the portable folder, and repeats the check with its
preserved portable profile. SHA-256 sidecars cover all six distribution files.

Hosted workflow outcomes and published download checks must be recorded after
they finish. This source document alone is not evidence of a completed build.
