# setup_and_run.ps1 — Setup + launch autoresearch loop
# Requires: uv, git, llama-server on port 8001

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " AUTORESEARCH - SVG Masterpiece Evolution"   -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Venv + deps
Write-Host "[1/4] Setting up venv with uv..." -ForegroundColor Yellow
uv venv .venv
& .\.venv\Scripts\Activate.ps1
uv pip install httpx

# 2. Git init
if (-not (Test-Path .git)) {
    Write-Host "[2/4] Initializing git repo..." -ForegroundColor Yellow
    git init
    git add -A
    git commit -m "autoresearch: seed"
} else {
    Write-Host "[2/4] Git repo already initialized." -ForegroundColor Green
}

# 3. Test scorer
Write-Host "[3/4] Testing scorer..." -ForegroundColor Yellow
python score_svg.py masterpiece.svg
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Scorer failed." -ForegroundColor Red
    exit 1
}

# 4. Check llama-server
Write-Host "[4/4] Checking llama-server..." -ForegroundColor Yellow
try {
    $null = Invoke-RestMethod -Uri "http://localhost:8001/v1/models" -TimeoutSec 5
    Write-Host "llama-server OK" -ForegroundColor Green
} catch {
    Write-Host "WARNING: llama-server not reachable on port 8001." -ForegroundColor Red
    Read-Host "Press Enter to continue anyway"
}

Write-Host ""
Write-Host "Launching loop... (Ctrl+C to stop)" -ForegroundColor Green
Write-Host ""

python autoresearch_loop.py
