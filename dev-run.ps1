param(
    [ValidateSet("api","worker")]
    [string]$Mode = "api",
    [int]$Port = 8000,
    [string]$VenvPath = ".venv",
    [string]$ConfigPath = "config/example_config.yaml"
)

Write-Host "Starting dev run (mode=$Mode)"

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment at $VenvPath..."
    python -m venv $VenvPath
}

Write-Host "Activating virtual environment..."
& "$VenvPath\Scripts\Activate.ps1"

Write-Host "Installing requirements (if needed)..."
pip install -r requirements.txt

# Ensure src is on PYTHONPATH so modules import as in README examples
$env:PYTHONPATH = (Join-Path (Get-Location) "src") + ";" + ($env:PYTHONPATH)

# Export config env var
$env:VNCRCC_CONFIG = (Resolve-Path $ConfigPath).Path

# Enable history tracking for development
$env:VNCRCC_WRITE_JSON_HISTORY = "1"
$env:VNCRCC_TRACK_POSITIONS = "1"

if ($Mode -eq 'api') {
    Write-Host "Running API (uvicorn) on port $Port..."
    # Import the app as vncrcc.app:app -- reload is supported when using
    # an import string (we set PYTHONPATH to include src so 'vncrcc' is importable).
    uvicorn vncrcc.app:app --host 127.0.0.1 --port $Port
} else {
    Write-Host "Running worker (poller) in foreground..."
    python -m src.vncrcc.worker
}
