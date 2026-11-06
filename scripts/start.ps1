$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 first.' }
    if (-not (Test-Path 'dist/index.html')) { throw 'Build the frontend with scripts/setup.ps1 first.' }
    $env:PYTHONPATH = $projectRoot
    & '.venv/Scripts/python.exe' scripts/init_db.py
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed. Check your .env file.' }
    Write-Host 'Open http://127.0.0.1:8000 . Press Ctrl+C to stop.'
    & '.venv/Scripts/python.exe' -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
} finally { Pop-Location }
