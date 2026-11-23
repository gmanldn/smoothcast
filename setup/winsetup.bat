@echo off
setlocal EnableExtensions
rem SmoothCast virgin-machine Windows installer: PowerShell detects and acquires Python,
rem then delegates to bootstrap.py --target windows (no Python initially required).
set "SETUP_DIR=%~dp0"
:TRY_PYTHON
where powershell.exe >nul 2>&1
if errorlevel 1 goto NO_PYTHON
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SETUP_DIR%windows_python.ps1" -Bootstrap "%SETUP_DIR%bootstrap.py" %*
exit /b %errorlevel%

:NO_PYTHON
echo SmoothCast requires built-in Windows PowerShell 5.1 or later to acquire Python. 1>&2
cmd /c exit 1
exit /b %errorlevel%
