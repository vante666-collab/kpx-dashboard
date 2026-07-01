@echo off
cd /d "%~dp0"
echo ============================================================
echo   KMOS API collector  (values used only in this window)
echo ============================================================
echo.
set /p KMOS_API_KEY=API_KEY :
set /p KMOS_USERNAME=USERNAME(ID) :
set /p KMOS_PASSWORD=PASSWORD :
set /p KMOS_APIKEY=apiKey (Enter if none) :
set /p KMOS_ENV=ENV prod or stg (Enter=prod) :
if "%KMOS_ENV%"=="" set KMOS_ENV=prod
set /p RUNDATE=DATE (e.g. 2026-06-18) :
echo.
echo --- running ---
set "PY=C:\Users\admin.SKENS-T1012-05\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" smp_api.py --debug %RUNDATE%
echo.
echo ============================================================
echo  Done.  OK  -> show JSON in 'reports' folder to Claude
echo         FAIL-> copy the error text above to Claude
echo  (do NOT send your password / key)
echo ============================================================
pause
