const $ = (id) => document.getElementById(id);

const state = {
  mode: "diary",
  level: "intermediate",
  topic: "",       // 학습자가 처음 쓴 원문
  history: [],     // [{role, content}] - 서버로 그대로 보낸다
  asked: [],       // 이미 물어본 질문(중복 방지용)
};

const voice = {
  recognizer: null,   // 받아쓰기 중이면 컨트롤러가 들어 있다
  autoRead: true,
};

const ANGLE_LABEL = {
  FACTS: "사실", DETAIL: "묘사", FEELING: "감정", REASON: "이유", OPINION: "의견",
  COMPARISON: "비교", HYPOTHETICAL: "가정", PAST_LINK: "과거 경험", FUTURE: "앞으로",
  OTHER_PERSPECTIVE: "상대 입장", CULTURE: "문화", VOCABULARY: "표현 확장",
  ROLE_PLAY: "역할극", SUMMARY_CHALLENGE: "요약 도전",
};

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: "응답을 읽지 못했습니다." }));
  if (!res.ok) throw new Error(data.error || "요청에 실패했습니다.");
  return data;
}

function showError(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ---------- 렌더링 ----------

function attachSpeaker(container, text) {
  if (!Voice.ttsSupported || !text) return;
  const button = el("button", "speak", "🔊");
  button.title = "읽어주기";
  button.setAttribute("aria-label", "읽어주기");
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    Voice.speak(text);
  });
  container.append(button);
}

/** 자동 읽기가 켜져 있을 때만 읽어 준다. */
function say(text) {
  if (voice.autoRead && Voice.ttsSupported && text) Voice.speak(text);
}

function addBubble(kind, en, ko) {
  const bubble = el("div", `bubble ${kind}`);
  bubble.append(el("div", "en", en));
  if (ko) bubble.append(el("div", "ko", ko));
  if (kind.startsWith("buddy") && !kind.includes("thinking")) attachSpeaker(bubble, en);
  $("chat").append(bubble);
  $("chat").scrollTop = $("chat").scrollHeight;
  return bubble;
}

function addFeedback(correction, betterExpressions) {
  const hasFix = correction && correction.has_issues && (correction.notes || []).length;
  const hasBetter = (betterExpressions || []).length;
  if (!hasFix && !hasBetter) return;

  const box = el("div", "feedback");
  if (hasFix) {
    box.append(el("h4", null, "고칠 부분"));
    for (const note of correction.notes) {
      const line = el("div", "fix");
      line.append(Object.assign(document.createElement("del"), { textContent: note.before }));
      line.append(document.createTextNode(" → "));
      line.append(Object.assign(document.createElement("ins"), { textContent: note.after }));
      line.append(el("div", "why", note.why_ko));
      box.append(line);
    }
  }
  if (hasBetter) {
    box.append(el("h4", null, "이렇게 말하면 더 자연스러워요"));
    for (const item of betterExpressions) {
      const line = el("div", "fix");
      line.append(el("span", "en", item.en));
      line.append(el("div", "why", item.ko));
      box.append(line);
    }
  }
  $("chat").append(box);
  $("chat").scrollTop = $("chat").scrollHeight;
}

function renderQuestions(questions, { append = false } = {}) {
  const box = $("questions");
  if (!append) box.innerHTML = "";
  for (const q of questions) {
    if (state.asked.includes(q.en)) continue;
    state.asked.push(q.en);

    const item = el("div", "q");
    item.setAttribute("role", "button");
    item.tabIndex = 0;
    item.append(el("span", "tag", ANGLE_LABEL[q.angle] || q.angle));
    item.append(el("span", "en", q.en));
    item.append(el("span", "ko", q.ko));
    attachSpeaker(item, q.en);

    const pick = () => {
      item.classList.add("used");
      $("answer").focus();
      $("answer").placeholder = q.en;
      say(q.en);
    };
    item.addEventListener("click", pick);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        pick();
      }
    });
    box.prepend(item);
  }
  $("qcount").textContent = `${box.childElementCount}개`;
}

function renderVocab(items) {
  const box = $("vocab");
  box.innerHTML = "";
  for (const item of items || []) {
    const row = el("div", "vocab-item", item.en + " ");
    row.append(el("span", null, item.ko));
    box.append(row);
  }
}

// ---------- 동작 ----------

async function start() {
  const text = $("seed").value.trim();
  if (!text) return showError($("setup-error"), "내용을 입력해 주세요.");

  state.mode = $("mode").value;
  state.level = $("level").value;
  state.topic = text;
  showError($("setup-error"), "");
  $("start").disabled = true;
  $("start").textContent = "질문을 만드는 중…";

  try {
    const data = await post("/api/questions", { text, mode: state.mode, level: state.level });
    $("setup").hidden = true;
    $("session").hidden = false;
    $("summary").textContent = data.topic_summary_ko;
    addBubble("me", text);
    addBubble("buddy", data.opener_en, data.opener_ko);
    renderQuestions(data.questions);
    renderVocab(data.key_vocabulary);
    say(data.opener_en);
    state.history.push({ role: "user", content: text });
    state.history.push({
      role: "assistant",
      content: `${data.opener_en}\n${data.questions.map((q) => q.en).join("\n")}`,
    });
    $("answer").focus();
  } catch (err) {
    showError($("setup-error"), err.message);
  } finally {
    $("start").disabled = false;
    $("start").textContent = "대화 시작하기";
  }
}

