@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================
echo   영상 자막 제거기
echo ============================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되지 않았습니다.
    pause
    exit /b 1
)

:: 영상 파일을 드래그해서 실행한 경우
if not "%~1"=="" (
    echo 대상: %~1
    echo.
    python clean_videos.py "%~1"
    echo.
    pause
    exit /b
)

echo 처리할 영상을 고르세요:
echo.
echo   1. outputs\source_videos 폴더 전체
echo   2. 폴더 경로 직접 입력
echo   3. 자막 위치만 확인 (지우지 않음)
echo.
set /p choice=번호 입력 (1-3):

if "%choice%"=="1" (
    python clean_videos.py
) else if "%choice%"=="2" (
    set /p folder=폴더 경로:
    python clean_videos.py "%folder%"
) else if "%choice%"=="3" (
    python clean_videos.py --check
) else (
    echo 잘못된 입력입니다.
)

echo.
pause
