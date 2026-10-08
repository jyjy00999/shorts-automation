@echo off
cd /d "%~dp0"

set PY=C:\Users\myeon\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

echo ============================================
echo   쇼핑 쇼츠 자동화 앱
echo ============================================
echo.

"%PY%" -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Streamlit이 설치되지 않았습니다.
    echo install.bat 을 먼저 실행해 주세요.
    pause
    exit /b 1
)

set PORT=8501
for %%P in (8501 8502 8503 8504 8505) do (
    netstat -ano | findstr ":%%P " >nul 2>&1
    if errorlevel 1 (
        set PORT=%%P
        goto :found
    )
)
:found

set MYIP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined MYIP set MYIP=%%a
)
set MYIP=%MYIP: =%

echo  이 PC에서  :  http://localhost:%PORT%
if defined MYIP echo  휴대폰에서 :  http://%MYIP%:%PORT%
echo.
echo  종료하려면 이 창에서 Ctrl+C
echo ============================================
echo.

"%PY%" -m streamlit run app.py --server.port %PORT% --server.address 0.0.0.0
pause