async function send() {
  const message = $("answer").value.trim();
  if (!message) return;

  if (voice.recognizer) voice.recognizer.stop();
  Voice.stop();
  showError($("chat-error"), "");
  $("answer").value = "";
  $("answer").placeholder = "영어로 답해 보세요. 막히면 한국어로 써도 영어 표현을 알려드립니다.";
  addBubble("me", message);
  const pending = addBubble("buddy thinking", "생각하는 중…");
  $("send").disabled = true;

  try {
    const data = await post("/api/chat", {
      message,
      topic: state.topic,
      history: state.history,
      asked: state.asked,
      mode: state.mode,
      level: state.level,
    });
    pending.remove();
    addBubble("buddy", data.reply_en, data.reply_ko);
    addFeedback(data.correction, data.better_expressions);
    renderQuestions(data.questions, { append: true });

    state.history.push({ role: "user", content: message });
    state.history.push({
      role: "assistant",
      content: `${data.reply_en}\n${data.questions.map((q) => q.en).join("\n")}`,
    });
    const nextQuestion = data.questions[0];
    if (nextQuestion) addBubble("buddy", nextQuestion.en, nextQuestion.ko);
    say(nextQuestion ? `${data.reply_en} ${nextQuestion.en}` : data.reply_en);
  } catch (err) {
    pending.remove();
    showError($("chat-error"), err.message);
  } finally {
    $("send").disabled = false;
    $("answer").focus();
  }
}

async function review() {
  $("review").disabled = true;
  try {
    const data = await post("/api/review", {
      history: state.history,
      mode: state.mode,
      level: state.level,
    });
    const body = $("modal-body");
    body.innerHTML = "";
    body.append(el("h3", null, "복습 노트"));
    body.append(el("p", null, data.summary_ko));

    if (data.mistakes.length) {
      body.append(el("h4", null, "기억할 실수"));
      const list = el("ul");
      for (const m of data.mistakes) {
        const li = el("li");
        li.append(Object.assign(document.createElement("del"), { textContent: m.before }));
        li.append(document.createTextNode(" → "));
        li.append(Object.assign(document.createElement("ins"), { textContent: m.after }));
        li.append(el("div", "why", m.why_ko));
        list.append(li);
      }
      body.append(list);
    }
    if (data.vocabulary.length) {
      body.append(el("h4", null, "표현 정리"));
      const list = el("ul");
      for (const v of data.vocabulary) {
        list.append(el("li", null, `${v.en} — ${v.ko} · ${v.example_en}`));
      }
      body.append(list);
    }
    if (data.unanswered_questions.length) {
      body.append(el("h4", null, "다음에 이어서 답해 볼 질문"));
      const list = el("ul");
      for (const q of data.unanswered_questions) list.append(el("li", null, q));
      body.append(list);
    }
    body.append(el("h4", null, "한마디"));
    body.append(el("p", null, data.encouragement_ko));
    $("modal").hidden = false;
  } catch (err) {
    showError($("chat-error"), err.message);
  } finally {
    $("review").disabled = false;
  }
}

// ---------- 음성 ----------

function setMicUI(listening) {
  $("mic").classList.toggle("on", listening);
  $("mic").setAttribute("aria-pressed", String(listening));
  $("mic-status").textContent = listening ? "듣는 중… 다 말하면 마이크를 다시 누르세요." : "";
}

function toggleMic() {
  if (voice.recognizer) {
    voice.recognizer.stop();
    return;
  }
  Voice.stop();  // 스피커 소리가 마이크로 들어가지 않게 먼저 끊는다
  showError($("chat-error"), "");

  const existing = $("answer").value.trim();
  voice.recognizer = Voice.listen({
    lang: $("stt-lang").value,
    onPartial: (text) => {
      $("answer").value = existing ? `${existing} ${text}` : text;
    },
    onEnd: () => {
      voice.recognizer = null;
      setMicUI(false);
      $("answer").focus();
    },
    onError: (error) => {
      showError(
        $("chat-error"),
        error === "not-allowed" || error === "service-not-allowed"
          ? "마이크 권한이 필요합니다. 브라우저 주소창의 자물쇠 아이콘에서 마이크를 허용해 주세요."
          : `받아쓰기 오류: ${error}`
      );
    },
  });
  setMicUI(Boolean(voice.recognizer));
}

function setupVoiceControls() {
  if (Voice.sttSupported) {
    $("mic").addEventListener("click", toggleMic);
  } else {
    $("mic").hidden = true;
    $("stt-lang").closest("label").hidden = true;
    $("mic-status").textContent = "이 브라우저는 받아쓰기를 지원하지 않습니다 (크롬 · 엣지 · 사파리 권장).";
  }

  if (Voice.ttsSupported) {
    Voice.setRate(parseFloat($("rate").value));
    $("rate").addEventListener("change", (event) => Voice.setRate(parseFloat(event.target.value)));
    $("autoread").addEventListener("change", (event) => {
      voice.autoRead = event.target.checked;
      if (!voice.autoRead) Voice.stop();
    });
  } else {
    $("autoread").closest("label").hidden = true;
    $("rate").closest("label").hidden = true;
  }
}

setupVoiceControls();

$("start").addEventListener("click", start);
$("send").addEventListener("click", send);
$("review").addEventListener("click", review);
$("modal-close").addEventListener("click", () => { $("modal").hidden = true; });
$("answer").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
});
