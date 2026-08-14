$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DemoRoot = Join-Path $ProjectRoot "examples\guided-demo"

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "Node.js and npm are required for the guided browser demo."
}

Push-Location $DemoRoot
try {
    if (-not (Test-Path (Join-Path $DemoRoot "node_modules"))) {
        npm.cmd install
    }
    npm.cmd run dev
}
finally {
    Pop-Location
}
