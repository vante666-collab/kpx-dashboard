@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   전력거래소 KMOS API 자동수집 실행
echo   (입력값은 이 창에서만 쓰이고 어디에도 저장되지 않습니다)
echo   (비밀번호는 화면에 보일 수 있으니 주변 주의)
echo ============================================================
echo.
set /p KMOS_API_KEY=API_KEY (발급받은 API키):
set /p KMOS_USERNAME=아이디:
set /p KMOS_PASSWORD=비밀번호:
set /p KMOS_APIKEY=apiKey (없으면 그냥 Enter):
set /p KMOS_ENV=환경 prod 또는 stg (기본 prod, 그냥 Enter):
if "%KMOS_ENV%"=="" set KMOS_ENV=prod
set /p RUNDATE=조회 날짜 (예: 2026-06-18, 여러개는 공백으로):
echo.
echo --- 실행 중... ---

set "PY=C:\Users\admin.SKENS-T1012-05\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" smp_api.py --debug %RUNDATE%

echo.
echo ============================================================
echo  끝났습니다.
echo  - 성공: reports 폴더의 JSON 파일을 클로드에게 보여주세요.
echo  - 실패: 위에 표시된 에러 메시지를 클로드에게 알려주세요.
echo  (어느 쪽이든 비밀번호/키는 보내지 마세요)
echo ============================================================
pause
