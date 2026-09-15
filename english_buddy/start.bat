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
  if "%ANTHROPIC_API_KEY%"=="" (
    echo.
    echo Claude API 키가 필요합니다. https://console.anthropic.com/settings/keys 에서 만들 수 있습니다.
    set /p KEY="키를 붙여넣고 Enter (sk-ant-...): "
    if "!KEY!"=="" (
      echo 키가 비어 있습니다. 다시 실행해 주세요.
      pause
      exit /b 1
    )
    > .env echo ANTHROPIC_API_KEY=!KEY!
    echo .env 에 저장했습니다. 다음부터는 묻지 않습니다.
  )
)

if "%PORT%"=="" set PORT=8000
start "" http://localhost:%PORT%
echo.
echo 브라우저에서 http://localhost:%PORT% 을 여세요. 끄려면 이 창에서 Ctrl+C.
call .venv\Scripts\python.exe server.py
pause
