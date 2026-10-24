"""Build a versioned Windows release with notices, integrity hashes and a privacy gate."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import marshal
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tkinter
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from imgmtx import __version__


def version_resource(version):
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) != 3:
        raise ValueError("Release versions must have three numeric components.")
    fields = {
        "FileDescription": "ImgMtx image mapping desktop application",
        "FileVersion": version,
        "InternalName": "ImgMtx",
        "LegalCopyright": "Copyright (c) 2026 fream",
        "OriginalFilename": "ImgMtx.exe",
        "ProductName": "ImgMtx",
        "ProductVersion": version,
    }
    entries = ",\n".join(f"StringStruct({key!r}, {value!r})" for key, value in fields.items())
    return (f"VSVersionInfo(ffi=FixedFileInfo(filevers={parts + (0,)!r}, "
            f"prodvers={parts + (0,)!r}, mask=0x3f, flags=0, OS=0x40004, "
            "fileType=0x1, subtype=0, date=(0, 0)), kids=["
            f"StringFileInfo([StringTable('040904B0', [{entries}])]), "
            "VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n")


def audit_executable(path):
    """Inspect decompressed archives and nested bytecode, not just executable strings."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(path))
    home = str(Path.home()).lower().replace("\\", "/")
    username = Path.home().name.encode().lower()
    login_pattern = re.compile(rb"(?<![a-z])" + re.escape(username) + rb"(?![a-z])", re.I)
    inspected = 0
    code_count = 0

    def check_bytes(data, label):
        normalized = data.lower().replace(b"\\", b"/")
        if home.encode() in normalized or home.encode("utf-16le") in normalized:
            raise RuntimeError(f"Personal build path found in {label}.")
        if login_pattern.search(data):
            raise RuntimeError(f"Local account identifier found in {label}.")

    def check_code(code):
        nonlocal code_count
        if not isinstance(code, types.CodeType):
            return
        code_count += 1
        if re.match(r"(?:[A-Za-z]:[\\/]|/)", code.co_filename):
            raise RuntimeError("Absolute source filename found in bundled bytecode.")
        for value in code.co_consts:
            if isinstance(value, types.CodeType):
                check_code(value)

    check_bytes(path.read_bytes(), "executable")
    for name, entry in archive.toc.items():
        if entry[-1] == "z":
            embedded = archive.open_embedded_archive(name)
            for module in embedded.toc:
                raw = embedded.extract(module, raw=True)
                if raw is not None:
                    check_bytes(raw, "bundled module")
                    check_code(embedded.extract(module))
                    inspected += 1
            continue
        data = archive.extract(name)
        check_bytes(data, name)
        inspected += 1
        if entry[-1] in ("s", "m", "M"):
            check_code(marshal.loads(data))
        if name == "base_library.zip":
            with zipfile.ZipFile(io.BytesIO(data)) as base:
                for member in base.namelist():
                    raw = base.read(member)
                    check_bytes(raw, "standard-library module")
                    if member.endswith(".pyc"):
                        check_code(marshal.loads(raw[16:]))
    return {"archive_entries_checked": inspected, "code_objects_checked": code_count,
            "personal_build_path_findings": 0}


