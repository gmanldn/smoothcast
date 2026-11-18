@echo off
setlocal
rem SmoothCast Windows installer. Python 3.10+ is the only initial prerequisite.
set "SETUP_DIR=%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys;sys.exit(sys.version_info < (3,10))" >nul 2>&1
    if not errorlevel 1 (
        py -3 "%SETUP_DIR%bootstrap.py" --target windows %*
        exit /b %errorlevel%
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys;sys.exit(sys.version_info < (3,10))" >nul 2>&1
    if not errorlevel 1 (
        python "%SETUP_DIR%bootstrap.py" --target windows %*
        exit /b %errorlevel%
    )
)
echo SmoothCast setup needs Python 3.10+ installed first. 1>&2
echo Install Python from https://www.python.org/downloads/windows/ and rerun this file. 1>&2
exit /b 1
