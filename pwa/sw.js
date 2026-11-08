// UNIVA Service Worker v2 - Network First (Asla eski arayüzü bellekte tutmaz)
const CACHE_NAME = 'univa-pwa-v2-' + Date.now();

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  // Her zaman doğrudan ağdan en güncel sayfayı al, ağ yoksa önbelleğe bak
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
