$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    New-Item -ItemType Directory -Path '.runtime' -Force | Out-Null
    if (-not (Test-Path '.venv/Scripts/python.exe')) { python -m venv --without-pip .venv }
    python -m pip --python .venv install -r requirements.lock.txt --cache-dir .runtime/pip-cache
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCommand) {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        npm run build
    } else {
        if (-not (Test-Path '.runtime/package/bin/npm-cli.js')) {
            Invoke-WebRequest -Uri 'https://registry.npmjs.org/npm/-/npm-11.6.2.tgz' -OutFile '.runtime/npm.tgz'
            tar -xzf .runtime/npm.tgz -C .runtime
        }
        node .runtime/package/bin/npm-cli.js ci --cache .runtime/npm-cache
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        node .runtime/package/bin/npm-cli.js run build
    }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Host 'Ready. Run scripts/start.ps1 to start the app.'
} finally { Pop-Location }
