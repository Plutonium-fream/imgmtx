param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# A workspace-local PyInstaller installation is optional.
$buildDependencies = Join-Path $PSScriptRoot '.build-deps'
$previousPythonPath = $env:PYTHONPATH
try {
    if (Test-Path -LiteralPath $buildDependencies) {
        $env:PYTHONPATH = "$buildDependencies;$previousPythonPath"
    }
    & $Python tools/package_release.py
    if ($LASTEXITCODE -ne 0) { throw 'ImgMtx portable release build failed.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
