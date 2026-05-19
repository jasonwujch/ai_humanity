// Service worker for 徐乃昌日记 KG explorer
// Strategy:
//   - /data/*.json    → network-first (fresh data wins; cache as fallback when offline)
//   - everything else → cache-first (HTML, JS libs, fonts, tiles, wiki pages)
// Cache version bumps invalidate all stale entries on activate.

const CACHE = 'xnc-kg-v12';
const PRECACHE = [
  './',
  './index.html',
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Same-origin only
  if (url.origin !== self.location.origin) return;
  const isData = url.pathname.includes('/data/') && url.pathname.endsWith('.json');
  if (isData) {
    // Network-first
    e.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
  } else {
    // Cache-first, then network + populate
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }))
    );
  }
});
