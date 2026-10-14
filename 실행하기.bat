@echo off
setlocal
rem ==============================================================
rem  Nonmun-Chaekbang (Battery Paper Agent) launcher for Windows
rem
rem  KEEP THIS FILE ASCII-ONLY AND CRLF.
rem   - Korean text inside a .bat breaks cmd.exe now and then.
rem     Korean messages live in webapp\launch_msgs\*.txt instead.
rem   - Saved with LF line endings, this file does not run at all.
rem   - Never put a closing parenthesis inside an echo within if-blocks.
rem  To change the port, replace 8100 everywhere in this file
rem  and in webapp\launch_msgs\running.txt.
rem ==============================================================

rem pushd also works for network paths: it maps a temporary drive letter.
pushd "%~dp0" || (
    echo  [!] Cannot open the program folder. Copy it to a local drive such as C: or D: and run again.
    pause
    exit /b 1
)
chcp 65001 > nul

echo.
echo  === Battery Paper Agent ===
echo.

rem -- 1. Python --------------------------------------------------
python --version > nul 2>&1
if errorlevel 1 (
    echo  [!] Python was not found. Install it from https://www.python.org/downloads/
    echo      and tick "Add Python to PATH" during setup.
    type "webapp\launch_msgs\no_python.txt" 2>nul
    echo.
    pause
    exit /b 1
)

rem -- 2. Settings file: never touched once it exists ---------------
if not exist ".env" (
    echo  [i] Creating the settings file .env from .env.example
    copy ".env.example" ".env" > nul
)

rem -- 3. Virtual environment ---------------------------------------
set "HADVENV=0"
if exist ".venv\Scripts\activate.bat" set "HADVENV=1"
if "%HADVENV%"=="0" (
    echo  [i] First run: creating the Python environment .venv
    python -m venv .venv
    if errorlevel 1 goto :fail
)
call ".venv\Scripts\activate.bat"

rem A .venv made in another folder points to that old folder.
python -c "import os,sys; sys.exit(0 if os.path.normcase(os.path.realpath(sys.prefix)) == os.path.normcase(os.path.realpath('.venv')) else 3)" > nul 2>&1
if errorlevel 3 (
    echo  [!] The .venv folder was made in another place - the program folder was moved or renamed.
    echo      Close this window, delete the .venv folder, and run this file again.
    type "webapp\launch_msgs\moved.txt" 2>nul
    echo.
    pause
    exit /b 1
)

rem -- 4. Libraries ----------------------------------------------------
rem  After a successful install, requirements.txt is copied into .venv.
rem  If that copy is missing or differs, install again. This covers
rem  an install that failed halfway and an upgrade that added libraries.
fc /b "webapp\backend\requirements.txt" ".venv\requirements.installed" > nul 2>&1
if errorlevel 1 (
    echo  [i] Installing libraries. This can take a few minutes. Do not close this window.
    type "webapp\launch_msgs\installing.txt" 2>nul
    echo.
    python -m pip install --upgrade pip
    python -m pip install -r "webapp\backend\requirements.txt"
    if errorlevel 1 goto :installfail
    copy /y "webapp\backend\requirements.txt" ".venv\requirements.installed" > nul
    echo.
    echo  [i] Install finished.
)

:run
rem -- 5. Run ----------------------------------------------------------
echo.
echo  Open this address in your browser:  http://localhost:8100
echo  To stop: press Ctrl+C in this window, or close it.
type "webapp\launch_msgs\running.txt" 2>nul
echo.

rem Open the browser a few seconds later, when the server is up.
start "" /b python -c "import time, webbrowser; time.sleep(4); webbrowser.open('http://localhost:8100')"
python -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8100

rem The server only returns here when it stops. Keep the window so the reason can be read.
echo.
echo  [i] The server has stopped. If it stopped by itself, read the messages above.
echo      Port already in use means the program is probably running in another window.
type "webapp\launch_msgs\stopped.txt" 2>nul
echo.
pause
goto :eof

:installfail
if "%HADVENV%"=="1" (
    echo.
    echo  [!] Could not install the new libraries. Starting with the libraries already installed.
    echo      Most features work. New features may not - for example Claude translation.
    type "webapp\launch_msgs\install_skipped.txt" 2>nul
    echo.
    goto :run
)

:fail
echo.
echo  [!] Install failed. Read the messages above.
echo      Behind a company proxy, pip may be blocked.
echo      After fixing the cause, run this file again. It resumes from the install step.
type "webapp\launch_msgs\failed.txt" 2>nul
echo.
pause
exit /b 1
