@echo off
REM ============================================================
REM  YouTube AI Agent - Windows Installer (uv-based)
REM  Run this once from inside the yt-agent\ folder.
REM  Uses uv instead of pip to avoid ALL common install errors:
REM    - pkg_resources / setuptools missing
REM    - pydantic_core compiled extension mismatch
REM    - cygrpc / grpcio wrong platform wheel
REM    - onnxruntime missing
REM    - numpy source directory error
REM    - resolution-too-deep
REM ============================================================

echo.
echo ============================================================
echo  YouTube AI Agent - Installation
echo ============================================================
echo.

REM ── Check Python ─────────────────────────────────────────────
python --version 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found.
    echo.
    echo Download Python 3.11 from https://www.python.org/downloads/
    echo During install, tick "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM ── Install uv ───────────────────────────────────────────────
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo ^> Installing uv package manager...
    echo    ^(This replaces pip and fixes all dependency errors^)
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    echo uv installed. Please CLOSE this window and run install.bat again.
    echo.
    pause
    exit /b 0
)
echo ^> uv found: OK

REM ── Nuke old venv if it exists ────────────────────────────────
if exist "venv" (
    echo.
    echo ^> Removing old virtual environment...
    rmdir /s /q venv
)

REM ── Create fresh venv ─────────────────────────────────────────
echo.
echo ^> Creating virtual environment with Python 3.11...
uv venv venv --python 3.11
if %errorlevel% neq 0 (
    echo ERROR: Could not create venv. Make sure Python 3.11 is installed.
    pause
    exit /b 1
)

REM ── Activate ──────────────────────────────────────────────────
call venv\Scripts\activate.bat

REM ── Remind user about VC++ Redistributable ───────────────────────────────────
REM    PyTorch's fbgemm.dll requires Microsoft Visual C++ Runtime.
REM    Without it you get: OSError [WinError 126] fbgemm.dll not found
echo.
echo ^> IMPORTANT: Make sure you have installed the Visual C++ Redistributable.
echo    If you see a fbgemm.dll error later, download and install it from:
echo    https://aka.ms/vs/17/release/vc_redist.x64.exe
echo    ^(free, ~25 MB, one click^)
echo.

REM ── Install PyTorch CPU (must come first, needs --index-url) ──
echo.
echo ^> Installing PyTorch CPU build ^(~500MB, may take a few minutes^)...
uv pip install torch==2.1.2 torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

REM ── Install everything else in ONE shot ───────────────────────
REM    uv resolves the full graph at once — no incremental errors
echo.
echo ^> Installing all dependencies...
uv pip install -r requirements.txt

REM ── Editable install ──────────────────────────────────────────
echo.
echo ^> Installing project...
uv pip install -e .

REM ── Verify ────────────────────────────────────────────────────
echo.
echo ^> Patching crewai...
python patch_crewai.py

echo.
echo ^> Verifying installation...
python main.py --help
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Something still went wrong. See error above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Installation complete!
echo ============================================================
echo.
echo Every time you open a new terminal:
echo   cd E:\Projects\AI\youtube-ai-agent\yt-agent
echo   venv\Scripts\activate
echo.
echo Next steps:
echo   1. copy .env.example .env
echo   2. Open .env and add your 3 API keys
echo   3. python main.py plan --topic "Personal Finance for Beginners"
echo.
pause
