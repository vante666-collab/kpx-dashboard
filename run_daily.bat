@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PY=C:\Users\admin.SKENS-T1012-05\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
echo. >> daily_forecast.log
"%PY%" daily_forecast.py >> daily_forecast.log 2>&1
