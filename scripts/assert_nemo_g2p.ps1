$ErrorActionPreference = "Stop"

if ($env:CONDA_DEFAULT_ENV -ne "nemo_g2p") {
    throw "Activate the required environment first: conda activate nemo_g2p"
}

$PythonVersion = python -c "import platform; print(platform.python_version())"
if (-not $PythonVersion.StartsWith("3.10.")) {
    throw "nemo_g2p must use Python 3.10; found $PythonVersion"
}

Write-Host "Using Conda environment nemo_g2p (Python $PythonVersion)."
