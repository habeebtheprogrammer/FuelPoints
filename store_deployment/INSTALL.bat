@echo off
echo.
echo ===================================================
echo  Birdies Sales Sync - Service Installation
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

:: Get current directory
set "APP_DIR=%~dp0"
set "EXE_PATH=%APP_DIR%BirdiesSalesSync.exe"
set "NSSM_PATH=%APP_DIR%nssm.exe"

:: Check if EXE exists
if not exist "%EXE_PATH%" (
    echo ERROR: BirdiesSalesSync.exe not found!
    echo Expected location: %EXE_PATH%
    echo.
    pause
    exit /b 1
)

:: Check if NSSM exists
if not exist "%NSSM_PATH%" (
    echo NSSM not found. Attempting to download...
    echo.
    
    :: Check if Python is available
    python --version >nul 2>&1
    if %errorLevel% equ 0 (
        echo Using Python to download NSSM...
        python "%APP_DIR%download_nssm.py" --output-dir "%APP_DIR%"
        if %errorLevel% neq 0 (
            echo.
            echo ERROR: NSSM download failed!
            echo Please download manually from https://nssm.cc/download
            echo Extract nssm.exe (64-bit) to: %APP_DIR%
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo ERROR: nssm.exe not found and Python not available!
        echo.
        echo Please download NSSM manually:
        echo 1. Go to https://nssm.cc/download
        echo 2. Download nssm-2.24.zip
        echo 3. Extract win64\nssm.exe to: %APP_DIR%
        echo.
        pause
        exit /b 1
    )
)

:: Check if config exists
if not exist "%APP_DIR%config.json" (
    echo No configuration found. Running setup wizard...
    echo.
    "%EXE_PATH%" --setup
    if %errorLevel% neq 0 (
        echo.
        echo Setup failed or was cancelled.
        pause
        exit /b 1
    )
)

:: Read store number from config (simplified - assumes config exists)
echo Reading configuration...
set SERVICE_NAME=BirdiesSalesSync

:: Install service
echo Installing Windows service...
"%NSSM_PATH%" install %SERVICE_NAME% "%EXE_PATH%"
"%NSSM_PATH%" set %SERVICE_NAME% AppParameters "--service"
"%NSSM_PATH%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM_PATH%" set %SERVICE_NAME% Description "Birdies Sales Data Sync Service"
"%NSSM_PATH%" set %SERVICE_NAME% Start SERVICE_AUTO_START

:: Start service
echo Starting service...
"%NSSM_PATH%" start %SERVICE_NAME%

echo.
echo ===================================================
echo  Installation Complete!
echo ===================================================
echo.
echo Service Name: %SERVICE_NAME%
echo Status: Running
echo.
echo To check status:
echo   nssm status %SERVICE_NAME%
echo.
echo To view logs:
echo   type logs\sync_*.log
echo.
pause
