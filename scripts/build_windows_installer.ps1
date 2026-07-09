param(
    [string]$PyInstaller = "pyinstaller",
    [string]$InnoSetupCompiler = "iscc",
    [switch]$SkipAppBuild
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host "[SafeVault Installer] $Message"
}

$root = Split-Path -Parent $PSScriptRoot
$distApp = Join-Path $root "dist\safevault"
$setupScript = Join-Path $root "packaging\windows\SafeVaultSetup.iss"
$setupExe = Join-Path $root "dist\SafeVaultSetup.exe"

if (-not $SkipAppBuild) {
    Write-Step "Building SafeVault application bundle"
    $entryPoint = Join-Path $root "src\safevault\__main__.py"
    & $PyInstaller --clean --name safevault --collect-all safevault --console $entryPoint
}

if (-not (Test-Path -LiteralPath $distApp)) {
    throw "Application bundle not found: $distApp"
}

Write-Step "Building SafeVaultSetup.exe"
& $InnoSetupCompiler $setupScript

if (-not (Test-Path -LiteralPath $setupExe)) {
    throw "Expected installer was not created: $setupExe"
}

Write-Step "Created $setupExe"
