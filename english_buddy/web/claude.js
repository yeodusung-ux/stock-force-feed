/* 프롬프트 · 스키마 · Claude 호출을 한곳에 모은 모듈. 두 가지 방식으로 동작한다.
   - server 모드: 옆에서 python server.py 가 돌고 있으면 그쪽으로 보낸다(키는 PC 안에만 있음).
   - direct 모드: 깃허브 Pages 같은 정적 호스팅에서 열렸을 때. 이 기기에 저장한 키로 직접 호출한다. */
window.Claude = (() => {
  const MODEL = "claude-opus-5";
  const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
  const KEY_STORAGE = "english-buddy.api-key";
  const MAX_HISTORY_TURNS = 40;

  let transport = "direct";
  let useFallbacks = true;

  // ---------- 프롬프트 ----------

  const QUESTION_ANGLES = `Question variety is the whole point of this app. Rotate through these angles, never use the same
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
  put that word in the Korean gloss (\`ko\`).
- Sound like a curious friend, not a quiz machine.`;

  const BASE_SYSTEM = `You are "English Buddy", a warm and genuinely curious English conversation partner for a Korean learner.

The learner writes a diary entry, describes a situation, or names a topic. Your job is to keep an English
conversation going about *their* content by asking as many genuinely different questions as possible.

${QUESTION_ANGLES}

If the learner writes in Korean, treat it as "I want to say this in English": give them the English version
in \`better_expressions\`, then carry on with the conversation in English.

Write every \`ko\` / \`_ko\` field in natural Korean, and every English field in natural English.`;

  const LEVEL_GUIDE = {
    beginner:
      "LEVEL: beginner. Use present and past simple, high-frequency vocabulary, at most ~12 words per " +
      "question. The Korean gloss matters a lot here. Your own replies stay very short.",
    intermediate:
      "LEVEL: intermediate. Everyday idioms and two-clause sentences are fine. Push them toward longer " +
      "answers with 'why' and 'how' questions.",
    advanced:
      "LEVEL: advanced. Ask abstract, hypothetical and nuanced questions. Challenge imprecise word choice, " +
      "register and collocation even when the grammar is already correct.",
  };

  const MODE_GUIDE = {
    diary: "The learner wrote a DIARY entry about their own day. Treat it as personal and real.",
    situation: "The learner described a SITUATION (real or imagined). Explore it, and use role-play often.",
    topic: "The learner named a TOPIC. Ask about their own experience and opinions on it, not encyclopedia facts.",
  };

  function systemBlocks(level, mode) {
    return [
      { type: "text", text: BASE_SYSTEM, cache_control: { type: "ephemeral" } },
      { type: "text", text: `${LEVEL_GUIDE[level] || LEVEL_GUIDE.intermediate}\n${MODE_GUIDE[mode] || MODE_GUIDE.diary}` },
    ];
  }

  // ---------- 스키마 ----------

  const QUESTION_ITEM = {
    type: "object",
    properties: {
      angle: {
        type: "string",
        enum: ["FACTS", "DETAIL", "FEELING", "REASON", "OPINION", "COMPARISON", "HYPOTHETICAL",
               "PAST_LINK", "FUTURE", "OTHER_PERSPECTIVE", "CULTURE", "VOCABULARY", "ROLE_PLAY",
               "SUMMARY_CHALLENGE"],
      },
      en: { type: "string", description: "The question, in English." },
      ko: { type: "string", description: "Korean gloss of the question." },
      difficulty: { type: "string", enum: ["easy", "medium", "hard"] },
    },
    required: ["angle", "en", "ko", "difficulty"],
    additionalProperties: false,
  };

  const PAIR = {
    type: "object",
    properties: { en: { type: "string" }, ko: { type: "string" } },
    required: ["en", "ko"],
    additionalProperties: false,
  };

  const NOTE = {
    type: "object",
    properties: { before: { type: "string" }, after: { type: "string" }, why_ko: { type: "string" } },
    required: ["before", "after", "why_ko"],
    additionalProperties: false,
  };

  const QUESTIONS_SCHEMA = {
    type: "object",
    properties: {
      topic_summary_ko: { type: "string", description: "학습자가 쓴 내용을 한 문장 한국어로 요약." },
      opener_en: { type: "string", description: "A warm 1-2 sentence English reaction to what they wrote." },
      opener_ko: { type: "string" },
      key_vocabulary: { type: "array", items: PAIR, description: "5-8 words or phrases they will need." },
      questions: { type: "array", items: QUESTION_ITEM, description: "12-15 questions, each from a different angle, easy to hard." },
    },
    required: ["topic_summary_ko", "opener_en", "opener_ko", "key_vocabulary", "questions"],
    additionalProperties: false,
  };

  const CHAT_SCHEMA = {
    type: "object",
    properties: {
      reply_en: { type: "string", description: "React to the MEANING of what they said, in 1-2 natural English sentences." },
      reply_ko: { type: "string", description: "Korean translation of reply_en." },
      correction: {
        type: "object",
        properties: {
          has_issues: { type: "boolean" },
          corrected_en: { type: "string", description: "Their sentence(s) rewritten correctly. Empty string if nothing to fix." },
          notes: { type: "array", items: NOTE, description: "At most 3 real errors. Never invent errors that are not there." },
        },
        required: ["has_issues", "corrected_en", "notes"],
        additionalProperties: false,
      },
      better_expressions: { type: "array", items: PAIR, description: "1-3 more natural or higher-level ways to say what they meant." },
      questions: { type: "array", items: QUESTION_ITEM, description: "2-4 brand-new follow-up questions, each from a different angle." },
    },
    required: ["reply_en", "reply_ko", "correction", "better_expressions", "questions"],
    additionalProperties: false,
  };

  const REVIEW_SCHEMA = {
    type: "object",
    properties: {
      summary_ko: { type: "string", description: "이번 대화에서 다룬 내용 요약." },
      mistakes: { type: "array", items: NOTE },
      vocabulary: {
        type: "array",
        items: {
          type: "object",
          properties: { en: { type: "string" }, ko: { type: "string" }, example_en: { type: "string" } },
          required: ["en", "ko", "example_en"],
          additionalProperties: false,
        },
      },
      unanswered_questions: { type: "array", items: { type: "string" } },
      encouragement_ko: { type: "string" },
    },
    required: ["summary_ko", "mistakes", "vocabulary", "unanswered_questions", "encouragement_ko"],
    additionalProperties: false,
  };

  // ---------- 키 보관 (이 기기에만) ----------

  function getKey() {
    try {
      return localStorage.getItem(KEY_STORAGE) || "";
    } catch (_) {
      return "";
    }
  }

  function setKey(value) {
    try {
      localStorage.setItem(KEY_STORAGE, value.trim());
    } catch (_) {
      /* 사생활 보호 모드 등에서는 저장이 막힐 수 있다 */
    }
  }

  function clearKey() {
    try {
      localStorage.removeItem(KEY_STORAGE);
    } catch (_) {
      /* 무시 */
    }
  }

  // ---------- 호출 ----------

  class ClaudeError extends Error {}

  function friendlyError(status, body) {
    const message = (body && body.error && body.error.message) || (body && body.error) || "";
    if (status === 401 || /authentication/i.test(message)) {
      return "API 키가 올바르지 않습니다. 설정에서 키를 다시 확인해 주세요.";
    }
    if (/credit balance/i.test(message)) {
      return "크레딧이 부족합니다. console.anthropic.com 에서 충전해 주세요.";
    }
    if (status === 429) return "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.";
    if (status >= 500) return "Claude 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요.";
    return message || `요청에 실패했습니다 (HTTP ${status}).`;
  }

  async function send(body) {
    if (transport === "server") {
      const response = await fetch("api/claude", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new ClaudeError(data.error || friendlyError(response.status, data));
      return data;
    }

    const key = getKey();
    if (!key) throw new ClaudeError("NO_KEY");

    const headers = {
      "content-type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    };
    const payload = { ...body };
    if (useFallbacks) {
      headers["anthropic-beta"] = "server-side-fallback-2026-07-01";
      payload.fallbacks = "default";
    }

    let response;
    try {
      response = await fetch(ANTHROPIC_URL, { method: "POST", headers, body: JSON.stringify(payload) });
    } catch (_) {
      throw new ClaudeError("네트워크에 연결하지 못했습니다. 인터넷 상태를 확인해 주세요.");
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = (data.error && data.error.message) || "";
      // 폴백 베타를 못 쓰는 계정이면 한 번만 끄고 다시 시도한다
      if (useFallbacks && response.status === 400 && /fallback|beta/i.test(message)) {
        useFallbacks = false;
        return send(body);
      }
      throw new ClaudeError(friendlyError(response.status, data));
    }
    return data;
  }

  async function callModel({ system, messages, schema, effort = "low", maxTokens = 4000 }) {
    const data = await send({
      model: MODEL,
      max_tokens: maxTokens,
      system,
      messages,
      thinking: { type: "adaptive" },
      output_config: { effort, format: { type: "json_schema", schema } },
    });

    if (data.stop_reason === "refusal") {
      throw new ClaudeError("모델이 이 입력에 대한 응답을 거절했습니다. 내용을 바꿔서 다시 시도해 주세요.");
    }
    if (data.stop_reason === "max_tokens") {
      throw new ClaudeError("응답이 너무 길어 잘렸습니다. 입력을 조금 짧게 해서 다시 시도해 주세요.");
    }
    const block = (data.content || []).find((item) => item.type === "text");
    if (!block) throw new ClaudeError("모델이 빈 응답을 반환했습니다.");
    return JSON.parse(block.text);
  }

  function historyToMessages(history) {
    return (history || [])
      .slice(-MAX_HISTORY_TURNS)
      .map((turn) => ({
        role: turn.role === "assistant" ? "assistant" : "user",
        content: (turn.content || "").trim(),
      }))
      .filter((turn) => turn.content);
  }

  return {
    ClaudeError,
    getKey,
    setKey,
    clearKey,

    get transport() {
      return transport;
    },

    /** 로컬 서버가 내려준 페이지면 server 모드, 정적 호스팅이면 direct 모드.
        (서버가 index.html 에 window.ENGLISH_BUDDY_SERVER 를 심어 준다) */
    detectTransport() {
      transport = window.ENGLISH_BUDDY_SERVER === true ? "server" : "direct";
      return transport;
    },

    /** direct 모드인데 키가 없으면 설정 화면부터 보여 줘야 한다. */
    needsKey() {
      return transport === "direct" && !getKey();
    },

    questions({ text, level, mode }) {
      const prompt =
        `Here is what the learner wrote:\n\n<learner_text>\n${text}\n</learner_text>\n\n` +
        "Summarise it in Korean, react warmly in English, list the vocabulary they'll need, " +
        "and write 12-15 questions about it - each from a different angle, ordered from easy to hard.";
      return callModel({
        system: systemBlocks(level, mode),
        messages: [{ role: "user", content: prompt }],
        schema: QUESTIONS_SCHEMA,
        effort: "medium",
        maxTokens: 6000,
      });
    },

    chat({ message, topic, history, asked, level, mode }) {
      let instructions =
        "For this turn:\n" +
        "1. React in English to the MEANING of what they just said - be a person, not a grader.\n" +
        "2. Correct their English gently. Flag only real errors; if the sentence is already fine, " +
        "set has_issues to false and leave corrected_en empty. Never invent errors.\n" +
        "3. Offer 1-3 more natural or higher-level ways to say what they meant.\n" +
        "4. Ask 2-4 NEW questions, each from a different angle, that build on their answer.\n";
      const recent = (asked || []).slice(-40);
      if (recent.length) {
        instructions += `\nAlready asked - do not repeat these or close variants:\n${recent.map((q) => `- ${q}`).join("\n")}\n`;
      }

      const messages = topic ? [{ role: "user", content: `The learner's original text was:\n\n${topic}` }] : [];
      messages.push(...historyToMessages(history));
      messages.push({ role: "user", content: message });
      messages.push({ role: "system", content: instructions });

      return callModel({ system: systemBlocks(level, mode), messages, schema: CHAT_SCHEMA, effort: "low", maxTokens: 4000 });
    },

    review({ history, level, mode }) {
      const messages = historyToMessages(history);
      messages.push({
        role: "user",
        content:
          "That's the end of today's practice. Write my review note: what we covered, the mistakes worth " +
          "remembering, vocabulary with example sentences, and questions to revisit next time.",
      });
      return callModel({ system: systemBlocks(level, mode), messages, schema: REVIEW_SCHEMA, effort: "medium", maxTokens: 6000 });
    },
  };
})();
