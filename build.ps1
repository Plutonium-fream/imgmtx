param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# A workspace-local PyInstaller installation is optional.
$buildDependencies = Join-Path $PSScriptRoot '.build-deps'
$iconPath = Join-Path $PSScriptRoot 'assets\ImgMtx.ico'
$previousPythonPath = $env:PYTHONPATH
try {
    if (Test-Path -LiteralPath $buildDependencies) {
        $env:PYTHONPATH = "$buildDependencies;$previousPythonPath"
    }
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name ImgMtx --icon $iconPath --add-data "$iconPath;assets" --workpath build --specpath build --distpath dist run_imgmtx.py
    if ($LASTEXITCODE -ne 0) { throw 'ImgMtx executable build failed.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
