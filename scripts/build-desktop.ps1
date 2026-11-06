$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv }
    python -m pip --python .venv install -r requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (Test-Path '.runtime/package/bin/npm-cli.js') { node .runtime/package/bin/npm-cli.js run build } else { npm ci; if ($LASTEXITCODE -eq 0) { npm run build } }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    .venv/Scripts/python.exe -m PyInstaller desktop/fandian.spec --distpath release --workpath .runtime/pyinstaller --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
    .venv/Scripts/python.exe scripts/package_desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
} finally { Pop-Location }
