"""English Buddy - 일기 / 상황 설명 / 주제를 입력하면
그 내용에 대해 최대한 다양한 각도의 질문을 던지며 영어 대화를 이어가는 학습 앱.

실행:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
    python server.py          # http://localhost:8000
"""

from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import anthropic

MODEL = os.environ.get("ENGLISH_BUDDY_MODEL", "claude-opus-5")
PORT = int(os.environ.get("PORT", "8000"))
STATIC_DIR = Path(__file__).parent / "static"
MAX_HISTORY_TURNS = 40

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """API 키는 환경변수(ANTHROPIC_API_KEY 등)에서 읽는다. 첫 요청 때 한 번만 만든다."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# Claude Opus 5 는 안전 분류기가 요청을 거절할 수 있어(stop_reason="refusal"),
# 서버사이드 폴백을 기본으로 켜 둔다. 계정에서 해당 베타를 못 쓰면 자동으로 끄고 재시도한다.
_use_fallbacks = os.environ.get("ENGLISH_BUDDY_FALLBACKS", "1") == "1"


# --------------------------------------------------------------------------
# 프롬프트
# --------------------------------------------------------------------------

QUESTION_ANGLES = """\
Question variety is the whole point of this app. Rotate through these angles, never use the same
angle twice in a row, and never repeat a question that has already been asked in this session:

1.  FACTS - who / when / where / how long / how often
2.  DETAIL - sensory detail: what it looked, sounded, smelled or tasted like
3.  FEELING - their emotional reaction, in the moment and now
4.  REASON - why it happened, why they chose that
5.  OPINION - evaluation, whether they'd recommend or do it again
6.  COMPARISON - versus another time, place, person, or versus the past
7.  HYPOTHETICAL - what if it had gone differently
8.  PAST LINK - an earlier experience of theirs that connects to this
9.  FUTURE - what happens next, plans, wishes
10. OTHER PERSPECTIVE - how another person in the story saw it
11. CULTURE - how this works in Korea versus other countries
12. VOCABULARY - ask them to express one specific idea from their own text a different way
13. ROLE-PLAY - drop them into the situation and ask for the actual line ("You're at the counter - what do you say?")
14. SUMMARY CHALLENGE - ask them to retell one part in two sentences

Hard rules for every question:
- Ask about what they actually wrote. Reuse their own nouns, names, places and details.
  Generic textbook questions ("What is your hobby?") are failures.
- One clear question per item. No double-barreled questions.
- Keep it answerable at the learner's stated level. If a question needs a word they may not know,
  put that word in the Korean gloss (`ko`).
- Sound like a curious friend, not a quiz machine."""

LEVEL_GUIDE = {
    "beginner": (
        "LEVEL: beginner. Use present and past simple, high-frequency vocabulary, at most ~12 words "
        "per question. The Korean gloss matters a lot here. Your own replies stay very short."
    ),
    "intermediate": (
        "LEVEL: intermediate. Everyday idioms and two-clause sentences are fine. Push them toward "
        "longer answers with 'why' and 'how' questions."
    ),
    "advanced": (
        "LEVEL: advanced. Ask abstract, hypothetical and nuanced questions. Challenge imprecise word "
        "choice, register and collocation even when the grammar is already correct."
    ),
}

MODE_GUIDE = {
    "diary": "The learner wrote a DIARY entry about their own day. Treat it as personal and real.",
    "situation": "The learner described a SITUATION (real or imagined). Explore it, and use role-play often.",
    "topic": "The learner named a TOPIC. Ask about their own experience and opinions on it, not encyclopedia facts.",
}

BASE_SYSTEM = """\
You are "English Buddy", a warm and genuinely curious English conversation partner for a Korean learner.

The learner writes a diary entry, describes a situation, or names a topic. Your job is to keep an English
conversation going about *their* content by asking as many genuinely different questions as possible.

{angles}

If the learner writes in Korean, treat it as "I want to say this in English": give them the English version
in `better_expressions`, then carry on with the conversation in English.

