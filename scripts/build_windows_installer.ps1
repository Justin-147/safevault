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
    & $PyInstaller --clean --noconfirm --name safevault --collect-all safevault `
        --collect-all fastapi --collect-all starlette --collect-all uvicorn `
        --collect-all jinja2 --collect-all multipart --collect-all pystray `
        --collect-all PIL --console $entryPoint
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $distApp)) {
    throw "Application bundle not found: $distApp"
}

Write-Step "Building SafeVaultSetup.exe"
$compilerCommand = Get-Command $InnoSetupCompiler -ErrorAction SilentlyContinue
if ($null -ne $compilerCommand) {
    $compilerPath = $compilerCommand.Source
} else {
    $standardCompiler = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path -LiteralPath $standardCompiler) {
        $compilerPath = $standardCompiler
    } else {
        throw "Inno Setup compiler not found: $InnoSetupCompiler"
    }
}
& $compilerPath $setupScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $setupExe)) {
    throw "Expected installer was not created: $setupExe"
}

Write-Step "Created $setupExe"
