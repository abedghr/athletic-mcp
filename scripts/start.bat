@echo off
REM Start the Athlete Training API in the background (Windows).

setlocal EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "LOGS_DIR=%PROJECT_ROOT%\logs"
set "PID_FILE=%LOGS_DIR%\api.pid"
set "LOG_FILE=%LOGS_DIR%\api.log"
set "ATHLETE_DIR=%USERPROFILE%\.athlete"
if "%ATHLETE_API_PORT%"=="" set "ATHLETE_API_PORT=8000"

echo Athlete Training — Startup
echo.

REM 1. Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] python not found on PATH
    exit /b 1
)
for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set "PY_VERSION=%%i"
echo [ OK ] Python !PY_VERSION!

REM 2. Check virtualenv
if "%VIRTUAL_ENV%"=="" (
    echo [WARN] No virtualenv active
) else (
    echo [ OK ] Virtualenv: %VIRTUAL_ENV%
)

REM 3. Check athlete_mcp package
python -c "import athlete_mcp" 2>nul
if errorlevel 1 (
    echo [FAIL] athlete_mcp package not installed. Run: pip install -e .
    exit /b 1
)
echo [ OK ] athlete_mcp package importable

REM 4. Check port not in use
netstat -an | findstr ":%ATHLETE_API_PORT%" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [FAIL] Port %ATHLETE_API_PORT% already in use. Stop it with: scripts\stop.bat
    exit /b 1
)
echo [ OK ] Port %ATHLETE_API_PORT% is free

REM 5. Ensure dirs exist
if not exist "%ATHLETE_DIR%" mkdir "%ATHLETE_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
echo [ OK ] Directories ready

REM 6. Start FastAPI in background
echo [INFO] Starting FastAPI server...
cd /d "%PROJECT_ROOT%"
start /B "" python scripts\run_api.py > "%LOG_FILE%" 2>&1
REM Save PID via wmic (best-effort)
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /NH ^| findstr python') do set "API_PID=%%i"
echo !API_PID! > "%PID_FILE%"
echo [INFO] API started with pid !API_PID!

REM 7. Wait for API
echo [INFO] Waiting for API to become healthy...
set "HEALTHY=0"
for /L %%i in (1,1,15) do (
    curl -s http://localhost:%ATHLETE_API_PORT%/health >nul 2>&1
    if !errorlevel! == 0 (
        set "HEALTHY=1"
        goto :healthy
    )
    timeout /t 1 /nobreak >nul
)
:healthy
if "!HEALTHY!"=="0" (
    echo [FAIL] API did not respond in 15s. Check %LOG_FILE%
    exit /b 1
)

echo.
echo [ OK ] API ready at http://localhost:%ATHLETE_API_PORT%
echo [ OK ] Swagger UI at http://localhost:%ATHLETE_API_PORT%/docs
echo [ OK ] Now open Claude Desktop — MCP servers will connect automatically
echo.
echo To stop: scripts\stop.bat
echo Tail logs: type %LOG_FILE%

endlocal
