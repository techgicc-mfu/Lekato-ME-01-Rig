@echo off
setlocal
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%~dp0launch.py" %*
    exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%~dp0launch.py" %*
    exit /b %ERRORLEVEL%
)
echo Python 3 was not found on PATH. Please install Python 3.
exit /b 1
