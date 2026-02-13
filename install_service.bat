@echo off
setlocal

REM ============================================================
REM  Duo Log Sync - Windows Service Installer
REM  Run this script from an elevated (Administrator) prompt.
REM ============================================================

if "%~1"=="" (
    echo Usage: install_service.bat ^<path-to-config.yml^>
    echo.
    echo Example:
    echo   install_service.bat C:\DuoLogSync\config.yml
    exit /b 1
)

set CONFIG_PATH=%~f1

if not exist "%CONFIG_PATH%" (
    echo Error: config file not found: %CONFIG_PATH%
    exit /b 1
)

echo.
echo Installing DuoLogSync service...
duologsync-service install --config "%CONFIG_PATH%" --startup auto
if errorlevel 1 (
    echo.
    echo Installation failed. Make sure you are running as Administrator
    echo and that pywin32 is installed: pip install pywin32
    exit /b 1
)

echo.
echo Starting DuoLogSync service...
net start DuoLogSync
if errorlevel 1 (
    echo.
    echo Failed to start the service. Check the Windows Event Log for details.
    exit /b 1
)

echo.
echo ============================================================
echo  DuoLogSync service installed and started successfully.
echo.
echo  Config: %CONFIG_PATH%
echo.
echo  Manage with:
echo    net stop DuoLogSync
echo    net start DuoLogSync
echo    duologsync-service remove
echo ============================================================

endlocal
