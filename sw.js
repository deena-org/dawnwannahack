const CACHE = 'bizbuddy-v1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/style.css',
  '/app.js',
  '/manifest.json',
  '/icons/icon.svg',
];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>BizBuddy — Offline</title>
<style>
  body{margin:0;background:#0d1117;color:#e8edf8;font-family:'DM Sans',Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;flex-direction:column;gap:16px;text-align:center;padding:24px;}
  .logo{font-size:32px;font-weight:900;background:linear-gradient(135deg,#00d4aa,#6c63ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
  .icon{font-size:56px;margin-bottom:8px;}
  h2{font-size:20px;margin:0;}
  p{color:#5a6785;font-size:14px;max-width:280px;line-height:1.6;margin:0;}
  button{margin-top:8px;background:linear-gradient(135deg,#00d4aa,#6c63ff);border:none;border-radius:10px;padding:12px 28px;color:#fff;font-weight:700;font-size:14px;cursor:pointer;}
</style>
</head>
<body>
  <div class="logo">BizBuddy</div>
  <div class="icon">📡</div>
  <h2>You're offline</h2>
  <p>BizBuddy needs internet to load your financial data. Connect and try again.</p>
  <button onclick="location.reload()">Try Again</button>
</body>
</html>`;

// Pre-cache static assets on install
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Delete old caches on activate
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch handler
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Network-only: Firebase, Google APIs (always need fresh data)
  if (
    url.hostname.includes('firestore.googleapis.com') ||
    url.hostname.includes('firebase.googleapis.com') ||
    url.hostname.includes('identitytoolkit.googleapis.com') ||
    url.hostname.includes('gstatic.com')
  ) return;

  // Stale-while-revalidate: CDN assets (fonts, chart.js)
  if (
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('cdn.jsdelivr.net')
  ) {
    e.respondWith(
      caches.open(CACHE).then(async cache => {
        const cached = await cache.match(e.request);
        const networkFetch = fetch(e.request).then(res => {
          if (res.ok) cache.put(e.request, res.clone());
          return res;
        }).catch(() => cached);
        return cached || networkFetch;
      })
    );
    return;
  }

  // Cache-first with network fallback + offline page for everything else
  e.respondWith(
    caches.open(CACHE).then(async cache => {
      const cached = await cache.match(e.request);
      if (cached) return cached;
      try {
        const response = await fetch(e.request);
        if (response.ok) cache.put(e.request, response.clone());
        return response;
      } catch {
        if (e.request.mode === 'navigate') {
          return new Response(OFFLINE_HTML, {
            headers: { 'Content-Type': 'text/html' }
          });
        }
      }
    })
  );
});

// Skip waiting when triggered by client (update flow)
self.addEventListener('message', e => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});
