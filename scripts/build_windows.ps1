param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw "This build script runs on Windows only."
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$buildVenv = Join-Path $root ".build-venv"
$pythonExe = "python"
$venvPython = Join-Path $buildVenv "Scripts\python.exe"

Write-Step "Preparing build virtual environment"
if (-not (Test-Path $venvPython)) {
    if (Test-Path $buildVenv) {
        Remove-Item $buildVenv -Recurse -Force
    }
    & $pythonExe -m venv $buildVenv
}
if (-not (Test-Path $venvPython)) {
    throw "Build virtual environment could not be created."
}

Write-Step "Upgrading build tooling"
& $venvPython -m pip install --upgrade pip setuptools wheel

Write-Step "Installing build and runtime dependencies"
& $venvPython -m pip install -r (Join-Path $root "requirements-build.txt") -r (Join-Path $root "requirements.txt")

Write-Step "Cleaning previous build artifacts"
foreach ($path in @(
    (Join-Path $root "build"),
    (Join-Path $root "dist\IPQC")
)) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
    }
}

Write-Step "Building IPQC release"
$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name",
    "IPQC",
    "--icon",
    (Join-Path $root "resources\biobot_robot_arm.ico"),
    "--add-data",
    "$(Join-Path $root 'resources');resources",
    "--add-data",
    "$(Join-Path $root 'project_configs');project_configs",
    # PyInstaller 6.21 on this environment does not expose the narrower Qt plugin CLI flag,
    # so we collect the PyQt6 package to ensure the required Qt runtime plugins ship with the release.
    "--collect-all",
    "PyQt6",
    "--hidden-import=matplotlib.backends.backend_qtagg",
    "--hidden-import=matplotlib.backends.backend_agg",
    (Join-Path $root "main.py")
)
& $venvPython -m PyInstaller @pyinstallerArgs

$distRoot = Join-Path $root "dist\IPQC"
if (-not (Test-Path $distRoot)) {
    throw "PyInstaller did not create the expected dist/IPQC folder."
}

Write-Step "Preparing runtime folders"
foreach ($folder in @(
    (Join-Path $distRoot "data"),
    (Join-Path $distRoot "data\logs"),
    (Join-Path $distRoot "data\exports"),
    (Join-Path $distRoot "data\config"),
    (Join-Path $distRoot "data\config\project_configs")
)) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}

Write-Step "Writing release manifest"
$pythonVersion = & $venvPython --version
$pyInstallerVersion = & $venvPython -m PyInstaller --version
$buildArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
$targetArchitecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } elseif ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { "unknown" }
$buildTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$appVersion = & $venvPython -c "from app_version import APP_VERSION; print(APP_VERSION)"
$gitCommit = $null
try {
    $gitCommit = (& git -C $root rev-parse --short HEAD 2>$null)
} catch {
    $gitCommit = $null
}

$manifestLines = @(
    "IPQC Release Info",
    "Application Version: $appVersion",
    "Build Timestamp: $buildTimestamp",
    "Python Version: $pythonVersion",
    "PyInstaller Version: $pyInstallerVersion",
    "Build Architecture: $buildArchitecture",
    "Target Architecture: $targetArchitecture"
)
if ($gitCommit) {
    $manifestLines += "Git Commit: $gitCommit"
}
Set-Content -Path (Join-Path $distRoot "RELEASE_INFO.txt") -Value ($manifestLines -join [Environment]::NewLine) -Encoding UTF8

Write-Step "Writing checksums"
$checksumPath = Join-Path $distRoot "SHA256SUMS.txt"
$checksumLines = Get-ChildItem -Path $distRoot -Recurse -File |
    Where-Object { $_.FullName -ne $checksumPath } |
    Sort-Object FullName |
    ForEach-Object {
        $hash = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash
        $relative = $_.FullName.Substring($distRoot.Length + 1).Replace('\', '/')
        "$hash  $relative"
    }
Set-Content -Path $checksumPath -Value $checksumLines -Encoding ASCII

Write-Host ""
Write-Host "Build complete: $distRoot"
