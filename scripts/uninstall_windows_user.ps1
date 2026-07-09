param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host "[SafeVault] $Message"
}

$python = (Get-Command python -ErrorAction Stop).Source
$startup = [Environment]::GetFolderPath("Startup")
$trayScript = Join-Path $startup "SafeVault Tray.cmd"

Write-Step "Removing daemon startup item"
if (-not $DryRun) {
    & $python -m safevault daemon uninstall
}

if (Test-Path -LiteralPath $trayScript) {
    Write-Step "Removing tray startup item: $trayScript"
    if (-not $DryRun) {
        Remove-Item -LiteralPath $trayScript
    }
} else {
    Write-Step "Tray startup item was not installed"
}

if ($DryRun) {
    Write-Step "Dry run complete; no startup items were removed"
} else {
    Write-Step "Uninstall complete"
}
