/* 医学综合刷题 Service Worker —— 离线优先缓存 */
const CACHE = 'med-quiz-v1.14';
const CORE = ['./', './index.html', './manifest.webmanifest', './icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 对导航请求：优先网络，失败回退缓存（保证更新后能拿到新版，同时离线可用）
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return; // 只接管本站资源
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('./index.html'))
    );
    return;
  }
  // 其余静态资源：缓存优先
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});
