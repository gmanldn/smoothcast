@echo off
setlocal EnableExtensions
rem Fresh Windows checkout: acquire Python if needed, then use canonical sc.py.
where powershell.exe >nul 2>&1
if errorlevel 1 goto NO_POWERSHELL
echo [SmoothCast] Starting SmoothCast. First run may need to install dependencies.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\windows_python.ps1" -Bootstrap "%~dp0setup\bootstrap.py" -Launch %*
set "SC_EXIT=%errorlevel%"
if "%SC_EXIT%"=="0" exit /b 0
echo [SmoothCast] Startup failed with exit code %SC_EXIT%. See the message above. 1>&2
echo Run setup\winsetup.bat to repair the installation. 1>&2
pause
exit /b %SC_EXIT%

:NO_POWERSHELL
echo SmoothCast requires built-in Windows PowerShell 5.1 or later. 1>&2
pause
exit /b 1
