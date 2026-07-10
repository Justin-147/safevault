param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host "[SafeVault] $Message"
}

$python = (Get-Command python -ErrorAction Stop).Source
$startup = [Environment]::GetFolderPath("Startup")
$trayEntries = @(
    (Join-Path $startup "SafeVault Tray.cmd"),
    (Join-Path $startup "SafeVault Tray.lnk")
)

Write-Step "Removing daemon startup item"
if (-not $DryRun) {
    & $python -m safevault daemon uninstall
}

foreach ($trayEntry in $trayEntries) {
    if (Test-Path -LiteralPath $trayEntry) {
        Write-Step "Removing tray startup item: $trayEntry"
        if (-not $DryRun) {
            Remove-Item -LiteralPath $trayEntry
        }
    }
}

if ($DryRun) {
    Write-Step "Dry run complete; no startup items were removed"
} else {
    Write-Step "Uninstall complete"
}
