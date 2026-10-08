@echo off
chcp 65001 > nul

:: ★ 핵심 수정: 이 bat 파일이 있는 폴더로 이동 (더블클릭 시 경로 오류 방지)
cd /d "%~dp0"

echo ============================================
echo  쇼핑 쇼츠 자동화 앱 - 설치 스크립트
echo ============================================
echo.
echo 현재 작업 경로: %CD%
echo.

:: ── Python 확인 ──────────────────────────────
echo [검사] Python 버전 확인 중...
python --version
if errorlevel 1 (
    echo.
    echo [오류] Python을 찾을 수 없습니다.
    echo Python 3.10 이상을 설치하세요: https://www.python.org
    echo 설치 후 "PATH에 Python 추가" 체크박스를 반드시 선택하세요.
    pause
    exit /b 1
)
echo.

:: ── requirements.txt 존재 확인 ───────────────
if not exist "requirements.txt" (
    echo [오류] requirements.txt 파일을 찾을 수 없습니다.
    echo 현재 경로: %CD%
    echo install.bat 과 requirements.txt 가 같은 폴더에 있어야 합니다.
    pause
    exit /b 1
)

:: ── pip 업그레이드 ───────────────────────────
echo [1/4] pip 업그레이드 중...
python -m pip install --upgrade pip --quiet
echo     완료
echo.

:: ── 패키지 설치 ─────────────────────────────
echo [2/4] 패키지 설치 중... (인터넷 속도에 따라 1~3분 소요)
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [오류] 패키지 설치 실패. 오류 메시지를 확인하세요.
    pause
    exit /b 1
)
echo.

:: ── FFmpeg 확인 ─────────────────────────────
echo [3/4] FFmpeg 설치 확인...
ffmpeg -version > nul 2>&1
if errorlevel 1 (
    echo     FFmpeg 없음. winget으로 설치 시도 중...
    winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo     [주의] FFmpeg 자동 설치 실패.
        echo     수동 설치 방법:
        echo     1. https://www.gyan.dev/ffmpeg/builds/ 접속
        echo     2. ffmpeg-release-essentials.zip 다운로드
        echo     3. C:\ffmpeg\ 에 압축 해제
        echo     4. 시스템 환경변수 PATH 에 C:\ffmpeg\bin 추가
        echo     (FFmpeg 없어도 ZIP 패키징까지는 정상 작동합니다)
    ) else (
        echo     FFmpeg 설치 완료!
    )
) else (
    echo     FFmpeg 이미 설치되어 있습니다.
)
echo.

:: ── .env 파일 생성 ───────────────────────────
echo [4/4] 환경변수 파일 설정...
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" > nul
        echo     .env 파일 생성 완료!
        echo     메모장이 열리면 API 키를 입력하고 저장하세요.
        echo.
        timeout /t 2 > nul
        notepad ".env"
    ) else (
        echo     [주의] .env.example 파일이 없습니다. 수동으로 .env 를 생성하세요.
    )
) else (
    echo     .env 파일이 이미 존재합니다.
)
echo.

:: ── 완료 ────────────────────────────────────
echo ============================================
echo  설치 완료!
echo.
echo  다음 단계:
echo  1. .env 파일에 API 키 입력 (이미 열렸다면 저장)
echo  2. run.bat 더블클릭으로 앱 실행
echo  3. 브라우저에서 http://localhost:8501 접속
echo ============================================
pause
