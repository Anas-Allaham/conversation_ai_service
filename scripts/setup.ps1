$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
. (Join-Path $PSScriptRoot "assert_nemo_g2p.ps1")

python -m pip install -e ".[agent,api,assessment,modal,dev]"

& (Join-Path $PSScriptRoot "configure_local_secrets.ps1") -ProjectRoot $ProjectRoot

python tools\validate_item_bank.py
python tools\validate_scenarios.py
python -m pytest
