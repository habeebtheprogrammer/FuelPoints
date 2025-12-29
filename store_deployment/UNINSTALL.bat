@echo off
echo.
echo ===================================================
echo  Birdies Sales Sync - Service Removal
echo ===================================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script requires administrator privileges!
    echo Please right-click and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

set "NSSM_PATH=%~dp0nssm.exe"
set SERVICE_NAME=BirdiesSalesSync

:: Check if NSSM exists
if not exist "%NSSM_PATH%" (
    echo ERROR: nssm.exe not found!
    echo.
    pause
    exit /b 1
)

:: Stop service
echo Stopping service...
"%NSSM_PATH%" stop %SERVICE_NAME%

:: Remove service
echo Removing service...
"%NSSM_PATH%" remove %SERVICE_NAME% confirm

echo.
echo ===================================================
echo  Service Removed Successfully
echo ===================================================
echo.
echo The service has been uninstalled.
echo Configuration and logs remain in this directory.
echo.
pause
