# setup_and_run.ps1 — Setup + launch autoresearch loop
# Requires: uv, git, llama-server on port 8001

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " AUTORESEARCH - SVG Masterpiece Evolution"   -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Venv + deps
Write-Host "[1/4] Venv + deps..." -ForegroundColor Yellow
if (Test-Path .venv) {
    Write-Host "  .venv exists, activating." -ForegroundColor Green
} else {
    uv venv .venv
}
& .\.venv\Scripts\Activate.ps1
uv pip install httpx --quiet

# 2. Verify files exist
Write-Host "[2/4] Checking files..." -ForegroundColor Yellow
$required = @("masterpiece.svg", "score_svg.py", "autoresearch_loop.py")
foreach ($f in $required) {
    if (-not (Test-Path $f)) {
        Write-Host "  MISSING: $f" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  All files present." -ForegroundColor Green

# 3. Test scorer
Write-Host "[3/4] Testing scorer..." -ForegroundColor Yellow
python score_svg.py masterpiece.svg
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Scorer failed." -ForegroundColor Red
    exit 1
}
Write-Host "  Scorer OK." -ForegroundColor Green

# 4. Check llama-server
Write-Host "[4/4] Checking llama-server..." -ForegroundColor Yellow
try {
    $null = Invoke-RestMethod -Uri "http://localhost:8001/v1/models" -TimeoutSec 5
    Write-Host "  llama-server OK." -ForegroundColor Green
} catch {
    Write-Host "  WARNING: llama-server not reachable on port 8001." -ForegroundColor Red
    Read-Host "  Press Enter to continue anyway"
}

Write-Host ""
Write-Host "Launching loop... (Ctrl+C to stop)" -ForegroundColor Green
Write-Host ""

python autoresearch_loop.py
