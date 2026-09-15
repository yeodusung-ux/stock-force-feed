/* 앱 껍데기를 캐시해 두는 서비스 워커.
   네트워크를 먼저 쓰고(고친 내용이 바로 반영되도록), 실패하면 캐시로 떨어진다(오프라인 대비).
   대화 요청(Anthropic · Gemini · 로컬 서버)은 절대 캐시하지 않는다. */
const CACHE = "english-buddy-2026-09-15.4";
const ASSETS = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "ai.js",
  "voice.js",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isAppAsset =
    event.request.method === "GET" && url.origin === self.location.origin && !url.pathname.includes("/api/");
  if (!isAppAsset) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || Promise.reject(new Error("offline"))))
  );
});
