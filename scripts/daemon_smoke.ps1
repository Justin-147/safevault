$ErrorActionPreference = "Stop"

$homeDir = Join-Path $env:TEMP "safevault-daemon-smoke"
$project = Join-Path $env:TEMP "safevault-project-smoke"
Remove-Item $homeDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $project -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $project | Out-Null
"hello" | Set-Content -Encoding UTF8 (Join-Path $project "a.txt")

$env:SAFEVAULT_HOME = $homeDir
python -m safevault protect add $project
python -m safevault daemon run --test-once
python -m safevault daemon status
Remove-Item (Join-Path $project "a.txt")
python -m safevault snapshot $project --reason smoke-delete
python -m safevault recent deleted --since 1h
python -m safevault restore (Join-Path $project "a.txt") --latest

Write-Host "daemon smoke ok"
