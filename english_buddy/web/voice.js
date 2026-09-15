/* 브라우저 내장 Web Speech API 래퍼.
   - 읽어주기(TTS): speechSynthesis. 긴 문장은 크롬의 ~15초 끊김을 피하려고 문장 단위로 쪼개 큐에 넣는다.
   - 받아쓰기(STT): SpeechRecognition. 크롬/엣지/사파리에서 동작하고, 파이어폭스에는 아직 없다. */
window.Voice = (() => {
  const synth = window.speechSynthesis || null;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;

  let preferredVoice = null;
  let rate = 1;
  let queue = [];
  let speaking = false;

  function loadVoices() {
    if (!synth) return;
    const voices = synth.getVoices();
    if (!voices.length) return;
    preferredVoice =
      voices.find((v) => v.lang === "en-US" && v.localService) ||
      voices.find((v) => v.lang === "en-US") ||
      voices.find((v) => v.lang && v.lang.startsWith("en")) ||
      null;
  }
  if (synth) {
    loadVoices();
    synth.addEventListener("voiceschanged", loadVoices);
  }

  /** 한 번에 읽히기 좋은 길이로 문장을 자른다. */
  function chunk(text, limit = 180) {
    const sentences = text.replace(/\s+/g, " ").trim().match(/[^.!?]+[.!?]*\s*/g) || [text];
    const chunks = [];
    let current = "";
    for (const sentence of sentences) {
      if (current && (current + sentence).length > limit) {
        chunks.push(current.trim());
        current = "";
      }
      current += sentence;
    }
    if (current.trim()) chunks.push(current.trim());
    return chunks;
  }

  function playNext(onDone) {
    const next = queue.shift();
    if (!next) {
      speaking = false;
      if (onDone) onDone();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(next);
    utterance.lang = preferredVoice ? preferredVoice.lang : "en-US";
    if (preferredVoice) utterance.voice = preferredVoice;
    utterance.rate = rate;
    utterance.onend = () => playNext(onDone);
    utterance.onerror = () => playNext(onDone);
    synth.speak(utterance);
  }

  return {
    ttsSupported: Boolean(synth),
    sttSupported: Boolean(Recognition),

    setRate(value) {
      rate = value;
    },

    /** 영어 텍스트를 읽어 준다. 이전 재생은 즉시 중단. */
    speak(text, onDone) {
      if (!synth || !text) return;
      synth.cancel();
      queue = chunk(text);
      speaking = true;
      playNext(onDone);
    },

    stop() {
      if (!synth) return;
      queue = [];
      speaking = false;
      synth.cancel();
    },

    isSpeaking() {
      return speaking;
    },

    /** 마이크 받아쓰기 시작. 컨트롤러의 stop() 으로 끝낸다.
        크롬은 침묵이 길어지면 스스로 멈추므로, 사용자가 멈추기 전까지는 다시 시작한다. */
    listen({ lang = "en-US", onPartial, onFinal, onEnd, onError }) {
      if (!Recognition) return null;

      let wantsListening = true;
      let finalText = "";
      const recognition = new Recognition();
      recognition.lang = lang;
      recognition.continuous = true;
      recognition.interimResults = true;

      recognition.onresult = (event) => {
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (result.isFinal) finalText += result[0].transcript;
          else interim += result[0].transcript;
        }
        if (onPartial) onPartial((finalText + interim).trim());
      };

      recognition.onerror = (event) => {
        if (event.error === "no-speech" || event.error === "aborted") return;
        wantsListening = false;
        if (onError) onError(event.error);
      };

      recognition.onend = () => {
        if (wantsListening) {
          try {
            recognition.start();
            return;
          } catch (_) {
            /* 재시작에 실패하면 그대로 종료한다 */
          }
        }
        if (onFinal) onFinal(finalText.trim());
        if (onEnd) onEnd();
      };

      try {
        recognition.start();
      } catch (error) {
        if (onError) onError(String(error));
        return null;
      }

      return {
        stop() {
          wantsListening = false;
          recognition.stop();
        },
      };
    },
  };
})();
