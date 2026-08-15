$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $ProjectRoot
try {
    if (-not (Test-Path ".env.local")) {
        Copy-Item ".env.example" ".env.local"
        Write-Host "Created .env.local. Fill in the required credentials, then rerun setup."
        exit 0
    }
    uv sync --all-extras
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed (uv sync)."
    }

    uv run python tools/setup_preflight.py
    if ($LASTEXITCODE -ne 0) {
        throw "Configuration preflight failed. Fix .env.local, then rerun setup."
    }

    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed. Verify DATABASE_URL and database availability."
    }

    uv run python -m livekit.agents download-files
    if ($LASTEXITCODE -ne 0) {
        throw "LiveKit plugin asset download failed."
    }

    & (Join-Path $PSScriptRoot "setup_piper.ps1") -ProjectRoot $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Piper setup failed."
    }
    Write-Host "Setup completed. Run the API, tutor worker, and assessment worker."
}
finally {
    Pop-Location
}
