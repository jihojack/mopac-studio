@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run_venv
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.11 launcher.py %*
  ) else (
    py -3 launcher.py %*
  )
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python launcher.py %*
  goto finished
)
echo Python 3.11 64-bit is required. Install it from https://www.python.org/downloads/
echo Enable the Python launcher or Add python.exe to PATH during installation.
pause
exit /b 1

:run_venv
".venv\Scripts\python.exe" launcher.py %*

:finished
set "MOPAC_STUDIO_EXIT=%ERRORLEVEL%"
if not "%MOPAC_STUDIO_EXIT%"=="0" pause
exit /b %MOPAC_STUDIO_EXIT%