Write every `ko` / `_ko` field in natural Korean, and every English field in natural English."""


def system_blocks(level: str, mode: str) -> list[dict]:
    """안정적인 프리픽스는 캐시하고, 세션마다 바뀌는 지시는 뒤에 붙인다."""
    return [
        {
            "type": "text",
            "text": BASE_SYSTEM.format(angles=QUESTION_ANGLES),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": LEVEL_GUIDE.get(level, LEVEL_GUIDE["intermediate"])
            + "\n"
            + MODE_GUIDE.get(mode, MODE_GUIDE["diary"]),
        },
    ]


# --------------------------------------------------------------------------
# 응답 스키마 (structured outputs)
# --------------------------------------------------------------------------

QUESTION_ITEM = {
    "type": "object",
    "properties": {
        "angle": {
            "type": "string",
            "enum": [
                "FACTS", "DETAIL", "FEELING", "REASON", "OPINION", "COMPARISON",
                "HYPOTHETICAL", "PAST_LINK", "FUTURE", "OTHER_PERSPECTIVE",
                "CULTURE", "VOCABULARY", "ROLE_PLAY", "SUMMARY_CHALLENGE",
            ],
        },
        "en": {"type": "string", "description": "The question, in English."},
        "ko": {"type": "string", "description": "Korean gloss of the question."},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
    },
    "required": ["angle", "en", "ko", "difficulty"],
    "additionalProperties": False,
}

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "topic_summary_ko": {
            "type": "string",
            "description": "학습자가 쓴 내용을 한 문장 한국어로 요약.",
        },
        "opener_en": {
            "type": "string",
            "description": "A warm 1-2 sentence English reaction to what they wrote.",
        },
        "opener_ko": {"type": "string"},
        "key_vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "en": {"type": "string"},
                    "ko": {"type": "string"},
                },
                "required": ["en", "ko"],
                "additionalProperties": False,
            },
            "description": "5-8 words or phrases they will need to talk about this content.",
        },
        "questions": {
            "type": "array",
            "items": QUESTION_ITEM,
            "description": "12-15 questions, each from a different angle, ordered easy to hard.",
        },
    },
    "required": ["topic_summary_ko", "opener_en", "opener_ko", "key_vocabulary", "questions"],
    "additionalProperties": False,
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply_en": {
            "type": "string",
            "description": "React to the MEANING of what they said, in 1-2 natural English sentences.",
        },
        "reply_ko": {"type": "string", "description": "Korean translation of reply_en."},
        "correction": {
            "type": "object",
            "properties": {
                "has_issues": {"type": "boolean"},
                "corrected_en": {
                    "type": "string",
                    "description": "Their sentence(s) rewritten correctly. Empty string if nothing to fix.",
                },
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "before": {"type": "string"},
                            "after": {"type": "string"},
                            "why_ko": {"type": "string"},
                        },
                        "required": ["before", "after", "why_ko"],
                        "additionalProperties": False,
                    },
                    "description": "At most 3 real errors. Never invent errors that are not there.",
                },
            },
            "required": ["has_issues", "corrected_en", "notes"],
            "additionalProperties": False,
        },
        "better_expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "en": {"type": "string"},
                    "ko": {"type": "string"},
                },
                "required": ["en", "ko"],
                "additionalProperties": False,
            },
            "description": "1-3 more natural or higher-level ways to say what they meant.",
        },
        "questions": {
            "type": "array",
            "items": QUESTION_ITEM,
            "description": "2-4 brand-new follow-up questions, each from a different angle.",
        },
    },
    "required": ["reply_en", "reply_ko", "correction", "better_expressions", "questions"],
    "additionalProperties": False,
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_ko": {"type": "string", "description": "이번 대화에서 다룬 내용 요약."},
        "mistakes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "why_ko": {"type": "string"},
                },
                "required": ["before", "after", "why_ko"],
                "additionalProperties": False,
            },
            "description": "Recurring or important mistakes from this session.",
        },
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "en": {"type": "string"},
                    "ko": {"type": "string"},
                    "example_en": {"type": "string"},
                },
                "required": ["en", "ko", "example_en"],
                "additionalProperties": False,
            },
        },
        "unanswered_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Questions worth revisiting next time, in English.",
        },
        "encouragement_ko": {"type": "string"},
    },
    "required": ["summary_ko", "mistakes", "vocabulary", "unanswered_questions", "encouragement_ko"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# 모델 호출
# --------------------------------------------------------------------------

class ModelError(RuntimeError):
    pass


def call_model(system, messages, schema, *, effort="low", max_tokens=4000) -> dict:
    """structured output 으로 JSON 한 덩어리를 받아 온다."""
    global _use_fallbacks

    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )

    client = get_client()
    try:
        if _use_fallbacks:
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = client.messages.create(**kwargs)
    except anthropic.BadRequestError as exc:
        # 서버사이드 폴백 베타를 못 쓰는 계정이면 한 번만 끄고 재시도한다.
        if _use_fallbacks and ("fallback" in str(exc).lower() or "beta" in str(exc).lower()):
            _use_fallbacks = False
            response = client.messages.create(**kwargs)
        else:
            raise

    if response.stop_reason == "refusal":
        raise ModelError("모델이 이 입력에 대한 응답을 거절했습니다. 내용을 바꿔서 다시 시도해 주세요.")
    if response.stop_reason == "max_tokens":
        raise ModelError("응답이 너무 길어 잘렸습니다. 입력을 조금 짧게 해서 다시 시도해 주세요.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ModelError("모델이 빈 응답을 반환했습니다.")
    return json.loads(text)


# 대화 중간의 system 메시지(운영 지시)를 지원하는 모델들. 그 외 모델에서는 400 이 나므로
# 같은 지시를 마지막 사용자 메시지 뒤에 붙인다.
MIDCONV_SYSTEM_PREFIXES = ("claude-opus-5", "claude-opus-4-8", "claude-fable", "claude-mythos")


def append_turn_instructions(messages: list[dict], instructions: str) -> None:
    if MODEL.startswith(MIDCONV_SYSTEM_PREFIXES):
        messages.append({"role": "system", "content": instructions})
    else:
        messages[-1]["content"] += f"\n\n<turn_instructions>\n{instructions}\n</turn_instructions>"


def history_to_messages(history: list[dict]) -> list[dict]:
    """브라우저가 보관한 대화 기록을 Messages API 형식으로 바꾼다."""
    messages = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


# --------------------------------------------------------------------------
# API 핸들러
# --------------------------------------------------------------------------

def api_questions(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    if not text:
        raise ModelError("내용을 입력해 주세요.")
    level = body.get("level", "intermediate")
    mode = body.get("mode", "diary")

    prompt = (
        f"Here is what the learner wrote:\n\n<learner_text>\n{text}\n</learner_text>\n\n"
        "Summarise it in Korean, react warmly in English, list the vocabulary they'll need, "
        "and write 12-15 questions about it - each from a different angle, ordered from easy to hard."
    )
    return call_model(
        system_blocks(level, mode),
        [{"role": "user", "content": prompt}],
        QUESTIONS_SCHEMA,
        effort="medium",
        max_tokens=6000,
    )


def api_chat(body: dict) -> dict:
    message = (body.get("message") or "").strip()
    if not message:
        raise ModelError("답변을 입력해 주세요.")
    level = body.get("level", "intermediate")
    mode = body.get("mode", "diary")
    topic = (body.get("topic") or "").strip()
    asked = [q for q in (body.get("asked") or []) if isinstance(q, str)][-40:]

    turn_instructions = (
        "For this turn:\n"
        "1. React in English to the MEANING of what they just said - be a person, not a grader.\n"
        "2. Correct their English gently. Flag only real errors; if the sentence is already fine, "
        "set has_issues to false and leave corrected_en empty. Never invent errors.\n"
        "3. Offer 1-3 more natural or higher-level ways to say what they meant.\n"
        "4. Ask 2-4 NEW questions, each from a different angle, that build on their answer.\n"
    )
    if asked:
        listed = "\n".join(f"- {q}" for q in asked)
        turn_instructions += f"\nAlready asked - do not repeat these or close variants:\n{listed}\n"

    messages = [{"role": "user", "content": f"The learner's original text was:\n\n{topic}"}] if topic else []
    messages += history_to_messages(body.get("history") or [])
    messages.append({"role": "user", "content": message})
    append_turn_instructions(messages, turn_instructions)

    return call_model(system_blocks(level, mode), messages, CHAT_SCHEMA, effort="low", max_tokens=4000)


def api_review(body: dict) -> dict:
    history = history_to_messages(body.get("history") or [])
    if not history:
        raise ModelError("복습할 대화가 아직 없습니다.")
    level = body.get("level", "intermediate")
    mode = body.get("mode", "diary")

    history.append(
        {
            "role": "user",
            "content": (
                "That's the end of today's practice. Write my review note: what we covered, the mistakes "
                "worth remembering, vocabulary with example sentences, and questions to revisit next time."
            ),
        }
    )
    return call_model(system_blocks(level, mode), history, REVIEW_SCHEMA, effort="medium", max_tokens=6000)


ROUTES = {
    "/api/questions": api_questions,
    "/api/chat": api_chat,
    "/api/review": api_review,
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "EnglishBuddy/1.0"

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        handler = ROUTES.get(path)
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(200, handler(body))
        except ModelError as exc:
            self._send_json(400, {"error": str(exc)})
        except anthropic.APIStatusError as exc:
            self._send_json(502, {"error": f"Claude API 오류 ({exc.status_code}): {exc.message}"})
        except anthropic.APIConnectionError:
            self._send_json(502, {"error": "Claude API에 연결하지 못했습니다. 네트워크를 확인해 주세요."})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._send_json(500, {"error": "서버 오류가 발생했습니다. 터미널 로그를 확인해 주세요."})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[english-buddy] {fmt % args}")


def main() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("경고: ANTHROPIC_API_KEY 가 설정되어 있지 않습니다. `export ANTHROPIC_API_KEY=sk-ant-...`")
    print(f"English Buddy: http://localhost:{PORT}  (model: {MODEL})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
