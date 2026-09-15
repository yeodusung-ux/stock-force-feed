"""API 키 없이 서버 배선(라우팅/정적 파일/에러 처리)을 확인하는 스모크 테스트.

    python smoke_test.py
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server

FAKE = {
    "topic_summary_ko": "지각한 날의 일기",
    "opener_en": "Oh no, oversleeping is the worst feeling.",
    "opener_ko": "늦잠은 정말 최악이죠.",
    "key_vocabulary": [{"en": "oversleep", "ko": "늦잠 자다"}],
    "questions": [{"angle": "FEELING", "en": "How did you feel?", "ko": "기분이 어땠나요?", "difficulty": "easy"}],
    "reply_en": "That silence would bother me too.",
    "reply_ko": "그 침묵은 저라도 신경 쓰였을 거예요.",
    "correction": {"has_issues": True, "corrected_en": "I was late for work.",
                   "notes": [{"before": "late to work", "after": "late for work", "why_ko": "late 뒤에는 for 를 씁니다."}]},
    "better_expressions": [{"en": "I slept through my alarm.", "ko": "알람을 못 듣고 잤어요."}],
    "summary_ko": "지각과 그때의 감정에 대해 이야기했습니다.",
    "mistakes": [], "vocabulary": [], "unanswered_questions": [], "encouragement_ko": "잘하고 있어요!",
}


def post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    calls = []

    def fake_call_model(system, messages, schema, *, effort="low", max_tokens=4000):
        calls.append({"system": system, "messages": messages, "effort": effort})
        keys = schema["properties"].keys()
        return {k: FAKE[k] for k in keys}

    server.call_model = fake_call_model

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    with urllib.request.urlopen(base + "/") as response:
        assert response.status == 200 and b"English Buddy" in response.read(), "index.html 서빙 실패"
    with urllib.request.urlopen(base + "/app.js") as response:
        assert response.status == 200, "app.js 서빙 실패"

    status, data = post(base + "/api/questions", {"text": "오늘 지각했다.", "level": "beginner", "mode": "diary"})
    assert status == 200 and data["questions"], data
    assert "beginner" in calls[-1]["system"][1]["text"], "레벨 지시가 시스템 프롬프트에 반영되지 않음"

    status, data = post(base + "/api/chat", {
        "message": "I was late to work.", "topic": "오늘 지각했다.",
        "history": [{"role": "user", "content": "오늘 지각했다."}, {"role": "assistant", "content": "Oh no."}],
        "asked": ["How did you feel?"], "level": "intermediate", "mode": "diary",
    })
    assert status == 200 and data["correction"]["has_issues"], data
    sent = calls[-1]["messages"]
    assert sent[-1]["role"] == "system" and "How did you feel?" in sent[-1]["content"], "중복 질문 방지 목록 누락"
    assert sent[-2]["content"] == "I was late to work.", "마지막 사용자 발화가 누락됨"

    status, data = post(base + "/api/review", {"history": [{"role": "user", "content": "hi"}]})
    assert status == 200 and data["summary_ko"], data

    status, data = post(base + "/api/chat", {"message": "  "})
    assert status == 400 and data["error"], "빈 입력 검증 실패"
    status, data = post(base + "/api/nope", {})
    assert status == 404, "알 수 없는 경로 처리 실패"

    httpd.shutdown()
    print("모든 스모크 테스트 통과")


if __name__ == "__main__":
    main()
