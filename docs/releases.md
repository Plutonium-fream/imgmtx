# Windows portable releases

The application version lives in `imgmtx/__init__.py`. The packaging script uses it for the Windows file/product version, folder names, ZIP, standalone executable, manifests, and third-party notices. Help displays the same version.

## Build

Use a clean, committed checkout and 64-bit Python on Windows. Python 3.12 is the tested release-build environment.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build.ps1 -Python .\.venv\Scripts\python.exe
```

The build requires Pillow 13 or newer. It includes complete notices for Python, Pillow and its native image libraries, Tcl/Tk, OpenSSL, libffi, and the PyInstaller bootloader. The Python notice includes the restrictions for its Microsoft runtime code. License source provenance is documented in [`licenses/README.md`](../licenses/README.md).

## Artifacts

For version `1.0.0`, the output is:

```text
dist/
├── ImgMtx-1.0.0-windows-x64/
│   ├── ImgMtx.exe
│   ├── README.md
│   ├── LICENSE
│   ├── THIRD_PARTY_NOTICES.md
│   ├── BUILD_INFO.json
│   ├── SHA256SUMS
│   └── licenses/
├── ImgMtx-1.0.0-windows-x64.zip
├── ImgMtx-1.0.0-windows-x64.exe
├── THIRD_PARTY_NOTICES.md
├── BUILD_INFO.json
└── SHA256SUMS
```

The inner checksum file covers files inside the portable folder. The outer file covers the downloadable ZIP, standalone executable, notices, and build metadata. Hashes are SHA-256, in the usual `digest  filename` format.

`BUILD_INFO.json` records the source commit, app/runtime versions, target platform, unsigned status, and binary privacy-audit counts. It contains no developer filesystem paths.

## Validation and publishing

Before packaging, source changes must be committed. After building:

1. Verify the Windows file/product version and inspect the portable ZIP contents.
2. Verify every inner and outer checksum and the executable's startup.
3. Run the packaged app's create/reveal workflow with both custom and image keys.
4. Publish a GitHub release tagged `v1.0.0` against the recorded source commit, attaching the five top-level download artifacts.
5. Verify the uploaded asset sizes and digests before publishing the release.

The build inspects decompressed PyInstaller archive data, nested module bytecode, standard-library bytecode, and the executable for local account identifiers and personal home-directory paths. Absolute Python source filenames fail the build. Only the explicitly managed release files enter the ZIP.

## Distribution notes

The executable is unsigned. Checksums detect download changes; they do not replace publisher signing or a malware assessment. Keep license notices with redistributed copies. Releases do not change the repository's visibility: private-repository downloads still require GitHub access.

Repeat dependency and binary audits for each release. Building on another machine can produce different binary hashes even from the same source; the build records provenance but does not claim bit-for-bit reproducibility.
