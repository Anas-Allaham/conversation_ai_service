$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if (-not (Test-Path (Join-Path $ProjectRoot ".venv"))) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[livekit,dev]"

& (Join-Path $PSScriptRoot "configure_local_secrets.ps1") -ProjectRoot $ProjectRoot

python tools\validate_item_bank.py
python -m unittest discover -s services\oral_assessment\tests -t . -v
