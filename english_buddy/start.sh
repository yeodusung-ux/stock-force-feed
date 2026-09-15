#!/usr/bin/env bash
# macOS · Linux 용 실행 스크립트. 가상환경 생성, 설치, API 키 입력, 브라우저 열기까지 한 번에.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 이 필요합니다. https://www.python.org/downloads/ 에서 설치해 주세요."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "가상환경을 만드는 중…"
  "$PYTHON" -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

if [ ! -f .env ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  echo
  echo "API 키가 필요합니다. 둘 중 아무거나 쓰면 됩니다."
  echo "  무료: Google Gemini 키 (AIza...)   https://aistudio.google.com/apikey"
  echo "  유료: Anthropic Claude 키 (sk-ant-...)  https://console.anthropic.com/settings/keys"
  read -r -p "키를 붙여넣고 Enter: " key
  case "$key" in
    sk-ant-*) name=ANTHROPIC_API_KEY ;;
    AIza*)    name=GEMINI_API_KEY ;;
    *)
      echo "키 형식을 알아보지 못했습니다. Gemini 키는 AIza, Claude 키는 sk-ant- 로 시작합니다."
      exit 1
      ;;
  esac
  printf '%s=%s\n' "$name" "$key" > .env
  chmod 600 .env
  echo ".env 에 $name 으로 저장했습니다. 다음부터는 묻지 않습니다."
fi

PORT="${PORT:-8000}"
URL="http://localhost:${PORT}"
(
  sleep 1
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi
) >/dev/null 2>&1 &

echo
echo "브라우저에서 ${URL} 을 여세요. 끄려면 이 창에서 Ctrl+C."
exec ./.venv/bin/python server.py
