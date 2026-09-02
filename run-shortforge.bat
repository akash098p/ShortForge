@echo off
setlocal
title ShortForge Launcher

:: ============================================================
:: ShortForge - Frontend + Backend Launcher
:: ============================================================

:: Get the folder where this .bat file is located
set "ROOT=%~dp0"

echo.
echo ==========================================
echo          S H O R T F O R G E
echo ==========================================
echo.
echo Project: %ROOT%
echo.

:: ------------------------------------------------------------
:: Check Python
:: ------------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found.
    echo Please install Python and make sure it is in PATH.
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Check Node.js
:: ------------------------------------------------------------
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found.
    echo Please install Node.js and make sure it is in PATH.
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Check FFmpeg
:: ------------------------------------------------------------
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFmpeg was not found.
    echo Please add FFmpeg to Windows PATH.
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Check FFprobe
:: ------------------------------------------------------------
ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFprobe was not found.
    echo Please add FFprobe to Windows PATH.
    pause
    exit /b 1
)

echo [OK] Python found
echo [OK] Node.js found
echo [OK] FFmpeg found
echo [OK] FFprobe found
echo.

:: ------------------------------------------------------------
:: Backend directory
:: ------------------------------------------------------------
if not exist "%ROOT%apps\api\main.py" (
    echo [ERROR] Backend not found:
    echo %ROOT%apps\api\main.py
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Frontend directory
:: ------------------------------------------------------------
if not exist "%ROOT%apps\web\package.json" (
    echo [ERROR] Frontend not found:
    echo %ROOT%apps\web\package.json
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Install backend dependencies if necessary
:: ------------------------------------------------------------
echo.
echo [1/2] Checking backend dependencies...

cd /d "%ROOT%apps\api"

if not exist ".venv" (
    echo Creating Python virtual environment...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip

if exist "requirements.txt" (
    python -m pip install -r requirements.txt
)

:: ------------------------------------------------------------
:: Install frontend dependencies if necessary
:: ------------------------------------------------------------
echo.
echo [2/2] Checking frontend dependencies...

cd /d "%ROOT%apps\web"

if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
)

:: ------------------------------------------------------------
:: Start Backend
:: ------------------------------------------------------------
echo.
echo Starting ShortForge Backend...
echo.

start "ShortForge Backend" cmd /k ^
"cd /d ""%ROOT%apps\api"" && call "".venv\Scripts\activate.bat"" && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"

:: ------------------------------------------------------------
:: Give backend a moment to start
:: ------------------------------------------------------------
timeout /t 3 /nobreak >nul

:: ------------------------------------------------------------
:: Start Frontend
:: ------------------------------------------------------------
echo Starting ShortForge Frontend...
echo.

start "ShortForge Frontend" cmd /k ^
"cd /d ""%ROOT%apps\web"" && npm run dev"

:: ------------------------------------------------------------
:: Done
:: ------------------------------------------------------------
echo.
echo ==========================================
echo       ShortForge is starting!
echo ==========================================
echo.
echo Backend:
echo http://localhost:8000
echo.
echo API Health:
echo http://localhost:8000/health
echo.
echo Frontend:
echo http://localhost:3000
echo.
echo Two terminals have been opened.
echo Keep them running while using ShortForge.
echo.

timeout /t 5 /nobreak >nul

:: Open browser
start "" "http://localhost:3000"

exit /b 0