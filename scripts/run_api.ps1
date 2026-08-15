$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $ProjectRoot
try {
    uv run uvicorn conversation_ai.api.main:app --host 0.0.0.0 --port 8000 --reload
}
finally {
    Pop-Location
}
