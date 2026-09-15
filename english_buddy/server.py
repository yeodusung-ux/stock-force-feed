"""English Buddy - PC에서 쓸 때의 로컬 서버.

정적 파일(web/)을 내려주고, /api/claude 로 들어온 요청에 API 키를 붙여 Claude 로 전달한다.
프롬프트와 대화 로직은 web/claude.js 한곳에만 있고, 이 서버는 키를 PC 밖으로 내보내지 않는
역할만 한다. 휴대폰에서는 서버 없이 같은 web/ 을 정적 호스팅해서 쓴다(그때는 키가 폰에 저장된다).

실행:
    ./start.sh          # 또는 Windows: start.bat
    python server.py    # 직접 실행할 때
"""

from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import anthropic

WEB_DIR = Path(__file__).parent / "web"

# 브라우저가 보낼 수 있는 요청 필드만 통과시킨다.
ALLOWED_FIELDS = {"model", "max_tokens", "system", "messages", "thinking", "output_config"}


def load_env_file() -> None:
    """옆에 있는 .env 파일을 환경변수로 읽어 온다(이미 설정된 값은 건드리지 않는다)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

PORT = int(os.environ.get("PORT", "8000"))

_client: anthropic.Anthropic | None = None

# Claude Opus 5 는 안전 분류기가 요청을 거절할 수 있어(stop_reason="refusal"),
# 서버사이드 폴백을 기본으로 켜 둔다. 계정에서 해당 베타를 못 쓰면 자동으로 끄고 재시도한다.
_use_fallbacks = os.environ.get("ENGLISH_BUDDY_FALLBACKS", "1") == "1"


def get_client() -> anthropic.Anthropic:
    """API 키는 환경변수(ANTHROPIC_API_KEY 등)에서 읽는다. 첫 요청 때 한 번만 만든다."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class RequestError(ValueError):
    """클라이언트 입력 문제(400)."""


def api_claude(body: dict) -> dict:
    """브라우저가 만든 요청을 그대로 Claude 로 전달하고 응답을 JSON 으로 돌려준다."""
    global _use_fallbacks

    unknown = set(body) - ALLOWED_FIELDS
    if unknown:
        raise RequestError(f"허용되지 않은 필드: {', '.join(sorted(unknown))}")
    for field in ("model", "max_tokens", "messages"):
        if field not in body:
            raise RequestError(f"필수 필드가 없습니다: {field}")

    client = get_client()
    try:
        if _use_fallbacks:
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **body
            )
        else:
            response = client.messages.create(**body)
    except anthropic.BadRequestError as exc:
        if _use_fallbacks and ("fallback" in str(exc).lower() or "beta" in str(exc).lower()):
            _use_fallbacks = False
            response = client.messages.create(**body)
        else:
            raise

    return response.model_dump(mode="json")


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "EnglishBuddy/2.0"

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return

        name = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB_DIR / name).resolve()
        if not target.is_file() or WEB_DIR.resolve() not in target.parents:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        if target.name == "index.html":
            # 이 서버가 키를 들고 있다는 표시. 정적 호스팅에서는 이 줄이 없으니 앱이 스스로 키를 묻는다.
            html = target.read_text(encoding="utf-8").replace(
                "</head>", "  <script>window.ENGLISH_BUDDY_SERVER = true;</script>\n</head>", 1
            )
            self._send(200, html.encode("utf-8"), CONTENT_TYPES[".html"])
            return

        self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/claude":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(200, api_claude(body))
        except (RequestError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
        except anthropic.APIStatusError as exc:
            message = getattr(exc, "message", None) or str(exc)
            if exc.status_code == 401:
                message = "API 키가 올바르지 않습니다. .env 의 ANTHROPIC_API_KEY 를 확인해 주세요."
            elif "credit balance" in message.lower():
                message = "크레딧이 부족합니다. console.anthropic.com 에서 충전해 주세요."
            self._send_json(exc.status_code, {"error": message})
        except anthropic.APIConnectionError:
            self._send_json(502, {"error": "Claude API 에 연결하지 못했습니다. 네트워크를 확인해 주세요."})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"error": "서버 오류가 발생했습니다. 터미널 로그를 확인해 주세요."})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[english-buddy] {fmt % args}")


def main() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "경고: Claude API 키가 없습니다.\n"
            "  이 폴더에 .env 파일을 만들고 `ANTHROPIC_API_KEY=sk-ant-...` 한 줄을 넣거나,\n"
            "  `export ANTHROPIC_API_KEY=sk-ant-...` 로 설정한 뒤 다시 실행해 주세요."
        )
    print(f"English Buddy: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
