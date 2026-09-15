@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python 이 필요합니다. https://www.python.org/downloads/ 에서 설치해 주세요.
  echo 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b 1
)

if not exist .venv (
  echo 가상환경을 만드는 중…
  python -m venv .venv
)
call .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
call .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

if not exist .env (
  if "%ANTHROPIC_API_KEY%%GEMINI_API_KEY%"=="" (
    echo.
    echo API 키가 필요합니다. 둘 중 아무거나 쓰면 됩니다.
    echo   무료: Google Gemini 키 ^(AIza...^)  https://aistudio.google.com/apikey
    echo   유료: Anthropic Claude 키 ^(sk-ant-...^)  https://console.anthropic.com/settings/keys
    set /p KEY="키를 붙여넣고 Enter: "
    set NAME=
    echo !KEY! | findstr /b /c:"sk-ant-" >nul && set NAME=ANTHROPIC_API_KEY
    echo !KEY! | findstr /b /c:"AIza" >nul && set NAME=GEMINI_API_KEY
    if "!NAME!"=="" (
      echo 키 형식을 알아보지 못했습니다. Gemini 키는 AIza, Claude 키는 sk-ant- 로 시작합니다.
      pause
      exit /b 1
    )
    > .env echo !NAME!=!KEY!
    echo .env 에 !NAME! 으로 저장했습니다. 다음부터는 묻지 않습니다.
  )
)

if "%PORT%"=="" set PORT=8000
start "" http://localhost:%PORT%
echo.
echo 브라우저에서 http://localhost:%PORT% 을 여세요. 끄려면 이 창에서 Ctrl+C.
call .venv\Scripts\python.exe server.py
pause
