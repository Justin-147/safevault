param(
    [switch]$WithTray,
    [switch]$OpenUi,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host "[SafeVault] $Message"
}

$python = (Get-Command python -ErrorAction Stop).Source
$startup = [Environment]::GetFolderPath("Startup")
$trayScript = Join-Path $startup "SafeVault Tray.cmd"

Write-Step "Using Python: $python"
Write-Step "Installing daemon startup item"

if (-not $DryRun) {
    & $python -m safevault daemon install
}

if ($WithTray) {
    Write-Step "Installing optional tray startup item"
    $content = "@echo off`r`n`"$python`" -m safevault tray`r`n"
    if (-not $DryRun) {
        Set-Content -LiteralPath $trayScript -Value $content -Encoding UTF8
    }
    Write-Step "Tray startup item: $trayScript"
}

Write-Step "Recommended first run: python -m safevault ui --open"
if ($OpenUi -and -not $DryRun) {
    Start-Process -FilePath $python -ArgumentList @("-m", "safevault", "ui", "--open") -WindowStyle Hidden
}

if ($DryRun) {
    Write-Step "Dry run complete; no startup items were written"
} else {
    Write-Step "Install complete"
}