def main():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build this release using 64-bit Python on Windows.")
    pillow = importlib.metadata.version("pillow")
    if int(pillow.split(".")[0]) < 13:
        raise RuntimeError("Install the patched Pillow requirement before building.")
    builder = importlib.metadata.distribution("pyinstaller")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        raise RuntimeError("Commit source changes before building a traceable release.")
    name = f"ImgMtx-{__version__}-windows-x64"
    stage = ROOT / "dist" / name
    work = ROOT / "build" / "release"
    stage.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    licenses = stage / "licenses"
    licenses.mkdir(exist_ok=True)
    base = Path(sys.base_prefix)
    # Distribution-relative license files live beneath the dist-info directory.
    pillow_license = next(importlib.metadata.distribution("pillow").locate_file(p)
                          for p in importlib.metadata.distribution("pillow").files
                          if str(p).endswith(".dist-info/licenses/LICENSE"))
    builder_license = next(builder.locate_file(p) for p in builder.files
                           if str(p).endswith("licenses/COPYING.txt"))
    inputs = {
        "Python-LICENSE": base / "LICENSE.txt",
        "Pillow-LICENSE": Path(pillow_license),
        "Tk-LICENSE": base / "tcl" / "tk8.6" / "license.terms",
        "PyInstaller-LICENSE": Path(builder_license),
        "Tcl-LICENSE": ROOT / "licenses" / "Tcl-LICENSE",
        "OpenSSL-LICENSE": ROOT / "licenses" / "OpenSSL-LICENSE",
        "libffi-LICENSE": ROOT / "licenses" / "libffi-LICENSE",
    }
    for filename, source in inputs.items():
        shutil.copyfile(source, licenses / filename)
    shutil.copyfile(ROOT / "LICENSE", stage / "LICENSE")
    window = tkinter.Tk()
    window.withdraw()
    tcl_version = window.tk.call("info", "patchlevel")
    tk_version = window.tk.call("package", "provide", "Tk")
    window.destroy()
    notices = f"""# Third-party notices — ImgMtx {__version__}

The ImgMtx application is MIT-licensed; see LICENSE. This distribution includes:

| Component | Version | License text |
| --- | --- | --- |
| CPython and standard library | {platform.python_version()} | licenses/Python-LICENSE |
| Pillow and its bundled native image libraries | {pillow} | licenses/Pillow-LICENSE |
| Tcl | {tcl_version} | licenses/Tcl-LICENSE |
| Tk | {tk_version} | licenses/Tk-LICENSE |
| OpenSSL | {ssl.OPENSSL_VERSION} | licenses/OpenSSL-LICENSE |
| libffi runtime | ABI 8 | licenses/libffi-LICENSE |
| PyInstaller bootloader/runtime | {builder.version} | licenses/PyInstaller-LICENSE |

Pillow's complete license file includes the notices for its bundled codecs and
libraries. The Python license file includes the conditions for its Windows
Microsoft Distributable Code. Those conditions apply only to that runtime code.
The PyInstaller file includes its bootloader exception. No licenses were removed.

These files are also embedded in the executable. Keep the notices with any
redistribution; the portable ZIP includes readable copies.
"""
    (stage / "THIRD_PARTY_NOTICES.md").write_text(notices, encoding="utf-8")
    (stage / "README.md").write_text(f"""# ImgMtx {__version__} — Windows x64

Extract the ZIP into a folder and double-click ImgMtx.exe. No installation or
separate Python runtime is needed. Keep the notices and licenses with the app.

Create a key from an original and hidden PNG, choosing Image (.png) or Custom
(.imgkey). Reveal using the exact original PNG plus its matching key. The hidden
source file is not needed for recovery. Original files are never overwritten.

Switch light/dark mode in the top bar; Help shows the application version.
This is image mapping, not password-protected encryption.

This executable is unsigned. SHA256SUMS verifies download integrity, not a digital
publisher signature. From PowerShell: Get-FileHash .\\ImgMtx.exe -Algorithm SHA256

Source and usage: https://github.com/Plutonium-fream/imgmtx
""", encoding="utf-8")
    version_file = work / "windows-version.txt"
    version_file.write_text(version_resource(__version__), encoding="utf-8")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "ImgMtx", "--icon", str(ROOT / "assets" / "ImgMtx.ico"),
        "--version-file", str(version_file),
        "--add-data", f"{ROOT / 'assets' / 'ImgMtx.ico'};assets",
        "--add-data", f"{licenses};licenses",
        "--add-data", f"{stage / 'LICENSE'};.",
        "--add-data", f"{stage / 'THIRD_PARTY_NOTICES.md'};.",
        "--workpath", str(work), "--specpath", str(work), "--distpath", str(stage),
        str(ROOT / "run_imgmtx.py"),
    ], cwd=ROOT, check=True)
    executable = stage / "ImgMtx.exe"
    audit = audit_executable(executable)
    info = {"application": "ImgMtx", "version": __version__, "platform": "windows-x64",
            "source_commit": commit, "python": platform.python_version(), "pillow": pillow,
            "tcl": tcl_version, "tk": tk_version, "pyinstaller": builder.version,
            "openssl": ssl.OPENSSL_VERSION, "signed": False, "binary_privacy_audit": audit}
    (stage / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    managed = {"ImgMtx.exe", "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "BUILD_INFO.json"}
    managed.update("licenses/" + filename for filename in inputs)
    actual = {str(p.relative_to(stage)).replace("\\", "/") for p in stage.rglob("*") if p.is_file()}
    if actual - {"SHA256SUMS"} != managed:
        raise RuntimeError("Release folder contains unexpected files; refusing to package it.")
    hashes = {file: hashlib.sha256((stage / file).read_bytes()).hexdigest() for file in sorted(managed)}
    (stage / "SHA256SUMS").write_text("".join(f"{digest}  {file}\n" for file, digest in hashes.items()), encoding="utf-8")
    portable = ROOT / "dist" / (name + ".zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(managed | {"SHA256SUMS"}):
            archive.write(stage / file, name + "/" + file)
    standalone = ROOT / "dist" / (name + ".exe")
    shutil.copyfile(executable, standalone)
    for filename in ("THIRD_PARTY_NOTICES.md", "BUILD_INFO.json"):
        shutil.copyfile(stage / filename, ROOT / "dist" / filename)
    artifacts = [portable, standalone, ROOT / "dist" / "THIRD_PARTY_NOTICES.md", ROOT / "dist" / "BUILD_INFO.json"]
    checksum = ROOT / "dist" / "SHA256SUMS"
    checksum.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in artifacts), encoding="utf-8")
    print(json.dumps({"version": __version__, "artifacts": [p.name for p in artifacts] + [checksum.name],
                      "binary_privacy_audit": audit}, indent=2))


if __name__ == "__main__":
    main()
