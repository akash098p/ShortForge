@echo off
setlocal EnableExtensions
title ShortForge Launcher

set "ROOT=%~dp0"
set "API_URL=http://127.0.0.1:8000"
set "WEB_URL=http://127.0.0.1:3000"

echo.
echo ==========================================
echo          S H O R T F O R G E
echo ==========================================
echo Project: %ROOT%
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found in PATH.
    pause
    exit /b 1
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFmpeg was not found in PATH.
    pause
    exit /b 1
)

ffprobe -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFprobe was not found in PATH.
    pause
    exit /b 1
)

echo [OK] Python, Node.js, FFmpeg and FFprobe found.
echo.

if not exist "%ROOT%apps\api\main.py" (
    echo [ERROR] Backend not found: %ROOT%apps\api\main.py
    pause
    exit /b 1
)

if not exist "%ROOT%apps\api\requirements.txt" (
    echo [ERROR] Backend requirements.txt not found.
    pause
    exit /b 1
)

if not exist "%ROOT%apps\web\package.json" (
    echo [ERROR] Frontend package.json not found.
    pause
    exit /b 1
)

echo [1/4] Preparing Python environment...
cd /d "%ROOT%apps\api"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create Python virtual environment.
        pause
        exit /b 1
    )
)

echo Checking Python dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [2/4] Preparing frontend...
cd /d "%ROOT%apps\web"

if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

echo.
echo [3/4] Starting backend...
start "ShortForge Backend" cmd /k "cd /d ""%ROOT%apps\api"" && "".venv\Scripts\python.exe"" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo Waiting for FastAPI on port 8000...

set "API_READY="
for /l %%N in (1,1,30) do (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%API_URL%/health'; if($r.StatusCode -eq 200){exit 0}else{exit 1} } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "API_READY=1"
        goto :api_ready
    )
    timeout /t 1 /nobreak >nul
)

echo [ERROR] FastAPI did not become ready within 30 seconds.
echo Check the "ShortForge Backend" window for the actual Python error.
pause
exit /b 1

:api_ready
echo [OK] Backend is healthy.
echo.

echo [4/4] Starting frontend...
start "ShortForge Frontend" cmd /k "cd /d ""%ROOT%apps\web"" && npm run dev"

echo.
echo ==========================================
echo       ShortForge is starting!
echo ==========================================
echo.
echo Backend:  %API_URL%
echo Health:   %API_URL%/health
echo Frontend: %WEB_URL%
echo.
echo The backend was verified before the frontend was started.
echo Keep both terminal windows open while using ShortForge.
echo.

timeout /t 3 /nobreak >nul
start "" "%WEB_URL%"

endlocal
exit /b 0
