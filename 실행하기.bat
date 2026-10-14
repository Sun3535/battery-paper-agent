@echo off
chcp 65001 > nul
setlocal

rem ══════════════════════════════════════════════════════════════
rem  Battery Paper Agent — 실행 스크립트 (Windows)
rem
rem  이 파일을 더블클릭하면 됩니다.
rem  처음 한 번만 필요한 것들을 자동으로 설치하고, 이후에는 바로 켜집니다.
rem ══════════════════════════════════════════════════════════════

cd /d "%~dp0"

echo.
echo  === Battery Paper Agent ===
echo.

rem ── 1) Python 확인 ────────────────────────────────────────────
python --version > nul 2>&1
if errorlevel 1 (
    echo  [!] Python 이 설치되어 있지 않습니다.
    echo      https://www.python.org/downloads/ 에서 설치하세요.
    echo      설치할 때 "Add Python to PATH" 를 꼭 체크하세요.
    echo.
    pause
    exit /b 1
)

rem ── 2) 설정 파일 ──────────────────────────────────────────────
if not exist ".env" (
    echo  [i] 설정 파일이 없어 기본값으로 만듭니다 (.env)
    copy ".env.example" ".env" > nul
)

rem ── 3) 가상환경 + 라이브러리 (처음 한 번만) ───────────────────
if not exist ".venv" (
    echo  [i] 처음 실행입니다. 필요한 라이브러리를 설치합니다.
    echo      몇 분 걸릴 수 있습니다. 창을 닫지 마세요.
    echo.
    python -m venv .venv
    if errorlevel 1 goto :fail
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r "webapp\backend\requirements.txt"
    if errorlevel 1 goto :fail
    echo.
    echo  [i] 설치 완료.
) else (
    call ".venv\Scripts\activate.bat"
)

rem ── 4) 실행 ───────────────────────────────────────────────────
echo.
echo  브라우저에서 아래 주소로 접속하세요:
echo.
echo      http://localhost:8100
echo.
echo  종료하려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.

start "" http://localhost:8100
python -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8100

goto :eof

:fail
echo.
echo  [!] 설치에 실패했습니다. 위 메시지를 확인하세요.
echo      사내망이라면 pip 가 막혔을 수 있습니다 (프록시 설정 필요).
echo.
pause
exit /b 1
