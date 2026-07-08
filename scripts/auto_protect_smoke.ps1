$ErrorActionPreference = "Stop"

$homeDir = Join-Path $env:TEMP "safevault-auto-protect-smoke"
$project = Join-Path $env:TEMP "safevault-auto-project-smoke"
Remove-Item $homeDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $project -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $project | Out-Null

$env:SAFEVAULT_HOME = $homeDir
python -m safevault protect auto-detect
python -m safevault protect add $project --profile coding
python -m safevault protect list
python -m safevault protect pause $project --duration 30m
python -m safevault protect resume $project

Write-Host "auto-protect smoke ok"
