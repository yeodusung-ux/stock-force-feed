"""API 키 없이 서버 배선(정적 파일 · /api/health · /api/ai 프록시)을 확인하는 스모크 테스트.
   Claude 모드와 Gemini 모드를 모두 돌려 본다.

    python smoke_test.py
"""

import io
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server

FAKE_ANSWER = {
    "topic_summary_ko": "지각한 날의 일기",
    "opener_en": "Oh no, oversleeping is the worst feeling.",
    "opener_ko": "늦잠은 정말 최악이죠.",
    "key_vocabulary": [{"en": "oversleep", "ko": "늦잠 자다"}],
    "questions": [{"angle": "FEELING", "en": "How did you feel?", "ko": "기분이 어땠나요?", "difficulty": "easy"}],
    "reply_en": "That silence would bother me too.",
    "reply_ko": "그 침묵은 저라도 신경 쓰였을 거예요.",
    "correction": {
        "has_issues": True,
        "corrected_en": "I was late for work.",
        "notes": [{"before": "late to work", "after": "late for work", "why_ko": "late 뒤에는 for 를 씁니다."}],
    },
    "better_expressions": [{"en": "I slept through my alarm.", "ko": "알람을 못 듣고 잤어요."}],
    "summary_ko": "지각과 그때의 감정에 대해 이야기했습니다.",
    "mistakes": [],
    "vocabulary": [],
    "unanswered_questions": [],
    "encouragement_ko": "잘하고 있어요!",
}

sent_requests = []


class FakeResponse:
    def model_dump(self, mode="json"):
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(FAKE_ANSWER, ensure_ascii=False)}],
        }


class FakeMessages:
    def create(self, **kwargs):
        sent_requests.append(kwargs)
        return FakeResponse()


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()
        self.beta = type("Beta", (), {"messages": FakeMessages()})()


class FakeGeminiHTTP:
    """urllib.request.urlopen 을 대신해 Gemini 응답을 흉내 낸다."""

    def __init__(self):
        self.urls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        if url.endswith("/models"):
            payload = {
                "models": [
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-3-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]},
                ]
            }
        else:
            payload = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(FAKE_ANSWER, ensure_ascii=False)}]},
                    }
                ]
            }
        return io.BytesIO(json.dumps(payload).encode())


def post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read()


ANTHROPIC_REQUEST = {
    "model": "claude-opus-5",
    "max_tokens": 4000,
    "system": [{"type": "text", "text": "system"}],
    "messages": [{"role": "user", "content": "오늘 지각했다."}],
    "thinking": {"type": "adaptive"},
    "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}},
}

GEMINI_REQUEST = {
    "systemInstruction": {"parts": [{"text": "system"}]},
    "contents": [{"role": "user", "parts": [{"text": "오늘 지각했다."}]}],
    "generationConfig": {"responseMimeType": "application/json", "responseSchema": {"type": "object"}},
}


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def check_claude_mode():
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    os.environ.pop("GEMINI_API_KEY", None)
    server.get_client = FakeClient
    httpd, base = serve()

    status, body = get(base + "/")
    assert status == 200 and b"English Buddy" in body, "index.html 서빙 실패"
    assert b'ENGLISH_BUDDY_SERVER = "anthropic"' in body, "제공자 플래그가 주입되지 않음"
    for path in ("/app.js", "/ai.js", "/voice.js", "/style.css", "/manifest.webmanifest", "/icons/icon-192.png"):
        assert get(base + path)[0] == 200, f"{path} 서빙 실패"

    status, body = get(base + "/api/health")
    assert status == 200 and json.loads(body) == {"ok": True, "provider": "anthropic"}, "health 체크 실패"

    status, data = post(base + "/api/ai", ANTHROPIC_REQUEST)
    assert status == 200, data
    assert json.loads(data["content"][0]["text"])["opener_en"], "모델 응답 전달 실패"
    forwarded = sent_requests[-1]
    assert forwarded["model"] == "claude-opus-5", "모델이 그대로 전달되지 않음"
    assert forwarded["fallbacks"] == "default", "서버사이드 폴백이 붙지 않음"

    status, data = post(base + "/api/ai", {**ANTHROPIC_REQUEST, "x-api-key": "sk-ant-sneaky"})
    assert status == 400 and "허용되지 않은" in data["error"], "허용되지 않은 필드가 통과됨"

    status, data = post(base + "/api/ai", {"model": "claude-opus-5"})
    assert status == 400 and "필수 필드" in data["error"], "필수 필드 검증 실패"

    status, data = post(base + "/api/nope", {})
    assert status == 404, "알 수 없는 경로 처리 실패"

    httpd.shutdown()
    print("  Claude 모드 통과")


def check_gemini_mode():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    os.environ["GEMINI_API_KEY"] = "AIza-test"
    server._gemini_model = None
    fake_http = FakeGeminiHTTP()
    server.urlopen = fake_http
    httpd, base = serve()

    status, body = get(base + "/")
    assert b'ENGLISH_BUDDY_SERVER = "gemini"' in body, "Gemini 플래그가 주입되지 않음"

    status, data = post(base + "/api/ai", GEMINI_REQUEST)
    assert status == 200, data
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    assert json.loads(text)["opener_en"], "Gemini 응답 전달 실패"
    assert server._gemini_model == "gemini-3-flash", f"모델 선택이 틀림: {server._gemini_model}"
    assert any("gemini-3-flash:generateContent" in url for url in fake_http.urls), "선택한 모델로 호출하지 않음"

    status, data = post(base + "/api/ai", {**GEMINI_REQUEST, "x-goog-api-key": "AIza-sneaky"})
    assert status == 400 and "허용되지 않은" in data["error"], "허용되지 않은 필드가 통과됨"

    httpd.shutdown()
    print("  Gemini 모드 통과")


def main() -> None:
    check_claude_mode()
    check_gemini_mode()
    print("모든 스모크 테스트 통과")


if __name__ == "__main__":
    main()
