const CACHE_NAME = "tiptib-static-v3";
const STATIC_ASSETS = ["/static/styles.css", "/static/app.js", "/static/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
  }
});
