$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
. (Join-Path $PSScriptRoot "assert_nemo_g2p.ps1")
& (Join-Path $PSScriptRoot "configure_local_secrets.ps1") -ProjectRoot $ProjectRoot
python -m uvicorn services.oral_assessment.main:app --host 0.0.0.0 --port 8080 --reload
