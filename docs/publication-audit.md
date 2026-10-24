# Public-release audit

Audit date: **2026-10-24**. This is a snapshot of the checks performed, not a guarantee against every possible bug or future vulnerability.

## Scope

- All four reachable commits through `f786c9c`, including commit messages and author/committer metadata.
- All 27 unique historical file blobs and the 25 tracked files present before cleanup.
- Tracked PNG/ICO metadata, sample image contents, and the screenshot linked by the README.
- Repository About fields, visibility, and release/issue inventory.
- The current runtime dependency requirement and the full application test suite.

## Privacy findings

- No private email addresses, personal home-directory paths, passwords, access tokens, or private keys were found in the audited history.
- Commit attribution uses GitHub aliases and GitHub no-reply email addresses. The repository is attributed to its owner; it is not anonymous.
- The sample PNGs and icon contained no EXIF or personal metadata.
- The README screenshot showed an empty application workspace without personal files, names, or other private content. Its original XMP contained orientation metadata. The README now uses a local copy with all ancillary metadata removed; the decoded pixels are unchanged.
- No releases, release assets, issues, pull requests, or enabled discussions were present at audit time.
- The repository remained private throughout the audit. No visibility or access settings were changed.

## Automated checks

- [detect-secrets](https://github.com/Yelp/detect-secrets): 27 detectors, zero findings across the extracted historical blobs. Network verification of potential secrets was disabled.
- Additional local checks covered private email addresses, personal paths, credential-bearing URLs, known private identifiers, and common access-token/private-key formats. No findings remained.
- [pip-audit](https://github.com/pypa/pip-audit): the previous allowed Pillow 12.x version had known advisory matches. The requirement was updated to `Pillow>=13.0,<14`; Pillow 13.0.0 returned zero known vulnerabilities at audit time.
- Application tests with Python 3.12 and Pillow 13.0.0: **61 tests, 60 passed, one hardlink test skipped by the sandbox**.

## Preventive changes

- The source launcher no longer searches a tool-specific user-profile runtime path.
- `.gitignore` excludes personal PNGs, generated key files, text outputs, builds, environments, caches, logs, and local credentials. Only the reviewed sample PNGs, metadata-free preview, and requirements text file are allowlisted for those file types.
- The documented minimum is now **Python 3.11**, as required by Pillow 13.

Review staged changes before future commits. Ignore rules cannot prevent every possible disclosure, and previously tracked files remain tracked regardless of an ignore rule.

## Binary distribution

The repository contains source and reviewed assets. Local `dist/` executables are ignored and were not part of the GitHub audit. Rebuild any older executable using the updated requirement before distributing it, and audit binary artifacts separately for embedded paths and bundled dependency licenses.

## Recheck after changes

Run the tests after updating dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Repeat history/secret scanning before publication if new files or commits are added. Recheck dependency advisories periodically; a clean result today does not establish future safety.
