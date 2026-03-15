@echo off
REM setup_and_run.bat — One-shot setup + launch autoresearch loop on Windows
REM Requires: uv, git, llama-server running on port 8001

echo.
echo ============================================
echo  AUTORESEARCH — SVG Masterpiece Evolution
echo ============================================
echo.

REM 1. Check prerequisites
where git >nul 2>&1 || (echo ERROR: git not found in PATH && exit /b 1)
where uv >nul 2>&1 || (echo ERROR: uv not found in PATH && exit /b 1)

REM 2. Create venv + install deps
echo [1/4] Setting up venv with uv...
uv venv .venv
call .venv\Scripts\activate.bat
uv pip install httpx

REM 3. Init git if needed
if not exist .git (
    echo [2/4] Initializing git repo...
    git init
    git add -A
    git commit -m "autoresearch: seed"
) else (
    echo [2/4] Git repo already initialized.
)

REM 4. Test scorer
echo [3/4] Testing scorer on seed SVG...
python scripts\score_svg.py masterpiece.svg
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Scorer failed on seed SVG.
    exit /b 1
)

REM 5. Check llama-server
echo [4/4] Checking llama-server on port 8001...
curl -s http://localhost:8001/v1/models >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo WARNING: llama-server not reachable on port 8001.
    echo Make sure it's running before the loop starts.
    echo.
    pause
)

echo.
echo Setup complete. Launching autoresearch loop...
echo Press Ctrl+C to stop at any time.
echo.

python autoresearch_loop.py
