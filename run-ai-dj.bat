@echo off
setlocal
rem ------------------------------------------------------------------
rem  AI DJ - one-click start for Windows.
rem  Double-click this file. First run sets up Python packages (a few
rem  minutes); later runs start straight away. Then open
rem  http://127.0.0.1:8000/ (it opens automatically).
rem ------------------------------------------------------------------
cd /d "%~dp0"

rem Find a real Python 3 (the "py" launcher first, then python on PATH).
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE (
  py -3 --version >nul 2>&1 && set "BASEPY=py -3"
)
if not defined PYEXE if not defined BASEPY (
  python --version >nul 2>&1 && set "BASEPY=python"
)
if not defined PYEXE if not defined BASEPY (
  echo.
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo or run:  winget install Python.Python.3.12
  echo Then double-click run-ai-dj.bat again.
  echo.
  pause
  exit /b 1
)

if not defined PYEXE (
  echo Creating the Python environment in .venv ...
  %BASEPY% -m venv .venv || goto :fail
  set "PYEXE=.venv\Scripts\python.exe"
)

echo Checking Python packages ...
"%PYEXE%" -m pip install --disable-pip-version-check -q --upgrade pip >nul
"%PYEXE%" -m pip install --disable-pip-version-check -q -r backend\requirements.txt || goto :fail

rem Optional keys (uncomment and fill in to enable):
rem set "AI_DJ_SPOTIFY_CLIENT_ID=your-spotify-client-id"
rem set "AI_DJ_JAMENDO_CLIENT_ID=your-jamendo-client-id"

echo.
echo Starting AI DJ at http://127.0.0.1:8000/   (close this window to stop it)
start "" "http://127.0.0.1:8000/"
cd backend
"..\%PYEXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:fail
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
