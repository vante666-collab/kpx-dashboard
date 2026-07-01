@echo off
cd /d "%~dp0"
echo ============================================================
echo   KMOS endpoint probe (values used only in this window)
echo   getDAEnSchedule / getDAGeneratingPrice structure check
echo ============================================================
echo.
set /p KMOS_API_KEY=API_KEY :
set /p KMOS_USERNAME=USERNAME(ID) :
set /p KMOS_PASSWORD=PASSWORD :
set /p KMOS_APIKEY=apiKey (Enter if none) :
set "KMOS_ENV="
set /p KMOS_ENV=ENV prod or stg (Enter=prod) :
if "%KMOS_ENV%"=="" set KMOS_ENV=prod
set /p RUNDATE=DATE (e.g. 2026-06-26) :
echo.
echo --- running ---
set "PY=C:\Users\admin.SKENS-T1012-05\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" probe_endpoints.py %RUNDATE%
echo.
echo ============================================================
echo  Done. Show reports\probe_*.json (two files) to Claude.
echo        Do NOT send your password / API key.
echo ============================================================
pause
