@echo off
REM Stop the Athlete Training API (Windows).

setlocal EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "PID_FILE=%PROJECT_ROOT%\logs\api.pid"
if "%ATHLETE_API_PORT%"=="" set "ATHLETE_API_PORT=8000"

echo Athlete Training — Stop
echo.

if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    echo [INFO] Stopping API (pid !PID!)...
    taskkill /F /PID !PID! >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Could not kill pid !PID!
    ) else (
        echo [ OK ] API stopped
    )
    del "%PID_FILE%"
) else (
    echo [INFO] No pid file found — API may not be running
)

endlocal
