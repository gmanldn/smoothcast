@echo off
setlocal
rem SmoothCast Windows bootstrap: only Python 3.10+ is required beforehand.
set "SETUP_DIR=%~dp0"
where py >nul 2>&1
if errorlevel 1 goto TRY_PYTHON
py -3 -c "import sys;sys.exit(sys.version_info < (3,10))" >nul 2>&1
if errorlevel 1 goto TRY_PYTHON
py -3 "%SETUP_DIR%bootstrap.py" --target windows %*
exit /b %errorlevel%

:TRY_PYTHON
where python >nul 2>&1
if errorlevel 1 goto NO_PYTHON
python -c "import sys;sys.exit(sys.version_info < (3,10))" >nul 2>&1
if errorlevel 1 goto NO_PYTHON
python "%SETUP_DIR%bootstrap.py" --target windows %*
exit /b %errorlevel%

:NO_PYTHON
echo SmoothCast setup needs Python 3.10+ installed first. 1>&2
echo Install Python from https://www.python.org/downloads/windows/ and rerun. 1>&2
exit /b 1
