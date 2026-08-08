$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
& (Join-Path $PSScriptRoot "configure_local_secrets.ps1") -ProjectRoot $ProjectRoot
& (Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1")
python -m uvicorn services.oral_assessment.main:app --host 0.0.0.0 --port 8080 --reload
