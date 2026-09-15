/* 앱 껍데기를 캐시해 두는 서비스 워커. 화면은 캐시에서 즉시 띄우고 뒤에서 새 버전을 받아 둔다.
   대화 요청(Anthropic · 로컬 서버)은 절대 캐시하지 않는다. */
const CACHE = "english-buddy-v2";
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
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
