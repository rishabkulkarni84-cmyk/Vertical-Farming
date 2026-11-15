@echo off
setlocal
title Verdant launcher
cd /d "%~dp0"

echo ============================================================
echo  Verdant - vertical farm planner (local)
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo     and tick "Add python.exe to PATH" during setup, then run this file again.
  pause & exit /b 1
)
if not exist frontend\dist\index.html (
  echo [!] frontend\dist is missing. Re-extract the zip, or run "npm install && npm run build" in frontend.
  pause & exit /b 1
)

echo.
echo Stopping any Verdant server that is already running...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8000/api/health; if ($r.Content -match 'simulator_loop') { Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force } ; Start-Sleep -Seconds 1 } } catch {}" >nul 2>nul

echo.
echo [1/3] Setting up the backend (first run downloads packages - a few minutes)...
cd backend
if not exist .venv (
  python -m venv .venv || (echo [!] Could not create a virtual environment & pause & exit /b 1)
)
rem Reinstall packages only when requirements.txt changed since the last successful install (much faster restarts)
fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
  call .venv\Scripts\python -m pip install --upgrade pip >nul
  call .venv\Scripts\python -m pip install -r requirements.txt || (echo [!] Backend install failed - see errors above & pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.installed >nul
) else (
  echo Packages already up to date.
)
if not exist .env copy .env.example .env >nul
if not exist storage mkdir storage

echo.
echo [2/3] Creating demo data (skipped if it already exists)...
call .venv\Scripts\python -m app.seed

echo.
echo [3/3] Starting Verdant...
start "Verdant server (close this window to stop)" cmd /k ".venv\Scripts\python -m uvicorn app.main:app --port 8000"

echo Waiting for the server...
set /a tries=0
:wait
timeout /t 2 /nobreak >nul
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health).StatusCode } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (if %tries% lss 30 goto wait)

set URL=http://localhost:8000
set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME="%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME="%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME="%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined CHROME (start "" %CHROME% %URL%) else (start "" %URL%)

echo.
echo Verdant is running at %URL%
echo Demo login:  demo@verdant.app  /  verdant-demo-2026
echo To stop: close the "Verdant server" window.
echo.
pause
