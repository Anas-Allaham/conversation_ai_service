$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $ProjectRoot
try {
    uv run python src/agent.py dev
}
finally {
    Pop-Location
}
