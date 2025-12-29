@echo off
REM Birdies Sales Data Collection - Installation Script
REM This script sets up the sales data collection system on a store computer

echo ========================================
echo Birdies Sales Data Collection
echo Installation Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or later from python.org
    pause
    exit /b 1
)

echo Python detected:
python --version
echo.

REM Create directory structure
echo Creating directory structure...
if not exist "C:\birdiesloyalty" mkdir "C:\birdiesloyalty"
if not exist "C:\birdiesloyalty\sales_data" mkdir "C:\birdiesloyalty\sales_data"
if not exist "C:\birdiesloyalty\logs" mkdir "C:\birdiesloyalty\logs"

REM Install Python dependencies
echo.
echo Installing Python dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo IMPORTANT: Before running the collection script, you MUST:
echo.
echo 1. Edit config.py and set your PDI_STORE_NUMBER
echo 2. Verify the API_BASE_URL is correct
echo 3. Verify network paths (MAIN_FOLDER and PJR_FOLDER) are accessible
echo.
echo To test the configuration, run:
echo   python main.py
echo.
echo To schedule daily collection, use Windows Task Scheduler:
echo   - Run: python main.py
echo   - Schedule: Daily at 1:00 AM
echo   - Run with highest privileges
echo.
pause
